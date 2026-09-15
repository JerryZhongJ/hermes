"""Container-side worker: the run-level entry, fully task-agnostic.

Runs INSIDE the annotator Docker image as ``python -m annotator.agent_worker``.
The host orchestrator (:mod:`annotator.docker_runner`) prepares the attempt
directory (bind-mounted at :data:`WORK`), drops the non-secret config there
(the prompt is the workflow's own — the worker never sees one), and passes
API-key/proxy env via ``docker run --env-file``.

This module owns the container plumbing only: the bind-mount path constants,
the worker-status sidecar, config validation, and ``main()`` — a plain
``resolve workflow → build → run`` pipeline that never sees a prompt: the
workflow owns its prompt. What a workflow's agent IS (coordinator,
annotator, hooks) lives entirely in the workflow's own package under
:mod:`annotator.workflows`.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from .stream_capture import OVERFLOW_FILE, install as install_stream_capture
from .tools.utils import atomic_write_json
from .workflows import WorkflowFactory, resolve_workflow_factory

LOGGER = logging.getLogger("agent_worker")

# Bind-mount target agreed with the host runner (docker_runner.py).
WORK = Path("/work")
CONFIG_FILE = WORK / ".agent_config.json"
WORKER_STATUS_FILE = WORK / ".worker_status.json"

# Capture the raw NDJSON line that exceeds the SDK's 1 MiB stream guard before
# the session terminates, so the culprit is identifiable post-hoc. Idempotent
# and layout-guarded; safe to install at import.
install_stream_capture(WORK / OVERFLOW_FILE)


def _write_worker_status(
    *, completed: bool, errors: list[str], session_id: str | None = None
) -> None:
    """Publish only worker state not guaranteed to exist in the transcript."""
    try:
        previous_session_id = None
        try:
            previous = json.loads(WORKER_STATUS_FILE.read_text(encoding="utf-8"))
            if isinstance(previous, dict):
                previous_session_id = previous.get("session_id")
        except (OSError, json.JSONDecodeError):
            pass
        atomic_write_json(
            WORKER_STATUS_FILE,
            {
                "started": True,
                "completed": completed,
                "errors": errors,
                "session_id": session_id or previous_session_id,
            },
        )
    except OSError as exc:
        LOGGER.error("could not write %s: %s", WORKER_STATUS_FILE, exc)


def _status_on_message(message: object, session_id: str | None) -> None:
    LOGGER.info(
        "claude message type=%s subtype=%s",
        type(message).__name__,
        getattr(message, "subtype", None),
    )
    if session_id:
        _write_worker_status(completed=False, errors=[], session_id=session_id)


def _status_on_result(_result: object) -> None:
    _write_worker_status(completed=False, errors=[])


def validate_config(cfg: dict[str, Any], work: Path) -> tuple[WorkflowFactory, tuple[str, ...]]:
    """Validate the host-staged config against the workspace.

    The host has already staged ``work`` (prompt, config, source); this is
    validation, not filesystem staging. Returns the resolved workflow
    factory and the deduplicated targets.
    """
    source_name = cfg.get("source")
    if not isinstance(source_name, str) or not source_name:
        raise RuntimeError("agent config missing 'source' (the JS filename)")
    source = (work / source_name).resolve()
    if not source.is_file():
        raise RuntimeError(f"source file not found in workspace: {source_name}")

    workflow_name = cfg.get("workflow", "annotate-hotspot-functions")
    if not isinstance(workflow_name, str):
        raise RuntimeError("agent config 'workflow' must be a string")
    try:
        factory = resolve_workflow_factory(workflow_name)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from None
    raw_targets = cfg.get("targets", [])
    if not isinstance(raw_targets, list) or not all(
        isinstance(target, str) and target for target in raw_targets
    ):
        raise RuntimeError("agent config 'targets' must be a list of strings")
    targets = tuple(dict.fromkeys(raw_targets))
    if factory.accepts_targets:
        if not targets:
            raise RuntimeError(f"workflow {factory.name!r} requires target functions")
    elif targets:
        raise RuntimeError(f"workflow {factory.name!r} does not accept target functions")
    return factory, targets


def main() -> int:
    logging.basicConfig(format="%(message)s", level=logging.INFO, stream=sys.stderr)

    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

    errors: list[str] = []
    _write_worker_status(completed=False, errors=[])
    try:
        factory, _targets = validate_config(cfg, WORK)
        if factory.build is None:
            raise RuntimeError(f"workflow {factory.name!r} has no build function")
        workflow = factory.build(cfg, WORK)
        outcome = workflow.run(
            on_message=_status_on_message,
            on_result=_status_on_result,
        )
        if not outcome.ok:
            errors = [outcome.error or "agent failed"]
    except Exception as exc:  # noqa: BLE001 — build/run failures land here
        errors = [f"{type(exc).__name__}: {exc}"]
        LOGGER.error("%s: %s", type(exc).__name__, exc)

    _write_worker_status(completed=not errors, errors=errors)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
