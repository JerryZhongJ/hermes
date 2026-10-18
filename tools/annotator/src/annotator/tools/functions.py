"""Function-universe extraction (NOT an MCP tool).

Parses the single JS source with tree-sitter and returns every function node
with its ``loc_key`` (``startLine:startCol``, 1-based — the node's START
point alone; tree-sitter function nodes include their prefix tokens like
``async``/``static``, so a nested function's start is always strictly after
its enclosing function's, making the start point collision-free). The
``loc_key`` is the unified join key for hotspot targets, checklist scoping,
and ``batch_add_guards``.

Byte offsets — never ``start_point``/``end_point`` — are turned into
``loc_key`` via :func:`locate_tool.byte_to_line_col`; the ``.start_point``
binding segfaults on some files (e.g. box2d.js — see ``fold_tool``).
"""

from __future__ import annotations

import re
from typing import Any

import tree_sitter_javascript as tjs
from tree_sitter import Language, Parser

from .callgraph import _FUNC_TYPES  # reuse the function-type set
from .locate_tool import byte_to_line_col
from .utils import SCOPE_HELP, build_line_starts, resolve_line_window

_PARSER: Parser | None = None


def _get_parser() -> Parser:
    """Process-wide tree-sitter parser (thread-confined use is fine; the
    parser is only used inside synchronous tool handlers)."""
    global _PARSER
    if _PARSER is None:
        _PARSER = Parser(Language(tjs.language()))
    return _PARSER


def extract_functions(data: bytes) -> list[dict[str, Any]]:
    """All function nodes, with their nearest enclosing function when present.

    Iterative preorder DFS is safe on large/minified files. ``parent_loc_key``
    keeps outer/nested functions distinguishable when scoping by range.
    """
    parser = _get_parser()
    tree = parser.parse(data)
    line_starts = build_line_starts(data)
    funcs: list[dict[str, Any]] = []
    # Frame: node, next child index, nearest enclosing function loc_key.
    stack: list[list[Any]] = [[tree.root_node, 0, None]]
    while stack:
        frame = stack[-1]
        node, next_child, enclosing = frame
        kids = node.children
        if next_child >= len(kids):
            stack.pop()
            continue
        child = kids[next_child]
        frame[1] += 1
        child_enclosing = enclosing
        if child.type in _FUNC_TYPES:
            sl, sc = byte_to_line_col(child.start_byte, line_starts, data)
            el, ec = byte_to_line_col(child.end_byte, line_starts, data)
            loc_key = f"{sl}:{sc}"
            funcs.append(
                {
                    "loc_key": loc_key,
                    "name": _function_name(child, data),
                    "kind": child.type,
                    "start_line": sl,
                    "start_col": sc,
                    "end_line": el,
                    "end_col": ec,
                    "parent_loc_key": enclosing,
                }
            )
            child_enclosing = loc_key
        stack.append([child, 0, child_enclosing])
    return funcs


# --- ownership-based scope selection ---------------------------------------- #
#
# The ONE scope contract across every selecting tool (checklist / dryrun /
# list_annotations / batch_add_guards / copy_annotations / locate /
# view_callgraph / view_hot_value). ``fold`` is the deliberate exception —
# a visual text window (see utils.parse_scope_window).

# Sentinel owner for positions outside every function's range (module
# top-level code). Function scopes never resolve to it; only "<top-level>"
# and the whole-file view address it.
TOP_LEVEL_KEY = "<top-level>"

_WINDOW_RE = re.compile(r"^\d+-\d+$")


def function_records(data: bytes) -> list[dict[str, Any]]:
    """The function universe with (start_line, start_col, end_line, end_col)."""
    return [
        {
            "loc_key": item["loc_key"],
            "start": (item["start_line"], item["start_col"]),
            "end": (item["end_line"], item["end_col"]),
        }
        for item in extract_functions(data)
    ]


