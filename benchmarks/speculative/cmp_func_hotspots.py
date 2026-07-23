#!/usr/bin/env python3
"""
profile_c_hotspots.py — 复用 bench.py 的编译/计时/统计设施，新增 perf 调用栈归因，
打印每个 AOT C 函数（JS 函数编译为符号 _<id>_<name>）的 self/total **绝对时间**，
并可对比"带标注 / 不带标注"两个版本。

两个指标：
  self   = 扣除 JS→JS 调用边。最近 AOT 帧归因天然实现：F 经 _sh_ljs_call 调用的
           JS 函数 G 在 F 之上 → 样本归 G 不归 F。self[F] = F 自身代码 + 属性访问/
           运算 helper + 经 call 调用的 native builtin(如 Math.sqrt)。
  total  = 不扣除(inclusive)：调用栈上包含 F 的所有样本 = F + 其全部 JS 子函数。

绝对时间(ms) = 程序 Time 输出(无则 wall-clock)的 -n 次中位数 × perf 样本占比。
默认禁 SH 内联(-fno-inline)：-O 会把叶子函数 inline 进调用者导致只剩顶层函数，
无法区分各 JS 函数；--inline 恢复真实内联。
注：Math.sqrt 等 builtin 在 SH 中经 _sh_ljs_call 调用(非 _sh_ljs_call_builtin)。

复用 bench.py：BenchmarkRunner(compile/run_once/measure_interleaved)、median/summarize、
fmt_ms/fmt_pct/print_header、info/die。CLI 参数与 bench.py 一致(-s/--opt/-n/-a/--cpu/--cc)。

用法:
  %(prog)s [-n 10] <file.js>                          # 单版本 self/total
  %(prog)s -a jelly <suite.js>                        # 对比 baseline vs 标注
  %(prog)s -a jelly -n 20 --only box2d-niceformat ...  # (同 bench.py 风格)
"""
import argparse
import contextlib
import hashlib
import os
import re
import subprocess
import time
from pathlib import Path
from collections import defaultdict

from bench import BenchmarkRunner, median, fmt_ms, fmt_pct, print_header, info, die

AOT_FUNC = re.compile(r"^_\d+_")
VIA_CALL_EDGES = {"_sh_ljs_call", "_sh_ljs_callRequire"}
FRAME_RE = re.compile(r"^\s+([0-9a-fA-F]+)\s+(.+?)\s+\(([^)]*)\)\s*$")


def is_via_call(sym):
    return sym in VIA_CALL_EDGES or "_legacyCall" in sym


class ProfilingRunner(BenchmarkRunner):
    """扩展 bench.py 的 Runner：
    - compile 默认加 -fno-inline（profile 区分各 JS 函数的前提；-O 否则全 inline 进顶层）。
    - run_once 在程序无 'Time:' 输出时回退 wall-clock 计时（兼容任意程序）。
    其余（measure_interleaved 的 warmup + A-B-A-B 交叉、cache_dir、taskset 固定核）复用父类。"""

    def __init__(self, *a, no_inline=True, **kw):
        super().__init__(*a, **kw)
        self.no_inline = no_inline

    def compile(self, js_file, output_bin, annotation_file=None):
        cmd = [self.shermes, self.opt, '-fstatic-builtins']
        if self.no_inline:
            cmd.append('-fno-inline')
        if annotation_file:
            cmd.append(f'-annotation-file={annotation_file}')
        cmd += ['-o', output_bin, js_file]
        env = {**os.environ, 'CC': self.cc}
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise RuntimeError(f"编译失败: {' '.join(cmd)}\n{proc.stderr.strip()}")

    def run_once(self, binary, cwd=None):
        cmd = ['taskset', '-c', str(self.cpu), binary] if self.cpu is not None else [binary]
        t0 = time.perf_counter()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=cwd)
        elapsed = (time.perf_counter() - t0) * 1000.0
        if proc.returncode != 0:
            raise RuntimeError(f"运行失败 ({binary}):\n{proc.stderr.strip()}")
        for line in proc.stdout.splitlines():
            if line.startswith('Time:'):
                return float(line[5:].strip())
        return elapsed  # 回退 wall-clock


