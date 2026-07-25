"""Annotation run orchestration, outputs, and reporting."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, TextIO

from .agents import AgentRun, AgentRunner, TraceArtifact
from .prompt import ABOUT_ANNOTATIONS_FILENAME, build_about_annotations_markdown, build_prompt
from .tools.annotation_tool import AnnotationDocument
from .tools.utils import atomic_write_json

LOGGER = logging.getLogger(__name__)


def generate_annotations(
    runner: AgentRunner,
    input_path: Path,
    output_path: Path,
    temp_root: Path,
    append_prompt: str | None = None,
    enabled_tools: list[str] | None = None,
) -> AgentRun:
    # The agent maintains the annotation document IN MEMORY via the annotation
    # MCP tools; the worker flushes it to .annotations.json at run end. That
    # flushed file is the real product — promoted to output below.
    source_annotations = temp_root / ".annotations.json"
    shutil.copyfile(input_path, temp_root / input_path.name)
    (temp_root / ABOUT_ANNOTATIONS_FILENAME).write_text(
        build_about_annotations_markdown(), encoding="utf-8"
    )

    prompt = build_prompt(input_path, enabled_tools)
    if append_prompt:
        prompt = prompt + "\n\n" + append_prompt
    LOGGER.info("prompt:\n%s", prompt)

    run = runner.run(prompt, temp_root, input_path.name)
    if run.errors:
        return run

    # Promote the flushed in-memory document to the output, validating first so
    # we never publish a malformed annotation file.
    try:
        document = _load_and_validate(source_annotations)
    except (OSError, ValueError) as exc:
        return replace(run, errors=[f"annotation document invalid: {exc}"])

    atomic_write_json(output_path, document)
    return run


def _load_and_validate(path: Path) -> dict[str, Any]:
    """Load and fully validate a flushed annotation document before publishing."""
    import json as _json

    raw = path.read_text(encoding="utf-8")
    document = _json.loads(raw)
    doc = AnnotationDocument.empty()
    doc.load_from_dict(document)
    return doc.to_dict()


def publish_trace(run_path: Path, run: AgentRun) -> AgentRun:
    """Copy the native Claude transcript into an immutable sibling directory."""
    source = run.trace_source
    if source is None:
        return run

    trace_root = run_path.with_name(run_path.name.removesuffix(".run.json") + ".trace")
    trace_root.mkdir(parents=True, exist_ok=True)
    final_dir = trace_root / source.session_id
    staging = Path(tempfile.mkdtemp(prefix=".tmp-", dir=trace_root))
    try:
        shutil.copy2(source.main, staging / "session.jsonl")
        source_session_dir = source.main.with_suffix("")
        source_subagents = source_session_dir / "subagents"
        if source_subagents.is_dir():
            shutil.copytree(source_subagents, staging / "subagents")
        if final_dir.exists():
            raise FileExistsError(f"trace already exists: {final_dir}")
        os.replace(staging, final_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    artifact = TraceArtifact(
        directory=final_dir,
        session_id=source.session_id,
        complete=run.worker_completed and not run.timed_out,
    )
    return replace(run, trace=artifact)


def write_run_manifest(
    path: Path,
    input_path: Path,
    output_path: Path,
    start_time: float,
    agent: str,
    run: AgentRun,
) -> None:
    trace = None
    if run.trace is not None:
        trace = {
            "format": "claude-code-jsonl",
            "path": os.path.relpath(run.trace.directory, path.parent),
            "main": "session.jsonl",
            "subagents": "subagents",
            "session_id": run.trace.session_id,
            "complete": run.trace.complete,
        }
    # output sha256 lets a consumer detect that the fixed annotation path was
    # overwritten by a later run (annotation + manifest cannot be published as
    # one cross-file transaction while the compiler expects a fixed path).
    output_sha256 = _sha256(output_path)
    atomic_write_json(
        path,
        {
            "schema_version": 2,
            "meta": {
                "input": str(input_path),
                "agent": agent,
                "duration_seconds": round(time.monotonic() - start_time, 3),
                "errors": run.errors,
                "timed_out": run.timed_out,
                "container_exit_code": run.container_exit_code,
                "worker_completed": run.worker_completed,
            },
            "output": {
                "path": str(output_path),
                "published": output_path.exists(),
                "sha256": output_sha256,
            },
            "trace": trace,
        },
    )


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def report_result(
    output_path: Path,
    run_path: Path,
    temp_root: Path,
    keep_workdir: bool,
    run: AgentRun,
) -> int:
    if not run.errors:
        print(f"Wrote annotations to {output_path}")
        print(f"Wrote run manifest to {run_path}")
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
