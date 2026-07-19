"""In-process MCP source tools for the annotator agent.

Each tool is a self-contained module exposing ``make_*_server`` (container-side
MCP factory) and, if it needs host-side setup, ``host_setup`` (start its own
service thread / pre-generate its own data / find its own binary). The
orchestrator (claude.py / agent_worker.py) only reads the registry +
``resolve_enabled`` — it does not know any specific tool (no dryrun/jelly/
feedback literals here).

**Nothing is enabled by default**: ``resolve_enabled(None) == []``. Every tool,
including the core fold/locate/dryrun, must be listed in ``config.enabled_tools``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from .dryrun_tool import make_dryrun_server
from .fold_tool import make_fold_server
from .locate_tool import make_locate_server

if TYPE_CHECKING:
    from ..config import AgentConfig


@dataclass
class ToolSpec:
    """A registered tool: container-side MCP factory + host-side setup hook."""
    make_server: Callable[[Path, Path], Any]
    host_setup: Callable[[Path, str, "AgentConfig", threading.Event], list[threading.Thread]]
    prompt: str


# --- host_setup wrappers (lazy import so the default import stays tool-free) --- #

def _no_host_setup(*_args: Any, **_kwargs: Any) -> list[threading.Thread]:
    return []


def _dryrun_host_setup(
    attempt_dir: Path, source_name: str, config: "AgentConfig", stop_event: threading.Event,
) -> list[threading.Thread]:
    from .dryrun_tool import host_setup
    return host_setup(attempt_dir, source_name, config, stop_event)


def _jelly_make(source: Path, workdir: Path) -> dict[str, Any]:
    from .callgraph_tool import make_callgraph_server
    return make_callgraph_server(source, workdir)


def _jelly_host_setup(
    attempt_dir: Path, source_name: str, config: "AgentConfig", stop_event: threading.Event,
) -> list[threading.Thread]:
    from .callgraph_tool import host_setup
    return host_setup(attempt_dir, source_name, config, stop_event)


def _jelly_dataflow_make(source: Path, workdir: Path) -> dict[str, Any]:
    from .dataflow_tool import make_dataflow_server
    return make_dataflow_server(source, workdir)


def _jelly_dataflow_host_setup(
    attempt_dir: Path, source_name: str, config: "AgentConfig", stop_event: threading.Event,
) -> list[threading.Thread]:
    from .dataflow_tool import host_setup
    return host_setup(attempt_dir, source_name, config, stop_event)


# The single registry. Add a tool = add one entry; the orchestrator (claude/agent_worker/prompt)
# never changes. Each entry carries its own prompt section (open/closed: build_prompt just joins).
REGISTRY: dict[str, ToolSpec] = {
    "source-fold": ToolSpec(
        lambda s, w: make_fold_server(s), _no_host_setup,
        prompt=(
            "- Use the `fold` tool first to get a structural view of large files: it folds "
            "multi-line blocks into ` … N lines folded …` and prints 1-based line numbers. "
            "Raise `unfold` (default 0) to expand a region, e.g. fold(from_line=176, to_line=200, unfold=1)."
        ),
    ),
    "source-locate": ToolSpec(
        lambda s, w: make_locate_server(s), _no_host_setup,
        prompt=(
            "- Use the `locate` tool to get exact source ranges for annotations instead of "
            "grep/awk or counting columns by hand. Example: locate(from_line=2, to_line=5, text=\"abc\"). "
            "It returns each match as `line:startcol-endline:endcol` — 1-based, EXCLUSIVE end column, "
            "cross-line OK — which matches the annotation format, plus a line-numbered context snippet "
            "with the match wrapped in »…«. Omit from_line/to_line to search the whole file. "
            "Pin one occurrence with `following`/`followed_by` (literal text, only whitespace between). "
            "Never guess a column."
        ),
    ),
    "dryrun": ToolSpec(
        lambda s, w: make_dryrun_server(w), _dryrun_host_setup,
        prompt=(
            "- After writing/editing annotations, call `dryrun_annotation` to check their effect — "
            "it compiles the file (trimmed pipeline, no execution) and caches the result, returning a "
            "whole-file summary (optimized / killed / no-effect). Example: dryrun_annotation(annotation=\"annotation.json\").\n"
            "- Then call `query_feedback` to inspect the cached result (optionally narrowed to a line range "
            "or a previous run). Per annotation it reports load failures, optimizations, kills, and no-effects; "
            "out-of-range effects show as \"somewhere else\". Iterate until no load failures and no surprising kills."
        ),
    ),
    "jelly": ToolSpec(
        _jelly_make, _jelly_host_setup,
        prompt=(
            "Jelly call-graph / heat tools identify functions / call sites by their **range** "
            "(startLine:startCol-endLine:endCol, 1-based, no filename — there's only one file); "
            "copy a range from one tool's output into another's argument.\n"
            "- Call graph: `view_callgraph(from_line=, to_line=)` lists call sites and their callees; "
            "`get_callers(callee=)` / `get_callees(caller=)` or `get_callees(callsite=)` look one up; "
            "`add_call_edges(edges=[{callsite, callee}])` / `delete_call_edges(...)` fix an edge Jelly got wrong.\n"
            "- Heat: `view_hot_value()` ranks functions by expected call frequency — annotate the hottest first; "
            "`set_hot_value(func=, value=)`, `set_exec_expt(callsite=, value=)`, "
            "`set_target_prob(callsite=, callee=, prob=)` calibrate with known runtime numbers."
        ),
    ),
    "jelly-dataflow": ToolSpec(
        _jelly_dataflow_make, _jelly_dataflow_host_setup,
        prompt=(
            "- Data flow: `query_dataflow(source=\"sl:sc:el:ec\")` — pass a range "
            "(startLine:startCol-endLine:endCol, 1-based, no filename); which source expressions "
            "a value starting there may flow to."
        ),
    ),
}


def resolve_enabled(enabled: list[str] | None) -> list[str]:
    """Normalize the enabled list. None → [] (no tools on by default)."""
    return list(enabled) if enabled else []


def build_source_mcp_servers(
    source: Path, workdir: Path, enabled: list[str] | None = None,
) -> dict[str, Any]:
    """Container-side: build the MCP servers for the enabled tools."""
    return {
        name: REGISTRY[name].make_server(source, workdir)
        for name in resolve_enabled(enabled)
        if name in REGISTRY
    }


def run_host_setups(
    attempt_dir: Path, source_name: str, config: "AgentConfig", stop_event: threading.Event,
    enabled: list[str] | None = None,
) -> list[threading.Thread]:
    """Host-side: run each enabled tool's host_setup, return un-started Threads.

    The orchestrator starts/joins them around the docker run (single lifecycle).
    """
    threads: list[threading.Thread] = []
    for name in resolve_enabled(enabled):
        spec = REGISTRY.get(name)
        if spec is not None:
            threads.extend(spec.host_setup(attempt_dir, source_name, config, stop_event))
    return threads
