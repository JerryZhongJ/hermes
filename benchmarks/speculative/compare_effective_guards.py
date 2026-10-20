#!/usr/bin/env python3
"""Compare runtime-effective Jelly and coverage-guided guard ranges."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


HERE = Path(__file__).resolve().parent
DEFAULT_JELLY_DETAILS = (
    HERE
    / "results"
    / "jelly-v1-guard-rate-20260923"
    / "jelly_shape_guard_rate_guards.csv"
)
DEFAULT_JELLY_REPORT = (
    HERE
    / "results"
    / "jelly-v1-guard-rate-20260923"
    / "jelly_shape_by_kind.md"
)
DEFAULT_AGENT_DETAILS = (
    HERE
    / "results"
    / "coverage-guided-guard-rate-post-migration-20260924"
    / "coverage_guided_guard_rate_guards.csv"
)
DEFAULT_JELLY_ANNOTATIONS = HERE / "annotations" / "jelly-v1"
DEFAULT_AGENT_ANNOTATIONS = HERE / "annotations" / "coverage-guided"
DEFAULT_JELLY_PERFORMANCE = (
    HERE
    / "results"
    / "jelly-v1-guard-rate-20260923"
    / "jelly_shape_ablation.csv"
)
DEFAULT_AGENT_PERFORMANCE = (
    HERE
    / "results"
    / "coverage-guided-ablation-20260924"
    / "coverage_guided_ablation.csv"
)
DEFAULT_OUTPUT = (
    HERE
    / "results"
    / "effective-guard-comparison-20260924"
    / "effective_guard_comparison.md"
)
CATEGORIES = ("type", "closure", "shape guard", "shape binding")
ANNOTATION_SECTIONS = ("shape bindings", "shape guards", "type guards")


@dataclass
class Counter:
    success: int = 0
    fail: int = 0

    def add(self, success: int, fail: int) -> None:
        self.success += success
        self.fail += fail

    @property
    def checks(self) -> int:
        return self.success + self.fail


def category(kind: str) -> str:
    lowered = kind.lower()
    if "shape binding" in lowered:
        return "shape binding"
    if "shape guard" in lowered:
        return "shape guard"
    if "closure" in lowered:
        return "closure"
    return "type"


def normalize_niceformat(name: str) -> str:
    parts = name.split("/")
    if parts[-1].endswith("-niceformat"):
        parts[-1] = parts[-1][: -len("-niceformat")]
    return "/".join(parts)


def selected_jelly_names(report: Path) -> dict[str, str]:
    """Read the final Jelly table where niceformat already replaced originals."""
    selected: dict[str, str] = {}
    in_table = False
    row = re.compile(r"^\| ([^|]+?) \|")
    for line in report.read_text().splitlines():
        if line.startswith("| benchmark | type S/T"):
            in_table = True
            continue
        if in_table and line.startswith("## 按 suite 聚合"):
            break
        if not in_table or line.startswith("|---"):
            continue
        match = row.match(line)
        if not match:
            continue
        source_name = match.group(1).strip()
        selected[normalize_niceformat(source_name)] = source_name
    return selected


def read_performance(path: Path) -> dict[str, float]:
    """Read full-annotation speedups, normalizing niceformat benchmark names."""
    output: dict[str, float] = {}
    with path.open() as fh:
        for row in csv.DictReader(fh):
            if row.get("all_speedup"):
                output[normalize_niceformat(row["benchmark"])] = float(
                    row["all_speedup"]
                )
    return output


def read_effective(
    path: Path,
    allowed_names: set[str] | None = None,
    aliases: dict[str, str] | None = None,
) -> dict[str, dict[str, dict[str, Counter]]]:
    """benchmark -> loc -> category -> aggregated runtime counter."""
    output: dict[str, dict[str, dict[str, Counter]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(Counter))
    )
    with path.open() as fh:
        for row in csv.DictReader(fh):
            source_name = row["benchmark"]
            benchmark = normalize_niceformat(source_name)
            if allowed_names is not None and benchmark not in allowed_names:
                continue
            if aliases is not None and aliases.get(benchmark) != source_name:
                continue
            success = int(row["success"])
            fail = int(row["fail"])
            if success + fail == 0:
                continue
            output[benchmark][row["loc"]][category(row["kind"])].add(success, fail)
    return output


def range_loc(source_range: dict) -> str:
    start = source_range["start"]
    end = source_range["end"]
    return f"{start['line']}:{start['column']}-{end['line']}:{end['column']}"


def annotation_path(root: Path, benchmark: str) -> Path:
    direct = root / f"{benchmark}.json"
    legacy_directory = direct / "main.json"
    nested = root / benchmark / "main.json"
    if direct.is_file():
        return direct
    if legacy_directory.is_file():
        return legacy_directory
    if nested.is_file():
        return nested
    raise FileNotFoundError(f"annotation not found for {benchmark} under {root}")


def normalized_range(source_range: dict | None) -> dict | None:
    """Compare source locations without optional/spelling-dependent file names."""
    if source_range is None:
        return None
    return {
        "start": source_range.get("start"),
        "end": source_range.get("end"),
    }


def resolved_shape(document: dict, name: str | None) -> object:
    if name is None:
        return None
    shapes = document.get("static shapes", {})
    if name not in shapes:
        return {"unresolved shape": name}
    return shapes[name]


def normalized_shape_definition(definition: object) -> object:
    """Canonicalize semantically equivalent spellings inside a static shape."""
    if not isinstance(definition, dict):
        return definition
    normalized = {
        key: value for key, value in definition.items() if key != "properties"
    }
    properties = []
    for original in definition.get("properties", []):
        prop = dict(original)
        # An omitted property type means the same unrestricted type as `any`.
        prop.setdefault("type", "any")
        if "target function" in prop:
            prop["target function"] = normalized_range(prop["target function"])
        properties.append(prop)
    normalized["properties"] = properties
    return normalized


def semantic_signature(section: str, annotation: dict, document: dict) -> str:
    """Canonical operational meaning of one annotation, excluding its target."""
    if section == "type guards":
        payload = {
            "kind": section,
            "type": annotation.get("type"),
            "target function": normalized_range(annotation.get("target function")),
        }
    else:
        payload = {
            "kind": section,
            "shape definition": normalized_shape_definition(
                resolved_shape(document, annotation.get("shape"))
            ),
        }
        if section == "shape guards":
            payload["prototype shape definition"] = normalized_shape_definition(
                resolved_shape(document, annotation.get("prototype shape"))
            )
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def read_signatures(
    root: Path, benchmarks: list[str]
) -> dict[str, dict[str, set[str]]]:
    """benchmark -> expression range -> all annotation meanings at that range."""
    output: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for benchmark in benchmarks:
        document = json.loads(annotation_path(root, benchmark).read_text())
        for section in ANNOTATION_SECTIONS:
            for annotation in document.get(section, []):
                output[benchmark][range_loc(annotation["target range"])].add(
                    semantic_signature(section, annotation, document)
                )
    return output


def split_intersection(
    benchmark: str,
    jset: set[str],
    aset: set[str],
    jelly_signatures: dict[str, dict[str, set[str]]],
    agent_signatures: dict[str, dict[str, set[str]]],
) -> tuple[set[str], set[str]]:
    exact: set[str] = set()
    expression_only: set[str] = set()
    for loc in jset & aset:
        if jelly_signatures[benchmark].get(loc) == agent_signatures[benchmark].get(loc):
            exact.add(loc)
        else:
            expression_only.add(loc)
    return exact, expression_only


def accuracy_cell(counter: Counter) -> str:
    if not counter.checks:
        return "—"
    return f"{counter.success / counter.checks:.2%}"


def add_counter(destination: Counter, source: Counter) -> None:
    destination.add(source.success, source.fail)


def partition_subset(
    data: dict[str, dict[str, Counter]], locations: set[str]
) -> tuple[dict[str, Counter], dict[str, int]]:
    """Assign every unique range to exactly one category and aggregate it."""
    counters = {category_name: Counter() for category_name in CATEGORIES}
    counts = {category_name: 0 for category_name in CATEGORIES}
    for loc in locations:
        loc_counters = data.get(loc, {})
        category_name = next(
            (
                candidate
                for candidate in ("shape guard", "shape binding", "closure", "type")
                if candidate in loc_counters
            ),
            None,
        )
        if category_name is None:
            raise KeyError(f"effective range has no category: {loc}")
        counts[category_name] += 1
        for counter in loc_counters.values():
            add_counter(counters[category_name], counter)
    return counters, counts


def write_csvs(
    benchmarks: list[str],
    jelly: dict[str, dict[str, dict[str, Counter]]],
    agent: dict[str, dict[str, dict[str, Counter]]],
    jelly_signatures: dict[str, dict[str, set[str]]],
    agent_signatures: dict[str, dict[str, set[str]]],
    performance_differences: dict[str, float],
    output_dir: Path,
) -> None:
    with (output_dir / "effective_guard_sets.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "benchmark",
                "jelly_effective_ranges",
                "agent_effective_ranges",
                "intersection_ranges",
                "exact_match_ranges",
                "expression_only_ranges",
                "jelly_only_ranges",
                "agent_only_ranges",
                "agent_minus_jelly_performance_pct_points",
            ]
        )
        for benchmark in benchmarks:
            jset = set(jelly.get(benchmark, {}))
            aset = set(agent.get(benchmark, {}))
            exact, expression_only = split_intersection(
                benchmark, jset, aset, jelly_signatures, agent_signatures
            )
            writer.writerow(
                [
                    benchmark,
                    len(jset),
                    len(aset),
                    len(jset & aset),
                    len(exact),
                    len(expression_only),
                    len(jset - aset),
                    len(aset - jset),
                    performance_differences[benchmark],
                ]
            )

    with (output_dir / "effective_guard_accuracy.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "subset",
                "benchmark",
                "side",
                "category",
                "ranges",
                "success",
                "fail",
                "checks",
                "rate",
            ]
        )
        for benchmark in benchmarks:
            jset = set(jelly.get(benchmark, {}))
            aset = set(agent.get(benchmark, {}))
            _, expression_only = split_intersection(
                benchmark, jset, aset, jelly_signatures, agent_signatures
            )
            for subset, jlocs, alocs in (
                ("expression_only", expression_only, expression_only),
                ("difference", jset - aset, aset - jset),
            ):
                for side, data, locs in (
                    ("jelly", jelly.get(benchmark, {}), jlocs),
                    ("agent", agent.get(benchmark, {}), alocs),
                ):
                    counters, counts = partition_subset(data, locs)
                    for category_name in CATEGORIES:
                        counter = counters[category_name]
                        writer.writerow(
                            [
                                subset,
                                benchmark,
                                side,
                                category_name,
                                counts[category_name],
                                counter.success,
                                counter.fail,
                                counter.checks,
                                counter.success / counter.checks if counter.checks else "",
                            ]
                        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jelly-details", type=Path, default=DEFAULT_JELLY_DETAILS)
    parser.add_argument("--jelly-report", type=Path, default=DEFAULT_JELLY_REPORT)
    parser.add_argument("--agent-details", type=Path, default=DEFAULT_AGENT_DETAILS)
    parser.add_argument(
        "--jelly-annotations", type=Path, default=DEFAULT_JELLY_ANNOTATIONS
    )
    parser.add_argument(
        "--agent-annotations", type=Path, default=DEFAULT_AGENT_ANNOTATIONS
    )
    parser.add_argument(
        "--jelly-performance", type=Path, default=DEFAULT_JELLY_PERFORMANCE
    )
    parser.add_argument(
        "--agent-performance", type=Path, default=DEFAULT_AGENT_PERFORMANCE
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    aliases = selected_jelly_names(args.jelly_report)
    agent_all = read_effective(args.agent_details)
    benchmarks = sorted(agent_all)
    jelly = read_effective(
        args.jelly_details, allowed_names=set(benchmarks), aliases=aliases
    )
    agent = {benchmark: agent_all[benchmark] for benchmark in benchmarks}
    missing = [benchmark for benchmark in benchmarks if benchmark not in jelly]
    if missing:
        parser.error(f"missing selected Jelly data: {', '.join(missing)}")

    jelly_signatures = read_signatures(args.jelly_annotations, benchmarks)
    agent_signatures = read_signatures(args.agent_annotations, benchmarks)
    jelly_performance = read_performance(args.jelly_performance)
    agent_performance = read_performance(args.agent_performance)
    missing_performance = [
        benchmark
        for benchmark in benchmarks
        if benchmark not in jelly_performance or benchmark not in agent_performance
    ]
    if missing_performance:
        parser.error(
            "missing performance data: " + ", ".join(missing_performance)
        )
    performance_differences = {
        benchmark: 100
        * (agent_performance[benchmark] - jelly_performance[benchmark])
        for benchmark in benchmarks
    }
    for side, data, signatures in (
        ("Jelly", jelly, jelly_signatures),
        ("Agent", agent, agent_signatures),
    ):
        unmapped = [
            f"{benchmark}@{loc}"
            for benchmark in benchmarks
            for loc in data[benchmark]
            if loc not in signatures[benchmark]
        ]
        if unmapped:
            parser.error(
                f"{side} effective ranges absent from annotation JSON: "
                + ", ".join(unmapped[:10])
                + (f" ... ({len(unmapped)} total)" if len(unmapped) > 10 else "")
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_csvs(
        benchmarks,
        jelly,
        agent,
        jelly_signatures,
        agent_signatures,
        performance_differences,
        args.output.parent,
    )

    lines = [
        "# Jelly-shape 与 coverage-guided 有效 guard 比较",
        "",
        f"范围：coverage-guided 的 {len(benchmarks)} 个 benchmark；Jelly 对存在 niceformat 替代项时采用报告中的 niceformat 版本。",
        "有效 = 运行时 `success + fail > 0`。集合按 `benchmark + 表达式范围 loc` 去重。",
        "表达式交集再分为：**完全一致** = 同一范围上的标注集合，其 guard/binding 类别、type、target function、解析后的 shape/prototype shape 定义结构均相同；**仅表达式一致** = 范围相同但标注语义集合不同。shape 名称本身不参与比较，比较其定义结构。",
        "正确率按运行次数加权：`Σsuccess / Σ(success + fail)`。Agent 指 coverage-guided。",
        "性能差 = coverage-guided 与 jelly-shape 分类消融实验中全量标注 speedup 的差，即 `(Agent speedup − Jelly speedup) × 100` 个百分点；正值表示 Agent 更快。绝对值至少 5 个百分点的 benchmark 加粗。",
        "",
        "## 有效标注范围数量",
        "",
        "| benchmark | Jelly 有效 | Agent 有效 | 表达式交集 | 完全一致 | 仅表达式一致 | Jelly−Agent | Agent−Jelly | Agent−Jelly 性能 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    total_jelly: set[tuple[str, str]] = set()
    total_agent: set[tuple[str, str]] = set()
    total_exact: set[tuple[str, str]] = set()
    total_expression_only: set[tuple[str, str]] = set()
    for benchmark in benchmarks:
        jset = set(jelly[benchmark])
        aset = set(agent[benchmark])
        exact, expression_only = split_intersection(
            benchmark, jset, aset, jelly_signatures, agent_signatures
        )
        total_jelly.update((benchmark, loc) for loc in jset)
        total_agent.update((benchmark, loc) for loc in aset)
        total_exact.update((benchmark, loc) for loc in exact)
        total_expression_only.update((benchmark, loc) for loc in expression_only)
        performance_difference = performance_differences[benchmark]
        benchmark_cell = (
            f"**{benchmark}**"
            if abs(performance_difference) >= 5.0
            else benchmark
        )
        lines.append(
            f"| {benchmark_cell} | {len(jset)} | {len(aset)} | {len(jset & aset)} | "
            f"{len(exact)} | {len(expression_only)} | {len(jset - aset)} | "
            f"{len(aset - jset)} | {performance_difference:+.1f}% |"
        )
    lines.append(
        f"| **总计** | **{len(total_jelly)}** | **{len(total_agent)}** | "
        f"**{len(total_jelly & total_agent)}** | **{len(total_exact)}** | "
        f"**{len(total_expression_only)}** | **{len(total_jelly - total_agent)}** | "
        f"**{len(total_agent - total_jelly)}** | — |"
    )

    def append_accuracy_table(title: str, subset: str) -> None:
        lines.extend(
            (
                "",
                f"## {title}",
                "",
                "每个单元格为 `正确率（唯一表达式范围数）`。同一范围存在多类时按 `shape guard > shape binding > closure > type` 唯一归类。",
                "",
                "| benchmark | "
                + " | ".join(
                    f"{c} Jelly | {c} Agent" for c in CATEGORIES
                )
                + " |",
                "|---" + "|---:" * (2 * len(CATEGORIES)) + "|",
            )
        )
        grand = {
            side: {category_name: Counter() for category_name in CATEGORIES}
            for side in ("jelly", "agent")
        }
        grand_counts = {
            side: {category_name: 0 for category_name in CATEGORIES}
            for side in ("jelly", "agent")
        }
        for benchmark in benchmarks:
            jset = set(jelly[benchmark])
            aset = set(agent[benchmark])
            if subset == "expression_only":
                _, expression_only = split_intersection(
                    benchmark, jset, aset, jelly_signatures, agent_signatures
                )
                jlocs = alocs = expression_only
            else:
                jlocs, alocs = jset - aset, aset - jset
            jc, jcounts = partition_subset(jelly[benchmark], jlocs)
            ac, acounts = partition_subset(agent[benchmark], alocs)
            for category_name in CATEGORIES:
                add_counter(grand["jelly"][category_name], jc[category_name])
                add_counter(grand["agent"][category_name], ac[category_name])
                grand_counts["jelly"][category_name] += jcounts[category_name]
                grand_counts["agent"][category_name] += acounts[category_name]
            if not any(
                counter.checks for counter in (*jc.values(), *ac.values())
            ):
                continue
            cells = []
            for category_name in CATEGORIES:
                cells.extend(
                    (
                        f"{accuracy_cell(jc[category_name])}（{jcounts[category_name]}）",
                        f"{accuracy_cell(ac[category_name])}（{acounts[category_name]}）",
                    )
                )
            lines.append(f"| {benchmark} | " + " | ".join(cells) + " |")
        total_cells = []
        for category_name in CATEGORIES:
            total_cells.extend(
                (
                    f"**{accuracy_cell(grand['jelly'][category_name])}（{grand_counts['jelly'][category_name]}）**",
                    f"**{accuracy_cell(grand['agent'][category_name])}（{grand_counts['agent'][category_name]}）**",
                )
            )
        lines.append("| **总计** | " + " | ".join(total_cells) + " |")

    append_accuracy_table("仅表达式一致范围正确率", "expression_only")
    append_accuracy_table("差集范围正确率", "difference")
    args.output.write_text("\n".join(lines) + "\n")
    print(f"报告：{args.output}")


if __name__ == "__main__":
    main()
