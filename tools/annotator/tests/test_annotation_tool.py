"""Tests for the in-process annotation MCP tools (list / add / delete).

The tools own an in-memory AnnotationDocument; the agent never writes a file.
Handlers are driven directly via ``await tool.handler(args)`` (same pattern as
test_locate_tool / test_callgraph_tool).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from annotator.tools.annotation_tool import (
    AnnotationDocument,
    build_annotation_tools,
    make_annotation_server,
)


# --- fixtures -------------------------------------------------------------- #


@pytest.fixture
def doc() -> AnnotationDocument:
    return AnnotationDocument.empty()


@pytest.fixture
def tools(doc: AnnotationDocument) -> dict[str, Any]:
    return {t.name: t for t in build_annotation_tools(Path("a.js"), Path("."), doc)}


async def _call(tool: Any, args: dict[str, Any]) -> dict[str, Any]:
    return await tool.handler(args)


def _run(tool: Any, args: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(_call(tool, args))


def _text(result: dict[str, Any]) -> str:
    return result["content"][0]["text"]


def _ids(text: str) -> list[str]:
    """Extract the leading [id] tokens from a list_annotations text response.

    The body lines are JSON dumps; only the summary header lines start with [.
    """
    import re

    return re.findall(r"^\[([^\]]+)\]", text, flags=re.MULTILINE)


def _range(sl: int, sc: int, el: int, ec: int) -> str:
    """loc_key string (the agent-facing range format)."""
    return f"{sl}:{sc}:{el}:{ec}"


def _add_shape(tools, name="Point", **kwargs):
    return _run(
        tools["add_annotation"],
        {"kind": "static_shape", "shape": name, "annotation": kwargs},
    )


# --- empty document / list baseline --------------------------------------- #


def test_empty_list(doc, tools):
    res = _run(tools["list_annotations"], {})
    assert not res.get("is_error")
    assert "0 annotation(s)" in _text(res)


def test_empty_document_snapshot(doc):
    snap = doc.to_dict()
    assert snap == {
        "static shapes": {},
        "shape guards": [],
        "shape bindings": [],
        "type guards": [],
    }


def test_make_server_returns_sdk_config(doc):
    srv = make_annotation_server(Path("a.js"), Path("."), doc)
    assert srv["type"] == "sdk"
    assert srv["name"] == "annotations"
    assert srv["instance"] is not None


# --- add + list roundtrip -------------------------------------------------- #


def test_add_shape_then_list(doc, tools):
    r = _add_shape(tools, "Point", properties=[{"name": "x", "type": "number"}])
    assert "revision 1" in _text(r)
    r = _run(tools["list_annotations"], {})
    assert "1 annotation(s)" in _text(r)
    assert "[static_shape:Point:1]" in _text(r)


def test_add_guard_requires_existing_shape(tools):
    r = _run(
        tools["add_annotation"],
        {"kind": "shape_guard", "annotation": {"target range": _range(1, 1, 1, 5), "shape": "Ghost"}},
    )
    assert r.get("is_error")
    assert "unknown shape" in _text(r)


def test_add_binding_then_guard_then_type_guard(doc, tools):
    _add_shape(tools, "P", properties=[{"name": "x"}])
    assert not _run(
        tools["add_annotation"],
        {"kind": "shape_binding", "annotation": {"target range": _range(1, 1, 1, 9), "shape": "P"}},
    ).get("is_error")
    assert not _run(
        tools["add_annotation"],
        {"kind": "shape_guard", "annotation": {"target range": _range(2, 1, 2, 9), "shape": "P"}},
    ).get("is_error")
    assert not _run(
        tools["add_annotation"],
        {"kind": "type_guard", "annotation": {"target range": _range(3, 1, 3, 9), "type": "number"}},
    ).get("is_error")
    text = _text(_run(tools["list_annotations"], {}))
    assert "4 annotation(s)" in text


def test_property_order_preserved(doc, tools):
    _add_shape(
        tools,
        "P",
        properties=[
            {"name": "z"},
            {"name": "a"},
            {"name": "m"},
        ],
    )
    snap = doc.to_dict()
    names = [p["name"] for p in snap["static shapes"]["P"]["properties"]]
    assert names == ["z", "a", "m"]  # NOT sorted


# --- validation failures --------------------------------------------------- #


def test_duplicate_shape_rejected(tools):
    _add_shape(tools, "P", properties=[])
    r = _add_shape(tools, "P", properties=[])
    assert r.get("is_error")
    assert "already exists" in _text(r)


def test_duplicate_array_item_rejected(tools):
    _add_shape(tools, "P", properties=[])
    body = {"target range": _range(1, 1, 1, 5), "shape": "P"}
    assert not _run(tools["add_annotation"], {"kind": "shape_binding", "annotation": body}).get("is_error")
    r = _run(tools["add_annotation"], {"kind": "shape_binding", "annotation": body})
    assert r.get("is_error")
    assert "duplicate" in _text(r)


def test_bad_type_rejected(tools):
    r = _run(
        tools["add_annotation"],
        {"kind": "type_guard", "annotation": {"target range": _range(1, 1, 1, 5), "type": "float"}},
    )
    assert r.get("is_error")


def test_closure_requires_target_function(tools):
    r = _add_shape(tools, "P", properties=[{"name": "m", "type": "closure"}])
    assert r.get("is_error")
    assert "target function" in _text(r)


def test_closure_with_target_ok(tools):
    r = _add_shape(
        tools,
        "P",
        properties=[
            {"name": "m", "type": "closure", "target function": _range(3, 1, 3, 10)}
        ],
    )
    assert not r.get("is_error")


def test_closure_cannot_be_in_union(tools):
    r = _run(
        tools["add_annotation"],
        {"kind": "type_guard", "annotation": {"target range": _range(1, 1, 1, 5), "type": ["closure", "number"]}},
    )
    assert r.get("is_error")


def test_range_end_before_start_rejected(tools):
    r = _run(
        tools["add_annotation"],
        {"kind": "type_guard", "annotation": {"target range": _range(2, 5, 2, 1), "type": "number"}},
    )
    assert r.get("is_error")


def test_unknown_field_rejected(tools):
    _add_shape(tools, "P", properties=[])
    r = _run(
        tools["add_annotation"],
        {"kind": "shape_guard", "annotation": {"target range": _range(1, 1, 1, 5), "shape": "P", "bogus": 1}},
    )
    assert r.get("is_error")
    assert "unknown field" in _text(r)


# --- list filtering -------------------------------------------------------- #


def _populate(doc, tools):
    _add_shape(tools, "P", properties=[{"name": "x"}])
    _add_shape(tools, "Q", properties=[{"name": "y"}])
    _run(tools["add_annotation"], {"kind": "shape_binding", "annotation": {"target range": _range(10, 1, 10, 5), "shape": "P"}})
    _run(tools["add_annotation"], {"kind": "shape_guard", "annotation": {"target range": _range(20, 1, 20, 5), "shape": "Q"}})
    _run(tools["add_annotation"], {"kind": "type_guard", "annotation": {"target range": _range(20, 1, 20, 5), "type": "number"}})


def test_list_filter_by_kind(doc, tools):
    _populate(doc, tools)
    text = _text(_run(tools["list_annotations"], {"kinds": ["type_guard"]}))
    assert "1 annotation(s)" in text
    assert "type_guard" in text
    assert "shape_guard" not in text.split("\n")[0]


def test_list_filter_by_shape(doc, tools):
    _populate(doc, tools)
    text = _text(_run(tools["list_annotations"], {"shape": "Q"}))
    # static_shape Q + shape_guard on Q = 2
    assert "2 annotation(s)" in text


def test_list_filter_by_line_range(doc, tools):
    _populate(doc, tools)
    text = _text(_run(tools["list_annotations"], {"from_line": 20, "to_line": 20}))
    # Two items on line 20: the shape_guard and the type_guard. Static shapes
    # have no range and are dropped under a line filter.
    assert "2 annotation(s)" in text


def test_line_range_overlap_boundaries(doc, tools):
    _add_shape(tools, "P", properties=[{"name": "x"}])
    # range on lines 10-12
    _run(tools["add_annotation"], {"kind": "type_guard", "annotation": {"target range": _range(10, 1, 12, 5), "type": "number"}})
    # window [5,10] overlaps (start line 10 <= 10)
    assert "1 annotation(s)" in _text(_run(tools["list_annotations"], {"from_line": 5, "to_line": 10}))
    # window [12,20] overlaps (end line 12 >= 12)
    assert "1 annotation(s)" in _text(_run(tools["list_annotations"], {"from_line": 12, "to_line": 20}))
    # window [13,20] does NOT overlap (range ends on line 12)
    assert "0 annotation(s)" in _text(_run(tools["list_annotations"], {"from_line": 13, "to_line": 20}))


def test_line_range_half_specified_is_error(tools):
    r = _run(tools["list_annotations"], {"from_line": 5})
    assert r.get("is_error")


def test_line_range_inverted_is_error(tools):
    r = _run(tools["list_annotations"], {"from_line": 10, "to_line": 5})
    assert r.get("is_error")


def test_line_filter_drops_static_shapes(doc, tools):
    _add_shape(tools, "P", properties=[{"name": "x"}])
    _run(tools["add_annotation"], {"kind": "type_guard", "annotation": {"target range": _range(5, 1, 5, 9), "type": "number"}})
    text = _text(_run(tools["list_annotations"], {"from_line": 1, "to_line": 100}))
    assert "1 annotation(s)" in text  # shape hidden, only the type guard


# --- delete + revision / stale ids ---------------------------------------- #


def test_delete_by_fresh_id(doc, tools):
    _add_shape(tools, "P", properties=[{"name": "x"}])
    _run(tools["add_annotation"], {"kind": "type_guard", "annotation": {"target range": _range(5, 1, 5, 9), "type": "number"}})
    ids = _ids(_text(_run(tools["list_annotations"], {})))
    type_guard_id = [i for i in ids if i.startswith("type_guard:")][0]
    r = _run(tools["delete_annotation"], {"id": type_guard_id})
    assert not r.get("is_error")
    assert "1 annotation(s)" in _text(_run(tools["list_annotations"], {}))  # only the shape left


def test_delete_stale_id_rejected(doc, tools):
    _add_shape(tools, "P", properties=[{"name": "x"}])
    _run(tools["add_annotation"], {"kind": "type_guard", "annotation": {"target range": _range(5, 1, 5, 9), "type": "number"}})
    ids = _ids(_text(_run(tools["list_annotations"], {})))
    type_guard_id = [i for i in ids if i.startswith("type_guard:")][0]
    # mutate the doc (add another), bumping the revision
    _run(tools["add_annotation"], {"kind": "type_guard", "annotation": {"target range": _range(6, 1, 6, 9), "type": "string"}})
    r = _run(tools["delete_annotation"], {"id": type_guard_id})
    assert r.get("is_error")
    assert "stale" in _text(r)


def test_delete_referenced_shape_rejected(doc, tools):
    _add_shape(tools, "P", properties=[{"name": "x"}])
    _run(tools["add_annotation"], {"kind": "shape_binding", "annotation": {"target range": _range(1, 1, 1, 5), "shape": "P"}})
    ids = _ids(_text(_run(tools["list_annotations"], {})))
    shape_id = [i for i in ids if i.startswith("static_shape:")][0]
    r = _run(tools["delete_annotation"], {"id": shape_id})
    assert r.get("is_error")
    assert "referenced" in _text(r)


def test_delete_shape_after_references_gone(doc, tools):
    _add_shape(tools, "P", properties=[{"name": "x"}])
    _run(tools["add_annotation"], {"kind": "shape_binding", "annotation": {"target range": _range(1, 1, 1, 5), "shape": "P"}})
    # delete the binding first
    ids = _ids(_text(_run(tools["list_annotations"], {})))
    bind_id = [i for i in ids if i.startswith("shape_binding:")][0]
    _run(tools["delete_annotation"], {"id": bind_id})
    # now the shape is deletable
    ids = _ids(_text(_run(tools["list_annotations"], {})))
    shape_id = [i for i in ids if i.startswith("static_shape:")][0]
    r = _run(tools["delete_annotation"], {"id": shape_id})
    assert not r.get("is_error")
    assert doc.to_dict()["static shapes"] == {}


def test_delete_preserves_array_order(doc, tools):
    _add_shape(tools, "P", properties=[{"name": "x"}])
    for line in (10, 20, 30):
        _run(tools["add_annotation"], {"kind": "type_guard", "annotation": {"target range": _range(line, 1, line, 5), "type": "number"}})
    # delete the middle one
    ids = _ids(_text(_run(tools["list_annotations"], {})))
    middle = [i for i in ids if i.startswith("type_guard:1:")][0]
    _run(tools["delete_annotation"], {"id": middle})
    remaining_lines = [
        g["target range"]["start"]["line"]
        for g in doc.to_dict()["type guards"]
    ]
    assert remaining_lines == [10, 30]


def test_delete_malformed_id_rejected(tools):
    r = _run(tools["delete_annotation"], {"id": "garbage"})
    assert r.get("is_error")