def find_annotation(bench_dir, ann_version, js_file):
    """定位标注（复用 bench.discover 的镜像路径逻辑）：
    annotations/<ann_version>/<js 相对 suites/ 的路径>.json。
    js 不在 suites/ 下时返回 None（改用 --annotation-file 直接指定）。"""
    suites_dir = Path(bench_dir) / 'suites'
    try:
        rel = Path(js_file).resolve().relative_to(suites_dir.resolve())
    except ValueError:
        return None
    pair = Path(bench_dir) / 'annotations' / ann_version / rel.with_suffix('.json')
    return str(pair) if pair.is_file() else None


# ─── perf 采样 + self/total 归因（bench.py 没有的部分） ───

def perf_record(binary, prog_args, freq, perf_data):
    cmd = ["perf", "record", "-F", str(freq), "--call-graph=dwarf,16384", "-g",
           "-o", str(perf_data), "--", binary] + prog_args
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        die(f"perf record 失败 (ret={proc.returncode})。"
            f"权限问题: sudo sysctl -w kernel.perf_event_paranoid=1")


def iter_chains(text):
    """yield 每个样本调用栈: list[sym], chain[0]=栈顶采样点 ... chain[-1]=main。"""
    chain = []
    for line in text.splitlines():
        m = FRAME_RE.match(line)
        if m:
            sym = m.group(2).strip()
            if sym != "[unknown]":
                sym = sym.split("+")[0] if "+" in sym else sym
            chain.append(sym)
        elif not line.strip():
            if chain:
                yield chain
                chain = []
    if chain:
        yield chain


def attribute(chains):
    """返回 (self_s, total_s, via_s, no_aot, n_total)。
    self[F]   = F 是离栈顶最近的 AOT 帧的样本数。
    total[F]  = 栈上含 F 的样本数(per-sample 去重防递归)。"""
    self_s, total_s, via_s = defaultdict(int), defaultdict(int), defaultdict(int)
    no_aot = n_total = 0
    for chain in chains:
        n_total += 1
        aot = [s for s in chain if AOT_FUNC.match(s)]  # 顺序: top → bottom
        if not aot:
            no_aot += 1
            continue
        nearest = aot[0]
        self_s[nearest] += 1
        idx0 = chain.index(nearest)
        callee = chain[idx0 - 1] if idx0 > 0 else None
        if callee is not None and is_via_call(callee):
            via_s[nearest] += 1
        seen = set()
        for s in aot:
            if s not in seen:
                total_s[s] += 1
                seen.add(s)
    return self_s, total_s, via_s, no_aot, n_total


def perf_attribute(binary, prog_args, freq, perf_data):
    perf_record(binary, prog_args, freq, perf_data)
    proc = subprocess.run(["perf", "script", "-i", perf_data], capture_output=True, text=True)
    if proc.returncode != 0:
        die("perf script 失败:\n" + proc.stderr)
    self_s, total_s, via_s, no_aot, n_total = attribute(iter_chains(proc.stdout))
    return {"self": self_s, "total": total_s, "via": via_s, "no_aot": no_aot, "n": n_total}


def ms_of(samples_f, n_total, t_median):
    return t_median * samples_f / n_total if n_total else 0.0


def _ms_str(x, delta=False):
    """对比表单元格(ms)：绝对值 X.X；delta=True 带符号 +/−。"""
    return f"{x:+.1f}" if delta else f"{x:.1f}"


