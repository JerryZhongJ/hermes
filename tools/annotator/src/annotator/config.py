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

    agent: Literal["claude"]
    model: str | None = None
    env: dict[str, Any] = Field(default_factory=dict)
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
            "runs a host-side callgraph_service so the agent's reanalyze_call_graph "
            "tool can re-run Jelly with call-edge priors (--call-edge-priors), "
            "making manual edge overrides actually affect points-to. None "
            "disables it (the in-session edge views still work, just not re-analysis)."
        ),
    )
    workflow: str = Field(
        default="annotate-hotspot-functions",
        description=(
            "Deprecated config-level run selector, superseded by the CLI "
            "--workflow flag; kept only so existing config files still validate "
            "under extra='forbid'. Never set it in new configs."
        ),
    )
    enabled_tools: list[str] | None = Field(
        default=None,
        description=(
            "Which additional in-process MCP tool servers to enable for the agent. "
            "The 'annotations' server (list/add/delete_annotation) is always "
            "enabled and is not listed here — the agent maintains the annotation "
            "set through it, never by writing a file. Opt into 'source-fold', "
            "'source-locate', 'dryrun' (reads the live annotation document), and "
            "the Jelly tools 'jelly' / 'jelly-dataflow' by listing them; 'jelly' "
            "benefits from jelly_bin for re-analysis. Unknown names are ignored."
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Hermes typed-shape annotation JSON with an agent."
    )
    parser.add_argument("input", type=Path, help="JavaScript input file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Output DIRECTORY receiving the whole attempt workdir — "
        "saved annotation products (main.json for annotate-file, "
        "hotspot:*.json for hotspot runs), transcripts, and status "
        "(must not already exist)",
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
        help="Agent run manifest JSON referencing the native Claude transcript. "
        "Defaults to <output>.run.json",
    )
    parser.add_argument(
        "--workflow",
        default="annotate-hotspot-functions",
        metavar="NAME",
        help="Run one registered workflow (default: annotate-hotspot-functions; "
        "also: annotate-file, annotate-file-parallel).",
    )
    parser.add_argument(
        "--target-function",
        action="append",
        default=[],
        metavar="LOC_KEY",
        help=(
            "Exact function loc_key sl:sc (the function's start point). "
            "Repeat for multiple targets; "
            "valid for annotate-hotspot-functions."
        ),
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
    args = parser.parse_args(argv)
    if args.append_prompt and args.append_prompt.startswith("@"):
        args.append_prompt = Path(args.append_prompt[1:]).read_text(encoding="utf-8")
    return args


def load_config(path: Path) -> AgentConfig:
    try:
        config = AgentConfig.model_validate_json(path.read_text(encoding="utf-8"))
        from .workflows import resolve_workflow_factory

        resolve_workflow_factory(config.workflow)
        return config
    except FileNotFoundError:
        raise ValueError(f"config file not found: {path}") from None
    except ValidationError as exc:
        raise ValueError(str(exc)) from None


def effective_config(
    config: AgentConfig,
    *,
    workflow_override: str | None = None,
) -> AgentConfig:
    """Return the immutable per-run config after applying CLI overrides."""
    if workflow_override is not None:
        from .workflows import resolve_workflow_factory

        resolve_workflow_factory(workflow_override)
        return config.model_copy(update={"workflow": workflow_override})
    return config


def validate_workflow_targets(
    workflow: str, targets: list[str], source_path: Path
) -> tuple[str, ...]:
    """Validate workflow/target compatibility and exact function identities.

    This pure pre-Docker gate is shared by the CLI and tests. Targets are
    deduplicated in first-seen order after exact matching against the function
    universe produced by ``extract_functions``.
    """
    from .workflows import resolve_workflow_factory

    resolved = resolve_workflow_factory(workflow)
    unique = tuple(dict.fromkeys(targets))
    if not resolved.accepts_targets:
        if unique:
            raise ValueError(f"run {workflow!r} does not accept target functions")
        return ()
    if not unique:
        raise ValueError(
            f"run {workflow!r} requires at least one --target-function"
        )

    from .tools.functions import extract_functions

    available = {item["loc_key"] for item in extract_functions(source_path.read_bytes())}
    missing = [target for target in unique if target not in available]
    if missing:
        raise ValueError(
            "target function loc_key(s) not found exactly in source: "
            + ", ".join(missing)
        )
    return unique


def system_proxy_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
    }
