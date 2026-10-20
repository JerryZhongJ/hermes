#!/usr/bin/env python3
"""Run guard-accuracy measurements for coverage-guided annotations.

Each benchmark is compile-smoke-tested first. If the source in ``suites``
produces many unmatched annotations and a source exists at the same relative
path under ``raw-suites/suites``, the raw source is smoke-tested and selected
when it has fewer unmatched annotations.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


HERE = Path(__file__).resolve().parent
SUITES = HERE / "suites"
RAW_SUITES = HERE / "raw-suites" / "suites"
ANNOTATIONS = HERE / "annotations" / "coverage-guided"
DEFAULT_SHERMES = Path("~/js_engines/static-build-release/bin/shermes").expanduser()

GUARD_LINE = re.compile(
    r"ann#(\d+) \[([^\]]+)\] @(\d+):(\d+)-(\d+):(\d+): "
    r"success=(\d+), fail=(\d+)"
)
UNMATCHED_LINE = re.compile(r'annotation \[[^\]]+\] unmatched:')


@dataclass(frozen=True)
class Benchmark:
    name: str
    annotation: Path
    current_source: Path

    @property
    def raw_source(self) -> Path:
        return RAW_SUITES / self.current_source.relative_to(SUITES)


@dataclass
class Preflight:
    benchmark: Benchmark
    source: Path
    source_kind: str
    current_unmatched: int
    raw_unmatched: int | None
    status: str


@dataclass
class Guard:
    ann_id: int
    kind: str
    loc: str
    success: int
    fail: int


@dataclass
class Result:
    preflight: Preflight
    status: str
    runtime_unmatched: int
    guards: list[Guard]

    @property
    def triggered(self) -> int:
        return sum(g.success + g.fail > 0 for g in self.guards)

    @property
    def all_fail(self) -> int:
        return sum(g.fail > 0 and g.success == 0 for g in self.guards)

    @property
    def successes(self) -> int:
        return sum(g.success for g in self.guards)

    @property
    def checks(self) -> int:
        return sum(g.success + g.fail for g in self.guards)

    @property
    def rate(self) -> float:
        return self.successes / self.checks if self.checks else math.nan


def discover() -> list[Benchmark]:
    """Find only final annotation JSON files that map to runnable suites."""
    found: dict[str, Benchmark] = {}
    for annotation in sorted(ANNOTATIONS.rglob("*.json")):
        if not annotation.is_file():
            continue
        rel = annotation.relative_to(ANNOTATIONS)
        direct_source = SUITES / rel.with_suffix(".js")
        directory_source = SUITES / rel.parent / "benchmark.js"
        if direct_source.is_file():
            name = rel.with_suffix("").as_posix()
            source = direct_source
        elif directory_source.is_file():
            name = rel.parent.as_posix()
            source = directory_source
        else:
            continue
        found[name] = Benchmark(name, annotation.resolve(), source.resolve())

    # Some early runs published a directory whose name already ended in
    # ``.json``.  Its merged annotation is ``main.json`` inside that directory.
    for annotation_dir in sorted(ANNOTATIONS.rglob("*.json")):
        annotation = annotation_dir / "main.json"
        if not annotation_dir.is_dir() or not annotation.is_file():
            continue
        rel = annotation_dir.relative_to(ANNOTATIONS)
        source = SUITES / rel.with_suffix(".js")
        if not source.is_file():
            continue
        name = rel.with_suffix("").as_posix()
        found[name] = Benchmark(name, annotation.resolve(), source.resolve())
    return [found[name] for name in sorted(found)]


def run_process(cmd: list[str], cwd: Path, timeout: int) -> tuple[int | None, str, str]:
    env = {**os.environ, "CC": "clang"}
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (
            exc.stdout.decode(errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode(errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
        return None, stdout, stderr
    return proc.returncode, proc.stdout, proc.stderr


def smoke_source(
    source: Path, annotation: Path, shermes: Path, timeout: int
) -> tuple[int | None, int]:
    cmd = [
        str(shermes),
        "-O",
        "-fstatic-builtins",
        "-dump-ir",
        f"-annotation-file={annotation}",
        source.name,
    ]
    rc, stdout, stderr = run_process(cmd, source.parent, timeout)
    return rc, len(UNMATCHED_LINE.findall(stdout + "\n" + stderr))


def preflight(
    benchmark: Benchmark,
    shermes: Path,
    timeout: int,
    unmatched_threshold: int,
) -> Preflight:
    current_rc, current_unmatched = smoke_source(
        benchmark.current_source, benchmark.annotation, shermes, timeout
    )
    status = (
        "ok"
        if current_rc == 0
        else ("timeout" if current_rc is None else f"rc={current_rc}")
    )
    chosen = benchmark.current_source
    source_kind = "suites"
    raw_unmatched = None

    if current_unmatched >= unmatched_threshold and benchmark.raw_source.is_file():
        raw_rc, raw_unmatched = smoke_source(
            benchmark.raw_source, benchmark.annotation, shermes, timeout
        )
        if raw_rc == 0 and raw_unmatched < current_unmatched:
            chosen = benchmark.raw_source.resolve()
            source_kind = "raw-suites"
            status = "fallback"

    return Preflight(
        benchmark=benchmark,
        source=chosen,
        source_kind=source_kind,
        current_unmatched=current_unmatched,
        raw_unmatched=raw_unmatched,
        status=status,
    )


def run_one(pre: Preflight, shermes: Path, timeout: int) -> Result:
    cmd = [
        str(shermes),
        "-O",
        "-fstatic-builtins",
        "-exec",
        "-instrument-guards",
        f"-annotation-file={pre.benchmark.annotation}",
        pre.source.name,
    ]
    rc, stdout, stderr = run_process(cmd, pre.source.parent, timeout)
    combined = stdout + "\n" + stderr
    guards = [
        Guard(
            ann_id=int(match.group(1)),
            kind=match.group(2),
            loc="-".join(
                (
                    f"{match.group(3)}:{match.group(4)}",
                    f"{match.group(5)}:{match.group(6)}",
                )
            ),
            success=int(match.group(7)),
            fail=int(match.group(8)),
        )
        for match in GUARD_LINE.finditer(combined)
    ]
    status = "ok" if rc == 0 else ("timeout" if rc is None else f"rc={rc}")
    return Result(
        preflight=pre,
        status=status,
        runtime_unmatched=len(UNMATCHED_LINE.findall(combined)),
        guards=guards,
    )


def pct(value: float) -> str:
    return "—" if math.isnan(value) else f"{value:.2%}"


def guard_category(kind: str) -> str:
    lowered = kind.lower()
    if "shape guard" in lowered:
        return "shape"
    if "closure" in lowered:
        return "closure"
    return "type"


def category_stats(guards: list[Guard]) -> dict[str, tuple[int, int]]:
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for guard in guards:
        category = guard_category(guard.kind)
        totals[category][0] += guard.success
        totals[category][1] += guard.success + guard.fail
    return {key: (values[0], values[1]) for key, values in totals.items()}


def write_csvs(results: list[Result], out_dir: Path) -> None:
    with (out_dir / "coverage_guided_guard_rate.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "benchmark",
                "source",
                "status",
                "preflight_current_unmatched",
                "preflight_raw_unmatched",
                "runtime_unmatched",
                "triggered_guards",
                "all_fail_guards",
                "checks",
                "rate",
            ]
        )
        for result in results:
            pre = result.preflight
            writer.writerow(
                [
                    pre.benchmark.name,
                    pre.source_kind,
                    result.status,
                    pre.current_unmatched,
                    "" if pre.raw_unmatched is None else pre.raw_unmatched,
                    result.runtime_unmatched,
                    result.triggered,
                    result.all_fail,
                    result.checks,
                    "" if math.isnan(result.rate) else result.rate,
                ]
            )

    with (out_dir / "coverage_guided_guard_rate_guards.csv").open(
        "w", newline=""
    ) as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["benchmark", "source", "ann_id", "kind", "loc", "success", "fail"]
        )
        for result in results:
            for guard in result.guards:
                writer.writerow(
                    [
                        result.preflight.benchmark.name,
                        result.preflight.source_kind,
                        guard.ann_id,
                        guard.kind,
                        guard.loc,
                        guard.success,
                        guard.fail,
                    ]
                )

    with (out_dir / "coverage_guided_preflight.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "benchmark",
                "selected_source",
                "current_unmatched",
                "raw_unmatched",
                "preflight_status",
                "source_path",
            ]
        )
        for result in results:
            pre = result.preflight
            writer.writerow(
                [
                    pre.benchmark.name,
                    pre.source_kind,
                    pre.current_unmatched,
                    "" if pre.raw_unmatched is None else pre.raw_unmatched,
                    pre.status,
                    pre.source,
                ]
            )


def write_report(results: list[Result], out_dir: Path, threshold: int) -> Path:
    report = out_dir / "coverage_guided_guard_rate.md"
    successful = [result for result in results if result.status == "ok"]
    fallback = [
        result for result in results if result.preflight.source_kind == "raw-suites"
    ]
    total_success = sum(result.successes for result in successful)
    total_checks = sum(result.checks for result in successful)
    total_rate = total_success / total_checks if total_checks else math.nan

    lines = [
        "# coverage-guided 标注运行时 guard 正确率",
        "",
        f"- benchmark：{len(results)} 个；成功 {len(successful)} 个",
        f"- 加权总正确率：{pct(total_rate)}（{total_success}/{total_checks}）",
        f"- unmatched 回退阈值：{threshold}；使用 raw-suites：{len(fallback)} 个",
        "",
        "## 总表",
        "",
        "| benchmark | 源码 | 状态 | unmatched | 触发 guard | 全失败 guard | checks | 正确率 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        lines.append(
            "| "
            + " | ".join(
                [
                    result.preflight.benchmark.name,
                    result.preflight.source_kind,
                    result.status,
                    str(result.runtime_unmatched),
                    str(result.triggered),
                    str(result.all_fail),
                    str(result.checks),
                    pct(result.rate),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## 按 guard 类别",
            "",
            "| benchmark | type S/T | type % | closure S/T | closure % | shape S/T | shape % |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for result in results:
        stats = category_stats(result.guards)
        cells = [result.preflight.benchmark.name]
        for category in ("type", "closure", "shape"):
            success, total = stats.get(category, (0, 0))
            cells.extend(
                [
                    f"{success}/{total}" if total else "—",
                    pct(success / total) if total else "—",
                ]
            )
        lines.append("| " + " | ".join(cells) + " |")

    suite_totals: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(lambda: [0, 0])
    )
    suite_benchmarks: dict[str, int] = defaultdict(int)
    for result in successful:
        suite = result.preflight.benchmark.name.split("/", 1)[0]
        suite_benchmarks[suite] += 1
        for category, (success, total) in category_stats(result.guards).items():
            suite_totals[suite][category][0] += success
            suite_totals[suite][category][1] += total

    lines.extend(
        [
            "",
            "## 按 suite 聚合",
            "",
            "| suite | benchmark 数 | type S/T | type % | closure S/T | closure % | shape S/T | shape % |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for suite in sorted(suite_benchmarks):
        cells = [suite, str(suite_benchmarks[suite])]
        for category in ("type", "closure", "shape"):
            success, total = suite_totals[suite].get(category, (0, 0))
            cells.extend(
                [
                    f"{success}/{total}" if total else "—",
                    pct(success / total) if total else "—",
                ]
            )
        lines.append("| " + " | ".join(cells) + " |")

    lines.extend(
        [
            "",
            "## 源码回退",
            "",
            "| benchmark | suites unmatched | raw-suites unmatched | 采用 |",
            "|---|---:|---:|---:|",
        ]
    )
    if fallback:
        for result in fallback:
            pre = result.preflight
            lines.append(
                f"| {pre.benchmark.name} | {pre.current_unmatched} | "
                f"{pre.raw_unmatched} | {pre.source_kind} |"
            )
    else:
        lines.append("| — | — | — | — |")

    report.write_text("\n".join(lines) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shermes", type=Path, default=DEFAULT_SHERMES)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--smoke-timeout", type=int, default=120)
    parser.add_argument("--unmatched-threshold", type=int, default=5)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=HERE / "results" / "coverage-guided-guard-rate-20260924",
    )
    parser.add_argument("benchmarks", nargs="*")
    args = parser.parse_args()

    benchmarks = discover()
    if args.benchmarks:
        wanted = set(args.benchmarks)
        benchmarks = [
            benchmark for benchmark in benchmarks if benchmark.name in wanted
        ]
        missing = wanted - {benchmark.name for benchmark in benchmarks}
        if missing:
            parser.error(f"unknown benchmark(s): {', '.join(sorted(missing))}")
    if not benchmarks:
        parser.error("no benchmarks discovered")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    results: list[Result] = []
    for index, benchmark in enumerate(benchmarks, 1):
        pre = preflight(
            benchmark,
            args.shermes,
            args.smoke_timeout,
            args.unmatched_threshold,
        )
        raw_note = (
            "" if pre.raw_unmatched is None else f", raw unmatched={pre.raw_unmatched}"
        )
        print(
            f"[{index}/{len(benchmarks)}] {benchmark.name}: smoke current "
            f"unmatched={pre.current_unmatched}{raw_note}; use {pre.source_kind}",
            flush=True,
        )
        result = run_one(pre, args.shermes, args.timeout)
        results.append(result)
        print(
            f"  {result.status}: runtime unmatched={result.runtime_unmatched}, "
            f"触发 guard={result.triggered}, 全 fail={result.all_fail}, "
            f"checks={result.checks}, 正确率={pct(result.rate)}",
            flush=True,
        )
        write_csvs(results, args.out_dir)
        write_report(results, args.out_dir, args.unmatched_threshold)

    report = write_report(results, args.out_dir, args.unmatched_threshold)
    print(f"\n报告：{report}", flush=True)


if __name__ == "__main__":
    main()
