"""In-process MCP ``coverage`` tool (phase 5 review).

Join the function universe (tree-sitter), target ranges in the live annotation
document, and explicit skip sidecars. Report coverage ratio plus uncovered
loc_keys so the main review agent can close gaps. Coverage = annotated ∪ skipped
and the goal is uncovered → 0.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from .annotation_tool import AnnotationDocument
from .chunk_tool import CHUNKS_SUBDIR, _read_skips, load_index
from .utils import _err


def _point(rng: dict[str, Any], half: str) -> tuple[int, int] | None:
    value = rng.get(half)
    if not isinstance(value, dict):
        return None
    line, column = value.get("line"), value.get("column")
    if not isinstance(line, int) or not isinstance(column, int):
        return None
    return line, column


def _contains(func: dict[str, Any], rng: dict[str, Any]) -> bool:
    """Whether ``func`` fully contains half-open annotation range ``rng``."""
    start, end = _point(rng, "start"), _point(rng, "end")
    if start is None or end is None:
        return False
    func_start = (func["start_line"], func["start_col"])
    func_end = (func["end_line"], func["end_col"])
    return func_start <= start and end <= func_end


def _annotation_owners(
    doc: AnnotationDocument, universe: list[dict[str, Any]]
) -> tuple[set[str], list[dict[str, Any]]]:
    """Assign every target range to its unique innermost containing function."""
    owners: set[str] = set()
    unattributed: list[dict[str, Any]] = []
    items = doc.shape_bindings + doc.shape_guards + doc.type_guards
    for item in items:
        rng = item.get("target range")
        if not isinstance(rng, dict):
            unattributed.append(item)
            continue
        containing = [func for func in universe if _contains(func, rng)]
        if not containing:
            unattributed.append(item)
            continue
        # Among enclosing function nodes, the innermost function starts latest.
        # This is exact for tree-sitter's properly nested function ranges.
        owner = max(
            containing,
            key=lambda func: (func["start_line"], func["start_col"]),
        )
        owners.add(owner["loc_key"])
    return owners, unattributed


def _read_all_skips(workdir: Path) -> dict[str, dict[str, Any]]:
    """loc_key -> skip record, across all chunk skip sidecars."""
    out: dict[str, dict[str, Any]] = {}
    d = workdir / CHUNKS_SUBDIR
    if not d.is_dir():
        return out
    for sf in sorted(d.glob("chunk_*.skips.json")):
        for s in _read_skips(sf):
            lk = s.get("loc_key")
            if isinstance(lk, str):
                out[lk] = s
    return out


def build_coverage_tools(source: Path, workdir: Path, doc: AnnotationDocument) -> list:
    """Build ``coverage``, bound to ``source``, ``workdir``, and the shared doc."""
    source_resolved = source.resolve()
    workdir_resolved = workdir.resolve()

    @tool(
        "coverage",
        "Report function coverage: how many functions in the universe are "
        "annotated OR explicitly skipped (COVERED) vs uncovered. A function is "
        "annotated if an annotation target belongs to it as its innermost "
        "fully containing function; skipped if "
        "record_skip was called on it. Returns the ratio + the uncovered "
        "loc_key list (with names + chunk ids) so you can close gaps. Goal: "
        "uncovered → 0 (skip genuinely unanalyzable functions rather than "
        "leave them silent).",
        {"type": "object", "properties": {}},
    )
    async def coverage(args: dict[str, Any]) -> dict[str, Any]:
        try:
            index = load_index(source_resolved, workdir_resolved)
        except FileNotFoundError:
            return _err(f"source file not found: {source_resolved}")
        except OSError as exc:
            return _err(f"cannot read {source_resolved!r}: {exc}")

        universe = index["function_universe"]
        by_loc = {f["loc_key"]: f for f in universe}
        annotated, unattributed = _annotation_owners(doc, universe)

        skips = _read_all_skips(workdir_resolved)
        skipped = {lk for lk in skips if lk in by_loc}

        universe_lks = set(by_loc)
        uncovered = sorted(universe_lks - annotated - skipped)
        total = len(universe_lks)
        covered = total - len(uncovered)
        ratio = covered / total if total else 0.0

        cat_counts: dict[str, int] = {}
        for lk in skipped:
            cat = skips[lk].get("category", "other")
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

        out: list[str] = [
            f"Coverage: {covered}/{total} ({ratio:.0%})  "
            f"annotated={len(annotated)}  skipped={len(skipped)}  "
            f"uncovered={len(uncovered)}",
        ]
        if cat_counts:
            cats = ", ".join(f"{k}={v}" for k, v in sorted(cat_counts.items()))
            out.append(f"skip categories: {cats}")
        if unattributed:
            out.append(f"unattributed annotations: {len(unattributed)}")
        if uncovered:
            out.append("Uncovered functions (loc_key name [chunk_id]):")
            for lk in uncovered[:50]:
                f = by_loc[lk]
                out.append(f"  {lk} {f['name']} [{f.get('chunk_id', '?')}]")
            if len(uncovered) > 50:
                out.append(f"  ... and {len(uncovered) - 50} more")
            out.append(
                "Spawn annotate-chunk subagents for these, or record_skip each "
                "with a real reason."
            )
        else:
            out.append("Every function is annotated or explicitly skipped.")
        return {"content": [{"type": "text", "text": "\n".join(out)}]}

    return [coverage]


def make_coverage_server(source: Path, workdir: Path, doc: AnnotationDocument):
    """Build the in-process MCP server exposing coverage."""
    return create_sdk_mcp_server(
        name="coverage", tools=build_coverage_tools(source, workdir, doc)
    )
