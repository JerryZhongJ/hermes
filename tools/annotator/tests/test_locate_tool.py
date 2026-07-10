"""Tests for the in-process MCP ``locate`` tool.

The core invariant: for every match, the source bytes sliced by the returned
range must equal the needle (a purely textual check, independent of how
columns are computed). Golden numeric assertions anchor specific regressions
(column math, cross-line, Unicode char counting).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from annotator.tools.locate_tool import (
    build_locate_tool,
    locate_in_file,
    make_locate_server,
)
from annotator.tools.utils import build_line_starts

# bytes for "abc\ndef\nghi\n": three 3-char lines.
ASCII_BYTES = b"abc\ndef\nghi\n"


@pytest.fixture
def ascii_file(tmp_path: Path) -> Path:
    p = tmp_path / "a.js"
    p.write_bytes(ASCII_BYTES)
    return p


@pytest.fixture
def unicode_file(tmp_path: Path) -> Path:
    # "ab中c\n": a(0) b(1) 中(2,3,4) c(5) \n(6). 中 is 3 UTF-8 bytes (E4 B8 AD).
    p = tmp_path / "u.js"
    p.write_bytes("ab中c\n".encode("utf-8"))
    return p


@pytest.fixture
def repeats_file(tmp_path: Path) -> Path:
    # "xax\nxbx\nxcx\n": 'x' appears twice per line (6 total); a/b/c once each.
    p = tmp_path / "r.js"
    p.write_bytes(b"xax\nxbx\nxcx\n")
    return p


def _slice(data: bytes, match: dict) -> bytes:
    """Slice [start, end) out of data using a match's line/column.

    Only valid for ASCII (byte offset == char offset); Unicode cases assert
    on column values directly instead.
    """
    ls = build_line_starts(data)
    s, e = match["start"], match["end"]
    start_byte = ls[s["line"] - 1] + s["column"] - 1
    end_byte = ls[e["line"] - 1] + e["column"] - 1
    return data[start_byte:end_byte]


# --- line counting --------------------------------------------------------


def test_build_line_starts_drops_phantom_trailing_line():
    # Trailing '\n' with no content after it must not create a 4th line.
    assert build_line_starts(ASCII_BYTES) == [0, 4, 8]


def test_build_line_starts_keeps_final_nonempty_line():
    # No trailing newline: 3 lines.
    assert build_line_starts(b"abc\ndef\nghi") == [0, 4, 8]


# --- core: range slices back to the needle (ASCII) ------------------------


def test_single_line_needle(ascii_file: Path):
    data = ascii_file.read_bytes()
    m = locate_in_file(ascii_file, 2, 2, b"def")[0]
    assert m["start"] == {"line": 2, "column": 1}
    assert m["end"] == {"line": 2, "column": 4}  # exclusive
    assert _slice(data, m) == b"def"


def test_cross_line_needle(ascii_file: Path):
    data = ascii_file.read_bytes()
    needle = b"c\nd"
    m = locate_in_file(ascii_file, 1, 2, needle)[0]
    assert m["start"] == {"line": 1, "column": 3}
    assert m["end"] == {"line": 2, "column": 2}
    assert _slice(data, m) == needle


def test_multiple_matches_returned(repeats_file: Path):
    # 'x' appears twice per line across 3 lines.
    assert len(locate_in_file(repeats_file, 1, 3, b"x")) == 6
    # 'a', 'b', 'c' each appear exactly once.
    assert len(locate_in_file(repeats_file, 1, 3, b"b")) == 1


def test_no_match_returns_empty(ascii_file: Path):
    assert locate_in_file(ascii_file, 1, 3, b"zzz") == []


def test_max_matches_caps_results(repeats_file: Path):
    res = locate_in_file(repeats_file, 1, 3, b"x", max_matches=2)
    assert len(res) == 2


# --- whole-file ("all") scope --------------------------------------------


def test_whole_file_equals_full_range(ascii_file: Path):
    needle = b"b"
    assert locate_in_file(ascii_file, None, None, needle) == locate_in_file(
        ascii_file, 1, 3, needle
    )


# --- Unicode: columns count chars, not bytes -----------------------------


def test_unicode_column_counts_chars(unicode_file: Path):
    # "ab中c": chars a=1 b=2 中=3 c=4. 'c' is at byte 5 but column 4.
    m = locate_in_file(unicode_file, 1, 1, "c".encode("utf-8"))[0]
    assert m["start"] == {"line": 1, "column": 4}


def test_unicode_multibyte_needle_end_column(unicode_file: Path):
    # needle "中c": 中 spans bytes 2-4 (char 3), c at byte 5 (char 4).
    # end is exclusive -> byte 6 -> char column 5.
    m = locate_in_file(unicode_file, 1, 1, "中c".encode("utf-8"))[0]
    assert m["start"] == {"line": 1, "column": 3}
    assert m["end"] == {"line": 1, "column": 5}


# --- defenses -------------------------------------------------------------


def test_empty_needle_rejected(ascii_file: Path):
    with pytest.raises(ValueError, match="empty needle"):
        locate_in_file(ascii_file, 1, 1, b"")


def test_half_range_rejected(ascii_file: Path):
    with pytest.raises(ValueError, match="both"):
        locate_in_file(ascii_file, 1, None, b"x")
    with pytest.raises(ValueError, match="both"):
        locate_in_file(ascii_file, None, 1, b"x")


def test_out_of_range_rejected(ascii_file: Path):
    with pytest.raises(ValueError, match="invalid"):
        locate_in_file(ascii_file, 0, 1, b"x")
    with pytest.raises(ValueError, match="invalid"):
        locate_in_file(ascii_file, 1, 99, b"x")


# --- MCP handler (async) --------------------------------------------------


async def _call(tool, args: dict) -> dict:
    """Invoke a tool's async handler and return its result dict.

    Wrapping ``await tool.handler(...)`` in an ``async def`` gives ``asyncio.run``
    a proper coroutine — the SDK types ``handler`` as ``Awaitable``, which
    ``asyncio.run`` rejects at type-check time even though it is fine at runtime.
    """
    return await tool.handler(args)


def test_handler_schema_marks_only_text_required():
    t = build_locate_tool(Path("."))
    schema = t.input_schema
    assert isinstance(schema, dict)
    assert schema["required"] == ["text"]
    assert set(schema["properties"]) == {
        "text",
        "from_line",
        "to_line",
        "max_matches",
        "following",
        "followed_by",
    }


def test_handler_range_query(ascii_file: Path):
    t = build_locate_tool(ascii_file)
    result = asyncio.run(_call(t, {"from_line": 2, "to_line": 2, "text": "def"}))
    assert not result.get("is_error")
    assert "2:1-2:4" in result["content"][0]["text"]
    assert "(1 match" in result["content"][0]["text"]
    assert "»def«" in result["content"][0]["text"]


def test_handler_whole_file_query(ascii_file: Path):
    t = build_locate_tool(ascii_file)
    result = asyncio.run(_call(t, {"text": "def"}))
    assert "2:1-2:4" in result["content"][0]["text"]
    assert "»def«" in result["content"][0]["text"]


def test_handler_empty_needle_error(ascii_file: Path):
    t = build_locate_tool(ascii_file)
    result = asyncio.run(_call(t, {"text": ""}))
    assert result.get("is_error") is True


def test_handler_missing_source_error(tmp_path: Path):
    # The bound source does not exist -> defensive FileNotFoundError error.
    t = build_locate_tool(tmp_path / "missing.js")
    result = asyncio.run(_call(t, {"text": "x"}))
    assert result.get("is_error") is True


def test_make_locate_server_returns_sdk_config(ascii_file: Path):
    srv = make_locate_server(ascii_file)
    assert srv["type"] == "sdk"
    assert srv["name"] == "source-locate"
    assert srv["instance"] is not None


# --- context rendering + following/followed_by filters --------------------


def test_context_vertical_surrounds_match_with_highlight(ascii_file: Path):
    # Whole-file window [1,3]; "def" on line 2 => neighbour lines shown.
    m = locate_in_file(ascii_file, None, None, b"def")[0]
    ctx = m["context"]
    assert "»def«" in ctx
    assert "1 | abc" in ctx       # preceding neighbour
    assert ">2 |" in ctx          # match line carries the ">" marker
    assert "3 | ghi" in ctx       # following neighbour


def test_context_cross_line_marks_first_and_last_line(ascii_file: Path):
    # "c\nd" spans lines 1-2: » sits at the match start (end of line 1), « at
    # the match end (start of line 2). Window [1,2] clamps out line 3.
    m = locate_in_file(ascii_file, 1, 2, b"c\nd")[0]
    ctx = m["context"]
    assert ">1 | ab»c" in ctx
    assert ">2 | d«ef" in ctx
    assert "3 |" not in ctx


def test_context_clamped_to_single_line_window(ascii_file: Path):
    # A one-line window shows only that line, no neighbours.
    m = locate_in_file(ascii_file, 2, 2, b"def")[0]
    ctx = m["context"]
    assert ">2 | »def«" in ctx
    assert "1 |" not in ctx
    assert "3 |" not in ctx


def test_context_horizontal_truncates_overlong_line(tmp_path: Path):
    # A single >200-char line: horizontal mode keeps a window around the match.
    blob = "a" * 250 + "ADD" + "b" * 250
    p = tmp_path / "m.js"
    p.write_bytes(blob.encode())
    m = locate_in_file(p, 1, 1, b"ADD")[0]
    ctx = m["context"]
    assert "»ADD«" in ctx
    assert ctx.count("…") == 2          # truncated on both sides, once each
    assert "a" * 250 not in ctx         # the bulk is cut
    assert "b" * 250 not in ctx
    assert ctx.count("\n") == 0         # only the match line, no neighbours


def test_followed_by_keeps_only_adjacent(tmp_path: Path):
    p = tmp_path / "f.js"
    p.write_bytes(b"obj .x = 1;\nobj = 2;\nobj.y = 3;\n")
    res = locate_in_file(p, 1, 3, b"obj", followed_by=b".x")
    assert len(res) == 1
    assert res[0]["start"]["line"] == 1   # the one-space gap is allowed


def test_followed_by_rejects_non_whitespace_gap(tmp_path: Path):
    p = tmp_path / "f.js"
    p.write_bytes(b"foo bar;\nfoo;\n")
    res = locate_in_file(p, 1, 2, b"foo", followed_by=b";")
    assert len(res) == 1
    assert res[0]["start"]["line"] == 2   # line 1 has "bar" in the gap


def test_following_keeps_only_preceded(tmp_path: Path):
    p = tmp_path / "f.js"
    p.write_bytes(b"var x = foo;\nlet foo;\n")
    res = locate_in_file(p, 1, 2, b"foo", following=b"var x =")
    assert len(res) == 1
    assert res[0]["start"]["line"] == 1


def test_following_and_followed_by_combined(tmp_path: Path):
    p = tmp_path / "f.js"
    p.write_bytes(b"x = mid = y;\nmid;\n")
    res = locate_in_file(p, 1, 2, b"mid", following=b"x =", followed_by=b"= y")
    assert len(res) == 1
    assert res[0]["start"]["line"] == 1


# --- integration: real minified box2d.js (golden regression) --------------

BOX2D = (
    Path(__file__).parents[3]
    / "benchmarks" / "speculative" / "suites" / "hermes" / "octane" / "box2d.js"
)
skip_box2d = pytest.mark.skipif(not BOX2D.exists(), reason="box2d.js not checked out")


@skip_box2d
class TestBox2dRegression:
    """Anchor against hand-verified ranges from
    annotations/naive/hermes/octane/box2d.json (end-exclusive)."""

    def test_add_short_needle_same_line(self):
        m = locate_in_file(BOX2D, 176, 177, b"A.prototype.Add")[0]
        assert m["start"] == {"line": 176, "column": 464}
        assert m["end"] == {"line": 176, "column": 479}  # 15 chars

    def test_add_cross_line_needle(self):
        needle = b"A.prototype.Add=function(p){this.x+=p.x;\nthis.y+=p.y}"
        m = locate_in_file(BOX2D, 176, 177, needle)[0]
        assert m["start"] == {"line": 176, "column": 464}
        assert m["end"] == {"line": 177, "column": 13}  # ; is at col 13

    def test_b2vec2_ctor_assignment(self):
        m = locate_in_file(BOX2D, 175, 175, b"this.x=p;this.y=B")[0]
        assert m["start"] == {"line": 175, "column": 485}

    def test_b2mat22_constructor(self):
        m = locate_in_file(BOX2D, 161, 161, b"F.b2Mat22=function")[0]
        assert m["start"] == {"line": 161, "column": 214}

    def test_param_p_appears_at_expected_col(self):
        # "p" matches many times on L176; the function(p) parameter is at 489.
        res = locate_in_file(BOX2D, 176, 176, b"p", max_matches=0)
        cols = {(m["start"]["column"], m["end"]["column"]) for m in res}
        assert (489, 490) in cols

    def test_add_followed_by_equals_function(self):
        # "Add" pinned by followed_by="=function" => the prototype assignment
        # (A.prototype.Add=function). The bare substring "Add" sits at col 476
        # on L176 (the leading "A" of A.prototype is at 464).
        res = locate_in_file(BOX2D, 176, 177, b"Add", followed_by=b"=function")
        assert len(res) == 1
        assert res[0]["start"] == {"line": 176, "column": 476}
