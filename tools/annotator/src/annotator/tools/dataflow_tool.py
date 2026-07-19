"""In-process MCP dataflow tool: forward may-flow from an agent-chosen source.

The agent calls ``query_dataflow`` with a ``source`` expression location
(``file:line:col``, 1-based column). That triggers a host Jelly re-run with
``--dataflow-json <file> --dataflow-source <source>`` to produce the forward
may-flow report for that exact source, then this tool loads it and reports the
**source expressions** the value may flow to — abstract object nodes
(``.property``) and internal analysis nodes are hidden, only reachable source
points (variable / return / this / arguments) with a location are shown.

Same in-process MCP pattern as the other tools. The host roundtrip is
synchronous (the agent asked a question and wants the answer), unlike call-edge
re-analysis which is async. Requires the host dataflow service (jelly_bin
configured).

Communication: ``.jelly/df_req.json`` (agent → host, carries the source) /
``.jelly/df_res.json`` (host → agent) / ``.jelly/df.json`` (the regenerated
report), mirroring the call-graph priors protocol under ``.jelly/``.
"""

from __future__ import annotations

import json
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from .utils import _err

EDGE_KINDS = (
    "store-property",
    "load-property",
    "argument",
    "return",
    "call-result",
    "assignment",
    "external-escape",
)
DEFAULT_MAX_RESULTS = 100
JELLY_DIR = ".jelly"
DF_TIMEOUT_S = 120

# node kinds that represent source-level points an agent cares about (the value
# "flowed to this expression"). Abstract object / internal nodes are traversed
# but not shown.
SHOWN_KINDS = frozenset({"variable", "return", "this", "arguments"})


