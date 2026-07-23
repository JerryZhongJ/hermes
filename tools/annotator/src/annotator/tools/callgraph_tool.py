"""In-process MCP tools over a Jelly call graph: browsing, manual edge
overrides and heat estimation.

The agent does NOT load or re-run anything manually — loading and re-analysis
are automatic:

- **Auto-load**: the first query reads ``.jelly/cg.json`` after the host's
  background prewarm publishes it. Until then it returns ``not yet ready``
  without blocking.
- **Auto-reanalyze (async)**: ``add_call_edges`` / ``delete_call_edges`` /
  ``clear_call_edge_overrides`` / ``set_target_prob(..., 0)`` return immediately.
  While Jelly refreshes, queries keep serving the last completed graph with a
  stale marker and the local override overlay. A later mutation is coalesced into
  one follow-up refresh instead of overwriting the in-flight request.

Heat-only changes (``set_hot_value`` / ``set_exec_expt`` / non-zero
``set_target_prob``) do not trigger a host re-run — they only reshape the
in-process heat estimate.

Loop depth is extracted with tree-sitter-javascript from the source tree under
``root`` (matches Jelly's basedir). All tools return
``{"content": [{"type": "text", ...}]}``; genuine argument errors add
``is_error: true``. ``not yet ready`` and stale-result notices are informational,
not errors.
"""

from __future__ import annotations

import json
import math
import uuid
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from .callgraph import (
    CallEdgeOverrides,
    CallGraphModel,
    HeatAssumptions,
    HeatParams,
    build_model,
    compute_heat,
    compute_loop_depths,
)
from .utils import _err, atomic_write_json, resolve_in_workdir

DEFAULT_VIEW_LIMIT = 50
DEFAULT_HEAT_LIMIT = 30
JELLY_DIR = ".jelly"
CG_DEFAULT = ".jelly/cg.json"


class _Session:
    """Per-server mutable state, closed over by every handler."""

    def __init__(self) -> None:
        self.model: CallGraphModel | None = None
        self.overrides = CallEdgeOverrides()
        self.assumptions = HeatAssumptions()
        self.loop_depths: dict[int, int] = {}
        self.params = HeatParams()
        self.revision = 0
        self.source_desc = ""
        self.cg_file: str = CG_DEFAULT
        self.cg_root: Path | None = None
        self.cg_include_deps: bool = False
        self.pending_cg_req: str | None = None  # host reanalyze req_id in flight
        self.refresh_dirty = False  # later override arrived while one refresh ran
        self.refresh_error: str | None = None


def _fun_ref(model: CallGraphModel, fun_index: int) -> dict[str, Any]:
    e = model.functions[fun_index]
    line = e.start["line"] if e.start else None
    return {"loc_key": e.loc_key, "file": e.file, "line": line}


def _call_ref(model: CallGraphModel, call_index: int) -> dict[str, Any]:
    e = model.calls[call_index]
    line = e.start["line"] if e.start else None
    return {"loc_key": e.loc_key, "file": e.file, "line": line}


def _fmt_num(x: float | None) -> str:
    if x is None:
        return "divergent"
    if x >= 1000 or (x != 0 and abs(x) < 1e-3):
        return f"{x:.3e}"
    return f"{x:.2f}"


