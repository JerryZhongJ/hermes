#!/usr/bin/env python3
"""jelly-shape 标注分类消融性能测试。

把每个标注拆成 type(非closure) / closure / shape 三类，与 baseline、全量共 5 配置，
各 1 warmup + N 次计时取中位，speedup = base/variant。
结果增量写入 markdown + csv，可中断续看。
"""
import argparse
import json
import os
import statistics
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITES = HERE / 'suites'
ANN = HERE / 'annotations' / 'jelly-shape'
TMP = Path('/tmp/jelly_ablation')
SHERMES = Path('~/js_engines/static-build-release/bin/shermes').expanduser()
EXCLUDE = {'micros', 'benchmarksgame', 'speedometer-todomvc', 'v8-curve'}

CONFIGS = ['all', 'type', 'closure', 'shape']


def all_benches():
    out = []
    for j in sorted(ANN.rglob('*.json')):
        if j.name.endswith('.bak'):
            continue
        rel = j.relative_to(ANN)
        if rel.parts[0] in EXCLUDE:
            continue
        js = SUITES / rel.with_suffix('.js')
        if js.is_file():
            out.append(rel.with_suffix('').as_posix())
        elif (SUITES / rel.parent / 'benchmark.js').is_file():
            out.append(rel.parent.as_posix())
    return out


def resolve(b):
    js = SUITES / f'{b}.js'
    ann = ANN / f'{b}.json'
    if not js.is_file():
        js = SUITES / b / 'benchmark.js'
        ann = ANN / b / 'benchmark.json'
    return js, ann


def make_variants(b, ann):
    """返回 {config: annotation路径或None}；某类为空则该 config 为 None。"""
    d = json.load(open(ann))
    shapes = d.get('static shapes', [])
    sbindings = d.get('shape bindings', [])
    sguards = d.get('shape guards', [])
    tg = d.get('type guards', [])
    empty_shapes = {} if isinstance(shapes, dict) else []
    outs = {'all': ann}
    TMP.mkdir(exist_ok=True)
    safe = b.replace('/', '_')
    for cfg, keep_tg, keep_shape in (
            ('type', lambda t: t.get('type') != 'closure', False),
            ('closure', lambda t: t.get('type') == 'closure', False),
            ('shape', lambda t: False, True)):
        n_tg = [t for t in tg if keep_tg(t)]
        if keep_shape:
            if not sbindings and not sguards:
                outs[cfg] = None
                continue
            sub = {'static shapes': shapes, 'shape bindings': sbindings,
                   'shape guards': sguards}
        else:
            if not n_tg:
                outs[cfg] = None
                continue
            sub = {'static shapes': empty_shapes, 'shape bindings': [],
                   'shape guards': [], 'type guards': n_tg}
        p = TMP / f'{safe}.{cfg}.json'
        json.dump(sub, open(p, 'w'))
        outs[cfg] = p
    return outs


def compile_bin(js, out_bin, annotation):
    cmd = [str(SHERMES), '-O', '-fstatic-builtins']
    if annotation:
        cmd.append(f'-annotation-file={annotation}')
    cmd += ['-o', str(out_bin), str(js)]
    env = {**os.environ, 'CC': 'clang'}
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env,
                          timeout=900)
    return proc.returncode, proc.stderr[-200:]


def time_bin(bin_path, runs, cpu, timeout):
    times = []
    for i in range(runs + 1):  # 第 1 次 warmup
        cmd = ['taskset', '-c', str(cpu), str(bin_path)]
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
        if proc.returncode != 0:
            return None
        el = time.perf_counter() - t0
        if i > 0:
            times.append(el)
    return statistics.median(times)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runs', type=int, default=3)
    ap.add_argument('--cpu', type=int, default=1)
    ap.add_argument('--timeout', type=int, default=600)
    ap.add_argument('--md', default='/tmp/jelly_shape_ablation.md')
    ap.add_argument('benches', nargs='*')
    args = ap.parse_args()
    benches = args.benches or all_benches()

    bin_dir = TMP / 'bins'
    bin_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, b in enumerate(benches, 1):
        js, ann = resolve(b)
        if not js.is_file():
            continue
        variants = make_variants(b, ann)
        safe = b.replace('/', '_')
        med = {}
        for cfg in ['base'] + CONFIGS:
            binp = bin_dir / f'{safe}.{cfg}'
            a = None if cfg == 'base' else variants[cfg]
            if cfg != 'base' and a is None:
                continue
            try:
                rc, err = compile_bin(js, binp, a)
            except subprocess.TimeoutExpired:
                rc, med[cfg] = 124, None
                continue
            if rc != 0:
                print(f"[{i}] {b} {cfg}: 编译失败 {err}", flush=True)
                continue
            m = time_bin(binp, args.runs, args.cpu, args.timeout)
            if m is None:
                print(f"[{i}] {b} {cfg}: 运行失败/超时", flush=True)
                continue
            med[cfg] = m
        base = med.get('base')
        row = {'benchmark': b, 'base': base}
        for cfg in CONFIGS:
            m = med.get(cfg)
            row[cfg] = (base / m) if (base and m) else None  # speedup
        rows.append(row)
        write_outputs(rows, args.md)
        desc = ' '.join(
            f"{c}={(row[c]-1)*100:+.1f}%" if row[c] else f"{c}=—"
            for c in CONFIGS)
        print(f"[{i}/{len(benches)}] {b}: base={base and f'{base:.2f}s'} {desc}",
              flush=True)
    write_outputs(rows, args.md, final=True)
    print("done")


def write_outputs(rows, md_path, final=False):
    def pct(v):
        if not v:
            return '—'
        d = (v - 1) * 100
        return f"{d:+.0f}%"

    lines = ['# jelly-shape 分类消融性能（speedup vs 无标注 baseline）', '',
             '总 = 完整 jelly-shape 标注；各类为单独消融；差 = 该类 Δ% − 总 Δ%（正值表示该类比全量更有利）',
             '', '| benchmark | 总 | type | closure | shape | type−总 | closure−总 | shape−总 |',
             '|---|---|---|---|---|---|---|---|']
    for r in rows:
        cells = [pct(r.get(c)) for c in CONFIGS]
        total_d = (r['all'] - 1) * 100 if r.get('all') else None
        diffs = []
        for c in CONFIGS[1:]:
            if r.get(c) and total_d is not None:
                diffs.append(f"{(r[c]-1)*100 - total_d:+.0f}%")
            else:
                diffs.append('—')
        lines.append(f"| {r['benchmark']} | " + ' | '.join(cells + diffs) + ' |')
    if not final:
        lines += ['', f'(进行中，已完成 {len(rows)})']
    open(md_path, 'w').write('\n'.join(lines) + '\n')
    csvp = Path(md_path).with_suffix('.csv')
    with open(csvp, 'w') as f:
        f.write('benchmark,base_s,all_speedup,type_speedup,closure_speedup,shape_speedup\n')
        for r in rows:
            f.write(f"{r['benchmark']},{r['base'] or ''},"
                    + ','.join(str(r[c]) if r.get(c) else '' for c in CONFIGS)
                    + '\n')


if __name__ == '__main__':
    main()
