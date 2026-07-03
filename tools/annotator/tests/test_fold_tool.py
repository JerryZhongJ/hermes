"""Tests for the in-process MCP ``fold`` tool.

Two layers: pure functions (``compute_levels`` / ``render`` / ``fold_source``)
asserted on hand-verified level arrays and folded output, and the async MCP
handler asserted on the same files plus defenses (path escape, bad ranges,
truncation). A coarse box2d.js regression checks that folding actually shrinks
a real multi-line file.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from annotator.tools.fold_tool import (
    build_fold_tool,
    compute_levels,
    fold_source,
    make_fold_server,
)

# function with a nested for-loop body:
#   row0 function solve(b) {
#   row1   const out = [];          <- inside func body (depth 1)
#   row2   for (...) {              <- inside func body (depth 1)
#   row3     out.push(p.x);         <- inside func + for body (depth 2)
#   row4   }                        <- inside func body (depth 1)
#   row5   return out;              <- inside func body (depth 1)
#   row6 }
SOLVE = (
    "function solve(b) {\n"
    "  const out = [];\n"
    "  for (const p of b.items) {\n"
    "    out.push(p.x);\n"
    "  }\n"
    "  return out;\n"
    "}\n"
)


@pytest.fixture
def solve_file(tmp_path: Path) -> Path:
    p = tmp_path / "solve.js"
    p.write_text(SOLVE)
    return p


# --- compute_levels ------------------------------------------------------


def test_compute_levels_solve():
    level, lines = compute_levels(SOLVE.encode())
    assert lines[0] == "function solve(b) {"
    # function body depth 1 over rows 1..5; for-body depth 2 over row 3.
    assert level == [0, 1, 1, 2, 1, 1, 0]


def test_single_line_block_is_not_folded():
    # Object literals on one line never fold, even nested.
    src = "const o = {x: 1, y: {z: 2}};\ntop();\n"
    level, _ = compute_levels(src.encode())
    assert level == [0, 0]


def test_multi_line_object_folds():
    src = "const o = {\n  x: 1,\n  y: 2,\n};\n"
    level, _ = compute_levels(src.encode())
    # header row0, body rows1..2, closing row3.
    assert level == [0, 1, 1, 0]


def test_empty_source_has_no_levels():
    level, lines = compute_levels(b"")
    assert level == []
    assert lines == []


# --- fold_source (rendering) --------------------------------------------


def test_fold_source_unfold_0(solve_file: Path):
    out = fold_source(solve_file.read_bytes(), None, None, 0)
    lines = out.split("\n")
    assert lines[0] == "1│ function solve(b) {"       # signature kept
    assert "… 5 lines folded …" in lines[1]        # body rows 2..6 collapsed
    assert lines[2] == "7│ }"                          # closing brace kept


def test_fold_source_unfold_1_shows_for_block(solve_file: Path):
    out = fold_source(solve_file.read_bytes(), None, None, 1)
    assert "2│   const out = [];" in out
    assert "3│   for (const p of b.items) {" in out    # for header kept
    assert "… 1 line folded …" in out               # for body row 4 collapsed
    assert "5│   }" in out                              # for closing kept


def test_fold_source_unfold_2_fully_expanded(solve_file: Path):
    out = fold_source(solve_file.read_bytes(), None, None, 2)
    assert "4│     out.push(p.x);" in out
    assert "folded" not in out


def test_fold_source_line_range_filters(solve_file: Path):
    out = fold_source(solve_file.read_bytes(), 2, 4, 1)
    assert "2│   const out = [];" in out
    assert "3│   for (const p of b.items) {" in out
    assert "… 1 line folded …" in out
    # lines outside [2,4] are dropped
    assert "function solve(b)" not in out
    assert "return out;" not in out


def test_adjacent_blocks_each_fold():
    src = "function a() {\n  x;\n}\nfunction b() {\n  y;\n}\n"
    out = fold_source(src.encode(), None, None, 0)
    assert out.count("folded") == 2
    assert "1│ function a() {" in out
    assert "4│ function b() {" in out


# --- defenses ------------------------------------------------------------


def test_empty_file_returns_marker(tmp_path: Path):
    p = tmp_path / "empty.js"
    p.write_text("")
    assert fold_source(p.read_bytes(), None, None, 0) == "(empty file)"


def test_half_range_rejected(solve_file: Path):
    with pytest.raises(ValueError, match="both"):
        fold_source(solve_file.read_bytes(), 1, None, 0)
    with pytest.raises(ValueError, match="both"):
        fold_source(solve_file.read_bytes(), None, 1, 0)


def test_out_of_range_rejected(solve_file: Path):
    with pytest.raises(ValueError, match="invalid"):
        fold_source(solve_file.read_bytes(), 0, 1, 0)
    with pytest.raises(ValueError, match="invalid"):
        fold_source(solve_file.read_bytes(), 1, 99, 0)


# --- MCP handler (async) -------------------------------------------------


async def _call(tool, args: dict) -> dict:
    return await tool.handler(args)


def test_handler_schema_marks_only_file_required():
    t = build_fold_tool(Path("."))
    schema = t.input_schema
    assert isinstance(schema, dict)
    assert schema["required"] == ["file"]
    assert set(schema["properties"]) == {
        "file",
        "from_line",
        "to_line",
        "unfold",
        "max_output_chars",
    }


def test_handler_fold_query(solve_file: Path):
    t = build_fold_tool(solve_file.parent)
    result = asyncio.run(_call(t, {"file": "solve.js"}))
    assert not result.get("is_error")
    text = result["content"][0]["text"]
    assert "function solve(b) {" in text
    assert "lines folded" in text


def test_handler_unfold_param(solve_file: Path):
    t = build_fold_tool(solve_file.parent)
    result = asyncio.run(_call(t, {"file": "solve.js", "unfold": 2}))
    text = result["content"][0]["text"]
    assert "out.push(p.x)" in text
    assert "folded" not in text


def test_handler_unfold_all_string(solve_file: Path):
    t = build_fold_tool(solve_file.parent)
    result = asyncio.run(_call(t, {"file": "solve.js", "unfold": "all"}))
    assert not result.get("is_error")
    text = result["content"][0]["text"]
    assert "out.push(p.x)" in text
    assert "folded" not in text


def test_handler_line_range(solve_file: Path):
    t = build_fold_tool(solve_file.parent)
    result = asyncio.run(
        _call(t, {"file": "solve.js", "from_line": 3, "to_line": 5, "unfold": 1})
    )
    text = result["content"][0]["text"]
    assert "for (const p of b.items)" in text
    assert "function solve(b)" not in text


def test_handler_path_escape_blocked(tmp_path: Path, solve_file: Path):
    # workdir is an inner dir; a file outside it must be refused even when
    # given as an absolute path.
    t = build_fold_tool(tmp_path / "work")
    result = asyncio.run(_call(t, {"file": str(solve_file.resolve())}))
    assert result.get("is_error") is True


def test_handler_file_not_found(solve_file: Path):
    t = build_fold_tool(solve_file.parent)
    result = asyncio.run(_call(t, {"file": "missing.js"}))
    assert result.get("is_error") is True


def test_handler_negative_unfold_error(solve_file: Path):
    t = build_fold_tool(solve_file.parent)
    result = asyncio.run(_call(t, {"file": "solve.js", "unfold": -1}))
    assert result.get("is_error") is True


def test_handler_empty_file(tmp_path: Path):
    (tmp_path / "e.js").write_text("")
    t = build_fold_tool(tmp_path)
    result = asyncio.run(_call(t, {"file": "e.js"}))
    assert not result.get("is_error")
    assert result["content"][0]["text"] == "(empty file)"


def test_handler_truncation_caps_output(solve_file: Path):
    t = build_fold_tool(solve_file.parent)
    result = asyncio.run(_call(t, {"file": "solve.js", "max_output_chars": 20}))
    text = result["content"][0]["text"]
    assert "truncated" in text
    assert len(text) < 100


def test_make_fold_server_returns_sdk_config(solve_file: Path):
    srv = make_fold_server(solve_file.parent)
    assert srv["type"] == "sdk"
    assert srv["name"] == "source-fold"
    assert srv["instance"] is not None


# --- level cache ---------------------------------------------------------


def test_cached_levels_reuses_object(solve_file: Path):
    from annotator.tools.fold_tool import _cached_levels

    first = _cached_levels(solve_file, solve_file.read_bytes())
    second = _cached_levels(solve_file, solve_file.read_bytes())
    # Same (path, mtime, size) → cache hit returns the very same level list.
    assert first[0] is second[0]


# --- integration: real box2d.js -----------------------------------------

BOX2D = (
    Path(__file__).parents[3]
    / "benchmarks" / "speculative" / "suites" / "hermes" / "octane" / "box2d.js"
)
skip_box2d = pytest.mark.skipif(not BOX2D.exists(), reason="box2d.js not checked out")


@skip_box2d
class TestBox2dRegression:
    def _full_line_count(self) -> int:
        text = BOX2D.read_bytes().decode("utf-8", "replace")
        lines = text.split("\n")
        if len(lines) > 1 and lines[-1] == "" and text.endswith("\n"):
            lines.pop()
        return len(lines)

    def test_fold_shrinks_output(self):
        data = BOX2D.read_bytes()
        out = fold_source(data, None, None, 0)
        out_lines = [ln for ln in out.split("\n") if ln]
        # Folding multi-line functions must cut the line count well below raw.
        assert len(out_lines) < self._full_line_count()
        assert any("lines folded" in ln for ln in out_lines)

    def test_unfold_grows_output_monotonically(self):
        data = BOX2D.read_bytes()
        n0 = len(fold_source(data, None, None, 0))
        n1 = len(fold_source(data, None, None, 1))
        n2 = len(fold_source(data, None, None, 2))
        assert n0 <= n1 <= n2
