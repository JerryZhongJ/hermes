"""Annotation run orchestration, outputs, and reporting."""

from __future__ import annotations

import json
import logging
import shutil
import sys
import time
from pathlib import Path
from typing import Any, TextIO

from .agents import AgentRun, AgentRunner
from .prompt import build_prompt

LOGGER = logging.getLogger(__name__)


def generate_annotations(
    runner: AgentRunner,
    input_path: Path,
    output_path: Path,
    temp_root: Path,
    append_prompt: str | None = None,
    enabled_tools: list[str] | None = None,
) -> AgentRun:
    annotation_path = temp_root / "annotation.json"
    shutil.copyfile(input_path, temp_root / input_path.name)

    prompt = build_prompt(input_path, annotation_path, enabled_tools)
    if append_prompt:
        prompt = prompt + "\n\n" + append_prompt
    LOGGER.info("prompt:\n%s", prompt)

    run = runner.run(prompt, temp_root, input_path.name)
    if run.errors:
        return run

    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(annotation_path, output_path)
    return run


def write_messages(
    path: Path, input_path: Path, start_time: float, agent: str, run: AgentRun
) -> None:
    """Dump raw agent messages (thinking_tokens filtered) for post-hoc analysis.

    meta holds non-message-derived facts (duration is wall-clock, not in the
    stream; agent selects the postprocess extractor); everything
    token/cost/tool-related is recomputable from messages.
    """
    write_json(
        path,
        {
            "meta": {
                "input": str(input_path),
                "agent": agent,
                "duration_seconds": round(time.monotonic() - start_time, 3),
                "errors": run.errors,
            },
            "messages": run.messages,
        },
    )


def report_result(
    output_path: Path,
    messages_path: Path,
    temp_root: Path,
    keep_workdir: bool,
    run: AgentRun,
) -> int:
    if not run.errors:
        print(f"Wrote annotations to {output_path}")
        print(f"Wrote messages to {messages_path}")
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
