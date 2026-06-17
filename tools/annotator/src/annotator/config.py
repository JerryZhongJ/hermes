"""Configuration and CLI parsing for the annotator."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Literal, cast

from claude_agent_sdk.types import SandboxSettings
from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_CLAUDE_SANDBOX: SandboxSettings = {
    "enabled": True,
    "autoAllowBashIfSandboxed": True,
    "allowUnsandboxedCommands": False,
}


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agent: Literal["claude", "codex"]
    model: str | None = None
    env: dict[str, Any] = Field(default_factory=dict)
    codex_config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Top-level contents of codex's config.toml for this run "
            "(e.g. model, model_provider, model_providers.<name>). Serialized "
            "into an isolated CODEX_HOME so the user's ~/.codex is never loaded."
        ),
    )
    claude_settings: str | dict[str, Any] | list[Any] | None = None
    claude_sandbox: SandboxSettings = Field(
        default_factory=lambda: cast(SandboxSettings, dict(DEFAULT_CLAUDE_SANDBOX))
    )

    def environment(self) -> dict[str, str]:
        env = system_proxy_env()
        for key, value in self.env.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = str(value)
        return env


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Hermes typed-shape annotation JSON with an agent."
    )
    parser.add_argument("input", type=Path, help="JavaScript input file")
    parser.add_argument(
        "-o", "--output", type=Path, required=True, help="Annotation JSON output"
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="JSON file with agent/model/env configuration",
    )
    parser.add_argument(
        "--stats",
        type=Path,
        help="Stats JSON output. Defaults to <output>.stats.json",
    )
    parser.add_argument(
        "--keep-workdir",
        action="store_true",
        help="Keep the temporary work directory for debugging",
    )
    parser.add_argument(
        "--agent-timeout",
        type=int,
        default=600,
        help="Agent timeout in seconds",
    )
    parser.add_argument(
        "--verbose-agent-logs",
        dest="verbose_agent_logs",
        action="store_true",
        help="Print selected SDK messages while the agent runs",
    )
    return parser.parse_args()


def load_config(path: Path) -> AgentConfig:
    try:
        return AgentConfig.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"config file not found: {path}") from None
    except ValidationError as exc:
        raise ValueError(str(exc)) from None


def system_proxy_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
    }