def innermost_owner(
    line: int, col: int, functions: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """The innermost function whose [start, end) range contains (line, col).

    Innermost is what makes nested functions independent scopes: a site
    inside ``inner`` resolves to ``inner``, never to the ``outer`` whose
    extents also contain it.
    """
    best = None
    for fn in functions:
        if fn["start"] <= (line, col) < fn["end"]:
            if best is None or fn["start"] > best["start"]:
                best = fn
    return best


def _parse_point(loc: Any) -> tuple[int, int] | None:
    """A 'line:col' string to its 1-based point, else None."""
    if not isinstance(loc, str):
        return None
    parts = loc.split(":")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _range_endpoints(
    rng: Any,
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """A range's 1-based (start, end) points from the formats tools carry.

    Annotation dicts ({"start": {line, column}, "end": {line, column}}),
    range_key strings "sl:sc:el:ec", and dryrun range strings "sl:sc-el:ec"
    all describe the same half-open source range — one parser so every tool
    selects ranges by the same rule.
    """
    if isinstance(rng, dict):
        try:
            s, e = rng["start"], rng["end"]
            return (int(s["line"]), int(s["column"])), (
                int(e["line"]),
                int(e["column"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(rng, str):
        # "sl:sc-el:ec" (dryrun ranges) first — split once on '-', each side
        # a 'l:c' point — then the 4-colon range_key form.
        halves = rng.split("-", 1)
        if len(halves) == 2:
            start, end = _parse_point(halves[0]), _parse_point(halves[1])
            if start is not None and end is not None:
                return start, end
        parts = rng.split(":")
        if len(parts) == 4:
            try:
                q1, q2, q3, q4 = (int(p) for p in parts)
            except ValueError:
                return None
            return (q1, q2), (q3, q4)
    return None


class ScopeSelection:
    """One resolved ``scope``: the set of source positions it selects.

    Ownership semantics — a function loc_key means that function's DIRECT
    statements only; the innermost function containing a position decides
    membership, so nested functions' sites belong to their own loc_keys and
    never appear in the enclosing scope. ``"<top-level>"`` addresses
    module-level code (positions outside every function). A line range
    selects positions whose own line falls inside it (any arbitrary region
    — never the whole function around it).
    """

    def __init__(
        self,
        functions: list[dict[str, Any]] | None = None,
        keys: list[str] | None = None,
        window: tuple[int, int] | None = None,
    ) -> None:
        self.functions = functions or []
        # Deduplicated in input order; None means "not a keys selection".
        self.keys: list[str] | None = list(dict.fromkeys(keys)) if keys is not None else None
        self.window = window

    @property
    def is_whole_file(self) -> bool:
        return self.keys is None and self.window is None

    def owns(self, line: int, col: int) -> bool:
        """Whether the scope selects the single 1-based point (line, col)."""
        if self.window is not None:
            a, b = self.window
            return a <= line <= b
        if self.keys is None:
            return True
        owner = innermost_owner(line, col, self.functions)
        return (TOP_LEVEL_KEY if owner is None else owner["loc_key"]) in self.keys

    def owns_loc(self, loc: Any) -> bool:
        """owns() for a 'line:col' string (a feedback/instruction site).

        Unparsable loci only match the whole-file selection — every other
        scope is a deliberate choice the caller made, so junk is out.
        """
        parsed = _parse_point(loc)
        if parsed is None:
            return self.is_whole_file
        return self.owns(*parsed)

    def selects_range(self, rng: Any) -> bool:
        """Whether the scope selects a source range (annotation target
        ranges, function extents).

        Ownership form: the range START's innermost owner decides — an
        annotation starting on the outer function's statement belongs to the
        outer scope even when its text runs on. Line window: any overlap
        (kept from the old window filter so multi-line ranges stay visible
        from any covering line).
        """
        if self.is_whole_file:
            return True
        endpoints = _range_endpoints(rng)
        if endpoints is None:
            return False
        (sl, _sc), (el, _ec) = endpoints
        if self.window is not None:
            a, b = self.window
            return el >= a and sl <= b
        return self.owns(sl, _sc)


def resolve_scope(scope: Any, source_data: bytes) -> ScopeSelection:
    """Resolve the shared ``scope`` argument under ownership semantics.

    Accepts ``None`` / ``"file"`` (whole file), one function loc_key or a
    list of them (each may also be ``TOP_LEVEL_KEY``), or one inclusive line
    range ``"a-b"`` (validated against the file's line count). Raises
    ValueError carrying the shared ``SCOPE_HELP`` message (or the window
    validation message) on anything else — the tool handlers report those
    verbatim as "unknown or malformed scope".
    """
    if scope is None or scope == "file":
        return ScopeSelection()
    keys = [scope] if isinstance(scope, str) else scope
    if (
        not isinstance(keys, list)
        or not keys
        or not all(isinstance(k, str) and k for k in keys)
    ):
        raise ValueError(SCOPE_HELP)
    functions = function_records(source_data)
    known = {fn["loc_key"] for fn in functions}
    if all(k in known or k == TOP_LEVEL_KEY for k in keys):
        return ScopeSelection(functions, keys=keys)
    # not loc_keys — allow a single line-range window
    if len(keys) == 1 and _WINDOW_RE.fullmatch(keys[0]):
        a, b = (int(x) for x in keys[0].split("-"))
        num_lines = len(build_line_starts(source_data))
        return ScopeSelection(
            functions, window=resolve_line_window(num_lines, a, b)
        )
    raise ValueError(SCOPE_HELP)


def _node_text(node, data: bytes) -> str:
    return data[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _function_name(node, data: bytes) -> str:
    """Best-effort name for a function node.

    ``function_declaration`` / ``method_definition`` carry an explicit name;
    ``function_expression`` / ``arrow_function`` borrow one from the binding
    context (assignment LHS, variable declarator, object pair key). Anything
    unresolved is ``<anonymous>``. The name is for agent readability only —
    ``loc_key`` is the authoritative identity.
    """
    if node.type in ("function_declaration", "generator_function_declaration"):
        nm = node.child_by_field_name("name")
        return _node_text(nm, data) if nm is not None else "<anonymous>"
    if node.type == "method_definition":
        nm = node.child_by_field_name("name")
        return _node_text(nm, data) if nm is not None else "<anonymous>"
    parent = node.parent
    if parent is not None:
        if parent.type == "assignment_expression":
            left = parent.child_by_field_name("left")
            if left is not None:
                return _node_text(left, data)
        elif parent.type == "variable_declarator":
            nm = parent.child_by_field_name("name")
            if nm is not None:
                return _node_text(nm, data)
        elif parent.type == "pair":
            key = parent.child_by_field_name("key")
            if key is not None:
                return _node_text(key, data)
    return "<anonymous>"
