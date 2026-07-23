"""In-process non-blocking Jelly dataflow tools.

A dataflow result is keyed by source range and direction. The first query queues
an asynchronous host analysis and returns ``not yet ready`` immediately. Later
queries return the last completed report for that same key; while a refresh is
in flight the report is explicitly marked stale. No MCP handler polls or waits
for Jelly.
"""

from __future__ import annotations

import json
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from .utils import _err, atomic_write_json

EDGE_KINDS = (
    "store-property", "load-property", "argument", "return",
    "call-result", "assignment", "external-escape",
)
DEFAULT_MAX_RESULTS = 100
JELLY_DIR = ".jelly"
SHOWN_KINDS = frozenset({"variable", "return", "this", "arguments"})
DIRECTIONS = ("forward", "reverse", "both")


def _loc_str(report: dict[str, Any], loc: str | None) -> str:
    if not loc:
        return "?"
    parts = loc.split(":")
    if len(parts) < 2:
        return "?"
    try:
        fi = int(parts[0])
    except ValueError:
        return "?"
    files = report.get("files", [])
    file = files[fi] if 0 <= fi < len(files) else "?"
    return f"{file}:{parts[1]}"


def _parse_kinds(args: dict[str, Any]) -> tuple[set[str] | None, set[str] | None, str | None]:
    inc = args.get("include_kinds")
    exc = args.get("exclude_kinds")
    include = set(inc) if isinstance(inc, list) else None
    exclude = set(exc) if isinstance(exc, list) else None
    bad = ((include or set()) | (exclude or set())) - set(EDGE_KINDS)
    if bad:
        return None, None, f"unknown edge kind(s): {', '.join(sorted(bad))}"
    return include, exclude, None


