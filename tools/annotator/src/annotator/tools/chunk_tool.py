"""In-process MCP ``chunk`` tool: function universe + fixed-line-window
chunking for the five-stage annotation protocol (phase 1).

It splits the single JS source into chunks along **function boundaries**
(function bodies are never cut). Each chunk is the *produce-scope* of one
map/reduce subagent: a subagent may READ the whole file, but every
comment/annotation/skip it produces must have a ``loc_key`` falling inside its
own chunk (one producer per loc_key → no write conflicts, no double coverage).

Three tools, bound to the single ``source`` and writing sidecars under
``workdir/.chunks/``:

- ``chunk_index()`` — parse once, return the function universe + chunk plan,
  persist ``.chunks/index.json``.
- ``read_chunk(chunk_id)`` — return one chunk's source with 1-based line numbers.
- ``record_skip(loc_key, category, reason)`` — append an explicit "does not
  fit" decision for a function to its chunk's ``.chunks/chunk_NNN.skips.json``.

Function boundaries come from tree-sitter-javascript (already a dependency).
Byte offsets — never ``start_point``/``end_point`` — are turned into
``loc_key`` via :func:`locate_tool.byte_to_line_col`; the ``.start_point``
binding segfaults on some files (e.g. box2d.js — see ``fold_tool``).
``loc_key`` is ``startLine:startCol:endLine:endCol`` (1-based, exclusive end),
the unified join key shared with annotation/comment/skip.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import tree_sitter_javascript as tjs
from claude_agent_sdk import create_sdk_mcp_server, tool
from tree_sitter import Language, Parser

from .callgraph import _FUNC_TYPES  # reuse the function-type set
from .locate_tool import byte_to_line_col
from .utils import _err, atomic_write_json, build_line_starts

CHUNKS_SUBDIR = ".chunks"
INDEX_FILE = "index.json"
DEFAULT_LINES_PER_CHUNK = 500
READ_CHUNK_MAX_CHARS = 32_768

# Explicit "does not fit" categories. `unanalyzable-dynamic` covers the
# pure-static ceiling (dynamic dispatch / eval / host-bound objects).
SKIP_CATEGORIES = frozenset(
    {
        "no-shape-info",
        "native-builtin",
        "trivial-getter",
        "trivial-setter",
        "no-hot-path",
        "unanalyzable-dynamic",
        "already-covered",
        "duplicate",
        "other",
    }
)

_parser_singleton: Parser | None = None


def _get_parser() -> Parser:
    global _parser_singleton
    if _parser_singleton is None:
        _parser_singleton = Parser(Language(tjs.language()))
    return _parser_singleton


def _split_lines(data: bytes) -> list[str]:
    """Split aligned with :func:`utils.build_line_starts` (no phantom last line)."""
    text = data.decode("utf-8", "replace")
    if not text:
        return []
    lines = text.split("\n")
    if len(lines) > 1 and lines[-1] == "" and text.endswith("\n"):
        lines.pop()
    return lines


def _node_text(node, data: bytes) -> str:
    """Node text via byte slice (does not rely on the ``.text`` attribute)."""
    return data[node.start_byte:node.end_byte].decode("utf-8", "replace")


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


def extract_functions(data: bytes) -> list[dict[str, Any]]:
    """All function nodes, with their nearest enclosing function when present.

    Iterative preorder DFS is safe on large/minified files. ``parent_loc_key``
    lets chunk planning keep an outer function and every nested function in one
    producer scope instead of splitting overlapping source ranges across chunks.
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
            loc_key = f"{sl}:{sc}:{el}:{ec}"
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


def _close_chunk(
    funcs: list[dict[str, Any]], lines_per_chunk: int, root_count: int
) -> dict[str, Any]:
    from_line = min(f["start_line"] for f in funcs)
    to_line = max(f["end_line"] for f in funcs)
    span = to_line - from_line + 1
    return {
        "from_line": from_line,
        "to_line": to_line,
        "line_span": span,
        "function_count": len(funcs),
        "function_loc_keys": [f["loc_key"] for f in funcs],
        # A root function subtree is the indivisible planning unit. It may
        # contain nested functions, yet must still be marked oversize when it
        # alone exceeds the target window.
        "oversize": span > lines_per_chunk and root_count == 1,
    }


