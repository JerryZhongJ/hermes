"""In-process MCP ``locate`` tool: precise source-range lookup for the agent.

The annotator agent runs in a sandbox that blocks ``python3``/``node`` and
shell redirection, so it cannot compute annotation ranges by running scripts.
It falls back to ``grep -ob`` plus hand-counting characters, which is painful
on minified single-line-thousand-char files and error-prone.

This module exposes a single MCP tool ``locate`` that the agent calls like a
built-in tool. The search runs *in the annotator host process* (via the SDK's
in-process MCP server), so the sandbox never sees it. Given a file, a line
window, and a literal substring, it returns every occurrence as a source range
in the exact shape the annotation JSON expects — each with a line-numbered
context snippet that wraps the match in ``»…«`` so the agent can tell
occurrences apart without re-reading the file. Optional ``following`` /
``followed_by`` lookbehind/lookahead filters keep only matches textually
adjacent to given neighbours (only whitespace may sit between) — the
programmatic "pick the expression you mean" for annotation work.

Column semantics deliberately mirror ``SourceErrorManager::findForCoordsImpl``
in ``lib/Support/SourceErrorManager.cpp``: 1-based line, 1-based column, where
a column counts **Unicode characters** — UTF-8 continuation bytes
(0x80–0xBF) are skipped, exactly as the consumer's UTF-8 reverse-lookup path
does (lines 427-435). On ASCII lines every byte is one character so a column
equals the byte offset; on UTF-8 lines it matches what
``AnnotationLoader::resolveLocation`` → ``findSMLocFromCoords`` expects. The
end column is EXCLUSIVE (half-open ``[start, end)``), so a range returned here
resolves to the same ``SMLoc`` the hermes parser would produce for those bytes
— i.e. it hits the ``DenseMap<SMRange>`` exact-pointer lookup on the consumer
side. The context/highlight rendering is display-only and never changes the
range values.
"""

from __future__ import annotations

import bisect
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from .utils import _err, build_line_starts

# Cap so an over-broad needle (e.g. "p") cannot flood the agent's context.
DEFAULT_MAX_MATCHES = 64
# Vertical context: how many lines above/below the match to show on normal code.
CONTEXT_SURROUND = 1
# A line longer than this (in characters) is treated as "minified": context
# switches from vertical (neighbour lines) to horizontal (a char window centred
# on the match), since minified neighbour lines are noise, not structure.
MAX_LINE_CHARS = 200
# Half-width of the horizontal char window shown around a minified match.
MARGIN = 60
# Whitespace allowed in the gap between a match and a following/followed_by
# neighbour. Any other byte (or running off the file) means "not adjacent".
_WS = b" \t\n\r\f\v"

_OPEN = "»"   # marks the first char of a match
_CLOSE = "«"  # marks the char right after the last char of a match


def _count_chars(data: bytes, start: int, end: int) -> int:
    """Count Unicode characters in ``data[start:end]``.

    UTF-8 continuation bytes (0x80–0xBF) belong to the preceding multi-byte
    sequence and must not be counted as separate columns. Mirrors
    ``findForCoordsImpl``'s ``isUTF8ContinuationByte`` skip. On ASCII slices
    this is just ``end - start``.
    """
    chars = 0
    for i in range(start, end):
        b = data[i]
        if b < 0x80 or b >= 0xC0:
            chars += 1
    return chars


def byte_to_line_col(byte: int, line_starts: list[int], data: bytes) -> tuple[int, int]:
    """Convert a byte offset into (1-based line, 1-based character column).

    ``col`` counts Unicode characters from the line start (continuation bytes
    skipped), plus 1. For a byte one past the last char of a line (the
    exclusive end of a range ending at end-of-line), this yields
    ``line_char_count + 1``, the end-of-line position ``findForCoordsImpl``
    accepts (lines 437-439).
    """
    idx = bisect.bisect_right(line_starts, byte) - 1
    if idx < 0:
        idx = 0
    line_start = line_starts[idx]
    return idx + 1, _count_chars(data, line_start, byte) + 1


