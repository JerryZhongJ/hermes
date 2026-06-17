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
from .pipeline import generate_annotations, report_result, write_stats


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
        source_text = args.input.read_text(encoding="utf-8")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    output_path = args.output
    stats_path = args.stats or output_path.with_name(output_path.name + ".stats.json")
    temp_root = Path(tempfile.mkdtemp(prefix="annotator-"))
    start_time = time.monotonic()
    runner = create_runner(agent_config, timeout_seconds=args.agent_timeout)
    try:
        run = generate_annotations(
            runner,
            args.input,
            source_text,
            output_path,
            temp_root,
        )
        if not run.errors:
            write_stats(stats_path, start_time, run)
        return report_result(output_path, stats_path, temp_root, args.keep_workdir, run)
    finally:
        if not args.keep_workdir:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
