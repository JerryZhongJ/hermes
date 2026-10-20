#!/usr/bin/env python3
"""从 guard 明细 CSV 生成 jelly-shape 分类正确率报告 jelly_shape_by_kind.md。

输入：jelly_guard_rate.py --detail 产出的 guards CSV（可多个，如 speedo 补测），
以及 annotations/ 下对应标注目录（统计三类 guard 总数）。
口径与 2026-09-23 报告一致：niceformat 版本有数据时取代原版。
"""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATEGORIES = ('type', 'closure', 'shape guard', 'shape binding')


def load_guards(paths):
    """benchmark -> ann_id -> (kind, loc, success, fail)"""
    out = defaultdict(dict)
    for p in paths:
        with open(p) as fh:
            for row in csv.DictReader(fh):
                out[row['benchmark']][int(row['ann_id'])] = (
                    row['kind'], row['loc'], int(row['success']), int(row['fail']))
    return out


def category(kind):
    if kind.startswith('shape binding'):
        return 'shape binding'
    if kind.startswith('shape guard'):
        return 'shape guard'
    if kind == 'type guard closure':
        return 'closure'
    return 'type'


def select_kept(benchmarks, ann_dir):
    """返回 (kept 排序列表, 被取代的原版名单, niceformat 版无数据而保留原版的名单)。

    benchmarks 为有 guard 数据的集合；niceformat 版本出现在其中（即有数据）才取代原版。
    """
    kept, replaced, no_data = [], [], []
    for b in sorted(benchmarks):
        kept.append(b)
        if b.endswith('-niceformat'):
            continue
        parts = b.rsplit('/', 1)
        candidate = f'{parts[0]}/{parts[1]}-niceformat' if len(parts) == 2 else None
        if candidate is None or not ann_path(ann_dir, candidate):
            continue
        if candidate in benchmarks:
            kept.pop()  # 原版被 niceformat 取代
            replaced.append(b)
        else:
            no_data.append(b)
    return kept, replaced, no_data


def ann_path(ann_dir, bench):
    p = ann_dir / f'{bench}.json'
    if p.is_file():
        return p
    p = ann_dir / bench / 'benchmark.json'
    if p.is_file():
        return p
    return None


def ann_totals(ann_dir, bench):
    """type/closure/shape 标注总数（shape = shape guard + shape binding）。"""
    p = ann_path(ann_dir, bench)
    if p is None:
        return None
    d = json.load(open(p))
    tg = d.get('type guards', [])
    return {
        'type': sum(1 for t in tg if t.get('type') != 'closure'),
        'closure': sum(1 for t in tg if t.get('type') == 'closure'),
        'shape guard': len(d.get('shape guards', [])),
        'shape binding': len(d.get('shape bindings', [])),
    }


def agg(rows):
    """[(kind, loc, s, f)] -> {cat: (success, checks, triggered, anomalous, worst)}

    worst = (最低单条成功率, ann_id) — checks>0 的 guard 中逐条最小值。
    """
    out = {}
    for cat in CATEGORIES:
        sub = [r for r in rows if category(r[0]) == cat]
        s = sum(r[2] for r in sub)
        checks = sum(r[2] + r[3] for r in sub)
        triggered = sum(1 for r in sub if r[2] + r[3] > 0)
        anomalous = sum(1 for r in sub if r[2] + r[3] > 0 and r[2] / (r[2] + r[3]) < 0.6)
        hit = [(r[2] / (r[2] + r[3]), r[4]) for r in sub if r[2] + r[3] > 0]
        worst = min(hit) if hit else None
        out[cat] = (s, checks, triggered, anomalous, worst)
    return out


def fmt_pct(x, digits=0):
    return f'{x * 100:.{digits}f}%'