def _loc_str(report: dict[str, Any], loc: str | None) -> str:
    """Render a Jelly LocationJSON ``"fileIdx:sl:sc:el:ec"`` as ``file:line``."""
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
    """Build the dataflow MCP tool, bound to ``workdir`` (where ``.jelly/`` lives).
    Exposed for tests to drive the handler directly."""
    source_name = source.name
    workdir_resolved = workdir.resolve()

    def _info(msg: str) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": msg}]}

    def _run_dataflow(source_range: str) -> tuple[dict[str, Any] | None, str | None]:
        """Trigger a host Jelly dataflow re-run for ``source_range`` and wait for
        the report. ``source_range`` is a range ``sl:sc:el:ec`` (like loc_key);
        Jelly's expLocationIndex keys expressions by full range, so we pass the
        range through. Returns (report, None) or (None, error_message)."""
        req_id = uuid.uuid4().hex
        fb = workdir_resolved / JELLY_DIR
        try:
            fb.mkdir(parents=True, exist_ok=True)
            # Jelly --dataflow-source wants file:sl:sc:el:ec (range); prepend the (only) file.
            (fb / "df_req.json").write_text(
                json.dumps({"req_id": req_id, "source": f"{source_name}:{source_range}"}), encoding="utf-8"
            )
        except OSError as exc:
            return None, f"could not request dataflow: {exc}"
        res_path = fb / "df_res.json"
        deadline = time.time() + DF_TIMEOUT_S
        while time.time() < deadline:
            if res_path.exists():
                try:
                    res = json.loads(res_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    time.sleep(0.1)
                    continue
                if res.get("req_id") == req_id:
                    res_path.unlink(missing_ok=True)
                    if not res.get("ok"):
                        return None, "dataflow 失败: " + (res.get("stderr") or "")[:200]
                    break
            time.sleep(0.1)
        else:
            return None, "host dataflow 超时(未配置 jelly_bin 或 host 未运行?)"
        try:
            report = json.loads((fb / "df.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return None, f".jelly/df.json 不可读: {exc}"
        return report, None

    @tool(
        "query_dataflow",
        "Trace where a source expression's value may flow. Give `source` as a "
        "range `sl:sc:el:ec` (same format view_callgraph returns). The host re-runs Jelly with "
        "--dataflow-source=<source> to build the forward may-flow report, then "
        "this returns the source-level points the value reaches (variable / "
        "return / this / arguments) — abstract object and internal nodes are "
        "hidden. Filter by edge kind with include_kinds/exclude_kinds "
        "(store-property, load-property, argument, return, call-result, "
        "assignment, external-escape). Requires the host dataflow service "
        "(jelly_bin).",
        {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "source range sl:sc:el:ec (same format view_callgraph returns)",
                },
                "include_kinds": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(EDGE_KINDS)},
                    "description": "only traverse these edge kinds",
                },
                "exclude_kinds": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(EDGE_KINDS)},
                    "description": "do not traverse these edge kinds",
                },
                "max_results": {
                    "type": "integer",
                    "description": f"cap on reached points (default {DEFAULT_MAX_RESULTS}; 0 = unlimited)",
                },
            },
            "required": ["source"],
        },
    )
    async def query_dataflow(args: dict[str, Any]) -> dict[str, Any]:
        source_range = args.get("source")
        if not isinstance(source_range, str) or not source_range:
            return _err("missing 'source' (a range sl:sc:el:ec, like the ones view_callgraph returns)")
        include, exclude, bad = _parse_kinds(args)
        if bad is not None:
            return _err(bad)
        try:
            max_results = int(args.get("max_results", DEFAULT_MAX_RESULTS))
        except (TypeError, ValueError):
            max_results = DEFAULT_MAX_RESULTS

        report, err = _run_dataflow(source_range)
        if err is not None:
            return _err(err)
        if report is None:
            return _err("internal: no dataflow report")

        nodes = {n["id"]: n for n in report.get("nodes", [])}
        # adjacency filtered by edge kind; property/internal nodes are traversed
        # as intermediates (kept in the graph) but only SHOWN_KINDS are reported.
        adj: dict[int, list[int]] = {}
        for e in report.get("edges", []):
            k = e.get("kind")
            if include is not None and k not in include:
                continue
            if exclude is not None and k in exclude:
                continue
            adj.setdefault(e["from"], []).append(e["to"])

        start = 0  # df.json node 0 is the source (dataflowToJSON addNode first)
        visited: set[int] = {start}
        dq: deque[int] = deque([start])
        endpoints: list[dict[str, Any]] = []
        while dq:
            n = dq.popleft()
            for m in adj.get(n, []):
                if m in visited:
                    continue
                visited.add(m)
                dq.append(m)
                node = nodes.get(m)
                if node and node.get("kind") in SHOWN_KINDS and node.get("location"):
                    endpoints.append(node)

        shown = endpoints if max_results <= 0 else endpoints[:max_results]
        src = report.get("source", {})
        lines = [
            f"source: {source_range} -> {src.get('var', '?')}"
            + (f" (resolved: {src.get('kind', '?')})" if src.get("resolved") else " (UNRESOLVED)"),
            f"reached {len(endpoints)} source point(s)"
            + (f" (showing {len(shown)})" if max_results and len(endpoints) > len(shown) else "")
            + f"; completeness: aborted={report.get('completeness', {}).get('aborted')} timeout={report.get('completeness', {}).get('timeout')}"
            + (" [TRUNCATED]" if report.get("truncated") else ""),
        ]
        for n in shown:
            label = n.get("label") or n.get("kind")
            lines.append(f"  {_loc_str(report, n.get('location'))}  {n.get('kind')} {label}")
        return _info("\n".join(lines))

    return [query_dataflow]


def make_dataflow_server(source: Path, workdir: Path):
    """Build an in-process MCP server exposing query_dataflow."""
    return create_sdk_mcp_server(
        name="jelly-dataflow",
        tools=build_dataflow_tools(source, workdir),
    )


def host_setup(attempt_dir: Path, source_name: str, config, stop_event) -> list:
    """Host-side: start the dataflow service (jelly re-run per query_dataflow source).

    Returns one un-started Thread, or [] when jelly_bin is absent.
    """
    import threading
    from ..priors_service import serve_dataflow
    jelly_bin = getattr(config, "jelly_bin", None)
    if not jelly_bin:
        return []
    return [threading.Thread(
        target=serve_dataflow, args=(attempt_dir, source_name, str(jelly_bin), stop_event),
        daemon=True, name="dataflow_service",
    )]
