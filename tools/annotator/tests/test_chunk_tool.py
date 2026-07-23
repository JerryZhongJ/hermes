"""Tests for chunk_tool: function-universe extraction + fixed-line chunking."""

from __future__ import annotations

from annotator.tools.chunk_tool import build_index, extract_functions, plan_chunks

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


def test_loc_key_is_1_based():
    fs = extract_functions(b"function foo(x){return x+1;}")
    assert len(fs) == 1
    assert fs[0]["loc_key"].startswith("1:1:1:")  # line 1, col 1 start
    assert fs[0]["start_line"] == 1


def test_plan_chunks_never_cuts_function_body():
    fs = extract_functions(SRC)
    locs = {f["loc_key"] for f in fs}
    for c in plan_chunks(fs, lines_per_chunk=1):
        for lk in c["function_loc_keys"]:
            assert lk in locs  # chunk boundaries align to whole functions only


def test_plan_chunks_oversize_single_function():
    big = b"function big(){\n" + b"  x;\n" * 20 + b"}\n"
    chunks = plan_chunks(extract_functions(big), lines_per_chunk=2)
    assert len(chunks) == 1
    assert chunks[0]["oversize"] is True


def test_plan_chunks_splits_when_window_exceeded():
    # four 1-line functions far apart in line number, tiny window -> 4 chunks
    src = b"".join(f"function f{i}(){{return {i};}}\n".encode() for i in range(4))
    # force each onto its own "line window" by using window=1
    chunks = plan_chunks(extract_functions(src), lines_per_chunk=1)
    assert len(chunks) == 4


def test_nested_function_subtree_stays_in_one_oversize_chunk():
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
    chunks = plan_chunks(funcs, lines_per_chunk=5)

    assert inner["parent_loc_key"] == outer["loc_key"]
    assert len(chunks) == 1
    assert chunks[0]["oversize"] is True
    assert {outer["loc_key"], inner["loc_key"]} <= set(chunks[0]["function_loc_keys"])


def test_build_index_tags_chunk_ids_and_writes_sidecar(tmp_path):
    src = tmp_path / "t.js"
    src.write_bytes(SRC)
    idx = build_index(src, tmp_path)
    assert all(f.get("chunk_id") for f in idx["function_universe"])
    assert (tmp_path / ".chunks" / "index.json").exists()
