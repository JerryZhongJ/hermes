"""Claude Code SDK-backed agent runner."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, query
from claude_agent_sdk.types import (
    AssistantMessage,
    Message,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    ToolPermissionContext,
    UserMessage,
)

from ..config import AgentConfig
from ..tools.fold_tool import make_fold_server
from ..tools.locate_tool import make_locate_server
from ..metrics import to_jsonable
from . import AgentRun, run_async_with_timeout

LOGGER = logging.getLogger("claude_code")


async def _user_prompt_stream(prompt: str) -> AsyncIterator[dict[str, object]]:
    """Wrap a prompt string as a single-message AsyncIterable.

    The Claude Agent SDK only honours the ``can_use_tool`` callback when the
    prompt is an AsyncIterable (streaming mode), not a plain string. Each
    yielded dict must match the SDK's user-message wire format used for string
    prompts (see ``_internal/client.py``).
    """
    yield {
        "type": "user",
        "session_id": "",
        "message": {"role": "user", "content": prompt},
        "parent_tool_use_id": None,
    }


class ClaudeSdkRunner:
    def __init__(self, config: AgentConfig, timeout_seconds: int) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds

    def run(self, prompt: str, attempt_dir: Path) -> AgentRun:
        messages: list[object] = []
        errors: list[str] = []

        try:
            run_async_with_timeout(
                self._collect_events(prompt, attempt_dir, messages),
                self.timeout_seconds,
            )
        except TimeoutError:
            errors = ["agent timed out"]
            LOGGER.error("Claude SDK run timed out")
        except Exception as exc:
            errors = [f"agent failed: {type(exc).__name__}: {exc}"]
            LOGGER.error("%s: %s", type(exc).__name__, exc)

        return AgentRun(errors=errors, messages=messages)

    async def _collect_events(
        self,
        prompt: str,
        attempt_dir: Path,
        messages: list[object],
    ) -> None:
        options = self._options(attempt_dir)
        async for message in query(
            prompt=_user_prompt_stream(prompt), options=options
        ):
            # Drop the thinking_tokens stream — reasoning models emit one per
            # generated reasoning token (thousands per run, zero signal).
            if isinstance(message, SystemMessage) and message.subtype == "thinking_tokens":
                continue
            LOGGER.info("claude 1: %r", message)
            entry = to_jsonable(message)
            if isinstance(entry, dict):
                # to_jsonable drops the SDK's `type` field (it serializes to
                # None then gets filtered); restore it so post-hoc tools can
                # tell assistant/user/system/result apart.
                entry["type"] = _message_kind(message)
            messages.append(entry)

    def _options(self, attempt_dir: Path) -> ClaudeAgentOptions:
        policy = ClaudeToolPolicy(attempt_dir)
        settings = self.config.claude_settings
        env = self.config.environment()
        # An annotator run is a one-shot labeling job, not an interactive
        # session; it must never write to the user's memory.
        env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
        return ClaudeAgentOptions(
            cwd=attempt_dir,
            env=env,
            model=self.config.model,
            permission_mode="acceptEdits",
            tools=["Bash", "Edit", "Read", "Write"],  # limit to the tools the annotator needs; Write lets the agent create the file directly
            # In-process MCP server the agent calls to get exact source ranges,
            # replacing grep -ob + hand-counting (the sandbox blocks python3/node).
            mcp_servers={
                "source-fold": make_fold_server(attempt_dir),
                "source-locate": make_locate_server(attempt_dir),
            },
            setting_sources=[],  # isolate from user/project/local Claude Code settings
            settings=(
                json.dumps(settings)
                if isinstance(settings, (dict, list))
                else settings
            ),
            sandbox=self.config.claude_sandbox,
            stderr=LOGGER.error,
            can_use_tool=policy.can_use_tool,
        )


class ClaudeToolPolicy:
    def __init__(self, attempt_dir: Path) -> None:
        self.attempt_dir = attempt_dir
        self.root = attempt_dir.resolve()

    async def can_use_tool(
        self,
        tool_name: str,
        tool_input: dict[str, object],
        _: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        if tool_name in {"Read", "Edit", "Write", "NotebookEdit"}:
            if not self._paths_inside_attempt_dir(tool_input):
                return PermissionResultDeny(
                    behavior="deny",
                    message=f"{tool_name} is limited to {self.root}",
                    interrupt=False,
                )
        return PermissionResultAllow(behavior="allow")

    def _paths_inside_attempt_dir(self, tool_input: dict[str, object]) -> bool:
        return all(
            self._path_inside(tool_input[key])
            for key in ("file_path", "path", "notebook_path")
            if key in tool_input
        )

    def _path_inside(self, path_value: object) -> bool:
        if not isinstance(path_value, str) or not path_value:
            return True
        path = Path(path_value)
        if not path.is_absolute():
            path = self.attempt_dir / path
        try:
            path.resolve().relative_to(self.root)
            return True
        except ValueError:
            return False


def _message_kind(message: Message) -> str:
    """Stable string tag for an SDK message (its `.type` is lost in to_jsonable)."""
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