def _adjacent_ok(
    data: bytes,
    hit: int,
    end_byte: int,
    following: bytes | None,
    followed_by: bytes | None,
) -> bool:
    """Whether the match at byte range ``[hit, end_byte)`` satisfies the
    optional lookbehind (``following``) and lookahead (``followed_by``)
    filters. Only whitespace may sit in either gap; any other byte, or the gap
    running off the end/start of the file, rejects the match. ``None`` skips
    that side. So ``text="obj" followed_by=".x"`` keeps ``obj`` only when ``.x``
    (modulo blanks) comes right after, and ``text="foo" following="var x ="``
    keeps ``foo`` only when ``var x =`` precedes it.
    """
    if followed_by is not None:
        g = end_byte
        while g < len(data) and data[g] in _WS:
            g += 1
        if data[g:g + len(followed_by)] != followed_by:
            return False
    if following is not None:
        g = hit
        while g > 0 and data[g - 1] in _WS:
            g -= 1
        start = g - len(following)
        if start < 0 or data[start:g] != following:
            return False
    return True


def _line_text(data: bytes, line_starts: list[int], i: int, num_lines: int) -> str:
    """Decode 1-based line ``i`` without its trailing ``\\n``.

    ``line_starts`` is :func:`utils.build_line_starts`; for ``i < num_lines``
    the line occupies ``[line_starts[i-1], line_starts[i])`` with a ``\\n`` just
    before the next start; the last line runs to EOF.
    """
    start = line_starts[i - 1]
    end = line_starts[i] if i < num_lines else len(data)
    if end > start and data[end - 1] == 0x0A:  # drop the trailing '\n'
        end -= 1
    return data[start:end].decode("utf-8", "replace")


def _insert_markers(s: str, open_pos: int | None, close_pos: int | None) -> str:
    """Insert ``«`` then ``»`` so the earlier index stays valid. Positions are
    0-based character indices into ``s``; either may be ``None``."""
    if close_pos is not None:
        cp = max(0, min(close_pos, len(s)))
        s = s[:cp] + _CLOSE + s[cp:]
    if open_pos is not None:
        op = max(0, min(open_pos, len(s)))
        s = s[:op] + _OPEN + s[op:]
    return s


def _render_line(
    text: str,
    seg: tuple[int, int] | None,
    open_pos: int | None,
    close_pos: int | None,
) -> str:
    """Render one context line.

    ``seg`` is the matched character span ``(lo, hi)`` within this line, or
    ``None`` for a non-match neighbour line. ``open_pos``/``close_pos`` are the
    0-based character positions at which to insert ``»``/``«`` (set only on the
    match's first/last line). Overlong lines are truncated: centred on ``seg``
    when present, else tail-truncated — neighbour lines never blow up tokens.
    """
    L = len(text)
    if L <= MAX_LINE_CHARS:
        return _insert_markers(text, open_pos, close_pos)
    if seg is not None:
        win_lo = max(0, seg[0] - MARGIN)
        win_hi = min(L, seg[1] + MARGIN)
    else:
        win_lo = 0
        win_hi = min(L, 2 * MARGIN)
    pre = "…" if win_lo > 0 else ""
    suf = "…" if win_hi < L else ""
    body = pre + text[win_lo:win_hi] + suf
    off = len(pre) - win_lo  # shift marker positions into `body`
    op = None if open_pos is None else open_pos + off
    cp = None if close_pos is None else close_pos + off
    return _insert_markers(body, op, cp)


