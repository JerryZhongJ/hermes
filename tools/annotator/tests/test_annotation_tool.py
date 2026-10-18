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

from annotator.annotation_drafts import add_unique_draft
from annotator.tools.annotation_tool import (
    AnnotationDocument,
    build_annotation_tools,
    make_annotation_server,
    parse_range_key,
)


# --- fixtures -------------------------------------------------------------- #


@pytest.fixture
def doc() -> AnnotationDocument:
    return AnnotationDocument.empty()


@pytest.fixture
def tools(doc: AnnotationDocument, tmp_path: Path) -> dict[str, Any]:
    # A real 100-line source: scope resolution reads it for loc_keys/windows.
    (tmp_path / "a.js").write_text("var a;\n" * 100, encoding="utf-8")
    return {t.name: t for t in build_annotation_tools(tmp_path / "a.js", tmp_path, [add_unique_draft(doc)])}


async def _call(tool: Any, args: dict[str, Any]) -> dict[str, Any]:
    return await tool.handler(args)


def _run(tool: Any, args: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(_call(tool, args))


def _text(result: dict[str, Any]) -> str:
    return result["content"][0]["text"]


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
    srv = make_annotation_server(Path("a.js"), Path("."), [add_unique_draft(doc)])
    assert srv["type"] == "sdk"
    assert srv["name"] == "annotations"
    assert srv["instance"] is not None


# --- add + list roundtrip -------------------------------------------------- #


def test_add_shape_then_list(doc, tools):
    r = _add_shape(tools, "Point", properties=[{"name": "x", "type": "number"}])
    assert not r.get("is_error")
    r = _run(tools["list_annotations"], {})
    assert "1 annotation(s)" in _text(r)
    assert "[static_shape] shape='Point'" in _text(r)


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


def test_shape_bindings_require_unique_target(tools):
    _add_shape(tools, "P", properties=[])
    _add_shape(tools, "Q", properties=[])
    target = _range(1, 1, 1, 5)
    assert not _run(
        tools["add_annotation"],
        {"kind": "shape_binding", "annotation": {"target range": target, "shape": "P"}},
    ).get("is_error")
    r = _run(
        tools["add_annotation"],
        {"kind": "shape_binding", "annotation": {"target range": target, "shape": "Q"}},
    )
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


def test_closure_type_guard_requires_and_roundtrips_target_function(doc, tools):
    body = {
        "target range": _range(1, 1, 1, 3),
        "type": "closure",
        "target function": _range(3, 1, 3, 10),
    }
    assert not _run(
        tools["add_annotation"], {"kind": "type_guard", "annotation": body}
    ).get("is_error")
    assert doc.to_dict()["type guards"][0]["target function"] == {
        "start": {"line": 3, "column": 1},
        "end": {"line": 3, "column": 10},
    }
    assert '"target function": "3:1:3:10"' in _text(
        _run(tools["list_annotations"], {"kinds": ["type_guard"]})
    )


def test_closure_type_guard_without_target_rejected(tools):
    r = _run(
        tools["add_annotation"],
        {
            "kind": "type_guard",
            "annotation": {
                "target range": _range(1, 1, 1, 3),
                "type": "closure",
            },
        },
    )
    assert r.get("is_error")
    assert "requires 'target function'" in _text(r)


def test_non_closure_type_guard_rejects_target_function(tools):
    r = _run(
        tools["add_annotation"],
        {
            "kind": "type_guard",
            "annotation": {
                "target range": _range(1, 1, 1, 3),
                "type": "number",
                "target function": _range(3, 1, 3, 10),
            },
        },
    )
    assert r.get("is_error")
    assert "only valid for type 'closure'" in _text(r)


def test_type_guards_require_unique_target_range(tools):
    target = _range(1, 1, 1, 3)
    assert not _run(
        tools["add_annotation"],
        {
            "kind": "type_guard",
            "annotation": {"target range": target, "type": "number"},
        },
    ).get("is_error")
    r = _run(
        tools["add_annotation"],
        {
            "kind": "type_guard",
            "annotation": {"target range": target, "type": "string"},
        },
    )
    assert r.get("is_error")
    assert "target range already has a guard" in _text(r)


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


def test_dict_range_rejected_at_interface(tools):
    """Ranges are range_key strings only — a dict body/field is an error."""
    _add_shape(tools, "P", properties=[])
    dict_range = {"start": {"line": 1, "column": 1}, "end": {"line": 1, "column": 5}}
    r = _run(
        tools["add_annotation"],
        {"kind": "shape_binding", "annotation": {"target range": dict_range, "shape": "P"}},
    )
    assert r.get("is_error")
    assert "range_key" in _text(r)
    # closure target function inside a shape property — same rule
    r = _add_shape(
        tools,
        "Proto",
        properties=[{"name": "m", "type": "closure", "target function": dict_range}],
    )
    assert r.get("is_error")
    assert "range_key" in _text(r)


def test_unknown_field_rejected(tools):
    _add_shape(tools, "P", properties=[])
    r = _run(
        tools["add_annotation"],
        {"kind": "shape_guard", "annotation": {"target range": _range(1, 1, 1, 5), "shape": "P", "bogus": 1}},
    )
    assert r.get("is_error")
    assert "unknown field" in _text(r)


def test_legacy_after_fields_rejected(tools):
    _add_shape(tools, "P", properties=[])
    for kind, field in (
        ("shape_guard", "guard after"),
        ("shape_binding", "bind after"),
    ):
        r = _run(
            tools["add_annotation"],
            {
                "kind": kind,
                "annotation": {
                    "target range": _range(1, 1, 1, 5),
                    "shape": "P",
                    field: _range(1, 5, 1, 9),
                },
            },
        )
        assert r.get("is_error")
        assert "unknown field" in _text(r)


def test_load_from_dict_rejects_legacy_after_atomically(doc, tools):
    _add_shape(tools, "Existing", properties=[])
    before = doc.to_dict()
    legacy = {
        "static shapes": {"P": {"properties": []}},
        "shape guards": [],
        "shape bindings": [
            {
                "target range": {
                    "start": {"line": 1, "column": 1},
                    "end": {"line": 1, "column": 5},
                },
                "shape": "P",
                "bind after": {
                    "start": {"line": 1, "column": 5},
                    "end": {"line": 1, "column": 9},
                },
            }
        ],
        "type guards": [],
    }

    with pytest.raises(ValueError, match="unknown field"):
        doc.load_from_dict(legacy)

    assert doc.to_dict() == before


def test_load_from_dict_validates_and_roundtrips_ordinary_shapes(doc):
    document = {
        "static shapes": {
            "Proto": {"properties": [{"name": "m"}]},
            "P": {"properties": [{"name": "x", "type": ["number", "string"]}]},
        },
        "shape guards": [
            {
                "target range": {
                    "start": {"line": 2, "column": 1},
                    "end": {"line": 2, "column": 2},
                },
                "shape": "P",
                "prototype shape": "Proto",
            }
        ],
        "shape bindings": [
            {
                "target range": {
                    "start": {"line": 1, "column": 1},
                    "end": {"line": 1, "column": 2},
                },
                "shape": "P",
            }
        ],
        "type guards": [],
    }

    doc.load_from_dict(document)

    assert doc.to_dict() == document
    assert "after" not in doc.to_json()

    document["shape bindings"][0]["target range"]["start"]["line"] = 99
    snapshot = doc.to_dict()
    snapshot["shape guards"][0]["target range"]["start"]["line"] = 88
    snapshot["static shapes"]["P"]["properties"][0]["type"].append("boolean")

    persisted = doc.to_dict()
    assert persisted["shape bindings"][0]["target range"]["start"]["line"] == 1
    assert persisted["shape guards"][0]["target range"]["start"]["line"] == 2
    assert persisted["static shapes"]["P"]["properties"][0]["type"] == [
        "number",
        "string",
    ]


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
    text = _text(_run(tools["list_annotations"], {"scope": "20-20"}))
    # Two items on line 20: the shape_guard and the type_guard. Static shapes
    # have no range and are dropped under a line filter.
    assert "2 annotation(s)" in text


def test_line_range_overlap_boundaries(doc, tools):
    _add_shape(tools, "P", properties=[{"name": "x"}])
    # range on lines 10-12
    _run(tools["add_annotation"], {"kind": "type_guard", "annotation": {"target range": _range(10, 1, 12, 5), "type": "number"}})
    # window [5,10] overlaps (start line 10 <= 10)
    assert "1 annotation(s)" in _text(_run(tools["list_annotations"], {"scope": "5-10"}))
    # window [12,20] overlaps (end line 12 >= 12)
    assert "1 annotation(s)" in _text(_run(tools["list_annotations"], {"scope": "12-20"}))
    # window [13,20] does NOT overlap (range ends on line 12)
    assert "0 annotation(s)" in _text(_run(tools["list_annotations"], {"scope": "13-20"}))


def test_scope_unknown_loc_key_is_error(tools):
    r = _run(tools["list_annotations"], {"scope": "999:1:999:9"})
    assert r.get("is_error")


def test_scope_inverted_range_is_error(tools):
    r = _run(tools["list_annotations"], {"scope": "10-5"})
    assert r.get("is_error")


def test_line_filter_drops_static_shapes(doc, tools):
    _add_shape(tools, "P", properties=[{"name": "x"}])
    _run(tools["add_annotation"], {"kind": "type_guard", "annotation": {"target range": _range(5, 1, 5, 9), "type": "number"}})
    text = _text(_run(tools["list_annotations"], {"scope": "1-100"}))
    assert "1 annotation(s)" in text  # shape hidden, only the type guard


# --- delete (content-addressed) -------------------------------------------- #


def _delete(tools, kind, **extra):
    return _run(tools["delete_annotation"], {"kind": kind, **extra})


def test_delete_by_target_range(doc, tools):
    _add_shape(tools, "P", properties=[{"name": "x"}])
    _run(tools["add_annotation"], {"kind": "type_guard", "annotation": {"target range": _range(5, 1, 5, 9), "type": "number"}})
    r = _delete(tools, "type_guard", target_range=_range(5, 1, 5, 9))
    assert not r.get("is_error")
    # The removed payload renders ranges as range_key strings, not dicts.
    assert r["content"][0]["removed"] == {
        "type guards": {"target range": "5:1:5:9", "type": "number"}
    }
    assert "1 annotation(s)" in _text(_run(tools["list_annotations"], {}))  # only the shape left


def test_delete_address_survives_unrelated_mutation(doc, tools):
    """Two deletes in the same round never invalidate each other."""
    _run(tools["add_annotation"], {"kind": "type_guard", "annotation": {"target range": _range(5, 1, 5, 9), "type": "number"}})
    _run(tools["add_annotation"], {"kind": "type_guard", "annotation": {"target range": _range(6, 1, 6, 9), "type": "string"}})
    r1 = _delete(tools, "type_guard", target_range=_range(5, 1, 5, 9))
    r2 = _delete(tools, "type_guard", target_range=_range(6, 1, 6, 9))
    assert not r1.get("is_error")
    assert not r2.get("is_error")
    assert "0 annotation(s)" in _text(_run(tools["list_annotations"], {}))


def test_delete_missing_range_reports_clearly(tools):
    r = _delete(tools, "type_guard", target_range=_range(5, 1, 5, 9))
    assert r.get("is_error")
    assert "no type_guard with target range" in _text(r)


def test_delete_shape_and_guard_same_range_distinguished_by_kind(doc, tools):
    _add_shape(tools, "P", properties=[{"name": "x"}])
    rng = _range(2, 1, 2, 5)
    _run(tools["add_annotation"], {"kind": "shape_guard", "annotation": {"target range": rng, "shape": "P"}})
    _run(tools["add_annotation"], {"kind": "type_guard", "annotation": {"target range": rng, "type": "number"}})
    assert not _delete(tools, "shape_guard", target_range=rng).get("is_error")
    assert len(doc.to_dict()["type guards"]) == 1  # the type guard survived


def test_delete_same_kind_same_range_two_shapes_ambiguous_then_disambiguated(doc, tools):
    _add_shape(tools, "P", properties=[])
    _add_shape(tools, "Q", properties=[])
    rng = _range(2, 1, 2, 5)
    doc.add_array_item("shape_guard", {"target range": parse_range_key(rng), "shape": "P"})
    doc.add_array_item("shape_guard", {"target range": parse_range_key(rng), "shape": "Q"})
    r = _delete(tools, "shape_guard", target_range=rng)
    assert r.get("is_error")
    assert "ambiguous" in _text(r)
    r = _delete(tools, "shape_guard", target_range=rng, shape="Q")
    assert not r.get("is_error")
    assert [g["shape"] for g in doc.to_dict()["shape guards"]] == ["P"]


def test_delete_referenced_shape_rejected(doc, tools):
    _add_shape(tools, "P", properties=[{"name": "x"}])
    _run(tools["add_annotation"], {"kind": "shape_binding", "annotation": {"target range": _range(1, 1, 1, 5), "shape": "P"}})
    r = _delete(tools, "static_shape", shape="P")
    assert r.get("is_error")
    assert "referenced" in _text(r)


def test_delete_shape_after_references_gone(doc, tools):
    _add_shape(tools, "P", properties=[{"name": "x"}])
    _run(tools["add_annotation"], {"kind": "shape_binding", "annotation": {"target range": _range(1, 1, 1, 5), "shape": "P"}})
    # delete the binding first
    assert not _delete(tools, "shape_binding", target_range=_range(1, 1, 1, 5)).get("is_error")
    # now the shape is deletable
    r = _delete(tools, "static_shape", shape="P")
    assert not r.get("is_error")
    assert doc.to_dict()["static shapes"] == {}


def _batch_tools(tmp_path, text):
    source = tmp_path / "input.js"
    source.write_text(text, encoding="utf-8")
    document = AnnotationDocument.empty()
    tools = {
        t.name: t for t in build_annotation_tools(source, tmp_path, [add_unique_draft(document)])
    }
    return tools, document


def test_batch_add_guards_structural_match_and_line_scope(tmp_path):
    tools, document = _batch_tools(
        tmp_path,
        "function f(obj) {\n"
        "  obj.x; obj . x; obj.x.y;\n"
        "  // obj.x\n"
        "  'obj.x';\n"
        "  obj.x;\n"
        "}\n"
        "function g(obj) { obj.x; }\n",
    )
    _add_shape(tools, "P", properties=[])

    result = _run(
        tools["batch_add_guards"],
        {"scope": "1-2", "expression": "obj . x", "shape": "P"},
    )

    assert not result.get("is_error")
    assert "matched 3 (declarations 0, uses 3); added 3 shape_guard(s)" in _text(result)
    guards = document.to_dict()["shape guards"]
    assert [g["target range"] for g in guards] == [
        {
            "start": {"line": 2, "column": 3},
            "end": {"line": 2, "column": 8},
        },
        {
            "start": {"line": 2, "column": 10},
            "end": {"line": 2, "column": 17},
        },
        {
            "start": {"line": 2, "column": 19},
            "end": {"line": 2, "column": 24},
        },
    ]


def test_batch_add_guards_whole_function_is_idempotent(tmp_path):
    tools, document = _batch_tools(tmp_path, "function f(obj) { obj.x; obj.x; }\n")
    _add_shape(tools, "P", properties=[])
    args = {"scope": "1:1", "expression": "obj.x", "shape": "P"}

    first = _run(tools["batch_add_guards"], args)
    second = _run(tools["batch_add_guards"], args)

    assert not first.get("is_error")
    assert "added 2" in _text(first)
    assert "added 0" in _text(second)
    assert "skipped 2" in _text(second)
    assert len(document.to_dict()["shape guards"]) == 2


def test_batch_add_guards_identifier_and_unicode_columns(tmp_path):
    tools, document = _batch_tools(
        tmp_path, "function f(obj) { const \u540d = obj; return \u540d; }\n"
    )
    _add_shape(tools, "P", properties=[])

    result = _run(
        tools["batch_add_guards"],
        {"scope": "file", "expression": "\u540d", "shape": "P"},
    )

    assert not result.get("is_error")
    guards = document.to_dict()["shape guards"]
    assert [g["target range"] for g in guards] == [
        {
            "start": {"line": 1, "column": 25},
            "end": {"line": 1, "column": 26},
        },
        {
            "start": {"line": 1, "column": 41},
            "end": {"line": 1, "column": 42},
        },
    ]


def test_batch_add_guards_scope_excludes_nested_functions(tmp_path):
    """Ownership scope: the outer loc_key covers its DIRECT statements only
    — the nested function's match belongs to inner's own scope, never the
    enclosing one (the unified scope contract)."""
    tools, document = _batch_tools(
        tmp_path,
        "function outer(obj) {\n"
        "  obj.x;\n"
        "  function inner() { obj.x; }\n"
        "}\n",
    )
    _add_shape(tools, "P", properties=[])

    result = _run(
        tools["batch_add_guards"],
        {"scope": "1:1", "expression": "obj.x", "shape": "P"},
    )
    assert not result.get("is_error")
    assert "matched 1" in _text(result)
    guards = document.to_dict()["shape guards"]
    assert [g["target range"]["start"]["line"] for g in guards] == [2]

    # the nested function's own loc_key still matches its site
    nested = _run(
        tools["batch_add_guards"],
        {"scope": "3:3", "expression": "obj.x", "shape": "P"},
    )
    assert not nested.get("is_error")
    assert "matched 1" in _text(nested)
    assert [g["target range"]["start"]["line"] for g in document.to_dict()["shape guards"]] == [2, 3]


def test_batch_add_guards_generator_expression(tmp_path):
    tools, document = _batch_tools(
        tmp_path, "const f = function* (obj) { obj.x; obj.x; };\n"
    )
    from annotator.tools.functions import extract_functions

    [function] = extract_functions((tmp_path / "input.js").read_bytes())
    _add_shape(tools, "P", properties=[])

    result = _run(
        tools["batch_add_guards"],
        {"scope": function["loc_key"], "expression": "obj.x", "shape": "P"},
    )

    assert not result.get("is_error")
    assert "matched 2" in _text(result)


def test_batch_add_guards_errors_are_atomic(tmp_path):
    tools, document = _batch_tools(tmp_path, "function f(obj) { obj.x; }\n")
    _add_shape(tools, "P", properties=[])
    before = document.to_dict()

    for patch, message in (
        ({"shape": "Missing"}, "unknown shape"),
        ({"expression": "obj.x; obj.y"}, "one valid JavaScript expression"),
        ({"scope": "9-9"}, "invalid"),
        ({"scope": "9:1"}, "scope must be one of"),
    ):
        args = {"scope": "1:1", "expression": "obj.x", "shape": "P", **patch}
        result = _run(tools["batch_add_guards"], args)
        assert result.get("is_error"), patch
        assert message in _text(result), patch
        assert document.to_dict() == before


def test_batch_add_guards_shape_and_type_are_exclusive(tmp_path):
    tools, document = _batch_tools(tmp_path, "function f(obj) { obj.x; }\n")
    _add_shape(tools, "P", properties=[])
    before = document.to_dict()

    neither = _run(tools["batch_add_guards"], {"scope": "file", "expression": "obj.x"})
    assert neither.get("is_error")
    assert "exactly one of 'shape' or 'type'" in _text(neither)

    both = _run(
        tools["batch_add_guards"],
        {"scope": "file", "expression": "obj.x", "shape": "P", "type": "number"},
    )
    assert both.get("is_error")
    assert "mutually exclusive" in _text(both)
    assert document.to_dict() == before


def test_batch_add_guards_type_guard_counts_declarations_and_uses(tmp_path):
    tools, document = _batch_tools(
        tmp_path,
        "function f(n) {\n"
        "  return n + 1;\n"
        "}\n"
        "function g(n) { return n; }\n",
    )

    result = _run(
        tools["batch_add_guards"],
        {"scope": "1-3", "expression": "n", "type": "number"},
    )

    assert not result.get("is_error")
    # line 1 declaration (formal parameter) + line 2 use
    assert "matched 2 (declarations 1, uses 1); added 2 type_guard(s)" in _text(result)
    guards = document.to_dict()["type guards"]
    assert [g["type"] for g in guards] == ["number", "number"]
    assert [g["target range"] for g in guards] == [
        {"start": {"line": 1, "column": 12}, "end": {"line": 1, "column": 13}},
        {"start": {"line": 2, "column": 10}, "end": {"line": 2, "column": 11}},
    ]
    assert result["content"][0]["ranges"] == ["1:12:1:13", "2:10:2:11"]


def test_batch_add_guards_closure_type_requires_target_function(tmp_path):
    tools, document = _batch_tools(tmp_path, "function f(cb) { cb(); }\n")

    missing = _run(
        tools["batch_add_guards"],
        {"scope": "file", "expression": "cb", "type": "closure"},
    )
    assert missing.get("is_error")
    assert "requires 'target function'" in _text(missing)
    assert document.to_dict()["type guards"] == []

    result = _run(
        tools["batch_add_guards"],
        {
            "scope": "file",
            "expression": "cb",
            "type": "closure",
            "target_function": "5:1:5:20",
        },
    )
    assert not result.get("is_error")
    # two matches (parameter declaration + call use), each a closure guard
    guards = document.to_dict()["type guards"]
    assert len(guards) == 2
    assert all(g["type"] == "closure" for g in guards)
    assert all(
        g["target function"]
        == {
            "start": {"line": 5, "column": 1},
            "end": {"line": 5, "column": 20},
        }
        for g in guards
    )


def test_batch_add_guards_type_union_and_bad_type_rejected(tmp_path):
    tools, document = _batch_tools(tmp_path, "function f(n) { return n; }\n")

    union = _run(
        tools["batch_add_guards"],
        {"scope": "file", "expression": "n", "type": ["number", "string"]},
    )
    assert not union.get("is_error")
    guards = document.to_dict()["type guards"]
    assert len(guards) == 2
    assert all(g["type"] == ["number", "string"] for g in guards)

    bad = _run(
        tools["batch_add_guards"],
        {"scope": "file", "expression": "n", "type": "float"},
    )
    assert bad.get("is_error")
    assert "is not one of" in _text(bad)


def test_batch_add_guards_keeps_schema_and_prototype(tmp_path):
    tools, document = _batch_tools(tmp_path, "function f(obj) { obj.x; }\n")
    _add_shape(tools, "P", properties=[])
    _add_shape(tools, "Proto", properties=[])

    result = _run(
        tools["batch_add_guards"],
        {
            "scope": "1:1",
            "expression": "obj.x",
            "shape": "P",
            "prototype_shape": "Proto",
        },
    )

    assert not result.get("is_error")
    snapshot = document.to_dict()
    assert set(snapshot) == {
        "static shapes",
        "shape guards",
        "shape bindings",
        "type guards",
    }
    assert snapshot["shape guards"] == [
        {
            "target range": {
                "start": {"line": 1, "column": 19},
                "end": {"line": 1, "column": 24},
            },
            "shape": "P",
            "prototype shape": "Proto",
        }
    ]




def test_delete_preserves_array_order(doc, tools):
    _add_shape(tools, "P", properties=[{"name": "x"}])
    for line in (10, 20, 30):
        _run(tools["add_annotation"], {"kind": "type_guard", "annotation": {"target range": _range(line, 1, line, 5), "type": "number"}})
    # delete the middle one
    assert not _delete(tools, "type_guard", target_range=_range(20, 1, 20, 5)).get("is_error")
    remaining_lines = [
        g["target range"]["start"]["line"]
        for g in doc.to_dict()["type guards"]
    ]
    assert remaining_lines == [10, 30]


def test_delete_bad_target_range_rejected(tools):
    r = _delete(tools, "type_guard", target_range="1:1:1:1")
    assert r.get("is_error")
    r = _delete(tools, "type_guard")  # missing target_range
    assert r.get("is_error")


# --- update_annotation ---------------------------------------------------- #


def _add_type_guard(tools, line, typ="number"):
    _run(
        tools["add_annotation"],
        {
            "kind": "type_guard",
            "annotation": {"target range": _range(line, 1, line, 9), "type": typ},
        },
    )


def test_update_changes_field_in_place(doc, tools):
    _add_type_guard(tools, 5)
    r = _run(
        tools["update_annotation"],
        {"kind": "type_guard", "target_range": _range(5, 1, 5, 9), "patch": {"type": "string"}},
    )
    assert not r.get("is_error")
    [guard] = doc.to_dict()["type guards"]
    assert guard["type"] == "string"
    assert guard["target range"]["start"]["line"] == 5  # unchanged field preserved


def test_update_rejects_legacy_after_without_mutating(doc, tools):
    _add_shape(tools, "P", properties=[])
    for kind, field in (
        ("shape_guard", "guard after"),
        ("shape_binding", "bind after"),
    ):
        added = _run(
            tools["add_annotation"],
            {
                "kind": kind,
                "annotation": {
                    "target range": _range(1, 1, 1, 5),
                    "shape": "P",
                },
            },
        )
        assert not added.get("is_error")
        before = doc.to_dict()

        result = _run(
            tools["update_annotation"],
            {"kind": kind, "target_range": _range(1, 1, 1, 5), "patch": {field: _range(1, 5, 1, 9)}},
        )

        assert result.get("is_error")
        assert "unknown field" in _text(result)
        assert doc.to_dict() == before


def test_update_address_survives_unrelated_mutation(doc, tools):
    """An address computed before an unrelated add still updates the right item."""
    _add_type_guard(tools, 5)
    _add_type_guard(tools, 6)
    r = _run(
        tools["update_annotation"],
        {"kind": "type_guard", "target_range": _range(5, 1, 5, 9), "patch": {"type": "string"}},
    )
    assert not r.get("is_error")
    guards = {g["target range"]["start"]["line"]: g["type"] for g in doc.to_dict()["type guards"]}
    assert guards == {5: "string", 6: "number"}


def test_update_rejects_duplicate(tools):
    _add_shape(tools, "P", properties=[{"name": "x"}])
    _run(tools["add_annotation"], {"kind": "type_guard", "annotation": {"target range": _range(5, 1, 5, 9), "type": "number"}})
    _run(tools["add_annotation"], {"kind": "type_guard", "annotation": {"target range": _range(6, 1, 6, 9), "type": "string"}})
    # patch the second to collide with the first's canonical key
    r = _run(
        tools["update_annotation"],
        {"kind": "type_guard", "target_range": _range(6, 1, 6, 9), "patch": {"target range": _range(5, 1, 5, 9), "type": "number"}},
    )
    assert r.get("is_error")
    assert "already has a guard" in _text(r)


def test_update_missing_target_reports_clearly(tools):
    r = _run(
        tools["update_annotation"],
        {"kind": "type_guard", "target_range": _range(5, 1, 5, 9), "patch": {"type": "string"}},
    )
    assert r.get("is_error")
    assert "no type_guard with target range" in _text(r)


def test_update_shape_property_target_function(doc, tools):
    tf = _range(3, 10, 3, 30)
    _add_shape(tools, "Proto", properties=[{"name": "m", "type": "closure", "target function": tf}])
    fixed = _range(3, 25, 3, 66)
    r = _run(
        tools["update_annotation"],
        {"kind": "static_shape", "shape": "Proto", "patch": {"property": {"name": "m", "target function": fixed}}},
    )
    assert not r.get("is_error")
    [shape] = doc.to_dict()["static shapes"]["Proto"]["properties"]
    assert shape["target function"] == {
        "start": {"line": 3, "column": 25},
        "end": {"line": 3, "column": 66},
    }


def test_update_shape_unknown_property_rejected(tools):
    _add_shape(tools, "Proto", properties=[{"name": "m", "type": "number"}])
    r = _run(
        tools["update_annotation"],
        {"kind": "static_shape", "shape": "Proto", "patch": {"property": {"name": "nope", "type": "number"}}},
    )
    assert r.get("is_error")
    assert "no property" in _text(r)


# --- copy_annotations (cross-draft merge with explicit compatibility) ------ #

from annotator.annotation_drafts import drafts  # noqa: E402
from annotator.tools.checklist_tool import reasons  # noqa: E402


def _two_draft_tools(tmp_path: Path):
    """Build tools over a named dest draft plus a second source draft."""
    (tmp_path / "a.js").write_text("var a;\n" * 100, encoding="utf-8")
    dest = add_unique_draft()
    src = add_unique_draft()
    # Both drafts are in the tool's allowed names (the coordinator pattern:
    # open access is names=None; a single-draft agent must NOT copy from
    # drafts it cannot see).
    tools = {t.name: t for t in build_annotation_tools(tmp_path / "a.js", tmp_path, [dest, src], dest)}
    return tools, drafts().get(dest), drafts().get(src), dest, src


def _copy(tools, source, **extra):
    return _run(tools["copy_annotations"], {"source": source, **extra})


def _copy_payload(tools, source, **extra):
    import json as _json

    text = _text(_copy(tools, source, **extra))
    # Strip a possible fold headline — the JSON report starts at the first '{'.
    return _json.loads(text[text.index("{"):])


def test_copy_folds_identical_shapes_across_names(tmp_path):
    tools, dest, src, dest_name, src_name = _two_draft_tools(tmp_path)
    dest.add_shape("Point", {"properties": [{"name": "x", "type": "number"}]})
    src.add_shape("P2", {"properties": [{"name": "x", "type": "number"}]})
    src.add_array_item(
        "shape_binding",
        {"target range": {"start": {"line": 2, "column": 1}, "end": {"line": 2, "column": 9}}, "shape": "P2"},
    )
    raw = _text(_copy(tools, src_name))
    # The fold is NOT silent: a headline names it before the JSON report.
    assert raw.startswith("Folded 1 same-structure shape(s)")
    assert "P2 -> Point" in raw
    assert "DIFFERENT objects" in raw
    payload = _copy_payload(tools, src_name)
    # Same structure under a different name maps to dest's name...
    assert payload["shapes_mapped"] == [{"from": "P2", "to": "Point"}]
    # ...and the copied binding's reference was rewritten to Point.
    [binding] = dest.shape_bindings
    assert binding["shape"] == "Point"
    assert set(dest.static_shapes) == {"Point"}


def test_copy_same_name_different_structure_is_a_conflict(tmp_path):
    tools, dest, src, dest_name, src_name = _two_draft_tools(tmp_path)
    dest.add_shape("Point", {"properties": [{"name": "x", "type": "number"}]})
    dest.add_array_item(
        "shape_binding",
        {"target range": {"start": {"line": 5, "column": 1}, "end": {"line": 5, "column": 9}}, "shape": "Point"},
    )
    src.add_shape("Point", {"properties": [{"name": "x", "type": "string"}]})
    src.add_array_item(
        "shape_guard",
        {"target range": {"start": {"line": 3, "column": 1}, "end": {"line": 3, "column": 5}}, "shape": "Point"},
    )
    r = _copy(tools, src_name)
    assert r.get("is_error")
    text = _text(r)
    # Actionable: the shape name, both property sets, both reference counts,
    # and the arbitration hint (rename_shape or delete one side).
    assert "shape name conflict on 'Point'" in text
    assert "'x'" in text
    assert "dest guards/bindings referencing it: 1, source: 1" in text
    assert "rename_shape" in text
    # All-or-nothing: dest completely untouched.
    assert set(dest.static_shapes) == {"Point"}
    assert not dest.shape_guards


def test_copy_succeeds_after_rename_shape_resolves_name_conflict(tmp_path):
    tools, dest, src, dest_name, src_name = _two_draft_tools(tmp_path)
    dest.add_shape("Point", {"properties": [{"name": "x", "type": "number"}]})
    src.add_shape("Point", {"properties": [{"name": "x", "type": "string"}]})
    src.add_array_item(
        "shape_guard",
        {"target range": {"start": {"line": 3, "column": 1}, "end": {"line": 3, "column": 5}}, "shape": "Point"},
    )
    assert _copy(tools, src_name).get("is_error")
    # Rename the SOURCE side out of the way, then the same copy succeeds
    # with the guard following the new name.
    r = _run(tools["rename_shape"], {"shape": "Point", "new_name": "PointStr", "draft": src_name})
    assert not r.get("is_error")
    payload = _copy_payload(tools, src_name)
    assert payload["counts"] == {"bindings": 0, "guards": 1, "type_guards": 0}
    [guard] = dest.shape_guards
    assert guard["shape"] == "PointStr"
    assert set(dest.static_shapes) == {"Point", "PointStr"}


def test_copy_conflict_is_all_or_nothing(tmp_path):
    tools, dest, src, dest_name, src_name = _two_draft_tools(tmp_path)
    rng = {"start": {"line": 2, "column": 1}, "end": {"line": 2, "column": 9}}
    far = {"start": {"line": 8, "column": 1}, "end": {"line": 8, "column": 9}}
    dest.add_shape("A", {"properties": [{"name": "x", "type": "number"}]})
    dest.add_array_item("shape_guard", {"target range": rng, "shape": "A"})
    # Source has one clean new binding (far range) AND one conflicting guard
    # (same range, different shape) -> the WHOLE copy fails, nothing applies.
    src.add_shape("A2", {"properties": [{"name": "x", "type": "number"}]})
    src.add_shape("B", {"properties": [{"name": "x", "type": "string"}]})
    src.add_array_item("shape_binding", {"target range": far, "shape": "A2"})
    src.add_array_item("shape_guard", {"target range": rng, "shape": "B"})
    r = _copy(tools, src_name)
    assert r.get("is_error")
    assert "conflict" in _text(r)
    # dest completely untouched: no new shape, no new binding.
    assert set(dest.static_shapes) == {"A"}
    assert not dest.shape_bindings
    # After removing the conflicting item from the source, the same copy
    # succeeds and carries the clean binding plus its shape dependency.
    src.shape_guards.clear()
    payload = _copy_payload(tools, src_name)
    assert payload["counts"] == {"bindings": 1, "guards": 0, "type_guards": 0}
    assert [b["shape"] for b in dest.shape_bindings] == ["A"]  # folded A2 -> A


def test_copy_scope_window_selects_and_pulls_shape_deps(tmp_path):
    tools, dest, src, dest_name, src_name = _two_draft_tools(tmp_path)
    rng_in = {"start": {"line": 12, "column": 1}, "end": {"line": 12, "column": 9}}
    rng_out = {"start": {"line": 2, "column": 1}, "end": {"line": 2, "column": 9}}
    src.add_shape("In", {"properties": [{"name": "v", "type": "number"}]})
    src.add_shape("Unref", {"properties": [{"name": "u", "type": "string"}]})
    src.add_array_item("shape_guard", {"target range": rng_in, "shape": "In"})
    src.add_array_item("shape_guard", {"target range": rng_out, "shape": "In"})
    payload = _copy_payload(tools, src_name, scope="10-20")
    # Only the in-window guard copied; Unref (unreferenced) NOT pulled in.
    assert payload["counts"] == {"bindings": 0, "guards": 1, "type_guards": 0}
    assert len(dest.shape_guards) == 1
    assert set(dest.static_shapes) == {"In"}
    # A second copy with the full-file scope brings the other guard too.
    _copy(tools, src_name)
    assert len(dest.shape_guards) == 2


def test_copy_does_not_touch_reasons(tmp_path):
    """copy_annotations is annotations-only: the reason store stays put."""
    tools, dest, src, dest_name, src_name = _two_draft_tools(tmp_path)
    rng = {"start": {"line": 2, "column": 1}, "end": {"line": 2, "column": 9}}
    dest.add_shape("A", {"properties": [{"name": "x", "type": "number"}]})
    src.add_shape("A2", {"properties": [{"name": "x", "type": "number"}]})
    src.add_array_item("shape_binding", {"target range": rng, "shape": "A2"})
    reasons().set(src_name, [{"location": "2:3", "kind": "arithmetic"}], "maybe-not-number")
    _copy(tools, src_name)
    assert reasons().get(dest_name) == []


def test_copy_rejects_self_unknown_and_invisible_source(tmp_path):
    tools, dest, src, dest_name, src_name = _two_draft_tools(tmp_path)
    r = _copy(tools, dest_name)
    assert r.get("is_error") and "itself" in _text(r)
    r = _copy(tools, "no-such-draft")
    assert r.get("is_error") and "one of your drafts" in _text(r)
    # A single-draft agent (names=[dest]) cannot copy from a draft outside
    # its allowed names, even though that draft exists in the store.
    solo = {t.name: t for t in build_annotation_tools(tmp_path / "a.js", tmp_path, [dest_name], dest_name)}
    r = _run(solo["copy_annotations"], {"source": src_name})
    assert r.get("is_error") and "one of your drafts" in _text(r)


# --- rename_shape (shape + every reference, in place) ------------------------ #


def test_rename_shape_rewrites_all_references(tools, doc):
    _add_shape(tools, "Vec", properties=[{"name": "x", "type": "number"}])
    _add_shape(tools, "VecProto", properties=[{"name": "m", "type": "number"}])
    _run(tools["add_annotation"], {"kind": "shape_binding", "annotation": {"target range": _range(1, 1, 1, 5), "shape": "Vec"}})
    _run(tools["add_annotation"], {"kind": "shape_guard", "annotation": {"target range": _range(2, 1, 2, 5), "shape": "Vec"}})
    _run(tools["add_annotation"], {"kind": "shape_guard", "annotation": {"target range": _range(3, 1, 3, 5), "shape": "VecProto", "prototype shape": "Vec"}})
    r = _run(tools["rename_shape"], {"shape": "Vec", "new_name": "Vector"})
    assert not r.get("is_error")
    assert "rewrote 3 guard/binding reference(s)" in _text(r)
    assert set(doc.static_shapes) == {"Vector", "VecProto"}
    assert [b["shape"] for b in doc.shape_bindings] == ["Vector"]
    assert [g["shape"] for g in doc.shape_guards] == ["Vector", "VecProto"]
    assert doc.shape_guards[1]["prototype shape"] == "Vector"
    # The document stays dryrun-consumable: every reference resolves.
    snap = doc.to_dict()
    names = set(snap["static shapes"])
    for item in snap["shape guards"] + snap["shape bindings"]:
        assert item["shape"] in names
        assert item.get("prototype shape") is None or item["prototype shape"] in names


def test_rename_shape_target_conflict_rejected(tools):
    _add_shape(tools, "A", properties=[{"name": "x"}])
    _add_shape(tools, "B", properties=[{"name": "y"}])
    r = _run(tools["rename_shape"], {"shape": "A", "new_name": "B"})
    assert r.get("is_error")
    assert "already exists" in _text(r)


def test_rename_shape_unknown_shape_rejected(tools):
    r = _run(tools["rename_shape"], {"shape": "Ghost", "new_name": "Ghost2"})
    assert r.get("is_error")
    assert "no static shape named 'Ghost'" in _text(r)


def test_rename_shape_to_own_name_is_noop(tools, doc):
    _add_shape(tools, "A", properties=[{"name": "x"}])
    r = _run(tools["rename_shape"], {"shape": "A", "new_name": "A"})
    assert not r.get("is_error")
    assert "nothing to do" in _text(r)
    assert set(doc.static_shapes) == {"A"}


# --- create_draft (the parallel workers' draft bootstrap) -------------------- #


def test_create_draft_creates_then_is_idempotent(tmp_path):
    from annotator.annotation_drafts import drafts

    tools = {t.name: t for t in build_annotation_tools(tmp_path / "a.js", tmp_path)}
    r = _run(tools["create_draft"], {"draft": "hotspot:1"})
    assert not r.get("is_error")
    assert drafts().has("hotspot:1")
    # A retried worker gets the same answer, not a collision error.
    r = _run(tools["create_draft"], {"draft": "hotspot:1"})
    assert not r.get("is_error")
    r = _run(tools["create_draft"], {"draft": ""})
    assert r.get("is_error")
