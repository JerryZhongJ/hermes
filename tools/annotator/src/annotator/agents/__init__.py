"""Agent runner interface and factory."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar

from ..config import AgentConfig


T = TypeVar("T")


@dataclass(frozen=True)
class AgentRun:
    errors: list[str]
    # Raw SDK messages for post-hoc analysis (thinking_tokens already
    # filtered). Lets stats be recomputed offline instead of inline.
    messages: list[object] = field(default_factory=list)


class AgentRunner(Protocol):
    def run(self, prompt: str, attempt_dir: Path, source_name: str) -> AgentRun:
        ...


def run_async_with_timeout(awaitable: Awaitable[T], timeout_seconds: int) -> T:
    async def run() -> T:
        if timeout_seconds > 0:
            return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
        return await awaitable

    return asyncio.run(run())


def create_runner(config: AgentConfig, timeout_seconds: int) -> AgentRunner:
    if config.agent == "codex":
        from .codex import CodexSdkRunner

        return CodexSdkRunner(config, timeout_seconds)
    if config.agent == "claude":
        from .claude import ClaudeSdkRunner

        return ClaudeSdkRunner(config, timeout_seconds)
    raise ValueError(f"unsupported agent: {config.agent}")
