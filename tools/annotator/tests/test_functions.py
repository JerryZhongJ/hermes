"""Tests for functions: function-universe extraction."""

from __future__ import annotations

from annotator.tools.functions import extract_functions

SRC = b"""function foo(x) { return x + 1; }
const Bar = function(a) { return a; };
A.prototype.Set = function(p) { this.p = p; };
class C { m() { return 1; } }
"""


def test_extract_finds_all_function_kinds():
    fs = extract_functions(SRC)
    names = {f["name"] for f in fs}
    kinds = {f["kind"] for f in fs}
    assert "foo" in names
    assert "Bar" in names
    assert "A.prototype.Set" in names  # borrowed from the assignment LHS
    assert "m" in names
    assert "function_declaration" in kinds
    assert "function_expression" in kinds
    assert "method_definition" in kinds


def test_extract_finds_generator_function_expressions():
    fs = extract_functions(
        b"const f = function* (obj) { obj.x; };\n"
        b"const g = async function* (obj) { obj.x; };\n"
    )
    assert [f["name"] for f in fs] == ["f", "g"]
    assert {f["kind"] for f in fs} == {"generator_function"}


def test_loc_key_is_1_based():
    fs = extract_functions(b"function foo(x){return x+1;}")
    assert len(fs) == 1
    assert fs[0]["loc_key"] == "1:1"  # line 1, col 1 start
    assert fs[0]["start_line"] == 1


def test_nested_functions_track_parent():
    src = (
        b"function outer() {\n"
        + b"  work();\n" * 4
        + b"  function inner() { return 1; }\n"
        + b"  work();\n" * 4
        + b"}\n"
    )
    funcs = extract_functions(src)
    outer = next(f for f in funcs if f["name"] == "outer")
    inner = next(f for f in funcs if f["name"] == "inner")
    assert inner["parent_loc_key"] == outer["loc_key"]
