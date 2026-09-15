"""In-process MCP ``locate`` tool: AST-syntax-role source-range lookup.

The annotator agent runs in a sandbox that blocks ``python3``/``node`` and
shell redirection, so it cannot compute annotation ranges by running scripts.
Analysis of real runs showed the agent uses ``locate`` for *semantic
addressing* of annotation targets — "where is this function's parameter
declared", "where is this function called" — and hand-counts columns on top of
raw text matches (callee identifier minus the paren, Nth column of a
parameter list), which caused rework.

``locate`` is therefore a **syntax-role query** over the same tree-sitter
parse the other source tools use (see :mod:`tools.functions`). ``what``
selects the role — ``param`` (a function's parameter declaration), ``callee``
(the callee identifier at each call site), ``def`` (a function definition,
for ``target function``), ``ref`` (every read/write/call/decl of an
identifier, each tagged with its enclosing function), ``member`` (the
``obj.prop`` property position plus the receiver expression) — and ``text``
remains the literal-substring fallback for minified or syntax-odd sources.

Column semantics deliberately mirror ``SourceErrorManager::findForCoordsImpl``
in ``lib/Support/SourceErrorManager.cpp``: 1-based line, 1-based column, where
a column counts **Unicode characters** — UTF-8 continuation bytes
(0x80–0xBF) are skipped, exactly as the consumer's UTF-8 reverse-lookup path
does. On ASCII lines every byte is one character so a column equals the byte
offset; on UTF-8 lines it matches what ``AnnotationLoader::resolveLocation``
→ ``findSMLocFromCoords`` expects. The end column is EXCLUSIVE (half-open
``[start, end)``), so a range returned here resolves to the same ``SMLoc`` the
hermes parser would produce for those bytes. Tree-sitter byte offsets go
through the exact same :func:`byte_to_line_col` path as the text matcher, so
AST and text roles share one column contract. The context/highlight rendering
is display-only and never changes the range values.
"""


from __future__ import annotations

import bisect
from pathlib import Path
from typing import Any, Iterator

from claude_agent_sdk import create_sdk_mcp_server, tool

from .utils import _err, build_line_starts

PROMPT = (
    "- Use the `locate` tool to get exact annotation target ranges instead of grep/awk or counting columns by hand. "
    'It queries AST syntax roles: locate(what="param", name="n", function="35:1") returns that function\'s parameter declaration; '
    'locate(what="callee", name="enleve_pierre", scope="file") returns the callee identifier (without the "(") at every call site, '
    'plus the full call-expression range; locate(what="def", name="scale") returns the function definition range (use it directly as a closure\'s "target function"); '
    'locate(what="ref", name="p", scope="35:1") returns every read/write/call/decl of the identifier, each tagged with its enclosing function; '
    'locate(what="member", name="x") returns each obj.x property position together with its receiver expression range. '
    'Ranges come back as 4-seg colon strings `sl:sc:el:ec` (e.g. "31:19:31:20") — 1-based, EXCLUSIVE end column, Unicode-char columns — the SAME format as annotation target_range, so copy them straight in. '
    "with a line-numbered context snippet wrapping the hit in »…«. Copy them straight into 'target range'. "
    "The scope is a function loc_key (e.g. \"31:1\" — that function's DIRECT statements only: nested functions are independent scopes, pass their own loc_keys), \"<top-level>\" for module-level code, a list of them, a line range (e.g. \"31-45\", hits whose own line falls inside), or \"file\". "
    "For `param` in a scope with several functions, pass `function` (its loc_key) or the error lists the candidates. "
    'Only fall back to what="text" (literal substring, may span lines) for minified or non-expression text. Never guess a column.'
)

# Roles accepted by the `what` argument.
WHAT_ROLES = ("param", "callee", "def", "ref", "member", "text")

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
# How many candidate functions to list when a `param` query is ambiguous.
MAX_CANDIDATES = 10

_OPEN = "»"   # marks the first char of a match
_CLOSE = "«"  # marks the char right after the last char of a match

