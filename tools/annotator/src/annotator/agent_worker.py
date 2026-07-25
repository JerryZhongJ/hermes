"""Container-side agent worker.

Runs INSIDE the annotator Docker image as ``python -m annotator.agent_worker``.
The host orchestrator (:mod:`annotator.agents.claude`) prepares the attempt
directory (bind-mounted at :data:`WORK`), drops the prompt + non-secret config
there, and passes API-key/proxy env via ``docker run --env-file``. This module
reads those inputs and runs the Claude agent with **no internal restrictions**
(the container is the only isolation boundary). Claude Code owns execution
telemetry through its native transcript; this worker writes only annotations
and a small worker-status sidecar.

The annotation document is maintained IN MEMORY by the agent through the
mandatory ``annotations`` MCP tools (``list``/``add``/``delete``). The agent
never writes ``annotation.json``; this worker flushes the document to
:data:`ANNOTATIONS_FILE` (``.annotations.json``) when the run ends, and the
host pipeline promotes it to the CLI output. ``dryrun_annotation`` reads the
same live document in-process.

Why unrestricted: ``permission_mode="bypassPermissions"`` makes the SDK skip
every permission check (``can_use_tool`` is never invoked — see
``claude_agent_sdk/types.py``), so the old host safeguards — SDK sandbox,
``can_use_tool`` path fence, ``setting_sources=[]`` isolation, the
``tools=[...]`` allowlist, and the auto-memory disable — are all gone. The
``fold``/``locate`` MCP tools are kept (the agent still benefits from exact
ranges / structural views).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from collections.abc import Callable
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk.types import ResultMessage, SystemMessage

from .subagents_def import (
    ANNOTATE_CHUNK_AGENT,
    SHAPE_FACTS_CHUNK_AGENT,
    SHAPE_REVIEW_AGENT,
    UNDERSTAND_CHUNK_AGENT,
)
from .stream_capture import OVERFLOW_FILE, install as install_stream_capture
from .tools.utils import atomic_write_json
from .tools import build_source_mcp_servers
from .tools.annotation_tool import AnnotationDocument

LOGGER = logging.getLogger("agent_worker")
TERMINAL_TASK_STATUSES = frozenset(("completed", "failed", "stopped", "killed"))

# Bind-mount target agreed with the host runner (agents/claude.py).
WORK = Path("/work")
PROMPT_FILE = WORK / ".prompt.txt"
CONFIG_FILE = WORK / ".agent_config.json"
WORKER_STATUS_FILE = WORK / ".worker_status.json"
# The in-memory annotation document is flushed here when the run ends. The
# host pipeline reads this file as the final annotation product (the agent
# never writes annotation.json — it maintains the doc via the annotation MCP).
ANNOTATIONS_FILE = WORK / ".annotations.json"

# Capture the raw NDJSON line that exceeds the SDK's 1 MiB stream guard before
# the session terminates, so the culprit is identifiable post-hoc. Idempotent
# and layout-guarded; safe to install at import.
install_stream_capture(WORK / OVERFLOW_FILE)


def _build_options(cfg: dict[str, Any]) -> tuple[ClaudeAgentOptions, AnnotationDocument]:
    """Build the unrestricted ClaudeAgentOptions for the in-container run.

    Returns the options plus the in-memory annotation document the agent
    maintains via the annotation MCP tools. The caller flushes the document to
    disk after the run.
    """
    # The single JS file the source tools bind to. The host writes its name
    # into .agent_config.json; resolve it under WORK instead of letting each
    # tool guess (or scan WORK for a *.js).
    source_name = cfg.get("source")
    if not isinstance(source_name, str) or not source_name:
        raise RuntimeError("agent config missing 'source' (the JS filename)")
    source = (WORK / source_name).resolve()

    doc = AnnotationDocument.empty()
    claude_settings = cfg.get("claude_settings")
    options = ClaudeAgentOptions(
        cwd=str(WORK),
        # API key / proxy already landed in os.environ via `docker run
        # --env-file`; the SDK inherits os.environ (subprocess_cli.py:430), so
        # env={} adds nothing and overwrites nothing.
        env={},
        model=cfg.get("model"),
        # A Task/Agent tool result carries the subagent's FULL transcript
        # (every tool_use + result, including the comment text it wrote) back to
        # the parent as a single NDJSON line. A hard-working phase2/4 subagent
        # easily exceeds the SDK's 1 MiB default — confirmed by .buffer-overflow
        # capture (a 1.05 MiB tool_result). Raise the framing cap so these
        # legitimate messages parse; stream_capture still logs anything bigger.
        max_buffer_size=64 * 1024 * 1024,
        permission_mode="bypassPermissions",
        # tools= omitted -> CLI default full set (Bash/Edit/Read/Write/Glob/...).
        # The agent maintains annotations ONLY via the in-process annotation
        # MCP (list/add/delete); the prompt never names an annotation file, so
        # the agent's only path to annotations is the MCP. bypassPermissions
        # keeps the run smooth (no per-tool prompts inside the container).
        mcp_servers=build_source_mcp_servers(source, WORK, doc, cfg.get("enabled_tools")),
        # Five-stage subagents run through Task. Phases 1/2 communicate through
        # staged comments; phase 4 mutates this same live document through MCP.
        # The worker alone flushes the document after the full run.
        agents={
            "understand-chunk": UNDERSTAND_CHUNK_AGENT,
            "shape-facts-chunk": SHAPE_FACTS_CHUNK_AGENT,
            "annotate-chunk": ANNOTATE_CHUNK_AGENT,
            "shape-review": SHAPE_REVIEW_AGENT,
        },
        # setting_sources= omitted -> no isolation (fresh image has no user
        # config anyway, and the container is the boundary).
        settings=(
            json.dumps(claude_settings)
            if isinstance(claude_settings, (dict, list))
            else claude_settings
        ),
        stderr=LOGGER.error,
    )
    return options, doc


def _message_session_id(message: object) -> str | None:
    session_id = getattr(message, "session_id", None)
    if isinstance(session_id, str) and session_id:
        return session_id
    if isinstance(message, SystemMessage):
        value = message.data.get("session_id")
        if isinstance(value, str) and value:
            return value
    return None


def _update_task_status(message: object, statuses: dict[str, str]) -> None:
    """Track background tasks monotonically from typed or raw system events."""
    if not isinstance(message, SystemMessage):
        return
    data = message.data
    task_id = data.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        return
    if message.subtype in ("task_started", "task_progress"):
        status: object = "running"
    elif message.subtype == "task_notification":
        status = data.get("status")
    elif message.subtype == "task_updated":
        patch = data.get("patch")
        status = patch.get("status") if isinstance(patch, dict) else data.get("status")
    else:
        return
    if not isinstance(status, str):
        return
    if statuses.get(task_id) in TERMINAL_TASK_STATUSES:
        return
    statuses[task_id] = status


def _result_error(result: ResultMessage) -> str:
    errors = getattr(result, "errors", None)
    details = "; ".join(errors or []) or result.result or result.subtype
    return f"Claude Code returned an error result: {details}"


async def _collect(
    prompt: str,
    options: ClaudeAgentOptions,
    doc: AnnotationDocument,
    *,
    client_factory: Callable[..., ClaudeSDKClient] = ClaudeSDKClient,
) -> None:
    """Drive one persistent SDK session until its background tasks finish.

    The annotation document is flushed on every top-level turn boundary so a
    timeout (or any kill) still leaves the latest annotations on disk in the
    kept workdir, instead of losing the whole run.
    """
    task_statuses: dict[str, str] = {}
    result: ResultMessage | None = None
    completed = False

    async with client_factory(options=options) as client:
        await client.query(prompt)
        async for message in client.receive_messages():
            LOGGER.info(
                "claude message type=%s subtype=%s",
                type(message).__name__,
                getattr(message, "subtype", None),
            )
            session_id = _message_session_id(message)
            if session_id:
                _write_worker_status(completed=False, errors=[], session_id=session_id)
            _update_task_status(message, task_statuses)
            # Only a ResultMessage is a real turn boundary. A background task
            # completing fires a task_updated/task_notification that will itself
            # trigger a follow-up main-agent turn; breaking on that event (with
            # a stale prior result) truncates the workflow before that turn
            # arrives. So: when a turn just ended AND nothing is still running,
            # no future event can re-prompt the agent — the session is done.
            if isinstance(message, ResultMessage):
                result = message
                # Incremental checkpoint: persist what the agent has built so
                # far. Cheap (small file) and makes a timeout non-destructive.
                _flush_annotations(doc)
                _write_worker_status(completed=False, errors=[])
                if not any(
                    status not in TERMINAL_TASK_STATUSES
                    for status in task_statuses.values()
                ):
                    completed = True
                    break

    if not completed:
        active = sorted(
            task_id
            for task_id, status in task_statuses.items()
            if status not in TERMINAL_TASK_STATUSES
        )
        if result is None:
            raise RuntimeError("message stream ended before ResultMessage")
        raise RuntimeError(
            "message stream ended with unfinished background tasks: "
            + ", ".join(active)
        )
    assert result is not None
    if result.is_error:
        raise RuntimeError(_result_error(result))


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


def main() -> int:
    logging.basicConfig(format="%(message)s", level=logging.INFO, stream=sys.stderr)

    prompt = PROMPT_FILE.read_text(encoding="utf-8")
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

    errors: list[str] = []
    doc: AnnotationDocument | None = None
    _write_worker_status(completed=False, errors=[])
    try:
        options, doc = _build_options(cfg)
        asyncio.run(_collect(prompt, options, doc))
    except Exception as exc:  # noqa: BLE001 — worker must still flush results.
        errors = [f"{type(exc).__name__}: {exc}"]
        LOGGER.error("%s: %s", type(exc).__name__, exc)

    # Flush the in-memory annotation document the agent maintained via the
    # annotation MCP. Always written (even on failure an empty/partial doc has
    # value); the host pipeline validates before promoting it to the output.
    _flush_annotations(doc)
    _write_worker_status(completed=not errors, errors=errors)
    return 0 if not errors else 1


def _flush_annotations(doc: AnnotationDocument | None) -> None:
    """Write the document snapshot to ANNOTATIONS_FILE (best-effort)."""
    if doc is None:
        return
    try:
        atomic_write_json(ANNOTATIONS_FILE, json.loads(doc.to_json()))
    except OSError as exc:
        LOGGER.error("could not write %s: %s", ANNOTATIONS_FILE, exc)


if __name__ == "__main__":
    raise SystemExit(main())
