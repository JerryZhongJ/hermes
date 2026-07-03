"""In-process MCP ``locate`` tool: precise source-range lookup for the agent.

The annotator agent runs in a sandbox that blocks ``python3``/``node`` and
shell redirection, so it cannot compute annotation ranges by running scripts.
It falls back to ``grep -ob`` plus hand-counting characters, which is painful
on minified single-line-thousand-char files and error-prone.

This module exposes a single MCP tool ``locate`` that the agent calls like a
built-in tool. The search runs *in the annotator host process* (via the SDK's
in-process MCP server), so the sandbox never sees it. Given a file, a line
window, and a literal substring, it returns every occurrence as a source range
in the exact shape the annotation JSON expects.

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
side.
"""

from __future__ import annotations

import bisect
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from .utils import _err, build_line_starts, resolve_in_workdir

# Cap so an over-broad needle (e.g. "p") cannot flood the agent's context.
DEFAULT_MAX_MATCHES = 64
# How many bytes of surrounding source to show for telling matches apart.
PREVIEW_BYTES = 48


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


def locate_in_file(
    path: Path,
    from_line: int | None,
    to_line: int | None,
    needle: bytes,
    max_matches: int = DEFAULT_MAX_MATCHES,
) -> list[dict[str, Any]]:
    """Find every occurrence of ``needle`` whose *start* byte falls in
    ``[from_line, to_line]`` (inclusive). The match itself may run past
    ``to_line`` (cross-line needles are the whole point). Returns a list of
    ``{"start": {...}, "end": {...}, "preview": str}`` with EXCLUSIVE end.

    If both ``from_line`` and ``to_line`` are None, the whole file is searched
    (the "all" scope). Specifying only one of them is an error.
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
        sl, sc = byte_to_line_col(hit, line_starts, data)
        el, ec = byte_to_line_col(end_byte, line_starts, data)
        preview_len = min(PREVIEW_BYTES, max(len(needle), 1))
        preview = data[hit : hit + preview_len].decode("utf-8", "replace")
        out.append(
            {
                "start": {"line": sl, "column": sc},
                "end": {"line": el, "column": ec},
                "preview": preview,
            }
        )
        pos = hit + max(1, len(needle))
    return out


def build_locate_tool(workdir: Path):
    """Build the ``locate`` SDK MCP tool, bound to ``workdir``.

    The agent addresses files by name relative to ``workdir`` (its cwd); the
    tool resolves and confines them under ``workdir`` so a malicious prompt
    can't read outside the attempt directory. Exposed separately from
    :func:`make_locate_server` so tests can invoke the handler directly.
    """
    workdir_resolved = workdir.resolve()

    @tool(
        "locate",
        "Find exact source ranges of a substring in the JS file being annotated. "
        "Use this instead of grep/awk or counting columns by hand. Returns ranges "
        "in annotation format: 1-based line/column (column counts Unicode chars), "
        "EXCLUSIVE end column, cross-line OK. Copy the range straight into "
        "'target range' / 'bind after'. Every match is returned with a preview — "
        "pick the one you mean. Omit from_line/to_line to search the whole file.",
        {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "filename relative to the workdir, e.g. 'box2d.js'"},
                "text": {"type": "string", "description": "literal substring to locate (NOT regex; may span lines)"},
                "from_line": {"type": "integer", "description": "1-based start line (inclusive); omit to search whole file"},
                "to_line": {"type": "integer", "description": "1-based end line (inclusive); omit to search whole file"},
                "max_matches": {"type": "integer", "description": "cap on results; 0 = unlimited (default 64)"},
            },
            "required": ["file", "text"],
        },
    )
    async def locate(args: dict[str, Any]) -> dict[str, Any]:
        try:
            needle = args["text"].encode("utf-8")
        except KeyError:
            return _err("missing 'text'")
        if needle == b"":
            return _err("empty needle")

        file_arg = args.get("file")
        if not isinstance(file_arg, str) or not file_arg:
            return _err("missing 'file'")
        target, err = resolve_in_workdir(workdir_resolved, file_arg)
        if err is not None:
            return err
        assert target is not None  # resolve_in_workdir returns a path unless err set

        try:
            fl = args.get("from_line")
            tl = args.get("to_line")
            from_line = int(fl) if fl is not None else None
            to_line = int(tl) if tl is not None else None
        except (TypeError, ValueError):
            return _err("from_line/to_line must be integers")

        max_matches = int(args.get("max_matches", DEFAULT_MAX_MATCHES))
        try:
            matches = locate_in_file(target, from_line, to_line, needle, max_matches)
        except ValueError as exc:
            return _err(str(exc))
        except FileNotFoundError:
            return _err(f"file not found: {file_arg}")

        if not matches:
            text = f"no match for {args['text']!r} in lines {from_line}-{to_line}"
        else:
            lines = [
                f"{m['start']['line']}:{m['start']['column']}-{m['end']['line']}:{m['end']['column']}  {m['preview']}"
                for m in matches
            ]
            text = "\n".join(lines) + f"\n({len(matches)} match(es))"
        return {"content": [{"type": "text", "text": text}]}

    return locate


def make_locate_server(workdir: Path):
    """Build an in-process MCP server exposing ``locate``, bound to ``workdir``."""
    return create_sdk_mcp_server(name="source-locate", tools=[build_locate_tool(workdir)])