def render_context(
    data: bytes,
    line_starts: list[int],
    hit: int,
    end_byte: int,
    window_lo: int,
    window_hi: int,
) -> str:
    """Build the line-numbered, ``»…«``-wrapped context for one match.

    Adaptive: if any line the match spans is overlong (minified), show only the
    match's own lines, each truncated to a window around the match
    (horizontal); otherwise show the match line(s) plus ``CONTEXT_SURROUND``
    neighbour lines (vertical). Neighbour lines are clamped to the search
    window ``[window_lo, window_hi]`` (1-based inclusive) — a tight window
    (e.g. a single line) yields a tight context; the match's own lines are
    always shown in full so a cross-line match is never cut.
    """
    num_lines = len(line_starts)
    sl, sc = byte_to_line_col(hit, line_starts, data)
    el, ec = byte_to_line_col(end_byte, line_starts, data)

    horizontal = any(
        len(_line_text(data, line_starts, i, num_lines)) > MAX_LINE_CHARS
        for i in range(sl, el + 1)
    )
    if horizontal:
        lo, hi = sl, el
    else:
        lo = max(window_lo, sl - CONTEXT_SURROUND)
        hi = min(window_hi, el + CONTEXT_SURROUND)
        lo = min(lo, sl)  # never drop the match's own first line
        hi = max(hi, el)  # never drop the match's own last line

    w = len(str(num_lines)) if num_lines else 1
    out: list[str] = []
    for i in range(lo, hi + 1):
        text = _line_text(data, line_starts, i, num_lines)
        if i == sl and i == el:
            seg: tuple[int, int] | None = (sc - 1, ec - 1)
        elif i == sl:
            seg = (sc - 1, len(text))
        elif i == el:
            seg = (0, ec - 1)
        elif sl < i < el:
            seg = (0, len(text))
        else:
            seg = None
        open_pos = (sc - 1) if i == sl else None
        close_pos = (ec - 1) if i == el else None
        rendered = _render_line(text, seg, open_pos, close_pos)
        marker = ">" if sl <= i <= el else " "
        out.append(f"{marker}{i:>{w}} | {rendered}")
    return "\n".join(out)


def locate_in_file(
    path: Path,
    from_line: int | None,
    to_line: int | None,
    needle: bytes,
    max_matches: int = DEFAULT_MAX_MATCHES,
    following: bytes | None = None,
    followed_by: bytes | None = None,
) -> list[dict[str, Any]]:
    """Find every occurrence of ``needle`` whose *start* byte falls in
    ``[from_line, to_line]`` (inclusive). The match itself may run past
    ``to_line`` (cross-line needles are the whole point). Returns a list of
    ``{"start": {...}, "end": {...}, "context": str}`` with EXCLUSIVE end.

    If both ``from_line`` and ``to_line`` are None, the whole file is searched
    (the "all" scope). Specifying only one of them is an error.

    ``following`` / ``followed_by`` (optional byte strings) filter matches by
    textual adjacency (see :func:`_adjacent_ok`); filtered-out matches do not
    count toward ``max_matches``.
    """
    if not needle:
        raise ValueError("empty needle")

    data = path.read_bytes()
    line_starts = build_line_starts(data)
    num_lines = len(line_starts)

    # Both None => whole-file ("all") search.
    if from_line is None and to_line is None:
        from_line, to_line = 1, num_lines
    elif from_line is None or to_line is None:
        raise ValueError("specify both from_line and to_line, or neither for whole-file")

    if from_line < 1 or to_line < from_line or to_line > num_lines:
        raise ValueError(
            f"line range [{from_line},{to_line}] invalid; file has {num_lines} line(s)"
        )

    window_start = line_starts[from_line - 1]
    # End of to_line's content = start of the next line, or EOF.
    window_end = line_starts[to_line] if to_line < num_lines else len(data)
    # Let a match's tail overshoot the window (cross-line), but never past EOF.
    search_end = min(window_end + len(needle), len(data))

    out: list[dict[str, Any]] = []
    pos = window_start
    while pos < window_end:
        if 0 < max_matches <= len(out):
            break
        hit = data.find(needle, pos, search_end)
        if hit < 0 or hit >= window_end:
            # hit >= window_end would mean the start is outside the window;
            # since finds are in order, we're done.
            break
        end_byte = hit + len(needle)
        if not _adjacent_ok(data, hit, end_byte, following, followed_by):
            pos = hit + max(1, len(needle))
            continue
        sl, sc = byte_to_line_col(hit, line_starts, data)
        el, ec = byte_to_line_col(end_byte, line_starts, data)
        context = render_context(data, line_starts, hit, end_byte, from_line, to_line)
        out.append(
            {
                "start": {"line": sl, "column": sc},
                "end": {"line": el, "column": ec},
                "context": context,
            }
        )
        pos = hit + max(1, len(needle))
    return out


