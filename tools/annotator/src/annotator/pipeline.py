"""Annotation run orchestration, outputs, and reporting."""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, TextIO

from .agents import AgentRun, AgentRunner
from .prompt import build_prompt


def generate_annotations(
    runner: AgentRunner,
    input_path: Path,
    source_text: str,
    output_path: Path,
    temp_root: Path,
) -> AgentRun:
    attempt_dir = temp_root / "attempt"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    annotation_path = attempt_dir / "annotation.json"

    prompt = build_prompt(input_path, source_text, annotation_path)
    (attempt_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

    run = runner.run(prompt, attempt_dir)
    if run.errors:
        return run

    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(annotation_path, output_path)
    return run


def write_stats(stats_path: Path, start_time: float, run: AgentRun) -> None:
    write_json(
        stats_path,
        {
            "duration_seconds": round(time.monotonic() - start_time, 3),
            "agent_metrics": run.metrics.to_json(),
        },
    )


def report_result(
    output_path: Path,
    stats_path: Path,
    temp_root: Path,
    keep_workdir: bool,
    run: AgentRun,
) -> int:
    if not run.errors:
        print(f"Wrote annotations to {output_path}")
        print(f"Wrote stats to {stats_path}")
        print_kept_workdir(temp_root, keep_workdir, sys.stdout)
        return 0

    print("Failed to generate annotations:", file=sys.stderr)
    for error in run.errors:
        print(f"  - {error}", file=sys.stderr)
    print_kept_workdir(temp_root, keep_workdir, sys.stderr)
    return 1


def print_kept_workdir(temp_root: Path, keep_workdir: bool, target: TextIO) -> None:
    if keep_workdir:
        print(f"Kept workdir at {temp_root}", file=target)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