def build_dataflow_tools(source: Path, workdir: Path):
    source_name = source.name
    workdir_resolved = workdir.resolve()
    reports: dict[tuple[str, str], dict[str, Any]] = {}
    pending_req: str | None = None
    pending_key: tuple[str, str] | None = None
    queued: deque[tuple[str, str]] = deque()
    queued_set: set[tuple[str, str]] = set()

    def _info(msg: str) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": msg}]}

    def _enqueue(key: tuple[str, str]) -> None:
        if key == pending_key or key in queued_set:
            return
        queued.append(key)
        queued_set.add(key)

    def _start_next() -> str | None:
        nonlocal pending_req, pending_key
        if pending_req is not None or not queued:
            return None
        key = queued.popleft()
        queued_set.remove(key)
        req_id = uuid.uuid4().hex
        fb = workdir_resolved / JELLY_DIR
        try:
            atomic_write_json(
                fb / "df_req.json",
                {
                    "req_id": req_id,
                    "source": f"{source_name}:{key[0]}",
                    "direction": key[1],
                },
            )
        except OSError as exc:
            return f"could not request dataflow: {exc}"
        pending_req = req_id
        pending_key = key
        return None

    def _poll() -> str | None:
        """Consume a completed response, cache its keyed report, then queue next."""
        nonlocal pending_req, pending_key
        if pending_req is None:
            return _start_next()
        fb = workdir_resolved / JELLY_DIR
        res_path = fb / "df_res.json"
        if not res_path.exists():
            return None
        try:
            response = json.loads(res_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if response.get("req_id") != pending_req:
            return None
        res_path.unlink(missing_ok=True)
        key = pending_key
        req_id = pending_req
        pending_req = None
        pending_key = None
        if not response.get("ok"):
            error = "dataflow refresh failed: " + (response.get("stderr") or "unknown error")[:200]
        else:
            try:
                report = json.loads((fb / f"df.{req_id}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                error = f"dataflow result is unreadable: {exc}"
            else:
                if key is not None:
                    reports[key] = report
                error = None
        next_error = _start_next()
        return error or next_error

    def _report_for(source_range: str, direction: str) -> tuple[dict[str, Any] | None, str]:
        key = (source_range, direction)
        refresh_error = _poll()
        if key not in reports:
            _enqueue(key)
            request_error = _start_next()
            if request_error:
                return None, request_error
            if refresh_error and pending_key != key:
                return None, refresh_error
            return None, "not yet ready: dataflow analysis was queued; retry in a few seconds"
        stale = key == pending_key or key in queued_set
        if stale:
            return reports[key], " [stale: refresh pending; retry in a few seconds]"
        if refresh_error:
            return reports[key], f" [stale: {refresh_error}]"
        return reports[key], ""

    def _extract(report: dict, nodes: dict, include: set | None, exclude: set | None):
        """Extract forward-reached and reverse-source nodes from Jelly's BFS edges."""
        fwd: list[dict] = []
        rev: list[dict] = []
        seen_f: set[int] = set()
        seen_r: set[int] = set()
        for edge in report.get("edges", []):
            kind = edge.get("kind")
            if include is not None and kind not in include:
                continue
            if exclude is not None and kind in exclude:
                continue
            if edge.get("direction", "forward") == "forward":
                nid = edge.get("to")
                if nid in seen_f:
                    continue
                node = nodes.get(nid)
                if node and node.get("kind") in SHOWN_KINDS and node.get("location"):
                    fwd.append(node)
                    seen_f.add(nid)
            else:
                nid = edge.get("from")
                if nid in seen_r:
                    continue
                node = nodes.get(nid)
                if node and node.get("kind") in SHOWN_KINDS and node.get("location"):
                    rev.append(node)
                    seen_r.add(nid)
        return fwd, rev

    @tool(
        "query_dataflow",
        "Trace possible data flow for a source range without blocking. The first "
        "query queues host analysis and returns 'not yet ready'; later queries return "
        "the cached report for this exact source/direction, marked stale while refreshing.",
        {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "source range sl:sc:el:ec"},
                "direction": {"type": "string", "enum": list(DIRECTIONS)},
                "include_kinds": {"type": "array", "items": {"type": "string", "enum": list(EDGE_KINDS)}},
                "exclude_kinds": {"type": "array", "items": {"type": "string", "enum": list(EDGE_KINDS)}},
                "max_results": {"type": "integer", "description": f"cap per direction (default {DEFAULT_MAX_RESULTS})"},
            },
            "required": ["source"],
        },
    )
    async def query_dataflow(args: dict[str, Any]) -> dict[str, Any]:
        source_range = args.get("source")
        if not isinstance(source_range, str) or not source_range:
            return _err("missing 'source' (a range sl:sc:el:ec)")
        direction = args.get("direction", "both")
        if direction not in DIRECTIONS:
            return _err(f"direction must be one of {DIRECTIONS}")
        include, exclude, bad = _parse_kinds(args)
        if bad is not None:
            return _err(bad)
        try:
            max_results = int(args.get("max_results", DEFAULT_MAX_RESULTS))
        except (TypeError, ValueError):
            max_results = DEFAULT_MAX_RESULTS
        report, state = _report_for(source_range, direction)
        if report is None:
            return _info(state)
        nodes = {node["id"]: node for node in report.get("nodes", [])}
        fwd, rev = _extract(report, nodes, include, exclude)
        fwd = fwd if max_results <= 0 else fwd[:max_results]
        rev = rev if max_results <= 0 else rev[:max_results]
        src = report.get("source", {})
        lines = [
            f"source: {source_range} -> {src.get('var', '?')}"
            + (f" (resolved: {src.get('kind', '?')})" if src.get("resolved") else " (UNRESOLVED)")
            + state,
        ]
        declaration = src.get("declaration")
        if declaration:
            lines.append(f"  defined at: {declaration}")
        if direction in ("forward", "both"):
            lines.append(f"→ flows out: {len(fwd)} point(s)")
            for node in fwd:
                lines.append(f"  → {_loc_str(report, node.get('location'))}  {node.get('kind')} {node.get('label') or ''}")
        if direction in ("reverse", "both"):
            lines.append(f"← flows in: {len(rev)} point(s)")
            for node in rev:
                lines.append(f"  ← {_loc_str(report, node.get('location'))}  {node.get('kind')} {node.get('label') or ''}")
        lines.append(
            f"completeness: aborted={report.get('completeness', {}).get('aborted')} "
            f"timeout={report.get('completeness', {}).get('timeout')}"
            + (" [TRUNCATED]" if report.get("truncated") else "")
        )
        return _info("\n".join(lines))

    @tool(
        "get_definition",
        "Resolve an identifier through the same non-blocking keyed dataflow cache. "
        "Returns 'not yet ready' until its first dataflow result completes.",
        {
            "type": "object",
            "properties": {"source": {"type": "string", "description": "identifier range sl:sc:el:ec"}},
            "required": ["source"],
        },
    )
    async def get_definition(args: dict[str, Any]) -> dict[str, Any]:
        source_range = args.get("source")
        if not isinstance(source_range, str) or not source_range:
            return _err("missing 'source'")
        report, state = _report_for(source_range, "forward")
        if report is None:
            return _info(state)
        src = report.get("source", {})
        declaration = src.get("declaration")
        if declaration:
            return _info(f"{src.get('var', '?')} defined at {declaration}{state}")
        if not src.get("resolved"):
            return _info(f"unresolved: no expression at {source_range}{state}")
        return _info(f"{src.get('var', '?')}: not an identifier (no declaration){state}")

    return [query_dataflow, get_definition]


def make_dataflow_server(source: Path, workdir: Path):
    return create_sdk_mcp_server(name="jelly-dataflow", tools=build_dataflow_tools(source, workdir))


def host_setup(attempt_dir: Path, source_name: str, config, stop_event) -> list:
    import threading

    from ..priors_service import serve_dataflow

    jelly_bin = getattr(config, "jelly_bin", None)
    if not jelly_bin:
        return []
    return [threading.Thread(
        target=serve_dataflow, args=(attempt_dir, source_name, str(jelly_bin), stop_event),
        daemon=True, name="dataflow_service",
    )]
