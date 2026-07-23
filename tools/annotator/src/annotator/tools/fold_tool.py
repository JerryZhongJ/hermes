"""In-process MCP ``fold`` tool: a syntax-aware, folded view of the JS file.

Companion to ``locate``: ``locate`` gives exact source ranges for annotations;
``fold`` gives a low-token structural overview so the agent can navigate large
or minified files. The file is parsed once with tree-sitter-javascript, each
line is tagged with the nesting depth of the multi-line foldable block whose
*body* it sits in, and rendering keeps every line at depth <= ``unfold`` while
replacing each contiguous folded run with a one-line placeholder.

Only multi-line blocks fold — exactly like an IDE. A block that sits on a
single line (e.g. an inlined minified blob on a multi-megabyte-char line) is
left untouched. The block's header line (carrying the opening ``{([``) and its
closing line (``)``}`]``) always stay visible — the signature stays readable
and the agent can see the exact end line — so only the body lines in between
are folded. Output is original source lines plus placeholder lines: no text is
ever reconstructed, so the view can never misrepresent the code.
"""

from __future__ import annotations

import bisect
from pathlib import Path
from typing import Any

import tree_sitter_javascript as tjs
from claude_agent_sdk import create_sdk_mcp_server, tool
from tree_sitter import Language, Parser

from .utils import _err, build_line_starts, resolve_line_window

# Delimiter blocks worth folding. We fold the block node *itself* (its header
# line carries the opener, its last line the matching close) rather than the
# enclosing declaration — otherwise function_declaration would swallow its own
# signature line and add a spurious nesting level on top of statement_block.
FOLDABLE = frozenset(
    {
        "statement_block",
        "class_body",
        "object",
        "array",
        "arguments",
        "formal_parameters",
        # tree-sitter-javascript uses one `comment` node for both // and /* */;
        # only multi-line ones (a /* */ block) fold, a single-line comment
        # stays put.
        "comment",
    }
)

DEFAULT_MAX_OUTPUT_CHARS = 16_384

_parser_singleton: Parser | None = None


def _get_parser() -> Parser:
    global _parser_singleton
    if _parser_singleton is None:
        _parser_singleton = Parser(Language(tjs.language()))
    return _parser_singleton


def _split_lines(data: bytes) -> list[str]:
    """Split into lines aligned with ``utils.build_line_starts``.

    A single trailing newline must not produce a phantom empty last line, so
    line N here == line N in ``locate`` and in the annotation JSON.
    """
    text = data.decode("utf-8", "replace")
    if not text:
        return []
    lines = text.split("\n")
    if len(lines) > 1 and lines[-1] == "" and text.endswith("\n"):
        lines.pop()
    return lines


