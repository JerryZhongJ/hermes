"""In-process MCP source tools for the annotator agent.

Each tool is a self-contained module exposing ``make_*_server`` (container-side
MCP factory) and, if it needs host-side setup, ``host_setup`` (start its own
service thread / pre-generate its own data / find its own binary). The
orchestrator (claude.py / agent_worker.py) only reads the registry +
``resolve_enabled`` — it does not know any specific tool (no dryrun/jelly/
feedback literals here).

The **annotation tools** (``list_annotations`` / ``add_annotation`` /
``delete_annotation``) are MANDATORY: they are always enabled regardless of
``config.enabled_tools`` and cannot be turned off. They own the in-memory
``AnnotationDocument`` for the run; the agent maintains the document only
through them (never by writing ``annotation.json``). ``dryrun`` shares the
same document instance so ``dryrun_annotation`` reads the live snapshot
in-process instead of parsing the file.

The five-stage workflow servers (``chunk``, ``comments``, and ``coverage``) are
also mandatory: they remain enabled regardless of ``config.enabled_tools``.
Every other tool defaults to OFF; opt into fold/locate/dryrun/Jelly by listing
it in ``config.enabled_tools``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from .annotation_tool import AnnotationDocument, make_annotation_server
from .chunk_tool import make_chunk_server
from .comment_tool import make_comment_server
from .coverage_tool import make_coverage_server
from .fold_tool import make_fold_server
from .locate_tool import make_locate_server

if TYPE_CHECKING:
    from ..config import AgentConfig


@dataclass
class ToolSpec:
    """A registered tool: container-side MCP factory + host-side setup hook.

    ``make_server`` receives the shared ``AnnotationDocument`` so the annotation
    and dryrun tools can read/write the same in-memory state. Tools that don't
    need it simply ignore the argument.
    """

    make_server: Callable[[Path, Path, AnnotationDocument], Any]
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


def _jelly_make(source: Path, workdir: Path, doc: AnnotationDocument) -> dict[str, Any]:
    from .callgraph_tool import make_callgraph_server
    return make_callgraph_server(source, workdir)


def _jelly_host_setup(
    attempt_dir: Path, source_name: str, config: "AgentConfig", stop_event: threading.Event,
) -> list[threading.Thread]:
    from .callgraph_tool import host_setup
    return host_setup(attempt_dir, source_name, config, stop_event)


def _jelly_dataflow_make(source: Path, workdir: Path, doc: AnnotationDocument) -> dict[str, Any]:
    from .dataflow_tool import make_dataflow_server
    return make_dataflow_server(source, workdir)


def _jelly_dataflow_host_setup(
    attempt_dir: Path, source_name: str, config: "AgentConfig", stop_event: threading.Event,
) -> list[threading.Thread]:
    from .dataflow_tool import host_setup
    return host_setup(attempt_dir, source_name, config, stop_event)


# The single registry. Add a tool = add one entry; the orchestrator
# (claude/agent_worker/prompt) never changes. Each entry carries its own prompt
# section (open/closed: build_prompt just joins). The annotation tools are not
# here — they are mandatory and injected unconditionally by
# build_source_mcp_servers.
REGISTRY: dict[str, ToolSpec] = {
    "source-fold": ToolSpec(
        lambda s, w, d: make_fold_server(s), _no_host_setup,
        prompt=(
            "- Use the `fold` tool first to get a structural view of large files: it folds "
            "multi-line blocks into ` … N lines folded …` and prints 1-based line numbers. "
            "Raise `unfold` (default 0) to expand a region, e.g. fold(from_line=176, to_line=200, unfold=1)."
        ),
    ),
    "source-locate": ToolSpec(
        lambda s, w, d: make_locate_server(s), _no_host_setup,
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
    "annotations": ToolSpec(
        lambda s, w, d: make_annotation_server(s, w, d), _no_host_setup,
        prompt=(
            "- Build the annotation set ONLY through `list_annotations`, `add_annotation`, "
            "and `delete_annotation`. There is no annotation file — the set is held in memory "
            "and finalized for you when the run ends.\n"
            "- `list_annotations(kinds?, shape?, from_line?, to_line?)` shows current annotations; "
            "filter by kind (static_shape/shape_binding/shape_guard/type_guard), by shape name, or "
            "by a 1-based inclusive line window (both from_line and to_line, or neither). Each row "
            "carries an `id` (kind:index:revision) for delete_annotation. Static shapes have no "
            "source range, so a line filter hides them.\n"
            "- `add_annotation(kind, annotation, shape?)` appends one annotation; duplicates and "
            "references to unknown shapes are rejected. Always add the static shape BEFORE any "
            "guard/binding that uses it.\n"
            "- `delete_annotation(id)` removes one annotation by a fresh id from list_annotations "
            "(the id embeds the revision; a stale id after a mutation is rejected). A static shape "
            "still used by a guard/binding cannot be deleted."
        ),
    ),
    "dryrun": ToolSpec(
        lambda s, w, d: _make_dryrun_with_doc(w, d), _dryrun_host_setup,
        prompt=(
            "- After changing annotations via add_annotation/delete_annotation, call "
            "`dryrun_annotation` to check their effect — it compiles the file (trimmed pipeline, "
            "no execution) against the CURRENT in-memory document and caches the result, returning "
            "a whole-file summary (optimized / killed / no-effect).\n"
            "- Then call `query_feedback` to inspect the cached result (optionally narrowed to a "
            "line range or a previous run). Per annotation it reports load failures, optimizations, "
            "kills, and no-effects; out-of-range effects show as \"somewhere else\". Iterate until "
            "no load failures and no surprising kills."
        ),
    ),
    "jelly": ToolSpec(
        _jelly_make, _jelly_host_setup,
        prompt=(
            "Jelly tools come from static analysis — results are conservative over-approximations "
            "(call graph may have spurious edges; heat is an estimate, not a measurement). "
            "Trust dryrun_feedback for ground truth.\n"
            "Functions / call sites are identified by their **range** "
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
            "- Data flow: `query_dataflow(source=\"sl:sc:el:ec\", direction=\"forward|reverse|both\")` — "
            "may-flow from static analysis (possible, not certain; conservative over-approximation). "
            "Pass a range (startLine:startCol-endLine:endCol); forward shows where the value goes, "
            "reverse shows where it comes from. `get_definition(source)` resolves an identifier to "
            "its declaration."
        ),
    ),
    "chunk": ToolSpec(
        lambda s, w, d: make_chunk_server(s, w), _no_host_setup,
        prompt=(
            "- `chunk_index()` splits the file into chunks along function boundaries and "
            "returns the function universe (loc_keys) + chunk plan. `read_chunk(chunk_id)` "
            "reads one chunk's source. `record_skip(loc_key, category, reason)` marks a "
            "function 'does not fit' so it still counts as covered. loc_key is "
            "startLine:startCol:endLine:endCol (1-based, exclusive end)."
        ),
    ),
    "comments": ToolSpec(
        lambda s, w, d: make_comment_server(s, w), _no_host_setup,
        prompt=(
            "- `write_comment(phase, from_line, to_line, comment, chunk_id?)` records a staged "
            "note. phase1/phase2/phase4 notes require their producing chunk_id and must stay inside "
            "that chunk; phase3/phase5 main-agent decisions may omit it. The comments MCP serializes "
            "writers and atomically publishes the shared sidecar; never write it directly. "
            "`list_comments(phase?, chunk_id?, from_line?, to_line?)` filters prior notes; without "
            "filters it lists all completed-stage notes."
        ),
    ),
    "coverage": ToolSpec(
        lambda s, w, d: make_coverage_server(s, w, d), _no_host_setup,
        prompt=(
            "- `coverage()`: report function coverage (annotated ∪ skipped over the universe) "
            "+ the uncovered loc_key list so you can close gaps. Goal: uncovered → 0."
        ),
    ),
}


def _make_dryrun_with_doc(workdir: Path, doc: AnnotationDocument) -> dict[str, Any]:
    """Build the dryrun server bound to the shared document (live snapshot)."""
    from .dryrun_tool import make_dryrun_server
    return make_dryrun_server(workdir, doc)


WORKFLOW_TOOLS = ("chunk", "comments", "coverage")


def resolve_enabled(enabled: list[str] | None) -> list[str]:
    """Return mandatory workflow tools plus configured optional tools.

    The annotation tools are injected separately by
    :func:`build_source_mcp_servers`. Preserve first occurrence order so prompt
    sections and server setup have a deterministic, shared tool order.
    """
    names = [*WORKFLOW_TOOLS, *(enabled or [])]
    return list(dict.fromkeys(names))


def build_source_mcp_servers(
    source: Path,
    workdir: Path,
    doc: AnnotationDocument,
    enabled: list[str] | None = None,
) -> dict[str, Any]:
    """Container-side: build the MCP servers.

    The annotation server is always present (mandatory) and shares ``doc``.
    Each enabled optional tool that wants the live document (dryrun) gets the
    same ``doc``; the rest ignore it.
    """
    servers: dict[str, Any] = {"annotations": make_annotation_server(source, workdir, doc)}
    for name in resolve_enabled(enabled):
        spec = REGISTRY.get(name)
        if spec is None:
            continue
        servers[name] = spec.make_server(source, workdir, doc)
    return servers


def run_host_setups(
    attempt_dir: Path, source_name: str, config: "AgentConfig", stop_event: threading.Event,
    enabled: list[str] | None = None,
) -> list[threading.Thread]:
    """Host-side: run each enabled tool's host_setup, return un-started Threads.

    The orchestrator starts/joins them around the docker run (single lifecycle).
    The annotation tools have no host needs.
    """
    threads: list[threading.Thread] = []
    for name in resolve_enabled(enabled):
        spec = REGISTRY.get(name)
        if spec is not None:
            threads.extend(spec.host_setup(attempt_dir, source_name, config, stop_event))
    return threads
