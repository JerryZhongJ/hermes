#!/usr/bin/env python3
"""CLI entry point for the Hermes annotation generator."""

from __future__ import annotations

import logging
import shutil
from dataclasses import replace
import sys
import tempfile
import time
from pathlib import Path

from .agents import create_runner
from .config import load_config, parse_args
from .pipeline import generate_annotations, publish_trace, report_result, write_run_manifest


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        format="%(message)s",
        level=logging.INFO if args.verbose_agent_logs else logging.WARNING,
    )
    try:
        agent_config = load_config(args.config)
        if not args.input.exists():
            raise ValueError(f"Input file not found: {args.input}")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    output_path = args.output
    run_path = args.output_run or output_path.with_name(output_path.name + ".run.json")
    temp_root = Path(tempfile.mkdtemp(prefix="annotator-"))
    start_time = time.monotonic()
    try:
        runner = create_runner(agent_config, timeout_seconds=args.agent_timeout)
        run = generate_annotations(
            runner,
            args.input,
            output_path,
            temp_root,
            append_prompt=args.append_prompt,
            enabled_tools=agent_config.enabled_tools,
        )
        # Publish the native transcript before deleting the attempt directory.
        # The small manifest is the commit marker and remains useful on failure.
        try:
            run = publish_trace(run_path, run)
        except OSError as exc:
            run = replace(run, errors=[*run.errors, f"could not publish trace: {exc}"])
        write_run_manifest(
            run_path, args.input, output_path, start_time, agent_config.agent, run
        )
        return report_result(output_path, run_path, temp_root, args.keep_workdir, run)
    finally:
        if not args.keep_workdir:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
