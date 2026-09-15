"""In-process MCP source tools for the annotator agent.

Each tool is a self-contained module exposing ``make_*_server`` (container-side
MCP factory) and, if it needs host-side setup, ``host_setup`` (start its own
service thread / pre-generate its own data / find its own binary). The
orchestrator (claude.py / agent_worker.py) only reads the registry +
``resolve_enabled`` — it does not know any specific tool (no dryrun/jelly/
feedback literals here).

The **annotation tools** (including ``list_annotations``, ``add_annotation``,
``batch_add_guards``, ``update_annotation``, and ``delete_annotation``)
are MANDATORY: they are always enabled regardless of
``config.enabled_tools`` and cannot be turned off. They operate on the named
drafts of the shared :mod:`annotator.annotation_drafts` store (the
construction-time argument is simply the list of draft names this agent may
use, plus the default for the omitted ``draft`` argument); the agent maintains
a draft only through them (never by writing ``annotation.json``). ``dryrun``
snapshots the same drafts by name.

Every tool defaults to OFF; opt into fold/locate/dryrun/Jelly by listing it in
``config.enabled_tools`` or through a workflow's ``required_tools``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from . import annotation_tool, callgraph_tool, dataflow_tool, dryrun_tool
from . import fold_tool, locate_tool, checklist_tool


if TYPE_CHECKING:
    from ..config import AgentConfig


@dataclass
class ToolSpec:
    """A registered tool: container-side MCP factory + host-side setup hook.

    ``make_server`` receives the per-agent drafts access ``(names, default)``
    (or None) and optional workflow workspace. Tools that don't need either
    simply ignore them.
    """

    make_server: Callable[[Path, Path, Any, Any | None], Any]
    host_setup: Callable[[Path, str, "AgentConfig", threading.Event], list[threading.Thread]]
    prompt: str


# --- host_setup wrappers (lazy import so the default import stays tool-free) --- #

def _no_host_setup(*_args: Any, **_kwargs: Any) -> list[threading.Thread]:
    return []


def _fold_make(source: Path, _workdir: Path, _view: Any, _workspace: Any | None) -> Any:
    from .fold_tool import make_fold_server

    return make_fold_server(source)


def _locate_make(source: Path, _workdir: Path, _view: Any, _workspace: Any | None) -> Any:
    from .locate_tool import make_locate_server

    return make_locate_server(source)


def _annotations_make(
    source: Path, workdir: Path, drafts_access: Any, _workspace: Any | None
) -> Any:
    from .annotation_tool import make_annotation_server

    if drafts_access is None:
        return make_annotation_server(source, workdir, None, None)
    return make_annotation_server(source, workdir, *drafts_access)


def _dryrun_make(
    _source: Path, workdir: Path, drafts_access: Any, _workspace: Any | None
) -> Any:
    return _make_dryrun_with_doc(workdir, drafts_access)


def _dryrun_host_setup(
    attempt_dir: Path, source_name: str, config: "AgentConfig", stop_event: threading.Event,
) -> list[threading.Thread]:
    from .dryrun_tool import host_setup
    return host_setup(attempt_dir, source_name, config, stop_event)


def _jelly_make(source: Path, workdir: Path, _view: Any, _workspace: Any | None) -> Any:
    from .callgraph_tool import make_callgraph_server
    return make_callgraph_server(source, workdir)


def _jelly_host_setup(
    attempt_dir: Path, source_name: str, config: "AgentConfig", stop_event: threading.Event,
) -> list[threading.Thread]:
    from .callgraph_tool import host_setup
    return host_setup(attempt_dir, source_name, config, stop_event)


def _jelly_dataflow_make(
    source: Path, workdir: Path, _view: Any, _workspace: Any | None
) -> dict[str, Any]:
    from .dataflow_tool import make_dataflow_server
    return make_dataflow_server(source, workdir)


def _jelly_dataflow_host_setup(
    attempt_dir: Path, source_name: str, config: "AgentConfig", stop_event: threading.Event,
) -> list[threading.Thread]:
    from .dataflow_tool import host_setup
    return host_setup(attempt_dir, source_name, config, stop_event)


def _checklist_make(
    source: Path, workdir: Path, drafts_access: Any, _workspace: Any | None
) -> Any:
    from .dryrun_tool import run_dryrun_sync
    from .checklist_tool import make_checklist_server

    if drafts_access is None:
        # Open access: no default — every call passes draft= explicitly.
        return make_checklist_server(source, run_dryrun_sync(workdir, None), None)
    names, default = drafts_access
    # Freshness/reasons follow the agent's default draft (its own).
    return make_checklist_server(
        source, run_dryrun_sync(workdir, default or (names[0] if names else None)), default
    )


# The single registry. Add a tool = add one entry; the orchestrator
# (claude/agent_worker/prompt) never changes. Each entry carries its own prompt
# section (open/closed: build_prompt just joins). The annotation tools are not
# here — they are mandatory and injected unconditionally by
# build_source_mcp_servers.
REGISTRY: dict[str, ToolSpec] = {
    "source-fold": ToolSpec(
        _fold_make, _no_host_setup,
        prompt=fold_tool.PROMPT,
    ),
    "source-locate": ToolSpec(
        _locate_make, _no_host_setup,
        prompt=locate_tool.PROMPT,
    ),
    "annotations": ToolSpec(
        _annotations_make, _no_host_setup,
        prompt=annotation_tool.PROMPT,
    ),
    "dryrun": ToolSpec(
        _dryrun_make, _dryrun_host_setup,
        prompt=dryrun_tool.PROMPT,
    ),
    "jelly": ToolSpec(
        _jelly_make, _jelly_host_setup,
        prompt=callgraph_tool.PROMPT,
    ),
    "jelly-dataflow": ToolSpec(
        _jelly_dataflow_make, _jelly_dataflow_host_setup,
        prompt=dataflow_tool.PROMPT,
    ),
    "checklist": ToolSpec(
        _checklist_make,
        _no_host_setup,
        prompt=checklist_tool.PROMPT,
    ),
}


def _make_dryrun_with_doc(workdir: Path, drafts_access: Any) -> dict[str, Any]:
    """Build the dryrun server bound to the agent's drafts (live snapshot)."""
    from .dryrun_tool import make_dryrun_server
    if drafts_access is None:
        return make_dryrun_server(workdir, None, None)
    return make_dryrun_server(workdir, *drafts_access)