# Call-shaped expressions whose `function` field is the callee.
_CALL_TYPES = frozenset({"call_expression", "new_expression", "optional_call_expression"})
# Function types, shared with the callgraph universe. Imported lazily inside
# :func:`_func_types` to break the import cycle (functions.py and callgraph.py
# both import `byte_to_line_col` from here at module level).


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
    accepts.
    """
    idx = bisect.bisect_right(line_starts, byte) - 1
    if idx < 0:
        idx = 0
    line_start = line_starts[idx]
    return idx + 1, _count_chars(data, line_start, byte) + 1


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


def _match(
    data: bytes,
    line_starts: list[int],
    start_byte: int,
    end_byte: int,
    window_lo: int,
    window_hi: int,
) -> dict[str, Any]:
    """One hit in the shared shape: exclusive-end start/end plus context."""
    sl, sc = byte_to_line_col(start_byte, line_starts, data)
    el, ec = byte_to_line_col(end_byte, line_starts, data)
    return {
        "start": {"line": sl, "column": sc},
        "end": {"line": el, "column": ec},
        "context": render_context(data, line_starts, start_byte, end_byte, window_lo, window_hi),
    }


def _node_text(node, data: bytes) -> str:
    return data[node.start_byte : node.end_byte].decode("utf-8", "replace")


# --- AST plumbing ----------------------------------------------------------


def _func_types() -> frozenset[str]:
    """The function-node type set, from :mod:`tools.callgraph` (lazily)."""
    from .callgraph import _FUNC_TYPES

    return _FUNC_TYPES


def _walk(root, data: bytes) -> Iterator[tuple[Any, Any]]:
    """Yield ``(node, enclosing_function_node)`` for every node, preorder.

    ``enclosing_function_node`` is the nearest ancestor whose type is in
    ``_FUNC_TYPES`` (None at top level). Iterative DFS — safe on
    minified files; avoids ``.parent`` walks per node.
    """
    stack: list[list[Any]] = [[root, 0, None]]
    while stack:
        frame = stack[-1]
        node, next_child, enclosing = frame
        kids = node.children
        if next_child >= len(kids):
            stack.pop()
            continue
        child = kids[next_child]
        frame[1] += 1
        yield child, enclosing
        stack.append([child, 0, child if child.type in _func_types() else enclosing])


def _loc_key(node, data: bytes, line_starts: list[int]) -> str:
    sl, sc = byte_to_line_col(node.start_byte, line_starts, data)
    return f"{sl}:{sc}"


def _param_nodes(func_node) -> list[tuple[set[str], Any]]:
    """Parameter declarations of one function node as ``(names, node)`` pairs.

    A plain ``identifier`` parameter answers for itself; a defaulted /
    destructuring / rest parameter answers for every identifier named inside
    it (the returned node is the identifier for ``x = 1``, the whole pattern
    for ``{a}`` — the smallest thing that declares the name).
    """
    params = func_node.child_by_field_name("parameters")
    if params is not None:
        top = list(params.children)
    else:
        # Paren-less arrow: the identifier(s) before "=>". The body identifiers
        # after "=>" must not be mistaken for parameters.
        top = []
        for child in func_node.children:
            if child.type == "=>":
                break
            if child.type == "identifier":
                top.append(child)
    out: list[tuple[set[str], Any]] = []
    for node in top:
        if node.type == "identifier":
            out.append(({node.text.decode()}, node))
        elif node.type == "assignment_pattern":
            left = node.child_by_field_name("left")
            if left is not None:
                out.append(({left.text.decode()}, left))
        else:
            names = {
                d.text.decode()
                for d, _enc in _walk(node, b"")
                if d.type in ("identifier", "shorthand_property_identifier_pattern")
            }
            out.append((names, node))
    return out


# --- role queries ----------------------------------------------------------
#
# Each query returns ``list[dict]`` in the shared hit shape (start/end/
# context) plus role-specific extras, filtered to hits whose start line falls
# inside ``[from_line, to_line]``.


def locate_text(
    path: Path,
    from_line: int | None,
    to_line: int | None,
    needle: bytes,
    max_matches: int = DEFAULT_MAX_MATCHES,
    point_selects: Any = None,
) -> list[dict[str, Any]]:
    """Find every occurrence of ``needle`` whose *start* byte falls in
    ``[from_line, to_line]`` (inclusive) and, when ``point_selects`` is
    given, whose start point it accepts (the ownership filter for loc_key
    scopes — those scan the whole file and filter hits afterwards). The match
    itself may run past ``to_line`` (cross-line needles are the whole point).
    Returns a list of ``{"start": {...}, "end": {...}, "context": str}`` with
    EXCLUSIVE end.

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
        if point_selects is not None:
            sl, sc = byte_to_line_col(hit, line_starts, data)
            if not point_selects(sl, sc):
                pos = hit + max(1, len(needle))
                continue
        out.append(_match(data, line_starts, hit, end_byte, from_line, to_line))
        pos = hit + max(1, len(needle))
    return out


