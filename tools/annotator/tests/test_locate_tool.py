"""Tests for the in-process MCP ``locate`` tool (AST syntax-role queries).

The core invariant: for every hit, the source bytes sliced by the returned
range must equal the identifier (or needle) in question — a purely textual
check, independent of how columns are computed. Golden numeric assertions
anchor specific regressions (column math, cross-line, Unicode char counting).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from annotator.tools.locate_tool import (
    build_locate_tool,
    locate_callee,
    locate_def,
    locate_member,
    locate_param,
    locate_ref,
    locate_text,
    make_locate_server,
)
from annotator.tools.utils import build_line_starts

# bytes for "abc\ndef\nghi\n": three 3-char lines.
ASCII_BYTES = b"abc\ndef\nghi\n"

# A small real-JS fixture exercising every role, incl. nested functions.
JS = b"""function f(a, b = 1) { return g(a) + b; }
const g = (x) => x + 1;
obj.prop.method();
obj[name];
f(g(2));
function outer(p) { const inner = (q) => p + q; return inner(p); }
"""


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


@pytest.fixture
def js_file(tmp_path: Path) -> Path:
    p = tmp_path / "js.js"
    p.write_bytes(JS)
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


# --- text role: range slices back to the needle (ASCII) -------------------


def test_single_line_needle(ascii_file: Path):
    data = ascii_file.read_bytes()
    m = locate_text(ascii_file, 2, 2, b"def")[0]
    assert m["start"] == {"line": 2, "column": 1}
    assert m["end"] == {"line": 2, "column": 4}  # exclusive
    assert _slice(data, m) == b"def"


def test_cross_line_needle(ascii_file: Path):
    data = ascii_file.read_bytes()
    needle = b"c\nd"
    m = locate_text(ascii_file, 1, 2, needle)[0]
    assert m["start"] == {"line": 1, "column": 3}
    assert m["end"] == {"line": 2, "column": 2}
    assert _slice(data, m) == needle


def test_multiple_matches_returned(repeats_file: Path):
    # 'x' appears twice per line across 3 lines.
    assert len(locate_text(repeats_file, 1, 3, b"x")) == 6
    # 'a', 'b', 'c' each appear exactly once.
    assert len(locate_text(repeats_file, 1, 3, b"b")) == 1


def test_no_match_returns_empty(ascii_file: Path):
    assert locate_text(ascii_file, 1, 3, b"zzz") == []


def test_max_matches_caps_results(repeats_file: Path):
    res = locate_text(repeats_file, 1, 3, b"x", max_matches=2)
    assert len(res) == 2


def test_whole_file_equals_full_range(ascii_file: Path):
    needle = b"b"
    assert locate_text(ascii_file, None, None, needle) == locate_text(
        ascii_file, 1, 3, needle
    )


# --- Unicode: columns count chars, not bytes -----------------------------


def test_unicode_column_counts_chars(unicode_file: Path):
    # "ab中c": chars a=1 b=2 中=3 c=4. 'c' is at byte 5 but column 4.
    m = locate_text(unicode_file, 1, 1, "c".encode("utf-8"))[0]
    assert m["start"] == {"line": 1, "column": 4}


def test_unicode_multibyte_needle_end_column(unicode_file: Path):
    # needle "中c": 中 spans bytes 2-4 (char 3), c at byte 5 (char 4).
    # end is exclusive -> byte 6 -> char column 5.
    m = locate_text(unicode_file, 1, 1, "中c".encode("utf-8"))[0]
    assert m["start"] == {"line": 1, "column": 3}
    assert m["end"] == {"line": 1, "column": 5}


def test_unicode_param_column(tmp_path: Path):
    # Line: "function f(pé) { return pé; }" — é is 2 UTF-8 bytes.
    # Chars 1-based: '('=11, p=12, é=13, ')'=14. Bytes: é at 11-12.
    src = "function f(pé) { return pé; }\n".encode("utf-8")
    hits, err = locate_param(src, "pé", None, "file")
    assert err is None and len(hits) == 1
    # start col 12 (byte 11), end EXCLUSIVE col 14: the next char ')' is at
    # byte 13 — a column count of CHARACTERS, not bytes (byte-wise would be 14
    # for the é alone; here é is one char).
    assert hits[0]["start"] == {"line": 1, "column": 12}
    assert hits[0]["end"] == {"line": 1, "column": 14}


# --- defenses (text role) -------------------------------------------------


def test_empty_needle_rejected(ascii_file: Path):
    with pytest.raises(ValueError, match="empty needle"):
        locate_text(ascii_file, 1, 1, b"")


def test_half_range_rejected(ascii_file: Path):
    with pytest.raises(ValueError, match="both"):
        locate_text(ascii_file, 1, None, b"x")
    with pytest.raises(ValueError, match="both"):
        locate_text(ascii_file, None, 1, b"x")


def test_out_of_range_rejected(ascii_file: Path):
    with pytest.raises(ValueError, match="invalid"):
        locate_text(ascii_file, 0, 1, b"x")
    with pytest.raises(ValueError, match="invalid"):
        locate_text(ascii_file, 1, 99, b"x")


# --- role: def ------------------------------------------------------------


def test_def_returns_whole_function_range(js_file: Path):
    data = js_file.read_bytes()
    hits = locate_def(data, 1, 6, "f", 64)
    assert len(hits) == 1
    h = hits[0]
    assert h["start"] == {"line": 1, "column": 1}
    assert h["end"] == {"line": 1, "column": 42}  # whole "function f(...) {...}" (41 chars + 1)
    assert h["role"] == "def"
    assert h["enclosing"] is None  # top level
    assert _slice(data, h).startswith(b"function f(")
    assert _slice(data, h).endswith(b"}")


def test_def_arrow_via_binding_name(js_file: Path):
    data = js_file.read_bytes()
    hits = locate_def(data, 1, 6, "g", 64)
    assert len(hits) == 1
    assert hits[0]["start"] == {"line": 2, "column": 11}  # the "(x) => x + 1"
    assert _slice(data, hits[0]) == b"(x) => x + 1"


def test_def_method_name(tmp_path: Path):
    # Only a class-body method_definition is a def; obj.method() at top level
    # is a plain member_expression and must NOT match.
    p = tmp_path / "cls.js"
    p.write_bytes(b"class K { method(z) { return z; } }\n")
    data = p.read_bytes()
    hits = locate_def(data, 1, 1, "method", 64)
    assert len(hits) == 1
    assert _slice(data, hits[0]).startswith(b"method(z)")
    assert locate_def(b"obj.method();\n", 1, 1, "method", 64) == []


def test_def_nested_function_enclosing(js_file: Path):
    data = js_file.read_bytes()
    hits = locate_def(data, 1, 6, "inner", 64)
    assert len(hits) == 1
    assert hits[0]["enclosing"] == "6:1"  # outer's loc_key


# --- role: param ----------------------------------------------------------


def test_param_plain_and_defaulted(js_file: Path):
    data = js_file.read_bytes()
    hits, err = locate_param(data, "b", "1:1", "file")
    assert err is None and len(hits) == 1
    h = hits[0]
    assert h["start"] == {"line": 1, "column": 15}  # the 'b' of 'b = 1'
    assert h["end"] == {"line": 1, "column": 16}
    assert h["role"] == "param"
    assert h["enclosing"] == "1:1"
    assert _slice(data, h) == b"b"


def test_param_scope_single_function_omits_function_arg(js_file: Path):
    data = js_file.read_bytes()
    hits, err = locate_param(data, "p", None, "6:1")
    assert err is None and len(hits) == 1
    assert hits[0]["start"] == {"line": 6, "column": 16}


def test_param_parenless_arrow(tmp_path: Path):
    p = tmp_path / "arrow.js"
    p.write_bytes(b"const sq = n => n * n;\n")
    hits, err = locate_param(p.read_bytes(), "n", None, "file")
    assert err is None and len(hits) == 1
    assert hits[0]["start"] == {"line": 1, "column": 12}


def test_param_ambiguous_scope_lists_candidates(js_file: Path):
    data = js_file.read_bytes()
    hits, err = locate_param(data, "b", None, "file")
    assert hits == []
    assert err is not None and "functions" in err
    assert "f (1:1)" in err  # candidates carry name + loc_key
    assert "outer (6:1)" in err


def test_param_wrong_function_reports_declared_params(js_file: Path):
    data = js_file.read_bytes()
    hits, err = locate_param(data, "zz", "1:1", "file")
    assert hits == []
    assert err is not None and "no parameter" in err
    assert "a" in err and "b" in err  # the declared names are listed


def test_param_unknown_function_key(js_file: Path):
    hits, err = locate_param(js_file.read_bytes(), "a", "9:9", "file")
    assert hits == []
    assert err is not None and "unknown function" in err


# --- role: callee ---------------------------------------------------------


def test_callee_bare_identifier_excludes_paren(js_file: Path):
    data = js_file.read_bytes()
    hits = locate_callee(data, 1, 6, "f", 64)
    assert len(hits) == 1
    h = hits[0]
    assert h["start"] == {"line": 5, "column": 1}
    assert h["end"] == {"line": 5, "column": 2}  # just 'f', NOT '('
    assert _slice(data, h) == b"f"
    assert h["role"] == "callee"
    assert h["call"]["start"] == {"line": 5, "column": 1}
    assert h["call"]["end"] == {"line": 5, "column": 8}  # f(g(2)) is 7 chars
    assert "receiver" not in h


def test_callee_nested_inner_calls(js_file: Path):
    data = js_file.read_bytes()
    hits = locate_callee(data, 1, 6, "g", 64)
    assert len(hits) == 2
    lines = [h["start"]["line"] for h in hits]
    assert lines == [1, 5]  # g(a) inside f, then g(2) on L5


def test_callee_method_call_carries_receiver(js_file: Path):
    data = js_file.read_bytes()
    hits = locate_callee(data, 1, 6, "method", 64)
    assert len(hits) == 1
    h = hits[0]
    assert _slice(data, h) == b"method"
    assert _slice(data, h["receiver"]) == b"obj.prop"
    assert _slice(data, h["call"]) == b"obj.prop.method()"
    assert h["enclosing"] is None  # top-level statement


def test_callee_new_expression(tmp_path: Path):
    p = tmp_path / "new.js"
    p.write_bytes(b"function C() {}\nnew C();\nC();\n")
    data = p.read_bytes()
    hits = locate_callee(data, 1, 3, "C", 64)
    assert len(hits) == 2
    assert {h["start"]["line"] for h in hits} == {2, 3}  # new C() and C()


def test_callee_name_mismatch_in_member(tmp_path: Path):
    # obj.other() must not match name="method".
    p = tmp_path / "m.js"
    p.write_bytes(b"obj.other();\n")
    assert locate_callee(p.read_bytes(), 1, 1, "method", 64) == []


# --- role: ref ------------------------------------------------------------


def test_ref_roles_and_enclosing(js_file: Path):
    data = js_file.read_bytes()
    hits = locate_ref(data, 1, 6, "p", 64)
    # p appears: outer's param decl (L6 c16), read in inner (L6 c42),
    # argument of inner(p) (L6 c62).
    assert [h["start"]["column"] for h in hits] == [16, 42, 62]
    assert [h["role"] for h in hits] == ["decl", "read", "read"]
    assert hits[0]["enclosing"] == "6:1"   # decl owned by outer
    assert hits[1]["enclosing"] == "6:35"  # read inside inner
    assert all(_slice(data, h) == b"p" for h in hits)


def test_ref_write_and_call_roles(tmp_path: Path):
    p = tmp_path / "w.js"
    p.write_bytes(b"let v = 1;\nv = v + 1;\nv();\nfunction v2() { v++; }\n")
    data = p.read_bytes()
    hits = locate_ref(data, 1, 4, "v", 64)
    roles = [h["role"] for h in hits]
    assert roles == ["decl", "write", "read", "call", "write"]  # v++ is a write


def test_ref_excludes_member_property(tmp_path: Path):
    # obj.v is a property, not a reference of the binding v.
    p = tmp_path / "e.js"
    p.write_bytes(b"const v = 1;\nobj.v = v;\n")
    data = p.read_bytes()
    hits = locate_ref(data, 1, 2, "v", 64)
    assert [h["start"]["line"] for h in hits] == [1, 2]
    assert _slice(data, hits[1]) == b"v"  # the RHS v, not obj.'v'


def test_ref_max_matches(js_file: Path):
    hits = locate_ref(js_file.read_bytes(), 1, 6, "p", 2)
    assert len(hits) == 2


# --- role: member ---------------------------------------------------------


def test_member_property_and_receiver(js_file: Path):
    data = js_file.read_bytes()
    hits = locate_member(data, 1, 6, "prop", 64)
    assert len(hits) == 1
    h = hits[0]
    assert h["start"] == {"line": 3, "column": 5}
    assert h["end"] == {"line": 3, "column": 9}
    assert _slice(data, h) == b"prop"
    assert h["role"] == "member"
    assert _slice(data, h["receiver"]) == b"obj"


def test_member_chain_each_level(js_file: Path):
    data = js_file.read_bytes()
    # obj.prop.method(): both member expressions carry distinct receivers.
    hits = locate_member(data, 1, 6, "method", 64)
    assert len(hits) == 1
    assert _slice(data, hits[0]["receiver"]) == b"obj.prop"


def test_member_ignores_computed_access(js_file: Path):
    # obj[name] on L4 is computed: no property match.
    data = js_file.read_bytes()
    assert locate_member(data, 1, 6, "name", 64) == []


def test_member_ignores_object_pair_keys(tmp_path: Path):
    p = tmp_path / "o.js"
    p.write_bytes(b"const o = { key: 1 };\nreturn o.key;\n")
    data = p.read_bytes()
    hits = locate_member(data, 1, 2, "key", 64)
    assert len(hits) == 1
    assert hits[0]["start"]["line"] == 2  # the o.key access, not the pair key


# --- MCP handler (async) --------------------------------------------------


async def _call(tool, args: dict) -> dict:
    """Invoke a tool's async handler and return its result dict.

    Wrapping ``await tool.handler(...)`` in an ``async def`` gives ``asyncio.run``
    a proper coroutine — the SDK types ``handler`` as ``Awaitable``, which
    ``asyncio.run`` rejects at type-check time even though it is fine at runtime.
    """
    return await tool.handler(args)


def test_handler_schema_marks_what_and_name_required():
    t = build_locate_tool(Path("."))
    schema = t.input_schema
    assert isinstance(schema, dict)
    assert schema["required"] == ["what", "name"]
    assert set(schema["properties"]) == {"what", "name", "scope", "function", "max_matches"}
    assert set(schema["properties"]["what"]["enum"]) == {
        "param", "callee", "def", "ref", "member", "text",
    }


def test_handler_param_query(js_file: Path):
    t = build_locate_tool(js_file)
    result = asyncio.run(
        _call(t, {"what": "param", "name": "b", "function": "1:1"})
    )
    assert not result.get("is_error")
    text = result["content"][0]["text"]
    assert "1:15:1:16" in text
    assert "role=param" in text
    assert "enclosing=1:1" in text
    assert "»b«" in text


def test_handler_param_ambiguous_error_lists_candidates(js_file: Path):
    t = build_locate_tool(js_file)
    result = asyncio.run(_call(t, {"what": "param", "name": "b"}))
    assert result.get("is_error") is True
    text = result["content"][0]["text"]
    assert "1:1" in text and "outer" in text


def test_handler_callee_query_with_call_range(js_file: Path):
    t = build_locate_tool(js_file)
    result = asyncio.run(_call(t, {"what": "callee", "name": "f"}))
    text = result["content"][0]["text"]
    assert "5:1:5:2" in text       # the callee identifier
    assert "call: 5:1:5:8" in text  # f(g(2))


def test_handler_member_query_with_receiver(js_file: Path):
    t = build_locate_tool(js_file)
    result = asyncio.run(_call(t, {"what": "member", "name": "method", "scope": "3-3"}))
    text = result["content"][0]["text"]
    assert "3:10:3:16" in text
    assert "receiver: 3:1:3:9" in text


def test_handler_text_role_still_works(ascii_file: Path):
    t = build_locate_tool(ascii_file)
    result = asyncio.run(_call(t, {"what": "text", "scope": "2-2", "name": "def"}))
    assert not result.get("is_error")
    assert "2:1:2:4" in result["content"][0]["text"]
    assert "(1 match" in result["content"][0]["text"]
    assert "»def«" in result["content"][0]["text"]


def test_handler_invalid_what_rejected(ascii_file: Path):
    t = build_locate_tool(ascii_file)
    result = asyncio.run(_call(t, {"what": "banana", "name": "x"}))
    assert result.get("is_error") is True
    assert "banana" in result["content"][0]["text"]


def test_handler_missing_name_rejected(ascii_file: Path):
    t = build_locate_tool(ascii_file)
    result = asyncio.run(_call(t, {"what": "text"}))
    assert result.get("is_error") is True


def test_handler_empty_needle_error(ascii_file: Path):
    t = build_locate_tool(ascii_file)
    result = asyncio.run(_call(t, {"what": "text", "name": ""}))
    assert result.get("is_error") is True


def test_handler_missing_source_error(tmp_path: Path):
    # The bound source does not exist -> defensive OSError error.
    t = build_locate_tool(tmp_path / "missing.js")
    result = asyncio.run(_call(t, {"what": "text", "name": "x"}))
    assert result.get("is_error") is True


def test_handler_unknown_scope_error(js_file: Path):
    t = build_locate_tool(js_file)
    result = asyncio.run(_call(t, {"what": "ref", "name": "p", "scope": "99-99"}))
    assert result.get("is_error") is True


def test_handler_no_hit_message_mentions_role(js_file: Path):
    t = build_locate_tool(js_file)
    result = asyncio.run(_call(t, {"what": "def", "name": "nosuch"}))
    assert not result.get("is_error")
    assert "no def hit" in result["content"][0]["text"]


def test_make_locate_server_returns_sdk_config(ascii_file: Path):
    srv = make_locate_server(ascii_file)
    assert srv["type"] == "sdk"
    assert srv["name"] == "source-locate"
    assert srv["instance"] is not None


# --- context rendering ----------------------------------------------------


def test_context_vertical_surrounds_match_with_highlight(ascii_file: Path):
    # Whole-file window [1,3]; "def" on line 2 => neighbour lines shown.
    m = locate_text(ascii_file, None, None, b"def")[0]
    ctx = m["context"]
    assert "»def«" in ctx
    assert "1 | abc" in ctx       # preceding neighbour
    assert ">2 |" in ctx          # match line carries the ">" marker
    assert "3 | ghi" in ctx       # following neighbour


def test_context_cross_line_marks_first_and_last_line(ascii_file: Path):
    # "c\nd" spans lines 1-2: » sits at the match start (end of line 1), « at
    # the match end (start of line 2). Window [1,2] clamps out line 3.
    m = locate_text(ascii_file, 1, 2, b"c\nd")[0]
    ctx = m["context"]
    assert ">1 | ab»c" in ctx
    assert ">2 | d«ef" in ctx
    assert "3 |" not in ctx


def test_context_clamped_to_single_line_window(ascii_file: Path):
    # A one-line window shows only that line, no neighbours.
    m = locate_text(ascii_file, 2, 2, b"def")[0]
    ctx = m["context"]
    assert ">2 | »def«" in ctx
    assert "1 |" not in ctx
    assert "3 |" not in ctx


def test_context_horizontal_truncates_overlong_line(tmp_path: Path):
    # A single >200-char line: horizontal mode keeps a window around the match.
    blob = "a" * 250 + "ADD" + "b" * 250
    p = tmp_path / "m.js"
    p.write_bytes(blob.encode())
    m = locate_text(p, 1, 1, b"ADD")[0]
    ctx = m["context"]
    assert "»ADD«" in ctx
    assert ctx.count("…") == 2          # truncated on both sides, once each
    assert "a" * 250 not in ctx         # the bulk is cut
    assert "b" * 250 not in ctx
    assert ctx.count("\n") == 0         # only the match line, no neighbours


# --- integration: real minified box2d.js (golden regression) --------------

BOX2D = (
    Path(__file__).parents[3]
    / "benchmarks" / "bench-runner" / "resource" / "test-suites" / "octane" / "box2d.js"
)
skip_box2d = pytest.mark.skipif(not BOX2D.exists(), reason="box2d.js not checked out")


@skip_box2d
class TestBox2dRegression:
    """Anchor against hand-verified ranges from
    annotations/naive/hermes/octane/box2d.json (end-exclusive)."""

    def test_add_short_needle_same_line(self):
        m = locate_text(BOX2D, 176, 177, b"A.prototype.Add")[0]
        assert m["start"] == {"line": 176, "column": 464}
        assert m["end"] == {"line": 176, "column": 479}  # 15 chars

    def test_add_cross_line_needle(self):
        needle = b"A.prototype.Add=function(p){this.x+=p.x;\nthis.y+=p.y}"
        m = locate_text(BOX2D, 176, 177, needle)[0]
        assert m["start"] == {"line": 176, "column": 464}
        assert m["end"] == {"line": 177, "column": 13}  # ; is at col 13

    def test_b2vec2_ctor_assignment(self):
        m = locate_text(BOX2D, 175, 175, b"this.x=p;this.y=B")[0]
        assert m["start"] == {"line": 175, "column": 485}

    def test_b2mat22_constructor(self):
        m = locate_text(BOX2D, 161, 161, b"F.b2Mat22=function")[0]
        assert m["start"] == {"line": 161, "column": 214}

    def test_param_p_via_ast_role(self):
        # The same parameter declaration the old text test pinned by hand
        # (col 489-490 on L176) now comes out of the AST role directly.
        data = BOX2D.read_bytes()
        from annotator.tools.functions import extract_functions

        target = next(
            fn for fn in extract_functions(data)
            if fn["name"] == "A.prototype.Add" and fn["start_line"] == 176
        )
        hits, err = locate_param(data, "p", target["loc_key"], "file")
        assert err is None and len(hits) == 1
        assert hits[0]["start"] == {"line": 176, "column": 489}
        assert hits[0]["end"] == {"line": 176, "column": 490}

    def test_add_callee_via_ast_role(self):
        # "Add" as a callee identifier (no "(" in the range) — previously the
        # agent had to hand-strip the paren from a text match. Real call sites
        # live on later lines (e.g. 338); each hit must slice to bare "Add".
        data = BOX2D.read_bytes()
        hits = locate_callee(data, 330, 345, "Add", 64)
        assert hits
        for h in hits:
            assert _slice(data, h) == b"Add"
            # method calls carry the receiver and the full call range
            assert _slice(data, h["receiver"]) in (b"t", b"this") or b"." in _slice(data, h["receiver"])
