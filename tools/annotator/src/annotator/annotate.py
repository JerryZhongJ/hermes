#!/usr/bin/env python3
"""CLI entry point for the Hermes annotation generator."""

from __future__ import annotations

import logging
import shutil
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from .agents import create_runner
from .config import effective_config, load_config, parse_args, validate_workflow_targets
from .pipeline import (
    generate_annotations,
    publish_trace,
    report_result,
    write_run_manifest,
)
from .workflows import AnnotationRequest, get_workflow_factory


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        format="%(message)s",
        level=logging.INFO if args.verbose_agent_logs else logging.WARNING,
    )
    try:
        agent_config = effective_config(load_config(args.config))
        if not args.input.exists():
            raise ValueError(f"Input file not found: {args.input}")
        factory = get_workflow_factory(args.workflow)
        targets = validate_workflow_targets(
            factory.name, args.target_function, args.input
        )
        if args.output.exists():
            # The whole attempt workdir is promoted into a fresh directory;
            # refusing an existing path prevents mixing results (or
            # overwriting) across runs.
            raise ValueError(f"output path already exists: {args.output}")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    output_path = args.output
    output_path.mkdir(parents=True)
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
            request=AnnotationRequest(
                source_path=args.input,
                workflow=factory.name,
                targets=targets,
                enabled_tools=tuple(agent_config.enabled_tools or ()),
            ),
        )
        run = replace(run, workflow=factory.name)

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
