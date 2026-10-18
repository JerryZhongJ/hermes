"""Cross-tool scope-semantics tests (the unified ownership contract).

Every selecting tool (checklist / dryrun / list_annotations / batch_add_guards
/ locate / view_callgraph / view_hot_value) must agree on what a scope
selects: a function loc_key means that function's DIRECT statements only —
the innermost function owning a position decides, so nested functions' sites
belong to their own loc_keys and never appear in the enclosing scope.
"<top-level>" addresses module-level code; a line range keeps its historical
window behavior; ``fold`` stays the one literal-window exception.

These tests pin the agreement itself: the same loc_key scope picks the same
source positions through every tool's own pipeline.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from annotator.annotation_drafts import add_unique_draft
from annotator.tools.annotation_tool import build_annotation_tools
from annotator.tools.checklist_tool import build_checklist_tools, coverage_snapshot
from annotator.tools.dryrun_tool import build_dryrun_tools
from annotator.tools.functions import TOP_LEVEL_KEY, resolve_scope
from test_dryrun_tool import _report, _start_fake_host

# Module-level stores on lines 1-2; outer (3:1, lines 3-9) directly stores on
# line 4 and wraps inner (5:3, lines 5-7) whose own store is line 6; third
# (10:1, lines 10-12) stores on line 11.
SRC = b"""var g = {n: 1};
g.m = g.n + 1;
function outer(o) {
  o.x = 1;
  function inner(p) {
    p.y = 2;
  }
  return inner;
}
function third(t) {
  t.z = 3;
}
"""

OUTER = "3:1"
INNER = "5:3"
THIRD = "10:1"

# Checklist opportunities: one outer-direct site, one inner site, one
# module-level site, one third site.
OPPORTUNITIES = [
    {"kind": "property_store", "location": "4:3", "property": "x", "outcome": "not-optimized"},
    {"kind": "property_store", "location": "6:5", "property": "y", "outcome": "not-optimized"},
    {"kind": "property_store", "location": "2:1", "property": "m", "outcome": "not-optimized"},
    {"kind": "property_store", "location": "11:3", "property": "z", "outcome": "not-optimized"},
]


def _write_source(tmp_path: Path) -> Path:
    src = tmp_path / "input.js"
    src.write_bytes(SRC)
    return src


def _run(tool, args: dict) -> dict:
    return asyncio.run(tool.handler(args))


def _text(tool, args: dict) -> str:
    result = _run(tool, args)
    assert not result.get("is_error"), result
    return result["content"][0]["text"]


# --- the shared Selection itself -------------------------------------------- #


def test_outer_scope_owns_only_direct_statements(tmp_path: Path):
    _write_source(tmp_path)
    selection = resolve_scope(OUTER, SRC)
    assert selection.owns(4, 3)  # outer's direct store
    assert selection.owns(3, 1)  # the function's own start
    assert not selection.owns(6, 5)  # inner's store: inner owns it
    assert not selection.owns(11, 3)  # third's store
    assert not selection.owns(2, 1)  # module level
    # ranges select by their start's owner
    assert selection.selects_range("4:3:4:9")
    assert not selection.selects_range("6:5:6:11")
    assert selection.selects_range({"start": {"line": 4, "column": 3}, "end": {"line": 4, "column": 9}})


def test_top_level_selection_addresses_module_level_only(tmp_path: Path):
    _write_source(tmp_path)
    selection = resolve_scope(TOP_LEVEL_KEY, SRC)
    assert selection.owns(2, 1)
    assert not selection.owns(4, 3)
    assert not selection.owns(6, 5)


def test_scope_list_does_not_sweep_unlisted_nested_functions(tmp_path: Path):
    """[outer, third] must not drag in inner although its lines fall inside
    outer's extents — the old contiguous-window resolution did."""
    _write_source(tmp_path)
    selection = resolve_scope([OUTER, THIRD], SRC)
    assert selection.owns(4, 3)
    assert selection.owns(11, 3)
    assert not selection.owns(6, 5)


def test_line_window_keeps_window_semantics(tmp_path: Path):
    _write_source(tmp_path)
    selection = resolve_scope("4-6", SRC)
    assert selection.owns(4, 3)
    assert selection.owns(6, 5)  # a window is positional, ownership-blind
    assert not selection.owns(2, 1)
    assert selection.selects_range("2:1-4:9")  # overlap
    assert not selection.selects_range("7:3-8:16")


def test_malformed_scopes_raise_shared_help(tmp_path: Path):
    import pytest

    _write_source(tmp_path)
    for bad in ("999:1", "4-99", ["3:1", "bogus"], ""):
        with pytest.raises(ValueError):
            resolve_scope(bad, SRC)


# --- checklist / dryrun / list_annotations agree on one loc_key scope ------ #


def _checklist_tool(tmp_path: Path):
    async def fake_run(name=None):
        return {"opportunities": OPPORTUNITIES}

    return build_checklist_tools(tmp_path / "input.js", fake_run, add_unique_draft())[0]


def _dryrun_tool(tmp_path: Path, draft: str):
    report = _report(
        annotations=[
            {
                "range": "4:3-4:9",
                "kind": "shape guard",
                "detail": "outer-direct",
                "optimizations": [{"location": "4:5", "instruction": "PrLoadInst", "property": "x"}],
                "blockages": [],
                "miss": [],
            },
            {
                "range": "6:5-6:11",
                "kind": "shape guard",
                "detail": "inner-direct",
                "optimizations": [{"location": "6:7", "instruction": "PrLoadInst", "property": "y"}],
                "blockages": [],
                "miss": [],
            },
            {
                "range": "2:1-2:8",
                "kind": "shape guard",
                "detail": "module-level",
                "optimizations": [{"location": "2:3", "instruction": "PrLoadInst", "property": "m"}],
                "blockages": [],
                "miss": [],
            },
        ]
    )
    state, stop, thread = _start_fake_host(tmp_path, [report])
    (tool_obj,) = build_dryrun_tools(tmp_path, [draft])
    return tool_obj, stop, thread


