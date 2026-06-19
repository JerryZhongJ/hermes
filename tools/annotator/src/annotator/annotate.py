#!/usr/bin/env python3
"""CLI entry point for the Hermes annotation generator."""

from __future__ import annotations

import logging
import shutil
import sys
import tempfile
import time
from pathlib import Path

from .agents import create_runner
from .config import load_config, parse_args
from .pipeline import generate_annotations, report_result, write_messages


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
    runner = create_runner(agent_config, timeout_seconds=args.agent_timeout)
    try:
        run = generate_annotations(
            runner,
            args.input,
            output_path,
            temp_root,
        )
        # Always dump the run record — even on failure the partial transcript
        # has value, and all stats are recomputed offline from this file.
        write_messages(run_path, args.input, start_time, agent_config.agent, run)
        return report_result(output_path, run_path, temp_root, args.keep_workdir, run)
    finally:
        if not args.keep_workdir:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