def locate_def(
    data: bytes,
    from_line: int,
    to_line: int,
    name: str,
    max_matches: int,
    point_selects: Any = None,
) -> list[dict[str, Any]]:
    """Whole-function ranges of every function bound to ``name``.

    The hit range IS the function node — ready to paste as a closure
    annotation's ``target function``.
    """
    from .functions import _function_name

    def extract(node, src):
        if node.type in _func_types() and _function_name(node, src) == name:
            return node, {}
        return None

    out: list[dict[str, Any]] = []
    for _node, hit in _role_hits(
        data, from_line, to_line, extract, max_matches, point_selects
    ):
        hit["role"] = "def"
        out.append(hit)
    return out


def _ref_role(node) -> str:
    """Classify an identifier occurrence: decl / write / call / read.

    Field lookups return fresh Node wrappers per call (identity is unstable),
    so membership is tested by ``==`` (same underlying node) or by byte range.
    """
    p = node.parent
    if p is None:
        return "read"
    if p.type in _CALL_TYPES and p.child_by_field_name("function") == node:
        return "call"
    if p.type == "assignment_expression" and p.child_by_field_name("left") == node:
        return "write"
    if p.type == "update_expression":
        return "write"
    if p.type == "variable_declarator" and p.child_by_field_name("name") == node:
        return "decl"
    if p.type == "formal_parameters":
        return "decl"  # a parameter identifier
    if p.type in ("assignment_pattern", "object_pattern", "array_pattern", "rest_pattern"):
        # inside a parameter pattern — only count it when under formal_parameters
        anc = p
        while anc is not None and anc.type not in _func_types():
            if anc.type == "formal_parameters":
                return "decl"
            anc = anc.parent
    if (
        p.type in ("function_declaration", "generator_function_declaration", "method_definition")
        and p.child_by_field_name("name") == node
    ):
        return "decl"
    return "read"


def _role_hits(
    data: bytes,
    from_line: int,
    to_line: int,
    extract,
    max_matches: int,
    point_selects: Any = None,
) -> list[tuple[Any, dict[str, Any]]]:
    """Shared DFS for the occurrence roles.

    ``extract(node, data)`` maps a visited node to ``None`` (skip) or
    ``(hit_node, extra)`` where ``hit_node`` supplies the primary range and
    ``extra`` maps label -> node for secondary ranges. This keeps the
    ``max_matches`` cap on FINAL hits (a broad visitor over e.g. every call
    expression must not flood contexts with pre-filter matches), and lets a
    role's primary range differ from the visited node (callee: the identifier,
    not the call). A hit is kept when its start line is inside
    ``[from_line, to_line]``, or — when ``point_selects`` is given (the
    ownership filter for loc_key scopes, which scan the whole file) — when
    it accepts the hit's start point.
    """
    line_starts = build_line_starts(data)
    from .functions import _get_parser

    # The window already clamps, but direct calls may overshoot: clamp so a
    # hit on the last line renders its context without running off the table.
    from_line = max(1, from_line)
    to_line = min(to_line, len(line_starts))
    root = _get_parser().parse(data).root_node
    out: list[tuple[Any, dict[str, Any]]] = []
    for node, enclosing in _walk(root, data):
        got = extract(node, data)
        if got is None:
            continue
        hit_node, extra_nodes = got
        line, col = byte_to_line_col(hit_node.start_byte, line_starts, data)
        if point_selects is not None:
            if not point_selects(line, col):
                continue
        elif not (from_line <= line <= to_line):
            continue
        hit = _match(
            data, line_starts, hit_node.start_byte, hit_node.end_byte, from_line, to_line
        )
        hit["enclosing"] = (
            _loc_key(enclosing, data, line_starts) if enclosing is not None else None
        )
        for label, n in extra_nodes.items():
            hit[label] = _match(data, line_starts, n.start_byte, n.end_byte, from_line, to_line)
        out.append((hit_node, hit))
        if 0 < max_matches <= len(out):
            break
    return out