DEFAULT_REQUIRED_TOOLS: tuple[str, ...] = ()


def resolve_enabled(
    enabled: list[str] | None,
    required_tools: tuple[str, ...] | list[str] | None = None,
) -> list[str]:
    """Return required workflow tools plus configured optional tools.

    Omitting ``required_tools`` preserves the historical full-workflow default.
    The annotation tools are injected separately by
    :func:`build_source_mcp_servers`. Preserve first occurrence order so prompt
    sections and server setup have a deterministic, shared tool order.
    """
    required = DEFAULT_REQUIRED_TOOLS if required_tools is None else required_tools
    unknown_required = [name for name in required if name not in REGISTRY]
    if unknown_required:
        raise ValueError(
            "unknown required tool(s): " + ", ".join(unknown_required)
        )
    names = [*required, *(enabled or [])]
    return list(dict.fromkeys(names))


def resolve_host_setup_tools(
    enabled: list[str] | None,
    required_tools: tuple[str, ...] | list[str] | None = None,
) -> list[str]:
    """Deduplicate host-side service setup across tool specs.

    Two specs may share one host service (``dryrun`` and ``checklist``
    both consume the annotation-dryrun service): start it once per run, not
    once per spec.
    """
    resolved: list[str] = []
    for name in resolve_enabled(enabled, required_tools):
        if name in resolved:
            continue
        # checklist has no host setup of its own; it shares dryrun's.
        if name == "checklist":
            continue
        resolved.append(name)
    return resolved


def render_tool_sections(
    enabled: list[str] | None,
    required_tools: tuple[str, ...] | list[str] | None = None,
) -> str:
    """Join the enabled tools' prompt sections for a run prompt.

    The one sanctioned bridge from tool registry to prompt construction: the
    workflow prompt layer calls this instead of walking REGISTRY itself.
    """
    return "\n".join(
        spec.prompt
        for name in resolve_enabled(enabled, required_tools)
        if (spec := REGISTRY.get(name)) is not None and spec.prompt
    )


def build_mcp_servers(
    source: Path,
    workdir: Path,
    drafts_access: Any,
    enabled: list[str] | None = None,
    required_tools: tuple[str, ...] | list[str] | None = None,
    workspace: Any | None = None,
) -> dict[str, Any]:
    """Container-side: build the MCP servers.

    ``drafts_access`` is the per-agent draft access over the process-wide
    drafts store, in one of two forms:

    - ``(names, default)`` — the agent may use the named drafts; ``default``
      is used when a tool's optional ``draft`` argument is omitted.
    - ``None`` — open access: any draft in the store by name (the parallel
      coordinators and their workers, whose draft names are only known at
      fan-out time).

    Each enabled optional tool that wants the live drafts (dryrun/checklist)
    gets the same access; the rest ignore it.
    """
    servers: dict[str, Any] = {}
    if drafts_access is None:
        # Open access: no enum, no default — every tool call passes draft=.
        access: tuple[Any, ...] = (None, None)
    else:
        access = tuple(drafts_access)
    from .annotation_tool import make_annotation_server

    servers["annotations"] = make_annotation_server(source, workdir, *access)
    for name in resolve_enabled(enabled, required_tools):
        spec = REGISTRY.get(name)
        if spec is None:
            continue
        servers[name] = spec.make_server(source, workdir, drafts_access, workspace)
    return servers


def run_host_setups(
    attempt_dir: Path, source_name: str, config: "AgentConfig", stop_event: threading.Event,
    enabled: list[str] | None = None,
    required_tools: tuple[str, ...] | list[str] | None = None,
) -> list[threading.Thread]:
    """Host-side: run each enabled tool's host_setup, return un-started Threads.

    The orchestrator starts/joins them around the docker run (single lifecycle).
    The annotation tools have no host needs. Tools sharing one host service
    (dryrun/checklist) get it started exactly once.
    """
    threads: list[threading.Thread] = []
    for name in resolve_host_setup_tools(enabled, required_tools):
        spec = REGISTRY.get(name)
        if spec is not None:
            threads.extend(spec.host_setup(attempt_dir, source_name, config, stop_event))
    return threads