def plan_chunks(
    funcs: list[dict[str, Any]], lines_per_chunk: int = DEFAULT_LINES_PER_CHUNK
) -> list[dict[str, Any]]:
    """Split only between top-level function subtrees.

    A root function and all of its nested descendants share one producer chunk.
    This avoids overlapping chunk ranges, while preserving every function in the
    universe for coverage and explicit skips.
    """
    by_loc = {f["loc_key"]: f for f in funcs}

    def root_of(func: dict[str, Any]) -> str:
        root = func
        seen: set[str] = set()
        while isinstance(root.get("parent_loc_key"), str):
            parent_key = root["parent_loc_key"]
            if parent_key in seen or parent_key not in by_loc:
                break
            seen.add(parent_key)
            root = by_loc[parent_key]
        return root["loc_key"]

    roots = [f for f in funcs if f.get("parent_loc_key") is None]
    groups: dict[str, list[dict[str, Any]]] = {root["loc_key"]: [] for root in roots}
    for func in funcs:
        groups.setdefault(root_of(func), []).append(func)
    units = sorted(
        ((by_loc[key], members) for key, members in groups.items()),
        key=lambda item: (item[0]["start_line"], item[0]["start_col"]),
    )

    chunks: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []
    cur_start: int | None = None
    root_count = 0
    for root, members in units:
        if cur_start is None:
            cur = list(members)
            cur_start = root["start_line"]
            root_count = 1
            continue
        if root["start_line"] - cur_start >= lines_per_chunk:
            chunks.append(_close_chunk(cur, lines_per_chunk, root_count))
            cur = list(members)
            cur_start = root["start_line"]
            root_count = 1
        else:
            cur.extend(members)
            root_count += 1
    if cur:
        chunks.append(_close_chunk(cur, lines_per_chunk, root_count))
    for i, chunk in enumerate(chunks, 1):
        chunk["id"] = f"chunk_{i:03d}"
    return chunks


def build_index(
    source: Path, workdir: Path, lines_per_chunk: int = DEFAULT_LINES_PER_CHUNK
) -> dict[str, Any]:
    """Parse the source, plan chunks, tag each function with its chunk_id, and
    persist ``workdir/.chunks/index.json``. Returns the index dict."""
    data = source.read_bytes()
    funcs = extract_functions(data)
    chunks = plan_chunks(funcs, lines_per_chunk)
    by_loc = {f["loc_key"]: f for f in funcs}
    for ch in chunks:
        for lk in ch["function_loc_keys"]:
            f = by_loc.get(lk)
            if f is not None:
                f["chunk_id"] = ch["id"]
    index = {
        "source": source.name,
        "num_lines": len(_split_lines(data)),
        "lines_per_chunk": lines_per_chunk,
        "function_universe": funcs,
        "chunks": chunks,
    }
    atomic_write_json(workdir / CHUNKS_SUBDIR / INDEX_FILE, index)
    return index


