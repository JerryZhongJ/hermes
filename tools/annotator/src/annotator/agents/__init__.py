"""Agent runner interface and factory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..workflows import AnnotationRequest

from ..config import AgentConfig


@dataclass(frozen=True)
class TraceSource:
    """Claude Code transcript still located in the attempt directory.

    ``main`` is the coordinator session. ``others`` carries every OTHER
    session jsonl of the same run (the workers' subagent sessions) so their
    transcripts survive the attempt-dir teardown too.
    """

    main: Path
    session_id: str
    others: tuple[Path, ...] = ()


@dataclass(frozen=True)
class TraceArtifact:
    """Published immutable transcript directory referenced by run.json."""

    directory: Path
    session_id: str
    complete: bool


@dataclass(frozen=True)
class AgentRun:
    errors: list[str]
    trace_source: TraceSource | None = None
    trace: TraceArtifact | None = None
    timed_out: bool = False
    container_exit_code: int | None = None
    worker_completed: bool = False
    workflow: str = "annotate-hotspot-functions"
    targets: tuple[str, ...] = ()
    output_published: bool = False
    output_sha256: str | None = None


class AgentRunner(Protocol):
    def run(
        self,
        attempt_dir: Path,
        source_name: str,
        request: AnnotationRequest,
        append_prompt: str | None = None,
    ) -> AgentRun:
        ...


def create_runner(config: AgentConfig, timeout_seconds: int) -> AgentRunner:
    # The annotation document is maintained through the in-process annotation
    # MCP, which only the Claude backend supports.
    if config.agent == "claude":
        from ..docker_runner import DockerRunner

        return DockerRunner(config, timeout_seconds)
    raise ValueError(f"unsupported agent: {config.agent}")