def cell(s, checks, bold_below=0.90):
    if checks == 0:
        return '— | —'
    pct = s / checks
    text = fmt_pct(pct)
    if pct < bold_below:
        text = f'**{text}**'
    return f'{s}/{checks} | {text}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--guards', nargs='+', required=True)
    ap.add_argument('--ann-dir', default='jelly-v1')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    ann_dir = HERE / 'annotations' / args.ann_dir

    guards = load_guards(args.guards)
    kept, replaced, no_data = select_kept(guards, ann_dir)
    per_bench = {b: agg([v + (aid,) for aid, v in guards[b].items()]) for b in guards}

    lines = ['# jelly-shape 分类 guard 正确率（per benchmark，niceformat 取代原版；shape 拆分为 shape guard 与 shape binding）', '']
    note = f'（原版被取代 {len(replaced)} 个'
    if no_data:
        note += '；' + '、'.join(no_data) + ' 的 niceformat 版无数据，保留原版'
    note += '）'
    lines.append(f'去重前 {len(guards)} → 保留 {len(kept)} {note}')
    lines.append('格式：success/total 与 百分比 分列；**低于 90% 加粗**（type 不含 closure）')
    cat_header = '|'.join(f' {c} S/T | {c} % ' for c in CATEGORIES)
    lines += ['', f'| benchmark |{cat_header}|',
              '|---' * (1 + 2 * len(CATEGORIES)) + '|']

    suite_agg = defaultdict(lambda: {c: [0, 0] for c in CATEGORIES})
    suite_count = defaultdict(int)
    for b in kept:
        a = per_bench[b]
        lines.append('| ' + b + ' | ' + ' | '.join(
            cell(*a[c][:2]) for c in CATEGORIES) + ' |')
        suite = b.split('/')[0]
        suite_count[suite] += 1
        for c in CATEGORIES:
            suite_agg[suite][c][0] += a[c][0]
            suite_agg[suite][c][1] += a[c][1]

    lines += ['', '## 按 suite 聚合', '',
              f'| suite | benchmark数 |{cat_header}|',
              '|---' * (2 + 2 * len(CATEGORIES)) + '|']
    for suite in sorted(suite_agg):
        cells = []
        for c in CATEGORIES:
            s, n = suite_agg[suite][c]
            cells.append(cell(s, n) if n else '— | —')
        lines.append(f'| {suite} | {suite_count[suite]} | ' + ' | '.join(cells) + ' |')

    # 异常低值表：kept 集合，展示名去掉 -niceformat 后缀
    anomalies = []
    for b in kept:
        a = per_bench[b]
        cats = [c for c in CATEGORIES if a[c][1] > 0 and a[c][0] / a[c][1] < 0.6]
        if cats:
            anomalies.append((b, [(c, a[c]) for c in cats]))
    lines += ['', f'## 异常低值（<60%）benchmark（仅含有异常者，{len(anomalies)}/{len(kept)}）', '',
              '`成功率` = 该类触发 guard 中的最低单条成功率（括号内为 ann#）。',
              '',
              '| benchmark | 异常类别 | 成功率 | guard 条数 | 异常 guard 数（<60%） |',
              '|---|---|---|---|---|']
    cat_count = defaultdict(int)
    for b, cats in anomalies:
        name = b[:-len('-niceformat')] if b.endswith('-niceformat') else b
        for c, (_, _, triggered, anomalous, worst) in cats:
            rate = f'**{fmt_pct(worst[0], 1)}**（#{worst[1]}）' if worst else '—'
            lines.append(f'| {name} | {c} | {rate} | {triggered} | {anomalous} |')
            cat_count[c] += 1
    counts = '，'.join(f'{c}×{cat_count[c]}' for c in CATEGORIES if cat_count[c])
    lines += ['', f'异常类别出现次数: {counts}；共 {len(anomalies)} 个 benchmark']

    # 触发数/标注总数
    lines += ['', '## 四类 guard 触发数/标注总数', '',
              '“触发”指运行中 `success + fail > 0` 的不同 guard 数；“总数”取对应标注文件中的 guard 数。',
              '', '| benchmark | ' + ' | '.join(f'{c} 触发/总数' for c in CATEGORIES) + ' |',
              '|---|' + '---:|' * len(CATEGORIES)]
    for b in kept:
        a = per_bench[b]
        totals = ann_totals(ann_dir, b) or {c: '?' for c in CATEGORIES}
        cells = [f'{a[c][2]}/{totals[c]}' for c in CATEGORIES]
        lines.append(f'| {b} | ' + ' | '.join(cells) + ' |')

    Path(args.out).write_text('\n'.join(lines) + '\n')
    print(f'已写入 {args.out}（去重前 {len(guards)}，保留 {len(kept)}）')


if __name__ == '__main__':
    main()
