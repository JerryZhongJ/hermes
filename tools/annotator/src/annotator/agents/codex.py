"""Codex SDK-backed agent runner."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from openai_codex import (
    ApprovalMode,
    AsyncCodex,
    AsyncTurnHandle,
    CodexConfig,
    Sandbox,
)
from openai_codex.generated.v2_all import (
    AgentMessageDeltaNotification,
    ItemCompletedNotification,
    ThreadTokenUsageUpdatedNotification,
    TurnCompletedNotification,
)

from ..config import AgentConfig
from ..metrics import to_jsonable
from . import AgentRun, run_async_with_timeout

LOGGER = logging.getLogger("codex")


def _prepare_isolated_codex_home(attempt_dir: Path, config: AgentConfig) -> Path:
    """Build a throwaway CODEX_HOME under ``attempt_dir``.

    Mirrors claude's ``setting_sources=[]``: codex is pointed at an isolated
    home holding only a ``config.toml``/``auth.json`` derived from this run's
    agent config, so the user's ``~/.codex`` — with its memories, goals,
    personality, project trust and default provider — never leaks into an
    annotator run.
    """
    home = attempt_dir / ".codex_home"
    home.mkdir(exist_ok=True)
    if config.codex_config:
        (home / "config.toml").write_text(
            _dump_toml(config.codex_config), encoding="utf-8"
        )
    api_key = config.env.get("OPENAI_API_KEY")
    if isinstance(api_key, str) and api_key:
        (home / "auth.json").write_text(
            json.dumps({"OPENAI_API_KEY": api_key}), encoding="utf-8"
        )
    return home


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    raise TypeError(f"cannot serialize {type(value).__name__} to TOML")


def _dump_toml_table(name: str, data: dict[str, Any]) -> list[str]:
    lines = [f"[{name}]"]
    # Scalars must precede sub-tables within a TOML table.
    for key, value in data.items():
        if not isinstance(value, dict):
            lines.append(f"{key} = {_toml_scalar(value)}")
    for key, value in data.items():
        if isinstance(value, dict):
            lines.extend(_dump_toml_table(f"{name}.{key}", value))
    return lines


def _dump_toml(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in data.items():
        if not isinstance(value, dict):
            lines.append(f"{key} = {_toml_scalar(value)}")
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append("")
            lines.extend(_dump_toml_table(key, value))
    return "\n".join(lines)


class CodexSdkRunner:
    def __init__(self, config: AgentConfig, timeout_seconds: int) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds

    def run(self, prompt: str, attempt_dir: Path) -> AgentRun:
        messages: list[object] = []
        errors: list[str] = []
        try:
            run_async_with_timeout(
                self._run_codex_sdk(prompt, attempt_dir, messages),
                self.timeout_seconds,
            )
        except TimeoutError:
            LOGGER.error("Codex SDK run timed out")
            errors = ["agent timed out"]
        except Exception as exc:
            LOGGER.error("%s: %s", type(exc).__name__, exc)
            errors = [f"agent failed: {type(exc).__name__}: {exc}"]

        return AgentRun(errors=errors, messages=messages)

    async def _run_codex_sdk(
        self, prompt: str, attempt_dir: Path, messages: list[object]
    ) -> None:
        env = self.config.environment()
        # Isolate codex from ~/.codex, mirroring claude's setting_sources=[]:
        # the run sees only a throwaway CODEX_HOME populated from this agent
        # config, never the user's memories/goals/personality/project trust.
        env["CODEX_HOME"] = str(_prepare_isolated_codex_home(attempt_dir, self.config))
        config = CodexConfig(cwd=str(attempt_dir), env=env)
        async with AsyncCodex(config=config) as codex:
            thread = await codex.thread_start(**self._thread_start_kwargs(attempt_dir))
            turn = await thread.turn(prompt)
            await collect_codex_turn(turn, messages)

    def _thread_start_kwargs(self, attempt_dir: Path) -> dict[str, Any]:
        # dict[str, Any] is required: **kwargs unpacking needs each value to be
        # assignable to every thread_start parameter, which only Any satisfies.
        kwargs = {
            "approval_mode": ApprovalMode.deny_all,
            "cwd": str(attempt_dir),
            "model": self.config.model,
            "sandbox": Sandbox.workspace_write,
        }
        # Provider definitions live in the isolated config.toml (from
        # codex_config); surface only the selected provider name here.
        model_provider = (self.config.codex_config or {}).get("model_provider")
        if isinstance(model_provider, str):
            kwargs["model_provider"] = model_provider
        return kwargs


async def collect_codex_turn(turn: AsyncTurnHandle, messages: list[object]) -> None:
    """Consume a codex turn stream: collect raw notifications for post-hoc
    analysis and detect completion / failure. No inline metric accumulation."""
    completed = None
    async for notification in turn.stream():
        payload = notification.payload
        LOGGER.info("codex %s: %r", turn.id, payload)
        entry = to_jsonable(payload)
        if isinstance(entry, dict):
            entry["type"] = _notification_kind(payload)
        messages.append(entry)
        if isinstance(payload, TurnCompletedNotification):
            completed = payload.turn

    if completed is None:
        raise RuntimeError("turn completed event not received")
    status = getattr(completed, "status", None)
    if str(getattr(status, "value", status)) == "failed":
        error = getattr(completed, "error", None)
        if error is not None and getattr(error, "message", None):
            raise RuntimeError(error.message)
        raise RuntimeError(f"turn failed with status {status}")


def _notification_kind(payload: object) -> str:
    """Stable string tag for a codex notification (postprocess dispatches on it)."""
    if isinstance(payload, TurnCompletedNotification):
        return "turn_completed"
    if isinstance(payload, ThreadTokenUsageUpdatedNotification):
        return "token_usage"
    if isinstance(payload, AgentMessageDeltaNotification):
        return "assistant_delta"
    if isinstance(payload, ItemCompletedNotification):
        return "item_completed"
    return type(payload).__name__
