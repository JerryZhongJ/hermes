#!/usr/bin/env python3
"""
Static Hermes Benchmark Runner

支持两种模式：

1. 兼容模式：比较 SH baseline 与 annotation，保留原有 CLI。
2. 多引擎实验模式：
   - 三个对象使用全部 3! 顺序做平衡交替；
   - anchor 与新增对象使用 AB/BA 配对；
   - 保存逐轮原始数据、配对 speedup 和 provenance。

兼容模式示例：
  python3 bench.py -a v1 -n 20 --json results.json

三对象实验：
  python3 bench.py \
    --variant v8 v8 /path/to/d8 \
    --variant hbc hbc /path/to/hermes \
    --variant sh sh /path/to/shermes \
    --schedule all-orders --anchor hbc --cycles 5 \
    --json results.json

新增对象相对锚点：
  python3 bench.py \
    --variant hbc hbc /path/to/reference/hermes \
    --variant new-sh sh /path/to/new/shermes \
    --schedule anchor-pairs --anchor hbc --cycles 10 \
    --json results.json
"""

import argparse
import hashlib
import itertools
import json
import math
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn


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
    """2σ 百分比边界，衡量结果波动幅度（不是置信区间）。"""
    m = mean(samples)
    if m == 0:
        return 0.0
    return 2 * stddev(samples) / m * 100.0


