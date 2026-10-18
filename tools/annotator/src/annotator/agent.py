"""The Agent class: one runnable agent per instantiation.

An agent, at this layer, is exactly: a name, a working directory, pre-built
MCP servers, optional subagents/session knobs, a timeout. NOTHING else.
The prompt is NOT agent state — it is a per-run input, passed to
:meth:`Agent.run` alongside the run callbacks. Instantiate one, fill in the
agent-level config, call :meth:`Agent.run` — exceptions never cross the
Agent boundary; success and failure both come back as :class:`RunOutcome`
data (``ok``/``error``). The agent persists its own product through its MCP
tools; the caller never flushes anything on its behalf.

The class is deliberately ignorant of annotations, drafts, jobs, and
workflows: ``mcp_servers`` arrives fully assembled (callers use
:func:`annotator.tools.build_mcp_servers`). Workflow assembly stays in the
workflow packages under :mod:`annotator.workflows`; the session engine
lives below in this same module (the former ``sessions.py``).

On failure ``outcome.error`` carries a one-line reason for reports (the
traceback goes to the log).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk.types import ResultMessage, SystemMessage

if TYPE_CHECKING:
    from claude_agent_sdk import ClaudeSDKClient

LOGGER = logging.getLogger("agent")


@dataclass(frozen=True)
class RunOutcome:
    """What :meth:`Agent.run` returns: the outcome of one run, as data.

    ``ok=False`` carries a one-line ``error`` for reports; the traceback is
    logged, never raised out of the Agent boundary. ``session_id`` is the
    transcript-traceability id (written into artifact manifests), not an
    exposed execution mechanism.
    """

    session_id: str | None
    ok: bool = True
    error: str | None = None


class Agent:
    """One runnable agent: cwd, pre-built MCP servers, session knobs.

    The name doubles as the error label in failure descriptions. ``run`` is
    the synchronous entry point for plain-thread callers; ``run_async`` is
    the escape hatch (tests inject a ``client_factory`` there). ``run`` must
    not be called from inside a live event loop.
    """

    def __init__(
        self,
        name: str,
        *,
        cwd: str,
        mcp_servers: dict[str, Any],
        agents: dict[str, Any] | None = None,
        model: str | None = None,
        settings: str | dict | list | None = None,
        stderr: Callable[[str], None] | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self.name = name
        self.cwd = cwd
        self.mcp_servers = mcp_servers
        self.agents = agents
        self.model = model
        self.settings = settings
        self.stderr = stderr
        self.timeout_s = timeout_s

    def run(
        self,
        prompt: str,
        *,
        on_message: Callable[[object, str | None], None] | None = None,
        on_result: Callable[[Any], None] | None = None,
        next_prompt: Callable[[Any], str | None] | None = None,
    ) -> RunOutcome:
        """Run to completion from a plain thread (no live event loop)."""
        return asyncio.run(
            self.run_async(
                prompt,
                on_message=on_message,
                on_result=on_result,
                next_prompt=next_prompt,
            )
        )

    async def run_async(
        self,
        prompt: str,
        *,
        on_message: Callable[[object, str | None], None] | None = None,
        on_result: Callable[[Any], None] | None = None,
        next_prompt: Callable[[Any], str | None] | None = None,
        client_factory: Callable[..., "ClaudeSDKClient"] | None = None,
    ) -> RunOutcome:
        """Run the session; return the outcome as data, never raise.

        ``prompt`` is this run's initial prompt (a per-run input, never
        agent state). ``timeout_s`` bounds the session (all turns). ``next_prompt``
        (optional) decides at each result boundary whether the same session
        continues with a new turn: return a prompt string to send it, None
        to end the session. It runs in a worker thread (it may block). The
        callback is not consulted after an error result. Session failures
        become ``RunOutcome(ok=False, error=<one line>)``; the traceback is
        logged via the module logger.
        """
        options = base_options(
            cwd=self.cwd,
            cfg={"model": self.model, "claude_settings": self.settings},
            mcp_servers=self.mcp_servers,
            agents=self.agents,
            stderr=self.stderr,
        )
        session_kwargs: dict[str, Any] = {
            "on_message": on_message,
            "on_result": on_result,
            "next_prompt": next_prompt,
            "error_label": self.name,
        }
        if client_factory is not None:
            session_kwargs["client_factory"] = client_factory
        try:
            session = run_persistent_session(
                prompt, options, **session_kwargs
            )
            if self.timeout_s is not None:
                session = asyncio.wait_for(session, timeout=self.timeout_s)
            return await session
        except Exception as exc:  # noqa: BLE001 — the Agent boundary: data out
            LOGGER.error(
                "agent %s failed: %s: %s",
                self.name,
                type(exc).__name__,
                exc,
                exc_info=exc,
            )
            return RunOutcome(
                session_id=None,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
            )




# --- session engine (merged from the former sessions module) ----------------- #
# The Agent class is the only consumer; the engine lives here so "agent" is
# one file, one concept. `annotator.sessions` is gone.


# A Task/Agent tool result carries the subagent's FULL transcript back to the
# parent as a single NDJSON line. A hard-working target agent easily exceeds
# the SDK's 1 MiB default; stream_capture still logs anything bigger.
MAX_BUFFER_SIZE = 64 * 1024 * 1024

TERMINAL_TASK_STATUSES = frozenset(("completed", "failed", "stopped", "killed"))


def base_options(
    *,
    cwd: str,
    cfg: dict,
    mcp_servers: dict,
    agents: dict | None = None,
    stderr: Callable[[str], None] | None = None,
) -> ClaudeAgentOptions:
    """The ClaudeAgentOptions every agent shares.

    ``env={}`` adds nothing and overwrites nothing (the SDK inherits
    os.environ); ``permission_mode="bypassPermissions"`` because the container
    is the only isolation boundary. ``agents``/``stderr`` default to the SDK's
    own None defaults so omitting them is byte-equivalent.
    """
    claude_settings = cfg.get("claude_settings")
    return ClaudeAgentOptions(
        cwd=cwd,
        env={},
        model=cfg.get("model"),
        max_buffer_size=MAX_BUFFER_SIZE,
        permission_mode="bypassPermissions",
        mcp_servers=mcp_servers,
        agents=agents,
        settings=(
            json.dumps(claude_settings)
            if isinstance(claude_settings, (dict, list))
            else claude_settings
        ),
        stderr=stderr,
    )


def message_session_id(message: object) -> str | None:
    session_id = getattr(message, "session_id", None)
    if isinstance(session_id, str) and session_id:
        return session_id
    if isinstance(message, SystemMessage):
        value = message.data.get("session_id")
        if isinstance(value, str) and value:
            return value
    return None


def update_task_status(message: object, statuses: dict[str, str]) -> None:
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


def result_error(result: ResultMessage) -> str:
    errors = getattr(result, "errors", None)
    details = "; ".join(errors or []) or result.result or result.subtype
    return f"Claude Code returned an error result: {details}"


def _dump_parse_error(exc: Exception) -> None:
    """Persist the raw payload of a message-parse failure for post-mortem.

    Third-party gateways intermittently emit non-conformant messages (e.g.
    thinking blocks without a signature); the SDK raises with the offending
    dict attached as ``data``. Dump it so the exact shape is knowable offline.
    """
    data = getattr(exc, "data", None)
    if data is None:
        return
    import json as _json
    import os
    import tempfile

    try:
        # /work is the container-mounted attempt dir (host-visible); fall back
        # to tempdir for host-side runs.
        base = "/work" if os.path.isdir("/work") else tempfile.gettempdir()
        path = os.path.join(base, "parse-error.json")
        with open(path, "w", encoding="utf-8") as handle:
            _json.dump({"error": str(exc), "data": data}, handle, indent=1)
    except OSError:
        pass


async def open_query_stream(
    prompt: str,
    options: ClaudeAgentOptions,
    *,
    client_factory: Callable[..., ClaudeSDKClient] = ClaudeSDKClient,
) -> AsyncIterator[tuple[object, str | None]]:
    """Open a client, send one query, yield (message, session_id) pairs."""
    async with client_factory(options=options) as client:
        await client.query(prompt)
        async for message in client.receive_messages():
            yield message, message_session_id(message)


async def run_persistent_session(
    prompt: str,
    options: ClaudeAgentOptions,
    *,
    on_message: Callable[[object, str | None], None] | None = None,
    on_result: Callable[[ResultMessage], None] | None = None,
    next_prompt: Callable[[ResultMessage], str | None] | None = None,
    client_factory: Callable[..., ClaudeSDKClient] = ClaudeSDKClient,
    error_label: str = "agent",
) -> "RunOutcome":
    """Drive one persistent SDK session until its background tasks finish.

    Only a ResultMessage is a real turn boundary. A background task completing
    fires a task_updated/task_notification that will itself trigger a
    follow-up main-agent turn; breaking on that event (with a stale prior
    result) would truncate the workflow before that turn arrives. So: when a
    turn just ended AND nothing is still running, no future event can
    re-prompt the agent — the session is done... unless ``next_prompt``
    supplies a follow-up prompt: it is then sent to the SAME client (same
    session, full history preserved) as a new turn. The callback runs in a
    worker thread (it may block, e.g. on a compile) and is not consulted
    after an error result.

    Raises after the client context exits when the stream ended without a
    result, with unfinished tasks, or on an error result (labeled with
    ``error_label``). ``on_message`` runs per message (logging/status side
    effects); ``on_result`` runs at each result boundary (status side
    effects).
    """
    task_statuses: dict[str, str] = {}
    result: ResultMessage | None = None
    session_id: str | None = None

    async with client_factory(options=options) as client:
        await client.query(prompt)
        while True:
            stream = client.receive_messages().__aiter__()
            while True:
                try:
                    message = await stream.__anext__()
                except StopAsyncIteration:
                    break
                except Exception as _exc:
                    _dump_parse_error(_exc)
                    raise
                sid = message_session_id(message)
                if sid is not None:
                    session_id = sid
                if on_message is not None:
                    on_message(message, sid)
                update_task_status(message, task_statuses)
                if isinstance(message, ResultMessage):
                    result = message
                    if on_result is not None:
                        on_result(message)
                    if not any(
                        status not in TERMINAL_TASK_STATUSES
                        for status in task_statuses.values()
                    ):
                        break  # turn boundary with nothing pending
            if result is None:
                break  # abnormal end; outer checks below raise the right error
            if result.is_error:
                break
            if next_prompt is None:
                break
            followup = await asyncio.to_thread(next_prompt, result)
            if not followup:
                break
            result = None
            await client.query(followup)  # same session, new turn

    if result is None:
        raise RuntimeError("message stream ended before ResultMessage")
    if any(status not in TERMINAL_TASK_STATUSES for status in task_statuses.values()):
        active = sorted(
            task_id
            for task_id, status in task_statuses.items()
            if status not in TERMINAL_TASK_STATUSES
        )
        raise RuntimeError(
            "message stream ended with unfinished background tasks: "
            + ", ".join(active)
        )
    if result.is_error:
        raise RuntimeError(f"{error_label}: {result_error(result)}")
    return RunOutcome(session_id=session_id)


__all__ = ["Agent", "RunOutcome"]