def compute_levels(data: bytes) -> tuple[list[int], list[str]]:
    """Return ``(level, lines)`` for the source bytes.

    ``level[i]`` is the deepest foldable-block depth whose *body* (header
    line + 1 .. closing line - 1) covers line i; 0 means line i is not inside
    any foldable body. Single-line blocks contribute nothing. Computed by one
    iterative DFS over the CST (no recursion, safe on large files). ``ERROR``
    and missing nodes are simply not in ``FOLDABLE``, so malformed input never
    crashes the tool — affected lines just stay unfolded.
    """
    lines = _split_lines(data)
    n = len(lines)
    level = [0] * n
    if n == 0:
        return level, lines

    # Reuse utils' line table to turn node byte offsets into line numbers. We
    # deliberately avoid node.start_point / node.end_point: on some files
    # (e.g. box2d.js) accessing those Point objects segfaults the tree-sitter
    # binding — a native crash no try/except can catch. Byte offsets are plain
    # ints and stay safe.
    line_starts = build_line_starts(data)
    parser = _get_parser()
    tree = parser.parse(data)
    fold = FOLDABLE

    def row(byte: int) -> int:
        return bisect.bisect_right(line_starts, byte) - 1

    # Iterative preorder DFS. Each frame is [node, next_child_index,
    # foldable_ancestor_count]. A child's foldable-ancestor count is its
    # parent's count plus one if the parent is itself a multi-line foldable.
    root = tree.root_node
    stack: list[list[Any]] = [[root, 0, 0]]
    while stack:
        frame = stack[-1]
        node = frame[0]
        kids = node.children
        if frame[1] < len(kids):
            child = kids[frame[1]]
            frame[1] += 1
            # end_byte is exclusive; back up one byte so a block whose close
            # sits at end-of-line maps to that line, not the next.
            p_s = row(node.start_byte)
            p_e = row(max(node.start_byte, node.end_byte - 1))
            parent_is_fold = node.type in fold and p_s < p_e
            child_anc = frame[2] + (1 if parent_is_fold else 0)
            c_s = row(child.start_byte)
            c_e = row(max(child.start_byte, child.end_byte - 1))
            child_is_fold = child.type in fold and c_s < c_e
            if child_is_fold:
                d = child_anc + 1
                lo = c_s + 1
                hi = c_e - 1
                if hi >= n:
                    hi = n - 1
                for i in range(lo, hi + 1):
                    if 0 <= i < n and d > level[i]:
                        level[i] = d
            stack.append([child, 0, child_anc])
        else:
            stack.pop()
    return level, lines


def render(
    lines: list[str],
    level: list[int],
    unfold: int,
    from_line: int | None,
    to_line: int | None,
) -> str:
    """Render the folded view: keep lines with ``level <= unfold`` and replace
    each contiguous deeper run with a placeholder. Optional ``from_line`` /
    ``to_line`` (1-based, inclusive) filter which lines/placeholders are
    emitted. Output lines carry a 1-based line-number prefix aligned with
    ``locate``.
    """
    n = len(lines)
    w = len(str(n)) if n else 1
    out: list[str] = []
    i = 0
    while i < n:
        if level[i] > unfold:
            j = i
            while j < n and level[j] > unfold:
                j += 1
            seg_lo = i + 1  # 1-based inclusive first folded line
            seg_hi = j      # 1-based inclusive last folded line
            in_range = (from_line is None or seg_hi >= from_line) and (
                to_line is None or seg_lo <= to_line
            )
            if in_range:
                cnt = j - i
                unit = "line" if cnt == 1 else "lines"
                out.append(f"{' ' * w}  … {cnt} {unit} folded …")
            i = j
        else:
            line_no = i + 1
            in_range = (from_line is None or line_no >= from_line) and (
                to_line is None or line_no <= to_line
            )
            if in_range:
                out.append(f"{line_no:>{w}}│ {lines[i].rstrip()}")
            i += 1
    return "\n".join(out)


def _resolve_range(
    n: int, from_line: int | None, to_line: int | None
) -> tuple[int, int]:
    """Validate and normalize the 1-based inclusive line window (delegates to
    the shared :func:`resolve_line_window`). Kept so the module's own tests and
    call sites stay unchanged after the helper moved to :mod:`utils`."""
    return resolve_line_window(n, from_line, to_line)


def fold_source(
    data: bytes,
    from_line: int | None,
    to_line: int | None,
    unfold: int,
) -> str:
    """Fold ``data`` (no path/workdir handling) — used by tests and the handler."""
    level, lines = compute_levels(data)
    n = len(lines)
    if n == 0:
        return "(empty file)"
    fl, tl = _resolve_range(n, from_line, to_line)
    return render(lines, level, unfold, fl, tl)


# Per-process level cache keyed by (path, mtime, size). An annotator run
# touches a handful of files once each, so an unbounded dict is fine; the key
# invalidates on any edit.
_LEVEL_CACHE: dict[tuple[str, float, int], tuple[list[int], list[str]]] = {}