def locate_callee(
    data: bytes,
    from_line: int,
    to_line: int,
    name: str,
    max_matches: int,
    point_selects: Any = None,
) -> list[dict[str, Any]]:
    """The callee identifier (without ``(``) at every call site of ``name``.

    Covers ``name(...)`` and ``obj.name(...)`` (receiver reported separately),
    including ``new name(...)``. Each hit also carries ``call`` — the full
    call/new expression range — and, for method calls, ``receiver``.
    """

    def extract(node, src):
        if node.type not in _CALL_TYPES:
            return None
        # new_expression names its callee `constructor`; call shapes use `function`.
        fn = node.child_by_field_name("function") or node.child_by_field_name("constructor")
        if fn is None:
            return None
        if fn.type == "identifier":
            if _node_text(fn, src) != name:
                return None
            return fn, {"call": node}
        if fn.type == "member_expression":
            prop = fn.child_by_field_name("property")
            if (
                prop is None
                or prop.type != "property_identifier"
                or _node_text(prop, src) != name
            ):
                return None
            return prop, {"call": node, "receiver": fn.child_by_field_name("object")}
        return None

    out: list[dict[str, Any]] = []
    for _node, hit in _role_hits(
        data, from_line, to_line, extract, max_matches, point_selects
    ):
        hit["role"] = "callee"
        out.append(hit)
    return out


def locate_ref(
    data: bytes,
    from_line: int,
    to_line: int,
    name: str,
    max_matches: int,
    point_selects: Any = None,
) -> list[dict[str, Any]]:
    """Every identifier occurrence named ``name`` (read/write/call/decl).

    Member property positions (``obj.name``) are NOT references of the binding
    and are excluded — use ``what="member"`` for those. Each hit carries its
    ``role`` and the ``enclosing`` function loc_key (None at top level).
    """

    def extract(node, src):
        if node.type == "identifier" and _node_text(node, src) == name:
            return node, {}
        return None

    out = []
    for node, hit in _role_hits(
        data, from_line, to_line, extract, max_matches, point_selects
    ):
        hit["role"] = _ref_role(node)
        out.append(hit)
    return out


def locate_member(
    data: bytes,
    from_line: int,
    to_line: int,
    name: str,
    max_matches: int,
    point_selects: Any = None,
) -> list[dict[str, Any]]:
    """Every ``obj.prop`` whose property is ``name``: primary range is the
    property, ``receiver`` the object expression (ready for a shape guard on
    the receiver). Computed ``obj[name]`` and quoted ``obj["name"]`` are not
    matched — the property must be written as a plain identifier.
    """

    def extract(node, src):
        if node.type != "member_expression":
            return None
        prop = node.child_by_field_name("property")
        if prop is None or prop.type != "property_identifier" or _node_text(prop, src) != name:
            return None
        return prop, {"receiver": node.child_by_field_name("object")}

    out: list[dict[str, Any]] = []
    for _node, hit in _role_hits(
        data, from_line, to_line, extract, max_matches, point_selects
    ):
        hit["role"] = "member"
        out.append(hit)
    return out