def _annotation_tools(tmp_path: Path, draft: str):
    return {t.name: t for t in build_annotation_tools(tmp_path / "input.js", tmp_path, [draft])}


def test_outer_scope_selects_the_same_sites_across_tools(tmp_path: Path):
    """The core unification invariant: under OUTER, the checklist site set,
    the dryrun-selected annotations, and the listed annotation entries all
    cover exactly outer's direct store — never inner's, never module level."""
    _write_source(tmp_path)
    draft = add_unique_draft()

    # checklist
    list_checklist = _checklist_tool(tmp_path)
    payload = json.loads(_text(list_checklist, {"scope": OUTER}))
    assert {i["location"] for i in payload["checklist"]} == {"4:3"}

    # annotations: two guards, outer-direct and inner-direct
    tools = _annotation_tools(tmp_path, draft)
    # a shape guard needs a known shape first
    _run(tools["add_annotation"], {"kind": "static_shape", "shape": "S", "annotation": {"properties": []}})
    for rng in ("4:3:4:9", "6:5:6:11"):
        r = _run(
            tools["add_annotation"],
            {"kind": "shape_guard", "annotation": {"target range": rng, "shape": "S"}},
        )
        assert not r.get("is_error"), r
    listing = _text(tools["list_annotations"], {"scope": OUTER, "kinds": ["shape_guard"]})
    assert "4:3:4:9" in listing
    assert "6:5:6:11" not in listing

    # dryrun
    dryrun, stop, thread = _dryrun_tool(tmp_path, draft)
    try:
        text = _text(dryrun, {"scope": OUTER})
        assert "outer-direct" in text
        assert "inner-direct" not in text
        assert "module-level" not in text
        assert "1 optimized" in text  # only outer's feedback point
    finally:
        stop.set()
        thread.join(timeout=2)


def test_inner_scope_selects_inner_sites_across_tools(tmp_path: Path):
    _write_source(tmp_path)
    draft = add_unique_draft()

    list_checklist = _checklist_tool(tmp_path)
    payload = json.loads(_text(list_checklist, {"scope": INNER}))
    assert {i["location"] for i in payload["checklist"]} == {"6:5"}

    tools = _annotation_tools(tmp_path, draft)
    _run(tools["add_annotation"], {"kind": "static_shape", "shape": "S", "annotation": {"properties": []}})
    for rng in ("4:3:4:9", "6:5:6:11"):
        _run(tools["add_annotation"], {"kind": "shape_guard", "annotation": {"target range": rng, "shape": "S"}})
    listing = _text(tools["list_annotations"], {"scope": INNER, "kinds": ["shape_guard"]})
    assert "6:5:6:11" in listing
    assert "4:3:4:9" not in listing


def test_top_level_scope_across_tools(tmp_path: Path):
    _write_source(tmp_path)
    draft = add_unique_draft()

    # checklist: only the module-level store
    list_checklist = _checklist_tool(tmp_path)
    payload = json.loads(_text(list_checklist, {"scope": TOP_LEVEL_KEY}))
    assert {i["location"] for i in payload["checklist"]} == {"2:1"}

    # the completion hook agrees with the tool
    snapshot = coverage_snapshot({"opportunities": OPPORTUNITIES}, SRC, TOP_LEVEL_KEY)
    assert snapshot is not None and snapshot["total"] == 1

    # list_annotations: only the module-level guard
    tools = _annotation_tools(tmp_path, draft)
    _run(tools["add_annotation"], {"kind": "static_shape", "shape": "S", "annotation": {"properties": []}})
    for rng in ("2:1:2:8", "4:3:4:9"):
        _run(tools["add_annotation"], {"kind": "shape_guard", "annotation": {"target range": rng, "shape": "S"}})
    listing = _text(tools["list_annotations"], {"scope": TOP_LEVEL_KEY, "kinds": ["shape_guard"]})
    assert "2:1:2:8" in listing
    assert "4:3:4:9" not in listing

    # dryrun: only the module-level annotation
    dryrun, stop, thread = _dryrun_tool(tmp_path, draft)
    try:
        text = _text(dryrun, {"scope": TOP_LEVEL_KEY})
        assert "module-level" in text
        assert "outer-direct" not in text
        assert "inner-direct" not in text
    finally:
        stop.set()
        thread.join(timeout=2)


def test_locate_ref_scope_owns_hits_by_start_point(tmp_path: Path):
    from annotator.tools.locate_tool import build_locate_tool

    _write_source(tmp_path)
    tool = build_locate_tool(tmp_path / "input.js")
    text = _text(tool, {"what": "ref", "name": "g", "scope": TOP_LEVEL_KEY})
    # every module-level `g` (lines 1-2), none beyond
    assert "1:5" in text and "2:1" in text and "2:7" in text
    assert "(3 match(es))" in text

    text = _text(tool, {"what": "ref", "name": "p", "scope": OUTER})
    assert "no ref hit" in text  # p belongs to inner, not outer
    text = _text(tool, {"what": "ref", "name": "p", "scope": INNER})
    assert "(2 match(es))" in text  # decl + use, both inside inner