def print_single(attr, t_median, n_iter, top, name):
    n = attr["n"]
    print_header(f"AOT C 函数热点 (绝对时间, JS→JS 已扣除)   源: {name}")
    print(f"  时间中位数({n_iter} 次): {fmt_ms(t_median)}    perf 样本: {n} (无 AOT 帧: {attr['no_aot']})")
    print()
    print(f"  {'self':>10}  {'total':>10}  {'via_call':>8}  function")
    print(f"  {'─'*10}  {'─'*10}  {'─'*8}  {'─'*34}")
    rows = sorted(attr["total"].keys(), key=lambda s: attr["self"][s], reverse=True)
    for sym in rows[:top]:
        s = ms_of(attr["self"][sym], n, t_median)
        tt = ms_of(attr["total"][sym], n, t_median)
        print(f"  {fmt_ms(s):>10}  {fmt_ms(tt):>10}  {attr['via'].get(sym,0):8d}  {sym}")
    if len(rows) > top:
        print(f"  ... 还有 {len(rows) - top} 个 AOT 函数未显示")


def print_compare(base_attr, base_t, ann_attr, ann_t, top, ann_file, n_iter):
    nb, na = base_attr["n"], ann_attr["n"]
    dt = ann_t - base_t
    dpct = (dt / base_t * 100) if base_t else 0
    print_header(f"标注对比: baseline(无标注)  vs  annotated({ann_file})")
    print(f"  时间中位数({n_iter} 次): base={fmt_ms(base_t)}   ann={fmt_ms(ann_t)}"
          f"   Δ={fmt_ms(dt)} ({fmt_pct(dpct)})")
    print()
    print(f"  {'function':<28} {'self_base':>9} {'self_ann':>9} {'Δself':>9}"
          f"  {'tot_base':>9} {'tot_ann':>9} {'Δtotal':>9}")
    print(f"  {'─'*28} {'─'*9} {'─'*9} {'─'*9}  {'─'*9} {'─'*9} {'─'*9}")
    syms = sorted(set(base_attr["total"]) | set(ann_attr["total"]),
                  key=lambda s: base_attr["self"].get(s, 0), reverse=True)
    for sym in syms[:top]:
        sb = ms_of(base_attr["self"].get(sym, 0), nb, base_t)
        sa = ms_of(ann_attr["self"].get(sym, 0), na, ann_t)
        tb_ = ms_of(base_attr["total"].get(sym, 0), nb, base_t)
        ta_ = ms_of(ann_attr["total"].get(sym, 0), na, ann_t)
        print(f"  {sym:<28} {_ms_str(sb):>9} {_ms_str(sa):>9} {_ms_str(sa-sb, True):>9}"
              f"  {_ms_str(tb_):>9} {_ms_str(ta_):>9} {_ms_str(ta_-tb_, True):>9}")
    if len(syms) > top:
        print(f"  ... 还有 {len(syms) - top} 个 AOT 函数未显示")