def _cached_levels(path: Path, data: bytes) -> tuple[list[int], list[str]]:
    try:
        st = path.stat()
        key = (str(path), st.st_mtime, st.st_size)
    except OSError:
        return compute_levels(data)
    cached = _LEVEL_CACHE.get(key)
    if cached is not None:
        return cached
    val = compute_levels(data)
    _LEVEL_CACHE[key] = val
    return val


def build_fold_tool(source: Path):
    """Build the ``fold`` SDK MCP tool, bound to the single source ``source``.

    One annotator run targets exactly one JS file, so the agent never picks a
    file — the tool always reads ``source``. Exposed separately from
    :func:`make_fold_server` so tests can invoke the handler directly.
    """
    source_resolved = source.resolve()

    @tool(
        "fold",
        "Show a folded, low-token structural view of the JS file. Use this "
        "first on large/minified files to see the skeleton, note the line "
        "numbers of interesting blocks, then `locate` for exact ranges and "
        "raise `unfold` to expand a region. Only multi-line blocks fold (like "
        "an IDE); block header + closing lines stay visible. Output is the "
        "original source lines plus `// … N lines folded …` placeholders with "
        "1-based line numbers.",
        {
            "type": "object",
            "properties": {
                "from_line": {
                    "type": "integer",
                    "description": "1-based start line (inclusive); omit to fold the whole file",
                },
                "to_line": {
                    "type": "integer",
                    "description": "1-based end line (inclusive); omit to fold the whole file",
                },
                "unfold": {
                    "type": ["integer", "string"],
                    "description": "nesting levels to keep expanded (default 0 = fold every multi-line block; 'all' = fully expand)",
                },
                "max_output_chars": {
                    "type": "integer",
                    "description": "cap on output size (default 16384; 0 = unlimited)",
                },
            },
            "required": [],
        },
    )
    async def fold(args: dict[str, Any]) -> dict[str, Any]:
        try:
            data = source_resolved.read_bytes()
        except FileNotFoundError:
            return _err(f"source file not found: {source_resolved}")
        except OSError as exc:
            return _err(f"cannot read {source_resolved!r}: {exc}")

        fl_raw = args.get("from_line")
        tl_raw = args.get("to_line")
        try:
            from_line = int(fl_raw) if fl_raw is not None else None
            to_line = int(tl_raw) if tl_raw is not None else None
        except (TypeError, ValueError):
            return _err("from_line/to_line must be integers")

        unfold_raw = args.get("unfold", 0)
        unfold_all = isinstance(unfold_raw, str) and unfold_raw.lower() == "all"
        if unfold_all:
            unfold = 0  # resolved to max(level)+1 once levels are known
        else:
            try:
                unfold = int(unfold_raw)
            except (TypeError, ValueError):
                return _err("unfold must be a non-negative integer or 'all'")
            if unfold < 0:
                return _err("unfold must be >= 0 or 'all'")

        try:
            max_chars = int(args.get("max_output_chars", DEFAULT_MAX_OUTPUT_CHARS))
        except (TypeError, ValueError):
            max_chars = DEFAULT_MAX_OUTPUT_CHARS

        level, lines = _cached_levels(source_resolved, data)
        n = len(lines)
        if n == 0:
            text = "(empty file)"
        else:
            try:
                fl, tl = _resolve_range(n, from_line, to_line)
            except ValueError as exc:
                return _err(str(exc))
            # 'all' => expand every block: any threshold above the max depth
            # makes `level[i] > unfold` false everywhere.
            u = (max(level) + 1) if unfold_all else unfold
            text = render(lines, level, u, fl, tl)

        if max_chars > 0 and len(text) > max_chars:
            text = text[:max_chars] + f"\n   // … output truncated at {max_chars} chars …"
        return {"content": [{"type": "text", "text": text}]}

    return fold


def make_fold_server(source: Path):
    """Build an in-process MCP server exposing ``fold``, bound to ``source``."""
    return create_sdk_mcp_server(name="source-fold", tools=[build_fold_tool(source)])