def locate_param(
    data: bytes, name: str, function_key: str | None, scope: Any
) -> tuple[list[dict[str, Any]], str | None]:
    """Parameter declaration of ``name`` in one function.

    Returns ``(hits, error)`` — exactly one is non-empty. ``function_key``
    (a function loc_key) disambiguates a multi-function scope; if absent and
    the scope covers several functions, the error lists the candidates.
    """
    from .functions import extract_functions

    funcs = extract_functions(data)
    by_key = {fn["loc_key"]: fn for fn in funcs}

    if function_key is not None:
        if function_key not in by_key:
            return [], f"unknown function loc_key {function_key!r}"
        target = by_key[function_key]
    else:
        # scope already a single function loc_key?
        if isinstance(scope, str) and scope in by_key:
            target = by_key[scope]
        else:
            from .functions import resolve_scope

            selection = resolve_scope(scope, data)
            if selection.keys is not None:
                # Ownership scope: the candidate functions ARE the keys'.
                inside = [fn for fn in funcs if fn["loc_key"] in selection.keys]
            else:
                from_line, to_line = selection.window or (
                    1,
                    len(build_line_starts(data)),
                )
                inside = [
                    fn for fn in funcs
                    if from_line <= fn["start_line"] and fn["end_line"] <= to_line
                ]
            if len(inside) == 1:
                target = inside[0]
            elif not inside:
                return [], f"no function in the scope has a parameter {name!r}"
            else:
                cands = ", ".join(
                    f"{fn['name']} ({fn['loc_key']})" for fn in inside[:MAX_CANDIDATES]
                )
                more = "" if len(inside) <= MAX_CANDIDATES else " …"
                return [], (
                    f"scope has {len(inside)} functions; pass 'function' (loc_key) to pick one: {cands}{more}"
                )

    line_starts = build_line_starts(data)
    # Re-find the function NODE (extract_functions returns records only).
    from .functions import _get_parser

    root = _get_parser().parse(data).root_node
    target_node = None
    for node, _enc in _walk(root, data):
        if node.type in _func_types() and _loc_key(node, data, line_starts) == target["loc_key"]:
            target_node = node
            break
    if target_node is None:  # unreachable unless loc_key math diverges
        return [], "internal: function node not found"

    params = _param_nodes(target_node)
    for names, pnode in params:
        if name in names:
            hit = _match(
                data, line_starts, pnode.start_byte, pnode.end_byte,
                target["start_line"], target["end_line"],
            )
            hit["role"] = "param"
            hit["enclosing"] = target["loc_key"]
            return [hit], None
    declared = ", ".join(sorted({n for names, _ in params for n in names})) or "(none)"
    return [], f"function {target['name']} ({target['loc_key']}) has no parameter {name!r}; declared: {declared}"


# --- MCP tool --------------------------------------------------------------