def main():
    ap = argparse.ArgumentParser(
        description="shermes AOT + perf 调用栈归因，打印 AOT C 函数 self/total 绝对时间(扣除 JS→JS)，可对比标注",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="程序参数放在 '--' 之后。CLI 与 bench.py 一致(-s/--opt/-n/-a/--cpu/--cc)。",
    )
    ap.add_argument("js_file", help="JS 源文件")
    ap.add_argument('-s', '--shermes', default='/home/zjc/js_engines/static-build-release/bin/shermes')
    ap.add_argument('--opt', default='-O', help='优化级别 (默认 -O)')
    ap.add_argument('-n', '--iterations', type=int, default=10, help='测时运行次数取中位数 (默认 10)')
    ap.add_argument('-a', '--ann-version', default=None, help='标注版本(annotations/ 下子目录); 给出则对比 baseline vs 标注')
    ap.add_argument('--annotation-file', default=None, help='直接指定标注 JSON 路径(与 -a 互补, 当 js 文件名与标注不匹配时用)')
    ap.add_argument('-o', '--output', default=None, help='结果写入文件(默认只打印 stdout; 进度信息仍到 stderr)')
    ap.add_argument('--cpu', type=int, default=1, help='固定 CPU 核 (默认 1, -1 不固定)')
    ap.add_argument('--cc', default='clang', help='C 编译器 (默认 clang)')
    ap.add_argument('--cache-dir', default=None, help='编译缓存目录 (默认 .bench_cache)')
    ap.add_argument('--inline', action='store_true', help='保留 SH 内联 (默认 -fno-inline 区分各函数)')
    ap.add_argument('--top', type=int, default=25, help='只显示前 N 个热点 (默认 25)')
    ap.add_argument('--freq', type=int, default=999, help='perf 采样频率 Hz (默认 999)')
    args, rest = ap.parse_known_args()
    prog_args = rest[1:] if rest and rest[0] == "--" else rest

    js = args.js_file
    if not os.path.isfile(js):
        die(f"找不到 JS 文件: {js}")
    if args.cpu is not None and args.cpu < 0:
        args.cpu = None

    runner = ProfilingRunner(
        args.shermes, opt=args.opt, iterations=args.iterations,
        cache_dir=args.cache_dir, cpu=args.cpu, cc=args.cc, no_inline=not args.inline)

    bench_dir = os.path.dirname(os.path.abspath(__file__))
    cwd = str(Path(js).resolve().parent)
    base_bin = os.path.join(runner.cache_dir, 'prof_base')
    ann_bin = ann_file = None

    try:
        info(f"[编译] baseline (无标注){' [-fno-inline]' if not args.inline else ''}")
        runner.compile(js, base_bin)
    except RuntimeError as e:
        die(str(e))

    ann_file = args.annotation_file
    if not ann_file and args.ann_version:
        ann_file = find_annotation(bench_dir, args.ann_version, js)
        if not ann_file:
            die(f"未找到标注: annotations/{args.ann_version}/{Path(js).stem}.json")
    if ann_file:
        ann_bin = os.path.join(runner.cache_dir, 'prof_ann')
        try:
            info(f"[编译] annotated (-annotation-file={ann_file})")
            runner.compile(js, ann_bin, ann_file)
        except RuntimeError as e:
            die(str(e))

    # 1) 计时（复用 bench.py 的 warmup + A-B-A-B 交叉测量）
    binaries = [base_bin] + ([ann_bin] if ann_bin else [])
    labels = ['baseline'] + (['annotated'] if ann_bin else [])
    info(f"[计时] 交叉测量 {args.iterations} 次/配置")
    samples = runner.measure_interleaved(binaries, labels, cwd=cwd)
    base_t = median(samples[0])
    ann_t = median(samples[1]) if ann_bin else None

    # 2) codegen 变化检测
    if ann_bin:
        mb = hashlib.md5(Path(base_bin).read_bytes()).hexdigest()[:12]
        ma = hashlib.md5(Path(ann_bin).read_bytes()).hexdigest()[:12]
        if mb == ma:
            info("[warn] baseline 与 annotated 二进制相同 —— 标注未改变 codegen"
                 " (type 标注在 SH 已推断的标量上无效, 或标注行号错位)")

    # 3) perf 采样归因（每版本一次）
    info("[perf] 采样 baseline...")
    base_attr = perf_attribute(base_bin, prog_args, args.freq,
                               os.path.join(runner.cache_dir, 'perf_base.data'))
    ann_attr = None
    if ann_bin:
        info("[perf] 采样 annotated...")
        ann_attr = perf_attribute(ann_bin, prog_args, args.freq,
                                  os.path.join(runner.cache_dir, 'perf_ann.data'))

    out_file = open(args.output, 'w') if args.output else None
    with contextlib.redirect_stdout(out_file) if out_file else contextlib.nullcontext():
        if ann_attr:
            print_compare(base_attr, base_t, ann_attr, ann_t, args.top, ann_file, args.iterations)
        else:
            print_single(base_attr, base_t, args.iterations, args.top, Path(js).name)
    if out_file:
        out_file.close()
        info(f"[结果已写入] {args.output}")


if __name__ == "__main__":
    main()