def build_locate_tool(source: Path):
    """Build the ``locate`` SDK MCP tool, bound to the single source ``source``.

    One annotator run targets exactly one JS file, so the agent never picks a
    file — the tool always reads ``source``. Exposed separately from
    :func:`make_locate_server` so tests can invoke the handler directly.
    """
    source_resolved = source.resolve()

    @tool(
        "locate",
        "Find exact source ranges of a substring in the JS file being annotated. "
        "Use this instead of grep/awk or counting columns by hand. Returns ranges "
        "in annotation format: 1-based line/column (column counts Unicode chars), "
        "EXCLUSIVE end column, cross-line OK. Copy the range straight into "
        "'target range'. Every match comes with a line-numbered "
        "context snippet with the match wrapped in »…« so you can tell matches "
        "apart at a glance. Optional 'following'/'followed_by' (literal text, only "
        "whitespace may sit between) keep just matches adjacent to a neighbour — "
        "e.g. text='obj' followed_by='.x' pins the obj in 'obj.x'. Omit "
        "from_line/to_line to search the whole file.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "literal substring to locate (NOT regex; may span lines)"},
                "from_line": {"type": "integer", "description": "1-based start line (inclusive); omit to search whole file"},
                "to_line": {"type": "integer", "description": "1-based end line (inclusive); omit to search whole file"},
                "max_matches": {"type": "integer", "description": "cap on results; 0 = unlimited (default 64)"},
                "following": {
                    "type": "string",
                    "description": "literal text that must immediately precede the match (lookbehind); "
                    "only whitespace may sit between. e.g. text='foo' following='var x ='",
                },
                "followed_by": {
                    "type": "string",
                    "description": "literal text that must immediately follow the match (lookahead); "
                    "only whitespace may sit between. e.g. text='obj' followed_by='.x'",
                },
            },
            "required": ["text"],
        },
    )
    async def locate(args: dict[str, Any]) -> dict[str, Any]:
        try:
            needle = args["text"].encode("utf-8")
        except KeyError:
            return _err("missing 'text'")
        if needle == b"":
            return _err("empty needle")

        try:
            fl = args.get("from_line")
            tl = args.get("to_line")
            from_line = int(fl) if fl is not None else None
            to_line = int(tl) if tl is not None else None
        except (TypeError, ValueError):
            return _err("from_line/to_line must be integers")

        fg = args.get("following")
        fb = args.get("followed_by")
        following = fg.encode("utf-8") if isinstance(fg, str) and fg else None
        followed_by = fb.encode("utf-8") if isinstance(fb, str) and fb else None

        max_matches = int(args.get("max_matches", DEFAULT_MAX_MATCHES))
        try:
            matches = locate_in_file(
                source_resolved, from_line, to_line, needle, max_matches, following, followed_by
            )
        except ValueError as exc:
            return _err(str(exc))
        except FileNotFoundError:
            return _err(f"source file not found: {source_resolved}")

        if not matches:
            text = f"no match for {args['text']!r} in lines {from_line}-{to_line}"
        else:
            blocks = [
                f"{m['start']['line']}:{m['start']['column']}-{m['end']['line']}:{m['end']['column']}\n{m['context']}"
                for m in matches
            ]
            text = "\n\n".join(blocks) + f"\n({len(matches)} match(es))"
        return {"content": [{"type": "text", "text": text}]}

    return locate


def make_locate_server(source: Path):
    """Build an in-process MCP server exposing ``locate``, bound to ``source``."""
    return create_sdk_mcp_server(name="source-locate", tools=[build_locate_tool(source)])