def load_index(source: Path, workdir: Path) -> dict[str, Any]:
    """Load the chunk index. Reads ``workdir/.chunks/index.json`` if present
    (written by chunk_index, possibly with a non-default lines_per_chunk); else
    builds one with the default window."""
    idx_path = workdir / CHUNKS_SUBDIR / INDEX_FILE
    if idx_path.exists():
        try:
            return json.loads(idx_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return build_index(source, workdir)


def _skips_path(workdir: Path, chunk_id: str) -> Path:
    return workdir / CHUNKS_SUBDIR / f"{chunk_id}.skips.json"


def _read_skips(path: Path) -> list[dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _write_skips(path: Path, skips: list[dict[str, Any]]) -> None:
    atomic_write_json(path, skips)


def build_chunk_tools(source: Path, workdir: Path) -> list:
    """Build ``chunk_index`` / ``read_chunk`` / ``record_skip``, bound to the
    single source ``source`` and the sidecar dir under ``workdir``. Exposed for
    tests to drive handlers directly."""
    source_resolved = source.resolve()
    workdir_resolved = workdir.resolve()

    @tool(
        "chunk_index",
        "Split the file into chunks along function boundaries (function "
        "bodies are never cut) and return the function universe + chunk plan. "
        "Each function has a `loc_key` (startLine:startCol:endLine:endCol, "
        "1-based, exclusive end) — the unified key for chunk/annotation/"
        "comment/skip. Call this FIRST in the five-stage protocol to plan"
        "subagent work. Persisted to .chunks/index.json.",
        {
            "type": "object",
            "properties": {
                "lines_per_chunk": {
                    "type": "integer",
                    "description": f"target lines per chunk (default {DEFAULT_LINES_PER_CHUNK}); "
                    "split points still align to function boundaries",
                },
            },
        },
    )
    async def chunk_index(args: dict[str, Any]) -> dict[str, Any]:
        lpc_raw = args.get("lines_per_chunk")
        try:
            lpc = int(lpc_raw) if lpc_raw is not None else DEFAULT_LINES_PER_CHUNK
        except (TypeError, ValueError):
            return _err("lines_per_chunk must be an integer")
        if lpc < 1:
            return _err("lines_per_chunk must be >= 1")
        try:
            index = build_index(source_resolved, workdir_resolved, lpc)
        except FileNotFoundError:
            return _err(f"source file not found: {source_resolved}")
        except OSError as exc:
            return _err(f"cannot read {source_resolved!r}: {exc}")

        chunks = index["chunks"]
        universe = index["function_universe"]
        out: list[str] = [
            f"{len(universe)} functions, {len(chunks)} chunk(s) "
            f"(~{index['lines_per_chunk']} lines/chunk, file {index['num_lines']} lines)",
            "Chunks:",
        ]
        for c in chunks:
            flag = " [oversize]" if c["oversize"] else ""
            out.append(
                f"  {c['id']}  lines {c['from_line']}-{c['to_line']} "
                f"({c['line_span']} lines, {c['function_count']} fn){flag}"
            )
        out.append(
            "Use read_chunk(chunk_id) to read a chunk; coverage() to see "
            "uncovered functions; record_skip to mark a function 'does not fit'."
        )
        return {"content": [{"type": "text", "text": "\n".join(out)}]}

    @tool(
        "read_chunk",
        "Return one chunk's source with 1-based line numbers (the produce-"
        "scope for a map/reduce subagent). You may still READ the WHOLE file "
        "with Read/fold/locate — this only scopes where your PRODUCE loc_keys "
        "must land. Copy chunk_id from chunk_index output.",
        {
            "type": "object",
            "properties": {
                "chunk_id": {
                    "type": "string",
                    "description": "chunk id from chunk_index (e.g. chunk_001)",
                },
            },
            "required": ["chunk_id"],
        },
    )
    async def read_chunk(args: dict[str, Any]) -> dict[str, Any]:
        chunk_id = args.get("chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id:
            return _err("missing 'chunk_id'")
        try:
            data = source_resolved.read_bytes()
        except FileNotFoundError:
            return _err(f"source file not found: {source_resolved}")
        except OSError as exc:
            return _err(f"cannot read {source_resolved!r}: {exc}")
        index = load_index(source_resolved, workdir_resolved)
        chunk = next((c for c in index["chunks"] if c["id"] == chunk_id), None)
        if chunk is None:
            return _err(f"unknown chunk_id {chunk_id!r}; call chunk_index first")
        lines = _split_lines(data)
        n = len(lines)
        fl = max(1, chunk["from_line"])
        tl = min(n, chunk["to_line"])
        w = len(str(n)) if n else 1
        body = [f"{i:>{w}}│ {lines[i - 1]}" for i in range(fl, tl + 1)]
        text = (
            f"{chunk_id}  lines {fl}-{tl}  ({chunk['function_count']} fn)\n"
            + "\n".join(body)
        )
        if len(text) > READ_CHUNK_MAX_CHARS:
            text = (
                text[:READ_CHUNK_MAX_CHARS]
                + f"\n   // … truncated at {READ_CHUNK_MAX_CHARS} chars …"
            )
        return {"content": [{"type": "text", "text": text}]}

    @tool(
        "record_skip",
        "Record an explicit 'does not fit' decision for a function, so it "
        "counts as COVERED (annotated OR skipped) in coverage. Use this "
        "instead of silently leaving a function unannotated. `reason` MUST say "
        "why static analysis cannot pin this function down. Written to "
        ".chunks/chunk_NNN.skips.json (never into the final annotation file).",
        {
            "type": "object",
            "properties": {
                "loc_key": {
                    "type": "string",
                    "description": "function loc_key from chunk_index (startLine:startCol:endLine:endCol)",
                },
                "category": {
                    "type": "string",
                    "description": "one of: " + ", ".join(sorted(SKIP_CATEGORIES)),
                },
                "reason": {
                    "type": "string",
                    "description": "1-2 sentences why this function cannot be annotated",
                },
            },
            "required": ["loc_key", "category", "reason"],
        },
    )
    async def record_skip(args: dict[str, Any]) -> dict[str, Any]:
        loc_key = args.get("loc_key")
        category = args.get("category")
        reason = args.get("reason")
        if not isinstance(loc_key, str) or not loc_key:
            return _err("missing 'loc_key'")
        if not isinstance(reason, str) or not reason.strip():
            return _err("missing 'reason' (say why static analysis cannot pin this function)")
        if category not in SKIP_CATEGORIES:
            return _err(f"category must be one of: {sorted(SKIP_CATEGORIES)}")
        index = load_index(source_resolved, workdir_resolved)
        func = next(
            (f for f in index["function_universe"] if f["loc_key"] == loc_key), None
        )
        if func is None:
            return _err(f"loc_key {loc_key!r} not in function universe; call chunk_index")
        chunk_id = func.get("chunk_id")
        if not chunk_id:
            return _err(f"loc_key {loc_key!r} has no chunk_id; rebuild index")
        path = _skips_path(workdir_resolved, chunk_id)
        skips = _read_skips(path)
        # Idempotent re-skip: replace any existing entry for the same loc_key.
        skips = [s for s in skips if s.get("loc_key") != loc_key]
        skips.append(
            {"loc_key": loc_key, "category": category, "reason": reason, "chunk_id": chunk_id}
        )
        _write_skips(path, skips)
        text = (
            f"recorded skip {loc_key} ({category}) in {chunk_id}. "
            f"{len(skips)} skip(s) in this chunk."
        )
        return {"content": [{"type": "text", "text": text}]}

    return [chunk_index, read_chunk, record_skip]


def make_chunk_server(source: Path, workdir: Path):
    """Build the in-process MCP server exposing the chunk tools."""
    return create_sdk_mcp_server(name="chunk", tools=build_chunk_tools(source, workdir))