def build_locate_tool(source: Path):
    """Build the ``locate`` SDK MCP tool, bound to the single source ``source``.

    One annotator run targets exactly one JS file, so the agent never picks a
    file — the tool always reads ``source``. Exposed separately from
    :func:`make_locate_server` so tests can invoke the handler directly.
    """
    source_resolved = source.resolve()

    @tool(
        "locate",
        "Get exact annotation target ranges by AST syntax role in the JS file "
        "being annotated — no grep, no hand-counted columns. what='param' "
        "returns a parameter's declaration range (pass function=<loc_key> when "
        "the scope holds several functions); what='callee' returns the callee "
        "identifier (without '(') at every call site of name, plus the full "
        "call-expression range (and the receiver for obj.name() calls); "
        "what='def' returns the function definition range — use it directly as "
        "a closure annotation's 'target function'; what='ref' returns every "
        "read/write/call/decl of an identifier with its enclosing function "
        "loc_key; what='member' returns each obj.prop property range with its "
        "receiver expression range; what='text' is the literal-substring "
        "fallback (may span lines). Ranges are 1-based line/column (column "
        "counts Unicode chars), EXCLUSIVE end column, cross-line OK — copy "
        "straight into 'target range'. The scope is a function loc_key (e.g. "
        "\"31:1\" — that function's DIRECT statements only: nested functions "
        "are independent scopes, pass their own loc_keys), \"<top-level>\" "
        "for module-level code, a list of them, a line range (e.g. "
        "\"31-45\", hits whose own line falls inside), or \"file\"/omitted "
        "for the whole file.",
        {
            "type": "object",
            "properties": {
                "what": {
                    "type": "string",
                    "enum": list(WHAT_ROLES),
                    "description": "syntax role: param | callee | def | ref | member | text (fallback)",
                },
                "name": {"type": "string", "description": "identifier (or, for what='text', literal substring; NOT regex)"},
                "scope": {
                    "type": ["string", "array"],
                    "description": "\"file\" (default), ONE function loc_key like \"31:1\" (that function's DIRECT statements only — nested functions are independent scopes, pass their own loc_keys), \"<top-level>\" for module-level code, a list of loc_keys like [\"31:1\", \"35:1\"], or an inclusive line range like \"31-45\" (hits whose own line falls inside)",
                    "items": {"type": "string"},
                },
                "function": {
                    "type": "string",
                    "description": "for what='param': the owning function's loc_key when the scope holds several functions",
                },
                "max_matches": {"type": "integer", "description": "cap on results; 0 = unlimited (default 64)"},
            },
            "required": ["what", "name"],
        },
    )
    async def locate(args: dict[str, Any]) -> dict[str, Any]:
        what = args.get("what")
        if what not in WHAT_ROLES:
            return _err(f"invalid 'what' {what!r}; expected one of {', '.join(WHAT_ROLES)}")
        name = args.get("name")
        if not isinstance(name, str) or name == "":
            return _err("missing or empty 'name'")

        try:
            data = source_resolved.read_bytes()
        except OSError:
            return _err(f"could not read source file: {source_resolved}")

        scope = args.get("scope", "file")
        try:
            from .functions import resolve_scope

            selection = resolve_scope(scope, data)
        except ValueError:
            return _err(f"unknown or malformed scope {scope!r}")

        # Search/context window: a line-range scope keeps its byte window and
        # the window check filters hits; ownership scopes (loc_keys /
        # "<top-level>") scan the whole file and filter hits by the selection.
        num_lines = len(build_line_starts(data))
        from_line, to_line = selection.window or (1, num_lines)
        point_selects = None if selection.window is not None else selection.owns

        max_matches = int(args.get("max_matches", DEFAULT_MAX_MATCHES))

        try:
            if what == "text":
                matches = locate_text(
                    source_resolved, from_line, to_line, name.encode("utf-8"),
                    max_matches, point_selects,
                )
                if not matches:
                    return {"content": [{"type": "text", "text": f"no match for {name!r} in lines {from_line}-{to_line}"}]}
            elif what == "param":
                matches, err = locate_param(data, name, args.get("function"), scope)
                if err is not None:
                    return _err(err)
            elif what == "def":
                matches = locate_def(data, from_line, to_line, name, max_matches, point_selects)
            elif what == "callee":
                matches = locate_callee(data, from_line, to_line, name, max_matches, point_selects)
            elif what == "ref":
                matches = locate_ref(data, from_line, to_line, name, max_matches, point_selects)
            else:  # member
                matches = locate_member(data, from_line, to_line, name, max_matches, point_selects)
        except ValueError as exc:
            return _err(str(exc))

        if not matches:
            return {"content": [{"type": "text", "text": f"no {what} hit for {name!r} in lines {from_line}-{to_line}"}]}

        def _fmt_range(r: dict[str, Any]) -> str:
            """4-seg colon form, identical to annotation target_range strings."""
            return f"{r['start']['line']}:{r['start']['column']}:{r['end']['line']}:{r['end']['column']}"

        blocks = []
        for m in matches:
            head = _fmt_range(m)
            tags = []
            if "role" in m:
                tags.append(f"role={m['role']}")
            if m.get("enclosing"):
                tags.append(f"enclosing={m['enclosing']}")
            if tags:
                head += "  " + " ".join(tags)
            extra = []
            for key in ("receiver", "call"):
                r = m.get(key)
                if r:
                    extra.append(f"{key}: {_fmt_range(r)}")
            block = head + "\n" + m["context"]
            if extra:
                block += "\n" + " | ".join(extra)
            blocks.append(block)
        text = "\n\n".join(blocks) + f"\n({len(matches)} match(es))"
        return {"content": [{"type": "text", "text": text}]}

    return locate


def make_locate_server(source: Path):
    """Build an in-process MCP server exposing ``locate``, bound to ``source``."""
    return create_sdk_mcp_server(name="source-locate", tools=[build_locate_tool(source)])
