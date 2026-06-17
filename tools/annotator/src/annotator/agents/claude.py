"""Claude Code SDK-backed agent runner."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Iterable
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
    ToolUseBlock,
    UserMessage,
)

from ..config import AgentConfig
from ..metrics import AgentMetrics, json_get_int, to_jsonable
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
        metrics = AgentMetrics()
        errors: list[str] = []

        try:
            run_async_with_timeout(
                self._collect_events(prompt, attempt_dir, metrics),
                self.timeout_seconds,
            )
        except TimeoutError:
            errors = ["agent timed out"]
            LOGGER.error("Claude SDK run timed out")
        except Exception as exc:
            errors = [f"agent failed: {type(exc).__name__}: {exc}"]
            LOGGER.error("%s: %s", type(exc).__name__, exc)

        return AgentRun(errors=errors, metrics=metrics)

    async def _collect_events(
        self,
        prompt: str,
        attempt_dir: Path,
        metrics: AgentMetrics,
    ) -> None:
        options = self._options(attempt_dir)
        async for message in query(
            prompt=_user_prompt_stream(prompt), options=options
        ):
            process_message(message, metrics, "1")

    def _options(self, attempt_dir: Path) -> ClaudeAgentOptions:
        policy = ClaudeToolPolicy(attempt_dir)
        settings = self.config.claude_settings
        return ClaudeAgentOptions(
            cwd=attempt_dir,
            env=self.config.environment(),
            model=self.config.model,
            permission_mode="acceptEdits",
            setting_sources=[],  # isolate from user/project/local Claude Code settings
            settings=(
                json.dumps(settings)
                if isinstance(settings, (dict, list))
                else settings
            ),
            sandbox=self.config.claude_sandbox,
            extra_args={"bare": None},
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


def process_message(message: Message, stats: AgentMetrics, turn_id: str) -> None:
    # Reasoning models (e.g. deepseek-v4) emit one SystemMessage(subtype=
    # "thinking_tokens") per generated reasoning token — thousands per run and
    # zero signal. Suppress only that stream's logging; stats still count it.
    if not (
        isinstance(message, SystemMessage) and message.subtype == "thinking_tokens"
    ):
        LOGGER.info("claude %s: %r", turn_id, message)
    if isinstance(message, SystemMessage):
        stats.add_event("system")
    elif isinstance(message, AssistantMessage):
        stats.add_event("assistant")
        # Content blocks are SDK dataclasses (e.g. ToolUseBlock) whose asdict()
        # form drops the "type" field, so iter_tool_names' type-string match
        # never fires. isinstance is the only reliable way to count tool use.
        for block in message.content or []:
            if isinstance(block, ToolUseBlock):
                stats.add_tool(block.name)
    elif isinstance(message, UserMessage):
        stats.add_event("user")
    elif isinstance(message, ResultMessage):
        stats.add_event("result")
        if message.usage:
            usage = to_jsonable(message.usage)
            # Claude reports cache_creation and cache_read separately; merge into one bucket.
            stats.set_usage(
                input_tokens=json_get_int(usage, "input_tokens"),
                output_tokens=json_get_int(usage, "output_tokens"),
                cached_input_tokens=(
                    json_get_int(usage, "cache_creation_input_tokens")
                    + json_get_int(usage, "cache_read_input_tokens")
                ),
                total_tokens=json_get_int(usage, "total_tokens"),
            )
        if message.total_cost_usd is not None:
            stats.add_cost(message.total_cost_usd)
    elif isinstance(message, StreamEvent):
        # Stream events don't count as a separate event_type; extract nested tool_use only.
        event_data = to_jsonable(message.event)
        if isinstance(event_data, dict):
            for name in iter_tool_names(event_data.get("content_block")):
                stats.add_tool(name)
    else:
        stats.add_event("unknown")
        stats.add_unknown_event(type(message).__name__)


def iter_tool_names(value: object) -> Iterable[str]:
    if isinstance(value, dict):
        if value.get("type") in {"tool_use", "tool_call"} and isinstance(
            value.get("name"), str
        ):
            yield value["name"]
        for child in value.values():
            yield from iter_tool_names(child)
    elif isinstance(value, list):
        for item in value:
            yield from iter_tool_names(item)
