"""In-process MCP ``comments`` tool: staged, line-range-anchored notes.

The five-stage annotation workflow uses one shared ``.chunks/comments.json`` as
its agent-to-agent communication channel.  Every mutation takes an advisory
cross-process lock and atomically publishes the complete sidecar, so parallel
chunk workers can safely append notes.  A note carries its workflow ``phase``
and, when it is produced by a chunk worker, its ``chunk_id`` as well as the
source line range it describes.

All writers must use these MCP tools; direct sidecar writes are unsupported.
"""

from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from .chunk_tool import load_index
from .utils import _err, atomic_write_json

CHUNKS_SUBDIR = ".chunks"
COMMENTS_FILE = "comments.json"
PHASES = ("phase1", "phase2", "phase3", "phase4", "phase5")
_CHUNK_PHASES = frozenset(("phase1", "phase2", "phase4"))


def _comments_path(workdir: Path) -> Path:
    return workdir / CHUNKS_SUBDIR / COMMENTS_FILE


def _comments_lock_path(workdir: Path) -> Path:
    return _comments_path(workdir).with_suffix(".lock")


@contextmanager
def _locked_comments(workdir: Path):
    """Serialize every comments read-modify-write across chunk subagents."""
    lock_path = _comments_lock_path(workdir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_all(workdir: Path) -> list[dict[str, Any]]:
    path = _comments_path(workdir)
    if not path.exists():
        return []
    items = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError(f"comments sidecar {path} is not an array of objects")
    return items


def _write_all(workdir: Path, items: list[dict[str, Any]]) -> None:
    atomic_write_json(_comments_path(workdir), items)


def _next_id(items: list[dict[str, Any]]) -> int:
    return max((i.get("id", 0) for i in items), default=0) + 1


def _intersects(cf: int, ct: int, qf: int, qt: int) -> bool:
    return cf <= qt and ct >= qf


def _first_line(comment: str) -> str:
    first = next((ln.strip() for ln in comment.splitlines() if ln.strip()), "")
    return first[:80] + "..." if len(first) > 80 else first


def _validate_chunk_owner(
    source: Path | None, workdir: Path, chunk_id: str, from_line: int, to_line: int
) -> None:
    if source is None:
        raise ValueError("chunk ownership validation requires the bound source")
    index = load_index(source, workdir)
    chunk = next((item for item in index["chunks"] if item.get("id") == chunk_id), None)
    if chunk is None:
        raise ValueError(f"unknown chunk_id {chunk_id!r}; call chunk_index first")
    if from_line < chunk["from_line"] or to_line > chunk["to_line"]:
        raise ValueError(
            f"comment lines {from_line}-{to_line} fall outside {chunk_id} "
            f"lines {chunk['from_line']}-{chunk['to_line']}"
        )


def _format_label(item: dict[str, Any]) -> str:
    chunk_id = item.get("chunk_id")
    chunk_text = f" {chunk_id}" if isinstance(chunk_id, str) else ""
    return f"#{item['id']} {item.get('phase', 'legacy')}{chunk_text} lines {item['from_line']}-{item['to_line']}"


def build_comment_tools(workdir: Path, source: Path | None = None) -> list:
    """Build staged comment tools bound to one attempt sidecar and source.

    ``source`` is optional only for direct legacy-style unit testing.  The MCP
    server always provides it, which enables chunk ownership validation.
    """
    workdir_resolved = workdir.resolve()
    source_resolved = source.resolve() if source is not None else None

    @tool(
        "write_comment",
        "Record one five-stage workflow note anchored to a 1-based inclusive source "
        "line range. phase1/phase2/phase4 require the producing chunk_id and the "
        "range must belong to that chunk; phase3/phase5 main-agent decisions may "
        "omit chunk_id. Writers are serialized and the shared sidecar is atomically "
        "published.",
        {
            "type": "object",
            "properties": {
                "phase": {"type": "string", "enum": list(PHASES)},
                "chunk_id": {
                    "type": "string",
                    "description": "chunk_index id for chunk-produced notes; omit for cross-chunk decisions",
                },
                "from_line": {"type": "integer", "description": "1-based start line (inclusive)"},
                "to_line": {"type": "integer", "description": "1-based end line (inclusive)"},
                "comment": {"type": "string", "description": "the staged understanding or review note"},
            },
            "required": ["phase", "from_line", "to_line", "comment"],
        },
    )
    async def write_comment(args: dict[str, Any]) -> dict[str, Any]:
        phase = args.get("phase")
        if phase not in PHASES:
            return _err(f"phase must be one of {list(PHASES)}")
        chunk_id = args.get("chunk_id")
        if chunk_id is not None and (not isinstance(chunk_id, str) or not chunk_id):
            return _err("chunk_id must be a non-empty string when provided")
        if phase in _CHUNK_PHASES and not isinstance(chunk_id, str):
            return _err(f"{phase} comments require chunk_id")
        try:
            fl = int(args["from_line"])
            tl = int(args["to_line"])
        except (KeyError, TypeError, ValueError):
            return _err("from_line and to_line must be integers")
        comment = args.get("comment")
        if not isinstance(comment, str) or not comment.strip():
            return _err("missing 'comment' (the staged note)")
        if fl < 1 or tl < fl:
            return _err(f"invalid line range [{fl},{tl}]")
        try:
            if isinstance(chunk_id, str):
                _validate_chunk_owner(source_resolved, workdir_resolved, chunk_id, fl, tl)
            with _locked_comments(workdir_resolved):
                items = _read_all(workdir_resolved)
                cid = _next_id(items)
                item = {
                    "id": cid,
                    "phase": phase,
                    "from_line": fl,
                    "to_line": tl,
                    "comment": comment,
                }
                if isinstance(chunk_id, str):
                    item["chunk_id"] = chunk_id
                items.append(item)
                _write_all(workdir_resolved, items)
        except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
            return _err(f"could not write comment: {exc}")
        return {"content": [{"type": "text", "text": f"wrote comment #{cid} {phase} lines {fl}-{tl}."}]}

    @tool(
        "list_comments",
        "Read staged workflow notes. Filter by phase, chunk_id, and/or a 1-based "
        "inclusive line window. With a line window, return full note text; otherwise "
        "return summaries. Omitting filters lists all prior notes, allowing a phase to "
        "consume every completed earlier phase.",
        {
            "type": "object",
            "properties": {
                "phase": {"type": "string", "enum": list(PHASES)},
                "chunk_id": {"type": "string", "description": "exact producing chunk id"},
                "from_line": {"type": "integer", "description": "1-based start line (inclusive)"},
                "to_line": {"type": "integer", "description": "1-based end line (inclusive)"},
            },
        },
    )
    async def list_comments(args: dict[str, Any]) -> dict[str, Any]:
        phase = args.get("phase")
        if phase is not None and phase not in PHASES:
            return _err(f"phase must be one of {list(PHASES)}")
        chunk_id = args.get("chunk_id")
        if chunk_id is not None and (not isinstance(chunk_id, str) or not chunk_id):
            return _err("chunk_id must be a non-empty string when provided")
        fl_raw = args.get("from_line")
        tl_raw = args.get("to_line")
        try:
            items = sorted(
                _read_all(workdir_resolved),
                key=lambda i: (i.get("from_line", 0), i.get("id", 0)),
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return _err(f"could not read comments: {exc}")
        if fl_raw is not None or tl_raw is not None:
            if fl_raw is None or tl_raw is None:
                return _err("specify both from_line and to_line, or neither")
            try:
                fl, tl = int(fl_raw), int(tl_raw)
            except (TypeError, ValueError):
                return _err("from_line and to_line must be integers")
            if fl < 1 or tl < fl:
                return _err(f"invalid line range [{fl},{tl}]")
        else:
            fl = tl = None
        def matches(item: dict[str, Any]) -> bool:
            if phase is not None and item.get("phase") != phase:
                return False
            if chunk_id is not None and item.get("chunk_id") != chunk_id:
                return False
            if fl is None:
                return True
            if not isinstance(tl, int):
                return False
            return _intersects(item["from_line"], item["to_line"], fl, tl)

        selected = [item for item in items if matches(item)]
        filters = []
        if phase is not None:
            filters.append(phase)
        if chunk_id is not None:
            filters.append(chunk_id)
        filter_text = f" ({', '.join(filters)})" if filters else ""
        if fl is not None:
            if not selected:
                return {"content": [{"type": "text", "text": f"no comments{filter_text} intersect lines {fl}-{tl}"}]}
            blocks = [f"{_format_label(item)}:\n{item['comment']}" for item in selected]
            return {"content": [{"type": "text", "text": "\n\n".join(blocks)}]}
        if not selected:
            return {"content": [{"type": "text", "text": f"(no comments{filter_text} yet)"}]}
        out = [f"{len(selected)} comment(s){filter_text}:"]
        for item in selected:
            out.append(f"  {_format_label(item)}: {_first_line(item.get('comment', ''))}")
        return {"content": [{"type": "text", "text": "\n".join(out)}]}

    @tool(
        "delete_comment",
        "Delete one staged note by its id (from list_comments).",
        {
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "comment id"}},
            "required": ["id"],
        },
    )
    async def delete_comment(args: dict[str, Any]) -> dict[str, Any]:
        try:
            cid = int(args["id"])
        except (KeyError, TypeError, ValueError):
            return _err("id must be an integer")
        try:
            with _locked_comments(workdir_resolved):
                items = _read_all(workdir_resolved)
                new = [item for item in items if item.get("id") != cid]
                if len(new) == len(items):
                    return _err(f"no comment #{cid}")
                _write_all(workdir_resolved, new)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return _err(f"could not delete comment: {exc}")
        return {"content": [{"type": "text", "text": f"deleted comment #{cid}"}]}

    return [write_comment, list_comments, delete_comment]


def make_comment_server(source: Path, workdir: Path):
    """Build the in-process MCP server exposing staged comment tools."""
    return create_sdk_mcp_server(name="comments", tools=build_comment_tools(workdir, source))
