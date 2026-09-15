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
from typing import Any, TextIO, TypeVar


from .agents import AgentRun, AgentRunner, TraceArtifact
from .prompt import ABOUT_ANNOTATIONS_FILENAME, build_about_annotations_markdown
from .tools.utils import atomic_write_json
from .workflows import AnnotationRequest

LOGGER = logging.getLogger(__name__)

T = TypeVar("T")


def generate_annotations(
    runner: AgentRunner,
    input_path: Path,
    output_path: Path,
    temp_root: Path,
    append_prompt: str | None = None,
    request: AnnotationRequest | None = None,
) -> AgentRun:
    # The agent saves its own product via save_annotations into the workdir;
    # promotion ships the whole workdir unchanged (file mover, not curator).
    shutil.copyfile(input_path, temp_root / input_path.name)
    (temp_root / ABOUT_ANNOTATIONS_FILENAME).write_text(
        build_about_annotations_markdown(), encoding="utf-8"
    )

    annotation_request = request or AnnotationRequest(source_path=input_path)
    if annotation_request.source_path != input_path:
        raise ValueError(
            "annotation request source_path must match input_path: "
            f"{annotation_request.source_path} != {input_path}"
        )
    # The workflow owns its prompt (built inside the container from cfg);
    # the host only forwards the optional prompt appendix through the run
    # config.
    run = runner.run(temp_root, input_path.name, annotation_request, append_prompt)
    run = replace(
        run,
        workflow=annotation_request.workflow,
        targets=annotation_request.targets,
    )
    if run.errors:
        return run

    # One promotion path for every workflow: ship the whole attempt workdir.
    return _promote_workdir(run, temp_root, output_path)


def _promote_workdir(run: AgentRun, temp_root: Path, output_path: Path) -> AgentRun:
    """Ship the whole attempt workdir as the run's output.

    There is no artifact protocol: the agent saved its product(s) via
    ``save_annotations`` (``main.json`` for annotate-file, ``hotspot:*.json``
    for hotspot runs), and everything else (transcripts, job workdirs,
    status) ships with them — the host is a file mover, not a curator: it
    never parses, validates, or rewrites a product. At least one saved
    product file is required, otherwise the run fails.
    """
    products = sorted(temp_root.glob("hotspot:*.json")) or [
        temp_root / "main.json"
    ]
    if not products[0].is_file():
        return replace(
            run,
            errors=["no annotation product was saved (missing save_annotations)"],
        )
    try:
        shutil.copytree(temp_root, output_path, dirs_exist_ok=True)
    except OSError as exc:
        return replace(run, errors=[f"could not publish workdir: {exc}"])
    return replace(
        run,
        output_published=True,
        output_sha256=_sha256(products[0]),
    )


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
        # Every other session of this run (hotspot target agents), each as
        # sessions/<session_id>.jsonl plus its own subagents/ if present.
        if source.others:
            sessions_dir = staging / "sessions"
            sessions_dir.mkdir()
            for other in source.others:
                shutil.copy2(other, sessions_dir / other.name)
                other_subagents = other.with_suffix("") / "subagents"
                if other_subagents.is_dir():
                    shutil.copytree(
                        other_subagents,
                        sessions_dir / other.stem / "subagents",
                    )
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
            "sessions": "sessions",
            "session_id": run.trace.session_id,
            "complete": run.trace.complete,
        }
    # Publication provenance comes from this run, not from whether a stale fixed
    # output path happens to exist from an earlier run.
    output_sha256 = run.output_sha256
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
            "workflow": {
                "name": run.workflow,
                "targets": list(run.targets),
            },
            "output": {
                "path": str(output_path),
                "kind": "directory" if output_path.is_dir() else "file",
                "published": run.output_published,
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
        if output_path.is_dir():
            fragments = sorted(output_path.glob("hotspot:*.json"))
            print(f"Wrote {len(fragments)} annotation fragment(s) to {output_path}")
        else:
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
