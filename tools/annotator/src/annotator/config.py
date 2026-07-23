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
        default_factory=lambda: cast(SandboxSettings, dict(DEFAULT_CLAUDE_SANDBOX)),
        description=(
            "Claude SDK sandbox settings. NOW A NO-OP: the claude backend runs "
            "the agent in a Docker container with bypassPermissions (the "
            "container is the isolation boundary), so there is no in-process "
            "sandbox. Kept only so existing config files still validate under "
            "extra='forbid'."
        ),
    )
    docker_image: str | None = Field(
        default=None,
        description=(
            "Docker image used by the claude backend to run the in-container "
            "agent. None resolves to the runner's DEFAULT_IMAGE "
            "('annotator-agent:latest')."
        ),
    )
    feedback_bin_dir: Path | None = Field(
        default=None,
        description=(
            "Host directory containing the annotation-dryrun binary. The claude "
            "backend runs a host-side dryrun_service that invokes it (hermes "
            "stays on the host; the in-container agent reaches it via a file "
            "protocol over the bind-mount, never directly). None disables the "
            "dryrun tool."
        ),
    )
    jelly_bin: Path | None = Field(
        default=None,
        description=(
            "Host path to the Jelly executable (e.g. `jelly`, or "
            "`node /path/to/jelly/lib/main.js`). When set, the claude backend "
            "runs a host-side priors_service so the agent's reanalyze_call_graph "
            "tool can re-run Jelly with call-edge priors (--call-edge-priors), "
            "making manual edge overrides actually affect points-to. None "
            "disables it (the in-session edge views still work, just not re-analysis)."
        ),
    )
    enabled_tools: list[str] | None = Field(
        default=None,
        description=(
            "Which additional in-process MCP tool servers to enable for the agent. "
            "The five-stage workflow servers 'chunk', 'comments', and 'coverage' "
            "are always enabled. The 'annotations' server (list/add/delete_annotation) "
            "is also always enabled and is not listed here — the agent maintains the "
            "annotation set through it, never by writing a file. Opt into "
            "'source-fold', 'source-locate', 'dryrun' (reads the live annotation "
            "document), and the Jelly tools 'jelly' / 'jelly-dataflow' by listing "
            "them; 'jelly' benefits from jelly_bin for re-analysis. Unknown names "
            "are ignored."
        ),
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
        "--output-run",
        type=Path,
        help="Agent run record JSON (meta + raw messages, thinking_tokens "
        "filtered) for post-hoc analysis. Defaults to <output>.run.json",
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
    parser.add_argument(
        "--append-prompt",
        metavar="TEXT",
        default=None,
        help="Append extra TEXT after the built prompt for this run only.",
    )
    args = parser.parse_args()
    if args.append_prompt and args.append_prompt.startswith("@"):
        args.append_prompt = Path(args.append_prompt[1:]).read_text(encoding="utf-8")
    return args


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
