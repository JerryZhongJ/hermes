#!/usr/bin/env python3
"""
TypeGuard Benchmark Runner

对比 Static Hermes 在有/无类型标注下的性能差异。
特性：
  - 自动递归发现 test-suites/ 下的 benchmark
  - 在 annotations/<version>/ 下查找镜像路径的 .json 标注
  - warmup 预热 + 多次迭代
  - 统计分析（median, mean, stddev, 2σ% bounds）
  - A/B 对比（基于 median 的 speedup + 显著性判断）
  - geomean 汇总
  - JSON 结果归档

目录结构:
  suites/                             # JS benchmark 套件（可嵌套子目录）
    nbody.js
    jetstream/cdjs/benchmark.js
  annotations/
    v1/                               # 标注版本 v1
      nbody.json                      # 对应 test-suites/nbody.js
      jetstream/cdjs/benchmark.json   # 对应 test-suites/jetstream/cdjs/benchmark.js
    v2/                               # 标注版本 v2
      ...

用法:
  python3 bench.py -a v1                          # 运行所有有标注的 benchmark
  python3 bench.py -a v1 -n 20                    # 每个配置运行 20 次
  python3 bench.py -a v1 --only jetstream         # 只运行 jetstream/ 下的
  python3 bench.py -a v1 --only nbody             # 只运行 nbody.js
  python3 bench.py -a v1 --json results.json      # 保存 JSON 结果
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ─── 统计函数 ───

def mean(samples):
    if not samples:
        return 0.0
    return sum(samples) / len(samples)

def stddev(samples):
    if len(samples) < 2:
        return 0.0
    m = mean(samples)
    return math.sqrt(sum((x - m) ** 2 for x in samples) / len(samples))

def bounds_pct(samples):
    """2σ 百分比边界，衡量结果波动幅度（与 bench-runner 一致）"""
    m = mean(samples)
    if m == 0:
        return 0.0
    return 2 * stddev(samples) / m * 100.0

def median(samples):
    """中位数，天然抗离群值"""
    if not samples:
        return 0.0
    s = sorted(samples)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2

def summarize(samples):
    """生成统计摘要（不剔除离群值，用 median 抗干扰）"""
    return {
        'samples': samples,
        'n': len(samples),
        'median': median(samples),
        'mean': mean(samples),
        'stddev': stddev(samples),
        'bounds_pct': bounds_pct(samples),
        'min': min(samples) if samples else 0,
        'max': max(samples) if samples else 0,
    }

# ─── 核心 Runner ───

class BenchmarkRunner:
    def __init__(self, shermes, opt='-O', iterations=10, cache_dir=None, cpu=None, cc='clang'):
        self.shermes = os.path.abspath(shermes)
        self.opt = opt
        self.iterations = iterations
        self.cpu = cpu
        self.cc = cc
        self.cache_dir = cache_dir or os.path.join(os.path.dirname(__file__), '.bench_cache')
        os.makedirs(self.cache_dir, exist_ok=True)

        if not os.path.isfile(self.shermes):
            die(f"shermes not found: {self.shermes}")

    def compile(self, js_file, output_bin, annotation_file=None):
        """编译 JS -> 原生二进制"""
        cmd = [self.shermes, self.opt, '-fstatic-builtins']
        if annotation_file:
            cmd.append(f'-annotation-file={annotation_file}')
        cmd += ['-o', output_bin, js_file]

        env = {**os.environ, 'CC': self.cc}
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise RuntimeError(
                f"编译失败: {' '.join(cmd)}\n{proc.stderr.strip()}"
            )

    def run_once(self, binary, cwd=None):
        """运行一次，解析 Time: 输出（毫秒）

        cwd 设为 benchmark 所在目录，使二进制内 read('./resources/...') 能定位到
        该 benchmark 的 resources；产物保持相对路径，不耦合绝对路径，可移植。
        """
        cmd = ['taskset', '-c', str(self.cpu), binary] if self.cpu is not None else [binary]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300, cwd=cwd
        )
        if proc.returncode != 0:
            raise RuntimeError(f"运行失败 ({binary}):\n{proc.stderr.strip()}")

        for line in proc.stdout.splitlines():
            # 支持 "Time:123" 和 "Time: 123" 两种格式
            if line.startswith('Time:'):
                return float(line[5:].strip())

        raise RuntimeError(
            f"输出中未找到 'Time:' 行\nstdout: {proc.stdout[:500]}"
        )

    def measure_interleaved(self, binaries, labels, cwd=None):
        """交叉测量多个二进制，消除顺序偏差（A-B-A-B...）

        cwd 透传给 run_once，让同一 benchmark 的所有二进制都在该 benchmark 目录下执行。
        """
        # 每个二进制 warmup 1 次（填充 page cache + 稳定 CPU 频率）
        for binary, label in zip(binaries, labels):
            self.run_once(binary, cwd=cwd)
            info(f"  warmup {label} 完成")

        # 交叉测量
        all_samples = [[] for _ in binaries]
        for i in range(self.iterations):
            for j, (binary, label) in enumerate(zip(binaries, labels)):
                t = self.run_once(binary, cwd=cwd)
                all_samples[j].append(t)
                info(f"  {label} [{i+1:2d}/{self.iterations}] {t:8.1f} ms")

        return all_samples

# ─── Benchmark 发现 ───

def discover(base_dir, match_dir, only=None):
    """
    发现 benchmark：
    - 递归搜索 test-suites/ 下所有 .js 文件
    - 在 match_dir/ 下查找镜像相对路径的配对文件（通常是 .json）
    - 只有 .js + 配对文件 都存在才算一个有效 benchmark

    参数:
      base_dir: benchmark 根目录（包含 test-suites/）
      match_dir: 配对目录，相对于 base_dir（如 'annotations/v1', 'candidates'）
      only: 相对于 test-suites/ 的路径，可以是目录或文件（不含 .js 后缀亦可）
    """
    suites_dir = Path(base_dir) / 'suites'
    match_base = Path(base_dir) / match_dir

    if not suites_dir.is_dir():
        die(f"suites 目录不存在: {suites_dir}")
    if not match_base.is_dir():
        die(f"配对目录不存在: {match_base}")

    # 确定搜索范围
    js_files = []
    if only:
        target = suites_dir / only
        if target.is_file():
            js_files = [target]
        elif target.is_dir():
            js_files = sorted(target.rglob('*.js'))
        elif target.with_suffix('.js').is_file():
            js_files = [target.with_suffix('.js')]
        else:
            die(f"路径不存在: {target}（也不存在 {target.with_suffix('.js')}）")
    else:
        js_files = sorted(suites_dir.rglob('*.js'))

    # 从 match_dir 推导输出 key: 取第一级目录名, 去掉末尾 's'
    # 'annotations/v1' → 'annotation', 'candidates' → 'candidate'
    key_raw = match_dir.rstrip('/').split('/')[0]
    match_key = key_raw[:-1] if key_raw.endswith('s') else key_raw

    benchmarks = []
    for js in js_files:
        rel = js.relative_to(suites_dir)
        pair = match_base / rel.with_suffix('.json')
        if pair.is_file():
            benchmarks.append({
                'name': str(rel.with_suffix('')),
                'js': str(js.resolve()),
                match_key: str(pair.resolve()),
            })
    return benchmarks

# ─── 输出格式化 ───

def fmt_ms(ms):
    if ms < 1:
        return f"{ms * 1000:.0f} us"
    if ms < 1000:
        return f"{ms:.1f} ms"
    return f"{ms / 1000:.2f} s"

def fmt_pct(pct):
    return f"{pct:.1f}%"

def print_summary_line(label, stats):
    """打印一行统计摘要"""
    med = stats['median']
    m = stats['mean']
    bp = stats['bounds_pct']
    n = stats['n']

    line = f"  {label:<20s}  median={fmt_ms(med):>10s}  mean={fmt_ms(m):>10s} ± {fmt_pct(bp):>6s}  (n={n})"
    print(line)

def print_comparison(baseline_stats, tg_stats, tg_label):
    """打印 A/B 对比（基于 median）"""
    bm = baseline_stats['median']
    tm = tg_stats['median']

    if tm > 0 and bm > 0:
        speedup = bm / tm
        delta_pct = (bm - tm) / bm * 100

        # 显著性判断：基于 mean 的 2σ 范围不重叠
        b_mean = baseline_stats['mean']
        t_mean = tg_stats['mean']
        b_half = b_mean * baseline_stats['bounds_pct'] / 100
        t_half = t_mean * tg_stats['bounds_pct'] / 100
        significant = (t_mean + t_half) < (b_mean - b_half) or \
                      (b_mean + b_half) < (t_mean - t_half)

        if speedup >= 1.0:
            icon = '↑' if significant else '~'
            color_start = '\033[32m' if significant else ''  # green
        else:
            icon = '↓' if significant else '~'
            color_start = '\033[31m' if significant else ''  # red
        color_end = '\033[0m' if color_start else ''

        sig_text = " (显著)" if significant else " (不显著)"
        print(f"  {color_start}{icon} {tg_label}: {speedup:.3f}x{sig_text}{color_end}")
    else:
        print(f"  ? {tg_label}: 无法计算")

def print_header(text):
    width = 70
    print()
    print("=" * width)
    print(f"  {text}")
    print("=" * width)

# ─── 主流程 ───

def info(msg):
    print(msg, file=sys.stderr, flush=True)

def die(msg):
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(1)

def run_all(args):
    runner = BenchmarkRunner(
        shermes=args.shermes,
        opt=args.opt,
        iterations=args.iterations,
        cache_dir=args.cache_dir,
        cpu=args.cpu,
        cc=args.cc,
    )

    bench_dir = args.bench_dir or os.path.dirname(os.path.abspath(__file__))

    if not args.ann_version:
        die("必须指定标注版本，例如 --ann-version v1（对应 annotations/v1/）")

    benchmarks = discover(bench_dir, f'annotations/{args.ann_version}', only=args.only)

    if not benchmarks:
        die(f"未找到 benchmark（目录: {bench_dir}）")

    info(f"发现 {len(benchmarks)} 个 benchmark")
    info(f"配置: iterations={args.iterations}, opt={args.opt}, cpu={args.cpu if args.cpu is not None else 'any'}, cc={args.cc}")
    info(f"shermes: {runner.shermes}")
    info("")

    all_results = []

    for bench in benchmarks:
        name = bench['name']
        js = bench['js']
        annotation = bench['annotation']

        print_header(f"Benchmark: {name}")
        info(f"JS: {js}")
        info(f"标注: {os.path.basename(annotation)}")

        result = {'name': name, 'js': js}

        # 1) 编译 baseline 和 typeguard
        # 编译使用安全文件名（替换路径分隔符）
        safe_name = name.replace('/', '_').replace('\\', '_')
        baseline_bin = os.path.join(runner.cache_dir, f'{safe_name}_baseline')
        tg_bin = os.path.join(runner.cache_dir, f'{safe_name}_typeguard')
        try:
            runner.compile(js, baseline_bin)
            runner.compile(js, tg_bin, annotation)
        except RuntimeError as e:
            print(f"  编译失败: {e}")
            continue

        # 2) 交叉测量（A-B-A-B）；cwd 设为 benchmark 目录，使 resources 相对路径可用
        info(f"\n  ▶ 交叉测量: baseline vs typeguard")
        all_samples = runner.measure_interleaved(
            [baseline_bin, tg_bin], ['baseline', 'typeguard'],
            cwd=str(Path(js).parent),
        )

        baseline_stats = summarize(all_samples[0])
        tg_stats = summarize(all_samples[1])
        result['baseline'] = baseline_stats
        result['typeguard'] = tg_stats

        print()
        print_summary_line('baseline', baseline_stats)
        print_summary_line('typeguard', tg_stats)
        print_comparison(baseline_stats, tg_stats, 'typeguard')

        all_results.append(result)

    # 汇总表
    if len(all_results) > 0:
        print_header("汇总")
        print(f"  {'Benchmark':<20s}  {'Baseline':>10s}  {'TypeGuard':>10s}  {'Speedup':>8s}")
        print(f"  {'─' * 20}  {'─' * 10}  {'─' * 10}  {'─' * 8}")

        speedups = []
        for r in all_results:
            bm = r.get('baseline', {}).get('median', 0)
            tm = r.get('typeguard', {}).get('median', 0)
            if tm > 0 and bm > 0:
                speedup = bm / tm
                speedups.append(speedup)
                print(f"  {r['name']:<20s}  {fmt_ms(bm):>10s}  {fmt_ms(tm):>10s}  {speedup:>7.3f}x")
            else:
                print(f"  {r['name']:<20s}  {fmt_ms(bm):>10s}  {'N/A':>10s}  {'N/A':>8s}")

        if speedups:
            geomean = math.exp(sum(math.log(s) for s in speedups) / len(speedups))
            print(f"  {'─' * 20}  {'─' * 10}  {'─' * 10}  {'─' * 8}")
            print(f"  {'geomean':<20s}  {'':>10s}  {'':>10s}  {geomean:>7.3f}x")

        print()

    # 保存 JSON
    if args.json:
        # 将结果转化为可序列化格式
        serializable = []
        for r in all_results:
            sr = {'name': r['name'], 'js': r['js']}
            for k, v in r.items():
                if k in ('name', 'js'):
                    continue
                if isinstance(v, dict):
                    sr[k] = {
                        'median': v.get('median', 0),
                        'mean': v.get('mean', 0),
                        'stddev': v.get('stddev', 0),
                        'bounds_pct': v.get('bounds_pct', 0),
                        'min': v.get('min', 0),
                        'max': v.get('max', 0),
                        'n': v.get('n', 0),
                        'samples': v.get('samples', []),
                    }
            serializable.append(sr)

        output = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'config': {
                'shermes': runner.shermes,
                'opt': args.opt,
                'iterations': args.iterations,
            },
            'results': serializable,
        }
        with open(args.json, 'w') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"结果已保存到: {args.json}")


def main():
    parser = argparse.ArgumentParser(
        description='TypeGuard Benchmark Runner - 对比有/无类型标注的 SH 性能',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s -a v1                                # 运行所有有标注的 benchmark
  %(prog)s -a v1 -n 20                          # 每配置运行 20 次
  %(prog)s -a v1 --only jetstream               # 只运行 jetstream/ 目录下的
  %(prog)s -a v1 --only jetstream/cdjs          # 只运行 jetstream/cdjs/ 下的
  %(prog)s -a v1 --only nbody                   # 只运行 nbody.js
  %(prog)s -a v1 --json results.json            # 保存 JSON 结果
        """
    )

    parser.add_argument(
        '--shermes', '-s',
        default='/home/zjc/js_engines/static-build-release/bin/shermes',
        help='shermes 可执行文件路径'
    )
    parser.add_argument(
        '--opt',
        default='-O',
        help='优化级别 (默认 -O)'
    )
    parser.add_argument(
        '--iterations', '-n',
        type=int, default=20,
        help='测量运行次数 (默认 10)'
    )
    parser.add_argument(
        '--ann-version', '-a',
        help='标注版本（annotations/ 下的子目录名，如 v1）'
    )
    parser.add_argument(
        '--only',
        help='只搜索 suites/ 下指定的相对路径（可以是目录或文件）'
    )
    parser.add_argument(
        '--json',
        help='保存 JSON 格式结果到文件'
    )
    parser.add_argument(
        '--bench-dir',
        help='benchmark 目录（默认为脚本所在目录）'
    )
    parser.add_argument(
        '--cc',
        default='clang',
        help='shermes 使用的 C 编译器 (默认 clang)'
    )
    parser.add_argument(
        '--cpu',
        type=int, default=1,
        help='固定运行的 CPU 核心编号 (默认 1，设 -1 不固定)'
    )
    parser.add_argument(
        '--cache-dir',
        help='编译缓存目录（默认 .bench_cache）'
    )
    parser.add_argument(
        '--clean',
        action='store_true',
        help='运行前清理编译缓存'
    )

    args = parser.parse_args()

    # --cpu -1 表示不固定核心
    if args.cpu is not None and args.cpu < 0:
        args.cpu = None

    if args.clean:
        cache = args.cache_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '.bench_cache'
        )
        if os.path.isdir(cache):
            shutil.rmtree(cache)
            info(f"已清理缓存: {cache}")

    run_all(args)


if __name__ == '__main__':
    main()