def build_callgraph_tools(source: Path, workdir: Path):
    """Build the Jelly call-graph MCP tools, bound to ``source`` (the JS file
    being annotated) and ``workdir`` (where ``.jelly/cg.json`` lives).

    Exposed separately from :func:`make_callgraph_server` so tests drive
    handlers directly via ``await tool.handler(args)``.
    """
    source_name = source.name  # the single JS file; prepended when exporting Jelly priors
    workdir_resolved = workdir.resolve()
    session = _Session()

    # ----- internal helpers (closed over session / workdir) ----- #

    def _info(msg: str) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": msg}]}

    def _load_cg_from(cg_file: str, root: Path, include_deps: bool) -> bool:
        cg_path, err = resolve_in_workdir(workdir_resolved, cg_file)
        if err is not None or cg_path is None or not cg_path.exists():
            return False
        try:
            model = build_model(json.loads(cg_path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return False
        try:
            loop_depths = compute_loop_depths(model, root, include_deps)
        except Exception:  # noqa: BLE001 — never block the agent on source reads
            loop_depths = {}
        session.model = model
        session.loop_depths = loop_depths
        session.cg_file = cg_file
        session.cg_root = root
        session.cg_include_deps = include_deps
        session.revision += 1
        depth_hist: dict[int, int] = {}
        for d in loop_depths.values():
            depth_hist[d] = depth_hist.get(d, 0) + 1
        session.source_desc = "loop-depth histogram: " + (
            " ".join(f"d{d}={c}" for d, c in sorted(depth_hist.items())) or "none"
        )
        return True

    def _reload_cg() -> bool:
        assert session.cg_file is not None
        root = session.cg_root or workdir_resolved
        return _load_cg_from(session.cg_file, root, session.cg_include_deps)

    def _check_pending() -> None:
        """Absorb a completed host refresh without blocking stale-model queries."""
        if not session.pending_cg_req:
            return
        res_path = workdir_resolved / JELLY_DIR / "res.json"
        if not res_path.exists():
            return
        try:
            res = json.loads(res_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if res.get("req_id") != session.pending_cg_req:
            return
        res_path.unlink(missing_ok=True)
        session.pending_cg_req = None
        if not res.get("ok"):
            session.refresh_error = (res.get("stderr") or "Jelly refresh failed")[:200]
            if session.refresh_dirty:
                session.refresh_dirty = False
                _trigger_reanalyze()
            return
        if not _reload_cg():
            session.refresh_error = "Jelly refresh completed but cg.json is unreadable"
            return
        session.refresh_error = None
        if session.refresh_dirty:
            session.refresh_dirty = False
            _trigger_reanalyze()
            return
        # Host has applied precisely the current override set. Do not overlay it
        # a second time over the confirmed model.
        session.overrides.clear()

    def _ensure_loaded() -> str | None:
        _check_pending()
        if session.model is not None:
            return None
        if _load_cg_from(CG_DEFAULT, workdir_resolved, False):
            return None
        return "not yet ready: Jelly call graph is still being prepared; retry in a few seconds"

    def _trigger_reanalyze() -> str | None:
        """Request one asynchronous host refresh, coalescing later mutations."""
        if session.pending_cg_req:
            session.refresh_dirty = True
            return None
        req_id = uuid.uuid4().hex
        fb = workdir_resolved / JELLY_DIR
        # session overrides use file-less range keys; Jelly priors are file-prefixed.
        rules = [
            {"callsite": f"{source_name}:{r['callsite']}", "callee": f"{source_name}:{r['callee']}", "mode": r["mode"]}
            for r in session.overrides.list()
        ]
        try:
            atomic_write_json(fb / "req.json", {"req_id": req_id, "rules": rules})
        except OSError as exc:
            return f"无法请求重分析(host priors_service 可能未运行): {exc}"
        session.pending_cg_req = req_id
        return None

    def _model_or_info() -> CallGraphModel | dict[str, Any]:
        """Ensure loaded; return model or an informational result dict."""
        msg = _ensure_loaded()
        if msg is not None:
            return _info(msg)
        assert session.model is not None
        return session.model

    def _staleness_note() -> str:
        if session.pending_cg_req:
            return " [stale: refresh pending; local overrides applied; retry in a few seconds]"
        if session.refresh_error:
            return f" [stale: last refresh failed: {session.refresh_error}]"
        return ""

    # ----- view_callgraph ----- #
    @tool(
        "view_callgraph",
        "Browse the call graph: call site -> callee(s). Call graph and manual "
        "edge overrides are loaded/applied automatically (no separate load step). "
        "While a re-analysis runs, the last completed result is marked stale; if "
        "no graph exists yet it says 'not yet ready'. Each row carries callsite/callee "
        "`loc_key` strings for the other tools.",
        {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "restrict to this source file (relative path)"},
                "from_line": {"type": "integer", "description": "1-based start line (inclusive)"},
                "to_line": {"type": "integer", "description": "1-based end line (inclusive)"},
                "min_callees": {"type": "integer", "description": "only call sites with >= this many callees"},
                "max_callees": {"type": "integer", "description": "only call sites with <= this many callees"},
                "sort": {
                    "type": "string",
                    "enum": ["file-line", "callees-desc"],
                    "description": "ordering (default file-line)",
                },
                "limit": {"type": "integer", "description": f"cap on rows (default {DEFAULT_VIEW_LIMIT}; 0 = unlimited)"},
            },
        },
    )
    async def view_callgraph(args: dict[str, Any]) -> dict[str, Any]:
        model = _model_or_info()
        if not isinstance(model, CallGraphModel):
            assert isinstance(model, dict)
            return model
        effective = session.overrides.effective_edges(model)
        file_filter = args.get("file")
        fl = args.get("from_line")
        tl = args.get("to_line")
        min_c = args.get("min_callees")
        max_c = args.get("max_callees")
        sort = args.get("sort", "file-line")
        try:
            limit = int(args.get("limit", DEFAULT_VIEW_LIMIT))
        except (TypeError, ValueError):
            limit = DEFAULT_VIEW_LIMIT

        rows: list[dict[str, Any]] = []
        for call_index, callees in effective.call2fun_by_call.items():
            ce = model.calls.get(call_index)
            if ce is None or ce.start is None:
                continue
            if isinstance(file_filter, str) and ce.file != file_filter:
                continue
            line = ce.start["line"]
            if isinstance(fl, int) and line < fl:
                continue
            if isinstance(tl, int) and line > tl:
                continue
            n = len(callees)
            if isinstance(min_c, int) and n < min_c:
                continue
            if isinstance(max_c, int) and n > max_c:
                continue
            caller_index = model.call2caller.get(call_index)
            callee_refs = [_fun_ref(model, f) for f in sorted(callees)]
            forced = any(
                e["call_index"] == call_index and e["source"] in ("included", "excluded")
                for e in effective.edges
            )
            rows.append(
                {
                    "call": _call_ref(model, call_index),
                    "caller": _fun_ref(model, caller_index) if caller_index is not None else None,
                    "callees": callee_refs,
                    "forced": forced,
                }
            )

        if sort == "callees-desc":
            rows.sort(key=lambda r: -len(r["callees"]))
        else:
            rows.sort(key=lambda r: (r["call"]["file"], r["call"]["line"] or 0))

        total = len(rows)
        shown = rows if limit <= 0 else rows[:limit]
        pend = f" [revision {session.revision}]" + _staleness_note()
        lines = [f"{total} call site(s){pend}" + (f" (showing {len(shown)})" if limit and total > len(shown) else "")]
        for r in shown:
            caller = r["caller"]
            caller_s = f"in {caller['loc_key']}" if caller else "(caller unknown)"
            tag = " [forced]" if r["forced"] else ""
            lines.append(f"\ncallsite {r['call']['loc_key']}  {caller_s}{tag}")
            for c in r["callees"]:
                lines.append(f"    -> {c['loc_key']}")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    # ----- get_callers ----- #
    @tool(
        "get_callers",
        "Reverse lookup: every call site and caller function that may reach the "
        "given callee function. `callee` is a callee range from view_callgraph "
        "/ view_hot_value.",
        {
            "type": "object",
            "properties": {"callee": {"type": "string", "description": "callee function range"}},
            "required": ["callee"],
        },
    )
    async def get_callers(args: dict[str, Any]) -> dict[str, Any]:
        model = _model_or_info()
        if not isinstance(model, CallGraphModel):
            assert isinstance(model, dict)
            return model
        callee_loc = args.get("callee")
        callee_idx = model.fun_by_loc_key.get(callee_loc) if isinstance(callee_loc, str) else None
        if callee_idx is None:
            return _err(f"unknown callee range: {callee_loc!r}")
        effective = session.overrides.effective_edges(model)
        out: list[dict[str, Any]] = []
        for call_index, callees in effective.call2fun_by_call.items():
            if callee_idx in callees:
                caller_index = model.call2caller.get(call_index)
                out.append(
                    {
                        "call": _call_ref(model, call_index),
                        "caller": _fun_ref(model, caller_index) if caller_index is not None else None,
                    }
                )
        out.sort(key=lambda r: (r["call"]["file"], r["call"]["line"] or 0))
        lines = [f"{len(out)} caller(s) of {callee_loc}"]
        for r in out:
            caller = r["caller"]
            caller_s = f"from {caller['loc_key']}" if caller else "(unknown)"
            lines.append(f"  {r['call']['loc_key']}  {caller_s}")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    # ----- get_callees ----- #
    @tool(
        "get_callees",
        "Forward lookup from a function or a single call site. Give `caller` (a "
        "function range) for every callee of that function, or `callsite` (a "
        "call site range) for that one site's callees.",
        {
            "type": "object",
            "properties": {
                "caller": {"type": "string", "description": "caller function range"},
                "callsite": {"type": "string", "description": "call site range"},
            },
        },
    )
    async def get_callees(args: dict[str, Any]) -> dict[str, Any]:
        model = _model_or_info()
        if not isinstance(model, CallGraphModel):
            assert isinstance(model, dict)
            return model
        effective = session.overrides.effective_edges(model)
        if isinstance(args.get("callsite"), str):
            call_idx = model.call_by_loc_key.get(args["callsite"])
            if call_idx is None:
                return _err(f"unknown callsite range: {args['callsite']!r}")
            callees = effective.call2fun_by_call.get(call_idx, set())
            refs = [_fun_ref(model, f) for f in sorted(callees)]
            lines = [f"{len(refs)} callee(s) at {args['callsite']}"]
            for c in refs:
                lines.append(f"  -> {c['loc_key']}")
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

        caller_loc = args.get("caller")
        caller_idx = model.fun_by_loc_key.get(caller_loc) if isinstance(caller_loc, str) else None
        if caller_idx is None:
            return _err("provide 'callsite' or a known 'caller' range")
        callees: set[int] = set()
        sites: list[int] = []
        for call_index, cs in effective.call2fun_by_call.items():
            if model.call2caller.get(call_index) == caller_idx:
                callees |= cs
                sites.append(call_index)
        refs = [_fun_ref(model, f) for f in sorted(callees)]
        lines = [f"{len(refs)} callee(s) of {caller_loc} across {len(sites)} call site(s)"]
        for c in refs:
            lines.append(f"  -> {c['file']}:{c['line']}  {c['loc_key']}")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    # ----- add / delete call edges ----- #
    @tool(
        "add_call_edges",
        "Force call site -> callee edge(s) into the graph. This triggers an "
        "asynchronous host Jelly re-run with the overrides as --call-edge-priors "
        "(the edge then propagates args/this/return in points-to). The in-session "
        "view updates immediately; completed queries keep serving the prior graph "
        "with a stale marker until the host refresh finishes.",
        {
            "type": "object",
            "properties": {
                "edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "callsite": {"type": "string"},
                            "callee": {"type": "string"},
                        },
                        "required": ["callsite", "callee"],
                    },
                }
            },
            "required": ["edges"],
        },
    )
    async def add_call_edges(args: dict[str, Any]) -> dict[str, Any]:
        return _apply_overrides(args, "include")

    @tool(
        "delete_call_edges",
        "Drop call site -> callee edge(s) from the graph (equivalent to "
        "set_target_prob 0). Triggers an asynchronous host Jelly re-run so the "
        "edge is excluded from points-to (reachability/data flow), not just the "
        "view. Picked up on the next query once the host finishes.",
        {
            "type": "object",
            "properties": {
                "edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "callsite": {"type": "string"},
                            "callee": {"type": "string"},
                        },
                        "required": ["callsite", "callee"],
                    },
                }
            },
            "required": ["edges"],
        },
    )
    async def delete_call_edges(args: dict[str, Any]) -> dict[str, Any]:
        return _apply_overrides(args, "exclude")

    # ----- list / clear overrides ----- #
    @tool(
        "list_call_edge_overrides",
        "List all manual call-edge overrides (force include / exclude) and "
        "whether each still resolves in the current analysis.",
        {},
    )
    async def list_call_edge_overrides(args: dict[str, Any]) -> dict[str, Any]:
        del args
        model = _model_or_info()
        if not isinstance(model, CallGraphModel):
            assert isinstance(model, dict)
            return model
        rules = session.overrides.list()
        effective = session.overrides.effective_edges(model)
        unresolved = {f"{r['callsite']}|{r['callee']}" for r in effective.unresolved_includes}
        lines = [f"{len(rules)} override(s)"]
        for r in rules:
            mark = " (unresolved)" if f"{r['callsite']}|{r['callee']}" in unresolved else ""
            lines.append(f"  [{r['mode']}] {r['callsite']} -> {r['callee']}{mark}")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "clear_call_edge_overrides",
        "Drop every manual call-edge override and trigger a host re-run back to "
        "the original (unmodified) call graph. Does not touch heat assumptions.",
        {},
    )
    async def clear_call_edge_overrides(args: dict[str, Any]) -> dict[str, Any]:
        del args
        had = session.overrides.size
        session.overrides.clear()
        trig = _trigger_reanalyze() if had else None
        if trig is not None:
            return _info(f"cleared {had} override(s); {trig}")
        return _info(f"cleared {had} override(s); 已请求 host 重分析(异步)" if had else "no overrides to clear")

    # ----- view_hot_value ----- #
    @tool(
        "view_hot_value",
        "Estimate per-function heat (expected calls per entry execution) on the "
        "override-adjusted graph, ranked hot-first. Each row carries a `loc_key` "
        "for set_hot_value. Status flags divergence/cap from recursive cycles. "
        "Filter by file/line range and minimum heat.",
        {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "restrict to this source file"},
                "from_line": {"type": "integer"},
                "to_line": {"type": "integer"},
                "min_hot": {"type": "number", "description": "only functions with heat >= this"},
                "limit": {"type": "integer", "description": f"cap on rows (default {DEFAULT_HEAT_LIMIT}; 0 = unlimited)"},
            },
        },
    )
    async def view_hot_value(args: dict[str, Any]) -> dict[str, Any]:
        model = _model_or_info()
        if not isinstance(model, CallGraphModel):
            assert isinstance(model, dict)
            return model
        effective = session.overrides.effective_edges(model)
        try:
            heat = compute_heat(
                model, effective, session.assumptions, session.params, session.loop_depths
            )
        except ValueError as exc:
            return _err(str(exc))
        file_filter = args.get("file")
        fl = args.get("from_line")
        tl = args.get("to_line")
        min_hot = args.get("min_hot")
        try:
            limit = int(args.get("limit", DEFAULT_HEAT_LIMIT))
        except (TypeError, ValueError):
            limit = DEFAULT_HEAT_LIMIT

        rows = heat["per_function"]
        out: list[dict[str, Any]] = []
        for r in rows:
            if isinstance(file_filter, str) and r["file"] != file_filter:
                continue
            line = r["line"]
            if isinstance(fl, int) and (line is None or line < fl):
                continue
            if isinstance(tl, int) and (line is None or line > tl):
                continue
            if isinstance(min_hot, (int, float)) and (r["hot"] is None or r["hot"] < min_hot):
                continue
            out.append(r)

        shown = out if limit <= 0 else out[:limit]
        p = heat["params"]
        header = (
            f"Heat ({heat['status']}): {p['functions']} functions, {p['entries']} entries, "
            f"{p['iterations']} iters, residual {p['residual']:.1e}; "
            f"reach {p['reachable']}. "
            f"overrides={heat['override_stats']} hot_overrides={heat['assumptions']['hot_value_overrides']}"
        )
        body = [
            f"{'rank':>4}  {'hot':>11}  {'inDeg':>5}  {'loop':>4}  {'entry':>5}  {'reach':>5}  {'st':>6}  range"
        ]
        for r in shown:
            entry = "ENTRY" if r["is_entry"] else "    "
            reach = "Y" if r["is_reachable"] else "n"
            st = {"finite": "fin", "capped": "cap", "divergent": "DIV"}.get(r["status"], "?")
            body.append(
                f"{r['rank']:>4}  {_fmt_num(r['hot']):>11}  {r['in_degree']:>5}  "
                f"{r['max_loop_depth']:>4}  {entry:>5}  {reach:>5}  {st:>6}  "
                f"{r['loc_key']}"
            )
        body.append("(st: fin=converged, cap=hit iteration cap, DIV=divergent cycle)")
        return {"content": [{"type": "text", "text": header + "\n" + "\n".join(body)}]}

    # ----- set_hot_value ----- #
    @tool(
        "set_hot_value",
        "Hard-override a function's heat to a fixed value: the function is pinned "
        "to that value and its outbound contributions propagate from it (inbound "
        "to it is ignored). Useful to inject a known runtime call count. This is "
        "heat-only — no host re-run. `func` is a range from view_callgraph / "
        "view_hot_value.",
        {
            "type": "object",
            "properties": {
                "func": {"type": "string", "description": "function range"},
                "value": {"type": "number", "description": "fixed heat value (>= 0)"},
            },
            "required": ["func", "value"],
        },
    )
    async def set_hot_value(args: dict[str, Any]) -> dict[str, Any]:
        model = _model_or_info()
        if not isinstance(model, CallGraphModel):
            assert isinstance(model, dict)
            return model
        func_loc = args.get("func")
        if not isinstance(func_loc, str) or func_loc not in model.fun_by_loc_key:
            return _err(f"unknown function range: {func_loc!r}")
        try:
            value = float(args["value"])
        except (KeyError, TypeError, ValueError):
            return _err("'value' must be a number")
        if not math.isfinite(value) or value < 0:
            return _err("'value' must be a finite, non-negative number")
        session.assumptions.function_hot[func_loc] = value
        return {"content": [{"type": "text", "text": f"heat({func_loc}) pinned to {value}"}]}

    # ----- set_exec_expt ----- #
    @tool(
        "set_exec_expt",
        "Set the expected number of executions of a call site per execution of "
        "its caller (overrides the default loopWeight^loopDepth estimate). "
        "Heat-only — no host re-run. `callsite` is a call site range.",
        {
            "type": "object",
            "properties": {
                "callsite": {"type": "string", "description": "call site range"},
                "value": {"type": "number", "description": "expected executions per caller execution (>= 0)"},
            },
            "required": ["callsite", "value"],
        },
    )
    async def set_exec_expt(args: dict[str, Any]) -> dict[str, Any]:
        model = _model_or_info()
        if not isinstance(model, CallGraphModel):
            assert isinstance(model, dict)
            return model
        cs = args.get("callsite")
        if not isinstance(cs, str) or cs not in model.call_by_loc_key:
            return _err(f"unknown callsite range: {cs!r}")
        try:
            value = float(args["value"])
        except (KeyError, TypeError, ValueError):
            return _err("'value' must be a number")
        if value < 0:
            return _err("'value' must be >= 0")
        session.assumptions.exec_expt[cs] = value
        return {"content": [{"type": "text", "text": f"exec_expt({cs}) = {value}"}]}

    # ----- set_target_prob ----- #
    @tool(
        "set_target_prob",
        "Set the probability that a call site dispatches to a given callee. "
        "Unset callees share the remaining mass (1 - sum of explicit). Probability "
        "0 is equivalent to delete_call_edges — it triggers an async host re-run "
        "so the edge is excluded from points-to. Non-zero values are heat-only "
        "(no re-run). Per-call-site explicit probabilities must sum to <= 1.",
        {
            "type": "object",
            "properties": {
                "callsite": {"type": "string", "description": "call site range"},
                "callee": {"type": "string", "description": "callee function range"},
                "prob": {"type": "number", "description": "probability in [0, 1]"},
            },
            "required": ["callsite", "callee", "prob"],
        },
    )
    async def set_target_prob(args: dict[str, Any]) -> dict[str, Any]:
        model = _model_or_info()
        if not isinstance(model, CallGraphModel):
            assert isinstance(model, dict)
            return model
        cs = args.get("callsite")
        callee = args.get("callee")
        if not isinstance(cs, str) or cs not in model.call_by_loc_key:
            return _err(f"unknown callsite range: {cs!r}")
        if not isinstance(callee, str) or callee not in model.fun_by_loc_key:
            return _err(f"unknown callee range: {callee!r}")
        try:
            prob = float(args["prob"])
        except (KeyError, TypeError, ValueError):
            return _err("'prob' must be a number")
        if not (0 <= prob <= 1):
            return _err("'prob' must be in [0, 1]")
        session.assumptions.target_prob.setdefault(cs, {})[callee] = prob
        note = ""
        if prob == 0:
            session.overrides.set(cs, callee, "exclude")
            trig = _trigger_reanalyze()
            note = " (== delete_call_edges; " + (
                "已请求 host 重分析(异步)" if trig is None else trig
            ) + ")"
        return {"content": [{"type": "text", "text": f"target_prob({cs} -> {callee}) = {prob}{note}"}]}

    def _apply_overrides(args: dict[str, Any], mode: str) -> dict[str, Any]:
        model = _model_or_info()
        if not isinstance(model, CallGraphModel):
            assert isinstance(model, dict)
            return model
        edges = args.get("edges")
        if not isinstance(edges, list) or not edges:
            return _err("'edges' must be a non-empty list of {callsite, callee}")
        applied = 0
        rejected: list[str] = []
        for e in edges:
            if not isinstance(e, dict):
                rejected.append(str(e))
                continue
            cs = e.get("callsite")
            callee = e.get("callee")
            if not isinstance(cs, str) or cs not in model.call_by_loc_key:
                rejected.append(f"unknown callsite {cs!r}")
                continue
            if not isinstance(callee, str) or callee not in model.fun_by_loc_key:
                rejected.append(f"unknown callee {callee!r}")
                continue
            session.overrides.set(cs, callee, mode)
            applied += 1
        trig = _trigger_reanalyze() if applied else None
        msg = f"{applied} edge(s) {mode}d"
        if trig is None and applied:
            msg += "; 已请求 host 重分析(异步),稍后查询看新结果"
        elif trig is not None:
            msg += f"; {trig}"
        if rejected:
            msg += f"; rejected: {'; '.join(rejected)}"
        return {"content": [{"type": "text", "text": msg}]}

    return [
        view_callgraph,
        get_callers,
        get_callees,
        add_call_edges,
        delete_call_edges,
        list_call_edge_overrides,
        clear_call_edge_overrides,
        view_hot_value,
        set_hot_value,
        set_exec_expt,
        set_target_prob,
    ]


def make_callgraph_server(source: Path, workdir: Path):
    """Build an in-process MCP server exposing the Jelly call-graph tools,
    bound to ``source`` (JS file being annotated) and ``workdir`` (``.jelly/``
    location)."""
    return create_sdk_mcp_server(
        name="jelly",
        tools=build_callgraph_tools(source, workdir),
    )


def host_setup(attempt_dir: Path, source_name: str, config, stop_event) -> list:
    """Start background callgraph prewarm and priors refresh workers.

    Setup returns immediately so agent startup never waits for Jelly. Until the
    prewarm atomically publishes ``cg.json``, queries report ``not yet ready``.
    """
    import threading
    from ..priors_service import prewarm_callgraph, serve

    jelly_bin = getattr(config, "jelly_bin", None)
    if not jelly_bin:
        return []
    return [
        threading.Thread(
            target=prewarm_callgraph,
            args=(attempt_dir, source_name, str(jelly_bin), stop_event),
            daemon=True,
            name="callgraph_prewarm",
        ),
        threading.Thread(
            target=serve,
            args=(attempt_dir, source_name, str(jelly_bin), stop_event),
            daemon=True,
            name="priors_service",
        ),
    ]
