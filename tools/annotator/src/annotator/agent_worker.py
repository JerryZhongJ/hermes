"""Container-side agent worker.

Runs INSIDE the annotator Docker image as ``python -m annotator.agent_worker``.
The host orchestrator (:mod:`annotator.agents.claude`) prepares the attempt
directory (bind-mounted at :data:`WORK`), drops the prompt + non-secret config
there, and passes API-key/proxy env via ``docker run --env-file``. This module
reads those inputs, runs the Claude agent with **no internal restrictions**
(the container is the only isolation boundary), and writes the collected
messages + errors back into the volume for the host to pick up.

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
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, query
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    UserMessage,
)

from .metrics import to_jsonable
from .tools import build_source_mcp_servers

LOGGER = logging.getLogger("agent_worker")

# Bind-mount target agreed with the host runner (agents/claude.py).
WORK = Path("/work")
PROMPT_FILE = WORK / ".prompt.txt"
CONFIG_FILE = WORK / ".agent_config.json"
MESSAGES_FILE = WORK / ".messages.json"
ERRORS_FILE = WORK / ".errors.json"


def _message_kind(message: object) -> str:
    """Stable string tag for an SDK message (its ``.type`` is lost in to_jsonable)."""
    if isinstance(message, AssistantMessage):
        return "assistant"
    if isinstance(message, UserMessage):
        return "user"
    if isinstance(message, SystemMessage):
        return "system"
    if isinstance(message, ResultMessage):
        return "result"
    if isinstance(message, StreamEvent):
        return "stream"
    return type(message).__name__


def _build_options(cfg: dict[str, Any]) -> ClaudeAgentOptions:
    """Build the unrestricted ClaudeAgentOptions for the in-container run."""
    # The single JS file the source tools bind to. The host writes its name
    # into .agent_config.json; resolve it under WORK instead of letting each
    # tool guess (or scan WORK for a *.js).
    source_name = cfg.get("source")
    if not isinstance(source_name, str) or not source_name:
        raise RuntimeError("agent config missing 'source' (the JS filename)")
    source = (WORK / source_name).resolve()

    claude_settings = cfg.get("claude_settings")
    return ClaudeAgentOptions(
        cwd=str(WORK),
        # API key / proxy already landed in os.environ via `docker run
        # --env-file`; the SDK inherits os.environ (subprocess_cli.py:430), so
        # env={} adds nothing and overwrites nothing.
        env={},
        model=cfg.get("model"),
        permission_mode="bypassPermissions",
        # tools= omitted -> CLI default full set (Bash/Edit/Read/Write/Glob/...).
        mcp_servers=build_source_mcp_servers(source, WORK, cfg.get("enabled_tools")),
        # setting_sources= omitted -> no isolation (fresh image has no user
        # config anyway, and the container is the boundary).
        settings=(
            json.dumps(claude_settings)
            if isinstance(claude_settings, (dict, list))
            else claude_settings
        ),
        stderr=LOGGER.error,
    )


async def _collect(
    prompt: str, options: ClaudeAgentOptions, messages: list[object]
) -> None:
    """Drive the SDK query and append normalized messages."""
    async for message in query(prompt=prompt, options=options):
        # Drop the thinking_tokens stream — one event per generated reasoning
        # token (thousands per run, zero signal for post-hoc analysis).
        if isinstance(message, SystemMessage) and message.subtype == "thinking_tokens":
            continue
        LOGGER.info("claude 1: %r", message)
        entry = to_jsonable(message)
        if isinstance(entry, dict):
            # to_jsonable drops the SDK's `type` field; restore it so post-hoc
            # tools can tell assistant/user/system/result apart.
            entry["type"] = _message_kind(message)
        messages.append(entry)


def _write_results(messages: list[object], errors: list[str]) -> None:
    """Flush messages + errors into the volume (defensive: best-effort)."""
    try:
        MESSAGES_FILE.write_text(
            json.dumps(messages, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        LOGGER.error("could not write %s: %s", MESSAGES_FILE, exc)
    try:
        ERRORS_FILE.write_text(
            json.dumps(errors, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        LOGGER.error("could not write %s: %s", ERRORS_FILE, exc)


def main() -> int:
    logging.basicConfig(format="%(message)s", level=logging.INFO, stream=sys.stderr)

    prompt = PROMPT_FILE.read_text(encoding="utf-8")
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

    messages: list[object] = []
    errors: list[str] = []
    try:
        options = _build_options(cfg)
        asyncio.run(_collect(prompt, options, messages))
    except Exception as exc:  # noqa: BLE001 — worker must still flush results.
        errors = [f"{type(exc).__name__}: {exc}"]
        LOGGER.error("%s: %s", type(exc).__name__, exc)

    _write_results(messages, errors)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
