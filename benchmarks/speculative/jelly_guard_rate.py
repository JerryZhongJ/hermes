#!/usr/bin/env python3
"""jelly 标注运行时正确率统计：-instrument-guards 跑一遍，解析 ann#N success/fail。

用法: python3 jelly_guard_rate.py [--timeout 300] [--out jelly_guard_rate.csv] [--all] [bench ...]
bench 形如 octane/box2d；裸跑即全部 jelly 标注 benchmark（排除 micros/benchmarksgame/
speedometer-todomvc/v8-curve）。
"""
import argparse
import os
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITES = HERE / 'suites'
ANN = HERE / 'annotations' / 'jelly'
SHERMES = Path('~/js_engines/static-build-release/bin/shermes').expanduser()

# ann#12 [type guard object] @34:9-34:13: success=123, fail=45
LINE = re.compile(
    r'ann#(\d+) \[([^\]]+)\] @(\d+):(\d+)-(\d+):(\d+): success=(\d+), fail=(\d+)')


def resolve(b):
    """benchmark 名 -> (js, annotation)；jetstream 目录型用 benchmark.js。"""
    js = SUITES / f'{b}.js'
    ann = ANN / f'{b}.json'
    if not js.is_file():
        js = SUITES / b / 'benchmark.js'
        ann = ANN / b / 'benchmark.json'
    return js, ann


def run_one(b, timeout):
    js, ann = resolve(b)
    if not js.is_file() or not ann.is_file():
        return None, {}, 'missing-file'
    cmd = [str(SHERMES), '-O', '-fstatic-builtins', '-exec',
           '-instrument-guards', f'-annotation-file={ann}', str(js)]
    env = {**os.environ, 'CC': 'clang'}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, env=env, cwd=str(js.parent))
    except subprocess.TimeoutExpired:
        return None, {}, 'timeout'
    stats = {}  # ann# -> (kind, loc, success, fail)
    for m in LINE.finditer(proc.stdout + '\n' + proc.stderr):
        aid, kind, l1, c1, l2, c2, s, fl = m.groups()
        stats[int(aid)] = (kind, f'{l1}:{c1}-{l2}:{c2}', int(s), int(fl))
    return proc.returncode, stats, ('ok' if proc.returncode == 0 else f'rc={proc.returncode}')


def all_benches():
    """枚举全部 jelly 标注 benchmark（口径同 mem_jelly_ab.py）。"""
    exclude = {'micros', 'benchmarksgame', 'speedometer-todomvc', 'v8-curve'}
    out = []
    for j in sorted(ANN.rglob('*.json')):
        if j.name.endswith('.bak'):
            continue
        rel = j.relative_to(ANN)
        if rel.parts[0] in exclude:
            continue
        js = SUITES / rel.with_suffix('.js')
        if js.is_file():
            out.append(rel.with_suffix('').as_posix())
        elif (SUITES / rel.parent / 'benchmark.js').is_file():
            out.append(rel.parent.as_posix())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--timeout', type=int, default=300)
    ap.add_argument('--out', default=str(HERE / 'jelly_guard_rate.csv'))
    ap.add_argument('--all', action='store_true', help='跑全部 jelly 标注 benchmark')
    ap.add_argument('--ann-dir', default='jelly',
                    help='标注目录名（annotations/ 下），如 jelly / jelly-shape')
    ap.add_argument('--detail', action='store_true',
                    help='同时输出 per-guard 明细 CSV 到 /tmp')
    ap.add_argument('benches', nargs='*', default=[])
    args = ap.parse_args()
    global ANN
    ANN = HERE / 'annotations' / args.ann_dir
    benches = all_benches() if args.all or not args.benches else args.benches
    detail_fh = open(f"/tmp/{Path(args.out).stem}_guards.csv", 'w') if args.detail else None
    if detail_fh:
        detail_fh.write("benchmark,ann_id,kind,loc,success,fail\n")

    rows = []
    for i, b in enumerate(benches, 1):
        rc, stats, status = run_one(b, args.timeout)
        if stats is None:
            print(f"[{i}/{len(benches)}] {b}: {status}", flush=True)
            rows.append((b, status, 0, 0, 0, 0.0))
            continue
        s = sum(v[2] for v in stats.values())
        f = sum(v[3] for v in stats.values())
        triggered = sum(1 for v in stats.values() if v[2] + v[3] > 0)
        allfail = sum(1 for v in stats.values() if v[3] > 0 and v[2] == 0)
        rate = s / (s + f) if s + f else float('nan')
        if detail_fh:
            for aid, (kind, loc, su, fa) in sorted(stats.items()):
                detail_fh.write(f"{b},{aid},{kind},{loc},{su},{fa}\n")
        rows.append((b, status, triggered, allfail, s + f, rate))
        print(f"[{i}/{len(benches)}] {b}: {status} 触发guard={triggered} "
              f"全fail={allfail} 次数={s+f} 正确率={rate:.4f}" if s + f else
              f"[{i}/{len(benches)}] {b}: {status} 无触发guard", flush=True)
    with open(args.out, 'w') as fh:
        fh.write("benchmark,status,triggered_guards,all_fail_guards,checks,rate\n")
        for b, st, t, af, n, r in rows:
            fh.write(f"{b},{st},{t},{af},{n},{r if r == r else ''}\n")
    if detail_fh:
        detail_fh.close()
        print(f"per-guard 明细已写入 /tmp/{Path(args.out).stem}_guards.csv")
    print(f"\n已写入 {args.out}")


if __name__ == '__main__':
    main()