def median(samples):
    """中位数，天然抗离群值。"""
    if not samples:
        return 0.0
    values = sorted(samples)
    count = len(values)
    if count % 2 == 1:
        return values[count // 2]
    return (values[count // 2 - 1] + values[count // 2]) / 2


def summarize(samples):
    """生成统计摘要；保留全部样本，不静默剔除离群值。"""
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


# ─── 通用执行 ───

def parse_time(stdout):
    """解析 benchmark 输出中的 Time:<ms>。"""
    for line in stdout.splitlines():
        if line.startswith('Time:'):
            try:
                value = float(line[5:].strip())
            except ValueError as exc:
                raise RuntimeError(f"无效的 Time 输出: {line}") from exc
            if not math.isfinite(value) or value <= 0:
                raise RuntimeError(f"Time 必须是有限正数: {line}")
            return value
    raise RuntimeError(f"输出中未找到 'Time:' 行\nstdout: {stdout[:500]}")


def execute_once(command, cpu=None, cwd=None, timeout=300):
    cmd = list(command)
    if cpu is not None:
        cmd = ['taskset', '-c', str(cpu)] + cmd
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"运行失败 ({' '.join(cmd)}):\n{proc.stderr.strip()}"
        )
    return parse_time(proc.stdout)


# ─── 兼容 Runner ───

class BenchmarkRunner:
    def __init__(self, shermes, opt='-O', iterations=10, cache_dir=None,
                 cpu=None, cc='clang'):
        self.shermes = os.path.abspath(shermes)
        self.opt = opt
        self.iterations = iterations
        self.cpu = cpu
        self.cc = cc
        self.cache_dir = os.path.abspath(cache_dir or os.path.join(
            os.path.dirname(__file__), '.bench_cache'))
        os.makedirs(self.cache_dir, exist_ok=True)

        if not os.path.isfile(self.shermes):
            die(f"shermes not found: {self.shermes}")

    def compile(self, js_file, output_bin, annotation_file=None):
        """编译 JS -> 原生二进制。"""
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
        """运行一次并解析 Time；cwd 用于 benchmark 相对资源。"""
        return execute_once([binary], cpu=self.cpu, cwd=cwd)

    def measure_interleaved(self, binaries, labels, cwd=None):
        """交叉测量；奇偶轮反转顺序以抵消固定位置偏差。"""
        for binary, label in zip(binaries, labels):
            self.run_once(binary, cwd=cwd)
            info(f"  warmup {label} 完成")

        all_samples = [[] for _ in binaries]
        indexed = list(enumerate(zip(binaries, labels)))
        for iteration in range(self.iterations):
            order = indexed if iteration % 2 == 0 else list(reversed(indexed))
            for index, (binary, label) in order:
                elapsed = self.run_once(binary, cwd=cwd)
                all_samples[index].append(elapsed)
                info(
                    f"  {label} [{iteration + 1:2d}/{self.iterations}] "
                    f"{elapsed:8.1f} ms"
                )

        return all_samples


# ─── Benchmark 发现 ───

def _find_js_files(suites_dir, only):
    if only:
        target = suites_dir / only
        if target.is_file():
            return [target]
        if target.is_dir():
            benchmark_entries = sorted(target.rglob('benchmark.js'))
            return benchmark_entries or sorted(target.rglob('*.js'))
        if target.with_suffix('.js').is_file():
            return [target.with_suffix('.js')]
        die(f"路径不存在: {target}（也不存在 {target.with_suffix('.js')}）")
    return sorted(suites_dir.rglob('*.js'))


def discover(base_dir, match_dir, only=None):
    """发现同时存在 JS 和镜像 JSON 的兼容模式 benchmark。"""
    suites_dir = Path(base_dir) / 'suites'
    match_base = Path(base_dir) / match_dir

    if not suites_dir.is_dir():
        die(f"suites 目录不存在: {suites_dir}")
    if not match_base.is_dir():
        die(f"配对目录不存在: {match_base}")

    key_raw = match_dir.rstrip('/').split('/')[0]
    match_key = key_raw[:-1] if key_raw.endswith('s') else key_raw
    benchmarks = []
    for js in _find_js_files(suites_dir, only):
        rel = js.relative_to(suites_dir)
        pair = match_base / rel.with_suffix('.json')
        if pair.is_file():
            benchmarks.append({
                'name': str(rel.with_suffix('')),
                'js': str(js.resolve()),
                match_key: str(pair.resolve()),
            })
    return benchmarks


def discover_suites(base_dir, only=None):
    """发现多引擎实验 benchmark，不要求 annotation 镜像文件。"""
    suites_dir = Path(base_dir) / 'suites'
    if not suites_dir.is_dir():
        die(f"suites 目录不存在: {suites_dir}")
    return [
        {
            'name': js.relative_to(suites_dir).with_suffix('').as_posix(),
            'js': str(js.resolve()),
        }
        for js in _find_js_files(suites_dir, only)
    ]


# ─── 多引擎实验 ───

@dataclass(frozen=True)
class VariantSpec:
    name: str
    kind: str
    executable: str
    compile_args: tuple = ()
    run_args: tuple = ()


@dataclass
class PreparedVariant:
    spec: VariantSpec
    run_command: list
    compile_command: list
    artifact_path: str | None


def build_all_orders(variant_names, cycles):
    """三个对象的完整六排列；返回 (cycle, round_index, pair_id, order)。"""
    if len(variant_names) != 3 or len(set(variant_names)) != 3:
        raise ValueError('all-orders 必须使用三个不同对象')
    base = list(itertools.permutations(variant_names))
    rounds = []
    for cycle in range(cycles):
        cycle_orders = base if cycle % 2 == 0 else list(reversed(base))
        for round_index, order in enumerate(cycle_orders):
            rounds.append((cycle, round_index, None, order))
    return rounds


def build_anchor_pair_orders(anchor, variant_names, cycles):
    """每个 candidate 独立与 anchor 执行 AB/BA。"""
    if anchor not in variant_names:
        raise ValueError(f'anchor 不存在: {anchor}')
    candidates = [name for name in variant_names if name != anchor]
    if not candidates:
        raise ValueError('anchor-pairs 至少需要一个 candidate')

    rounds = []
    for cycle in range(cycles):
        cycle_candidates = candidates if cycle % 2 == 0 else list(reversed(candidates))
        round_index = 0
        for candidate in cycle_candidates:
            pair_id = f'{anchor}__{candidate}'
            rounds.append(
                (cycle, round_index, pair_id, (anchor, candidate)))
            round_index += 1
            rounds.append(
                (cycle, round_index, pair_id, (candidate, anchor)))
            round_index += 1
    return rounds


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def benchmark_input_manifest(js_file):
    """记录入口所在目录的文件树，覆盖相对加载的 helper/resources。"""
    root = Path(js_file).parent
    files = []
    for path in sorted(item for item in root.rglob('*') if item.is_file()):
        files.append({
            'path': path.relative_to(root).as_posix(),
            'sha256': sha256_file(path),
        })
    digest = hashlib.sha256()
    for item in files:
        digest.update(item['path'].encode('utf-8'))
        digest.update(b'\0')
        digest.update(item['sha256'].encode('ascii'))
        digest.update(b'\n')
    return {'root': str(root), 'sha256': digest.hexdigest(), 'files': files}


def _safe_name(value):
    return re.sub(r'[^A-Za-z0-9_.-]+', '_', value)


class EngineAdapter:
    """准备 V8、HBC、SH，并提供统一的一次运行接口。"""

    def __init__(self, opt, cpu, cc, timeout=300):
        self.opt = opt
        self.cpu = cpu
        self.cc = cc
        self.timeout = timeout

    def prepare(self, spec, benchmark, cache_dir):
        js_file = benchmark['js']
        safe = _safe_name(f"{benchmark['name']}__{spec.name}")
        compile_command = []
        artifact_path = None

        if spec.kind == 'v8':
            run_command = [spec.executable, *spec.run_args, js_file]
        elif spec.kind == 'qjs':
            run_command = [spec.executable, *spec.run_args, js_file]
        elif spec.kind == 'hbc':
            artifact_path = os.path.join(cache_dir, f'{safe}.hbc')
            compile_command = [
                spec.executable, self.opt, '-Wno-undefined-variable',
                '-emit-binary', *spec.compile_args,
                '-out', artifact_path, js_file,
            ]
            run_command = [spec.executable, *spec.run_args, '-b', artifact_path]
        elif spec.kind == 'sh':
            artifact_path = os.path.join(cache_dir, safe)
            compile_command = [
                spec.executable, self.opt, '-fstatic-builtins',
                *spec.compile_args, '-o', artifact_path, js_file,
            ]
            run_command = [artifact_path, *spec.run_args]
        else:
            raise ValueError(f'未知 variant kind: {spec.kind}')

        if compile_command:
            env = {**os.environ, 'CC': self.cc}
            proc = subprocess.run(
                compile_command, capture_output=True, text=True, env=env,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"编译失败 ({spec.name}): {' '.join(compile_command)}\n"
                    f"{proc.stderr.strip()}"
                )

        return PreparedVariant(
            spec=spec,
            run_command=run_command,
            compile_command=compile_command,
            artifact_path=artifact_path,
        )

    def run_once(self, prepared, cwd):
        return execute_once(
            prepared.run_command,
            cpu=self.cpu,
            cwd=cwd,
            timeout=self.timeout,
        )


def _parse_variant_args(raw_args, option):
    result = {}
    for value in raw_args or []:
        if '=' not in value:
            raise ValueError(f'{option} 必须使用 NAME=ARG: {value}')
        name, argument = value.split('=', 1)
        if not name or not argument:
            raise ValueError(f'{option} 必须使用 NAME=ARG: {value}')
        result.setdefault(name, []).append(argument)
    return result


def parse_variants(raw_variants, raw_compile_args=None, raw_run_args=None):
    compile_args = _parse_variant_args(
        raw_compile_args, '--variant-compile-arg')
    run_args = _parse_variant_args(raw_run_args, '--variant-run-arg')
    variants = []
    names = set()
    for name, kind, executable in raw_variants or []:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
            raise ValueError(f'无效 variant 名称: {name}')
        if name in names:
            raise ValueError(f'重复 variant 名称: {name}')
        if kind not in ('v8', 'qjs', 'hbc', 'sh'):
            raise ValueError(f'无效 variant kind: {kind}')
        path = os.path.abspath(executable)
        if not os.path.isfile(path):
            raise ValueError(f'variant 可执行文件不存在: {path}')
        names.add(name)
        variants.append(VariantSpec(
            name, kind, path,
            tuple(compile_args.get(name, [])),
            tuple(run_args.get(name, [])),
        ))
    unknown = (set(compile_args) | set(run_args)) - names
    if unknown:
        raise ValueError(
            f'附加参数引用了未知 variant: {", ".join(sorted(unknown))}')
    return variants


def paired_speedups(rounds, anchor, candidates):
    """按同一 round 计算 anchor_time / candidate_time。"""
    result = {candidate: [] for candidate in candidates}
    for round_data in rounds:
        values = {
            observation['variant']: observation['elapsed_ms']
            for observation in round_data['observations']
        }
        if anchor not in values:
            continue
        for candidate in candidates:
            if candidate in values:
                result[candidate].append(values[anchor] / values[candidate])
    return result


def _git_provenance(repo_root):
    def run(*args):
        proc = subprocess.run(
            ['git', '-C', repo_root, *args], capture_output=True, text=True,
        )
        return proc.stdout.strip() if proc.returncode == 0 else None

    commit = run('rev-parse', 'HEAD')
    status = run('status', '--porcelain')
    return {
        'root': repo_root,
        'commit': commit,
        'dirty': bool(status) if status is not None else None,
    }


def write_json_new(path, document):
    """严格写入一个新的 JSON 文件；已有文件绝不覆盖。"""
    output = Path(path).resolve()
    with open(output, 'x', encoding='utf-8') as result_file:
        json.dump(
            document, result_file, indent=2, ensure_ascii=False,
            allow_nan=False,
        )
        result_file.flush()
        os.fsync(result_file.fileno())


def variant_configuration(variant, opt):
    if variant.kind in ('v8', 'qjs'):
        return {
            'compile_args': [],
            'run_args': list(variant.run_args),
        }
    if variant.kind == 'hbc':
        return {
            'compile_args': [
                opt, '-Wno-undefined-variable', '-emit-binary',
                *variant.compile_args,
            ],
            'run_args': [*variant.run_args, '-b'],
        }
    return {
        'compile_args': [
            opt, '-fstatic-builtins', *variant.compile_args,
        ],
        'run_args': list(variant.run_args),
    }


def _cpu_model():
    try:
        with open('/proc/cpuinfo', encoding='utf-8') as cpuinfo:
            for line in cpuinfo:
                if line.startswith('model name'):
                    return line.split(':', 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or None


def build_provenance(args, variants, bench_dir):
    script = os.path.abspath(__file__)
    compiler = shutil.which(args.cc)
    repo_root = subprocess.run(
        ['git', '-C', bench_dir, 'rev-parse', '--show-toplevel'],
        capture_output=True, text=True,
    )
    root = repo_root.stdout.strip() if repo_root.returncode == 0 else bench_dir
    return {
        'tool': {'path': script, 'sha256': sha256_file(script)},
        'repository': _git_provenance(root),
        'host': {
            'hostname': socket.gethostname(),
            'platform': platform.platform(),
            'machine': platform.machine(),
            'cpu_model': _cpu_model(),
            'cpu_affinity': args.cpu,
        },
        'environment': {
            'CC': args.cc,
            'cc_path': os.path.realpath(compiler) if compiler else None,
            'cc_sha256': sha256_file(compiler) if compiler else None,
        },
        'variants': [
            {
                'id': variant.name,
                'kind': variant.kind,
                'executable': {
                    'path': variant.executable,
                    'real_path': os.path.realpath(variant.executable),
                    'sha256': sha256_file(variant.executable),
                },
                'configuration': variant_configuration(variant, args.opt),
            }
            for variant in variants
        ],
    }


def _artifact_record(prepared):
    if not prepared.artifact_path:
        return None
    return {
        'variant': prepared.spec.name,
        'path': prepared.artifact_path,
        'sha256': sha256_file(prepared.artifact_path),
        'compile_argv': prepared.compile_command,
        'run_argv': prepared.run_command,
    }


def run_experiment_benchmark(adapter, benchmark, variants, schedule, cache_dir,
                             anchor):
    cwd = str(Path(benchmark['js']).parent)
    prepared = {
        variant.name: adapter.prepare(variant, benchmark, cache_dir)
        for variant in variants
    }

    for variant in variants:
        adapter.run_once(prepared[variant.name], cwd)
        info(f"  warmup {variant.name} 完成")

    raw_rounds = []
    sequence = 0
    for cycle, round_index, pair_id, order in schedule:
        observations = []
        for position, name in enumerate(order):
            elapsed = adapter.run_once(prepared[name], cwd)
            observations.append({
                'sequence': sequence,
                'position': position,
                'variant': name,
                'elapsed_ms': elapsed,
            })
            sequence += 1
            info(
                f"  cycle={cycle + 1} round={round_index + 1} "
                f"pos={position + 1} {name}: {elapsed:.1f} ms"
            )
        raw_rounds.append({
            'cycle': cycle,
            'round_index': round_index,
            'pair_id': pair_id,
            'order': list(order),
            'observations': observations,
        })

    samples = {variant.name: [] for variant in variants}
    for round_data in raw_rounds:
        for observation in round_data['observations']:
            samples[observation['variant']].append(observation['elapsed_ms'])

    candidates = [variant.name for variant in variants if variant.name != anchor]
    speedups = paired_speedups(raw_rounds, anchor, candidates)
    artifacts = [
        record for record in (
            _artifact_record(prepared[variant.name]) for variant in variants
        ) if record
    ]
    return {
        'id': benchmark['name'],
        'status': 'ok',
        'source': {
            'path': benchmark['js'],
            'sha256': sha256_file(benchmark['js']),
            'inputs': benchmark_input_manifest(benchmark['js']),
        },
        'cwd': cwd,
        'artifacts': artifacts,
        'rounds': raw_rounds,
        'summaries': {
            name: summarize(values) for name, values in samples.items()
        },
        'anchor_comparisons': [
            {
                'anchor': anchor,
                'candidate': candidate,
                'definition': 'anchor_elapsed_ms / candidate_elapsed_ms',
                'speedup_samples': speedups[candidate],
                'speedup': summarize(speedups[candidate]),
            }
            for candidate in candidates
        ],
    }


def run_experiment(args):
    try:
        variants = parse_variants(
            args.variant, args.variant_compile_arg, args.variant_run_arg)
    except ValueError as exc:
        die(str(exc))

    if args.cycles is None or args.cycles <= 0:
        die('实验模式必须指定正数 --cycles')
    if not args.schedule:
        die('实验模式必须指定 --schedule')
    if not args.anchor:
        die('实验模式必须指定 --anchor')
    if args.anchor not in {variant.name for variant in variants}:
        die(f'anchor 不存在: {args.anchor}')
    if args.schedule == 'anchor-pairs' and len(variants) < 2:
        die('anchor-pairs 至少需要 anchor 和一个 candidate')
    if args.ann_version is not None:
        die('实验模式不能使用 --ann-version；annotation A/B 请使用兼容模式')
    if not args.json:
        die('实验模式必须使用 --json 保存原始结果')

    names = [variant.name for variant in variants]
    try:
        if args.schedule == 'all-orders':
            schedule = build_all_orders(names, args.cycles)
        else:
            schedule = build_anchor_pair_orders(args.anchor, names, args.cycles)
    except ValueError as exc:
        die(str(exc))

    bench_dir = os.path.abspath(
        args.bench_dir or os.path.dirname(os.path.abspath(__file__)))
    if not args.only:
        die('实验模式必须使用 --only 明确指定 benchmark 文件或目录')
    benchmarks = discover_suites(bench_dir, only=args.only)
    if not benchmarks:
        die(f'未找到 benchmark（目录: {bench_dir}）')

    output_path = Path(args.json).resolve()
    if not output_path.parent.is_dir():
        die(f'JSON 输出目录不存在: {output_path.parent}')
    if output_path.exists():
        die(f'实验 session 已存在，拒绝覆盖: {output_path}')

    cache_dir = os.path.abspath(
        args.cache_dir or os.path.join(bench_dir, '.bench_cache'))
    os.makedirs(cache_dir, exist_ok=True)
    adapter = EngineAdapter(args.opt, args.cpu, args.cc)

    per_variant = len(schedule) if args.schedule == 'all-orders' else args.cycles * 2
    info(f"发现 {len(benchmarks)} 个 benchmark")
    info(
        f"实验: schedule={args.schedule}, cycles={args.cycles}, "
        f"anchor={args.anchor}, 每对象/配对样本={per_variant}"
    )

    output = {
        'schema': 'static-hermes-performance-experiment',
        'version': 1,
        'session': {
            'id': str(uuid.uuid4()),
            'started_at_utc': datetime.now(timezone.utc).isoformat(),
            'argv': sys.argv,
            'cwd': os.getcwd(),
        },
        'protocol': {
            'schedule': args.schedule,
            'anchor': args.anchor,
            'cycles': args.cycles,
            'warmup_runs_per_variant': 1,
            'timeout_seconds': 300,
            'time_unit': 'ms',
            'ratio_definition': 'anchor_elapsed_ms / candidate_elapsed_ms',
        },
        'provenance': build_provenance(args, variants, bench_dir),
        'benchmarks': [],
    }

    failed = False
    for benchmark in benchmarks:
        print_header(f"Benchmark: {benchmark['name']}")
        try:
            result = run_experiment_benchmark(
                adapter, benchmark, variants, schedule, cache_dir, args.anchor)
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            failed = True
            result = {
                'id': benchmark['name'],
                'status': 'failed',
                'source': {
                    'path': benchmark['js'],
                    'sha256': sha256_file(benchmark['js']),
                    'inputs': benchmark_input_manifest(benchmark['js']),
                },
                'error': str(exc),
            }
            print(f"  失败: {exc}")
        output['benchmarks'].append(result)

        if result['status'] == 'ok':
            for name, stats in result['summaries'].items():
                print_summary_line(name, stats)
            for comparison in result['anchor_comparisons']:
                speedup = comparison['speedup']['median']
                print(
                    f"  {comparison['candidate']} vs {args.anchor}: "
                    f"{speedup:.3f}x (paired median)"
                )

    try:
        write_json_new(output_path, output)
    except FileExistsError:
        die(f'实验 session 已存在，拒绝覆盖: {output_path}')
    print(f"结果已保存到: {output_path}")
    return 1 if failed else 0


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
    print(
        f"  {label:<20s}  median={fmt_ms(stats['median']):>10s}  "
        f"mean={fmt_ms(stats['mean']):>10s} ± "
        f"{fmt_pct(stats['bounds_pct']):>6s}  (n={stats['n']})"
    )


def print_comparison(baseline_stats, target_stats, target_label):
    baseline_median = baseline_stats['median']
    target_median = target_stats['median']
    if target_median <= 0 or baseline_median <= 0:
        print(f"  ? {target_label}: 无法计算")
        return
    speedup = baseline_median / target_median
    print(f"  {'↑' if speedup >= 1 else '↓'} {target_label}: {speedup:.3f}x")


def print_header(text):
    print()
    print('=' * 70)
    print(f"  {text}")
    print('=' * 70)


def info(msg):
    print(msg, file=sys.stderr, flush=True)


def die(msg) -> NoReturn:
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(1)


# ─── 兼容模式主流程 ───

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
        die('必须指定标注版本，例如 --ann-version v1（对应 annotations/v1/）')

    benchmarks = discover(
        bench_dir, f'annotations/{args.ann_version}', only=args.only)
    if not benchmarks:
        die(f"未找到 benchmark（目录: {bench_dir}）")

    info(f"发现 {len(benchmarks)} 个 benchmark")
    info(
        f"配置: iterations={args.iterations}, opt={args.opt}, "
        f"cpu={args.cpu if args.cpu is not None else 'any'}, cc={args.cc}"
    )
    all_results = []

    for benchmark in benchmarks:
        name = benchmark['name']
        js_file = benchmark['js']
        annotation = benchmark['annotation']
        print_header(f"Benchmark: {name}")

        safe_name = _safe_name(name)
        baseline_bin = os.path.join(runner.cache_dir, f'{safe_name}_baseline')
        annotated_bin = os.path.join(runner.cache_dir, f'{safe_name}_typeguard')
        try:
            runner.compile(js_file, baseline_bin)
            runner.compile(js_file, annotated_bin, annotation)
            samples = runner.measure_interleaved(
                [baseline_bin, annotated_bin], ['baseline', 'typeguard'],
                cwd=str(Path(js_file).parent),
            )
        except RuntimeError as exc:
            print(f"  失败: {exc}")
            continue

        baseline_stats = summarize(samples[0])
        annotated_stats = summarize(samples[1])
        result = {
            'name': name,
            'js': js_file,
            'baseline': baseline_stats,
            'typeguard': annotated_stats,
        }
        all_results.append(result)
        print_summary_line('baseline', baseline_stats)
        print_summary_line('typeguard', annotated_stats)
        print_comparison(baseline_stats, annotated_stats, 'typeguard')

    if all_results:
        print_header('汇总')
        speedups = []
        for result in all_results:
            baseline = result['baseline']['median']
            target = result['typeguard']['median']
            if baseline > 0 and target > 0:
                speedup = baseline / target
                speedups.append(speedup)
                print(f"  {result['name']:<35s} {speedup:>7.3f}x")
        if speedups:
            geomean = math.exp(sum(math.log(x) for x in speedups) / len(speedups))
            print(f"  {'geomean':<35s} {geomean:>7.3f}x")

    if args.json:
        output = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'config': {
                'shermes': runner.shermes,
                'opt': args.opt,
                'iterations': args.iterations,
            },
            'results': all_results,
        }
        with open(args.json, 'w', encoding='utf-8') as result_file:
            json.dump(output, result_file, indent=2, ensure_ascii=False)
        print(f"结果已保存到: {args.json}")


def main():
    parser = argparse.ArgumentParser(
        description='SH annotation A/B 与多引擎平衡性能实验',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--shermes', '-s',
        default='/home/zjc/js_engines/static-build-release/bin/shermes',
        help='兼容模式的 shermes 可执行文件路径',
    )
    parser.add_argument('--opt', default='-O', help='优化级别 (默认 -O)')
    parser.add_argument(
        '--iterations', '-n', type=int, default=20,
        help='兼容模式每配置测量次数 (默认 20)',
    )
    parser.add_argument(
        '--ann-version', '-a',
        help='兼容模式 annotation 版本（annotations/ 下的子目录）',
    )
    parser.add_argument(
        '--variant', nargs=3, action='append', metavar=('NAME', 'KIND', 'EXECUTABLE'),
        help='实验对象；KIND 为 v8、qjs、hbc 或 sh，可重复指定',
    )
    parser.add_argument(
        '--variant-compile-arg', action='append', default=[], metavar='NAME=ARG',
        help='给指定 variant 追加编译参数，可重复指定',
    )
    parser.add_argument(
        '--variant-run-arg', action='append', default=[], metavar='NAME=ARG',
        help='给指定 variant 追加运行参数，可重复指定',
    )
    parser.add_argument(
        '--schedule', choices=('all-orders', 'anchor-pairs'),
        help='实验调度：三对象六排列或 anchor AB/BA',
    )
    parser.add_argument('--anchor', help='实验归一化锚点的 variant 名称')
    parser.add_argument('--cycles', type=int, help='完整平衡调度的重复次数')
    parser.add_argument(
        '--only', help='只搜索 suites/ 下指定的相对路径（目录或文件）')
    parser.add_argument('--json', help='保存 JSON 结果到文件')
    parser.add_argument('--bench-dir', help='benchmark 目录（默认脚本目录）')
    parser.add_argument(
        '--cc', default='clang', help='SH 使用的 C 编译器 (默认 clang)')
    parser.add_argument(
        '--cpu', type=int, default=1,
        help='固定 CPU 核心编号 (默认 1，设 -1 不固定)',
    )
    parser.add_argument('--cache-dir', help='编译产物目录（默认 .bench_cache）')
    parser.add_argument(
        '--clean', action='store_true', help='运行前清理编译产物目录')
    args = parser.parse_args()

    if args.cpu is not None and args.cpu < 0:
        args.cpu = None
    if args.iterations <= 0:
        die('--iterations 必须是正数')
    if not args.variant and args.iterations % 2 != 0:
        die('兼容模式的 --iterations 必须是偶数，以完成 AB/BA 平衡块')

    if args.clean:
        cache = args.cache_dir or os.path.join(
            args.bench_dir or os.path.dirname(os.path.abspath(__file__)),
            '.bench_cache',
        )
        if os.path.isdir(cache):
            shutil.rmtree(cache)
            info(f"已清理缓存: {cache}")

    if args.variant:
        return run_experiment(args)
    run_all(args)
    return 0


if __name__ == '__main__':
    sys.exit(main())
