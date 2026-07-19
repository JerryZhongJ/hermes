"""Jelly call-graph model, manual edge overrides and heat estimation.

Consumes a Jelly call-graph JSON (``jelly -j cg.json``) and rebuilds an
in-memory model keyed by *stable* source locations (file path + 1-based range),
never by Jelly's transient integer indices. On top of it:

- call-graph queries (callers/callees, filters/sort);
- session-level manual edge overrides (force include / force exclude) folded
  into a single "effective" graph consumed by every view and by heat;
- heat estimation — the expected-call-count model — with hard per-function
  overrides, per-callsite execution expectation and per-target probability.

tree-sitter-javascript (already an annotator dependency) replaces Babel for
loop-depth extraction. Loop depth is matched to Jelly callsites by *line*
only: Jelly's columns come from Babel (character based) while tree-sitter
reports byte offsets, so (line, column) would not line up. Same-line callsites
are rare on the multi-line sources annotator targets, and callsites sharing a
line almost always share a loop nest, so per-line max depth is a sound first
approximation.

First-stage scope (kept honest in docstrings): overrides act on the rebuilt
graph only — they do not re-run Jelly's points-to analysis, so they cannot
affect reachability or data flow discovered by Jelly. A full re-analysis with
priors injected into the solver is a later stage.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tree_sitter_javascript as tjs
from tree_sitter import Language, Parser

from .utils import build_line_starts

# Jelly loc string: "fileIndex:startLine:startCol(1-based):endLine:endCol(1-based)".
# Columns were +1 on serialization (see src/misc/util.ts makeLocString), so we
# subtract 1 on parse to get 0-based internal columns for range arithmetic.

_CALL_TYPES = frozenset(
    {"call_expression", "new_expression", "optional_call_expression"}
)
_LOOP_TYPES = frozenset(
    {"for_statement", "for_in_statement", "for_of_statement", "while_statement", "do_statement"}
)
_FUNC_TYPES = frozenset(
    {
        "function_declaration",
        "function_expression",
        "arrow_function",
        "method_definition",
        "generator_function_declaration",
    }
)

_parser_singleton: Parser | None = None


def _get_parser() -> Parser:
    global _parser_singleton
    if _parser_singleton is None:
        _parser_singleton = Parser(Language(tjs.language()))
    return _parser_singleton


# --------------------------------------------------------------------------- #
# Locations
# --------------------------------------------------------------------------- #


def parse_loc(s: str) -> dict[str, Any]:
    """Parse a Jelly loc string. Returns ``{"file_index": int}`` when the
    location is unknown (``"3:?:?:?:?"``), otherwise adds 0-based ``start`` /
    ``end`` ``{line, column}``."""
    parts = str(s).split(":")
    file_index = int(parts[0])
    if len(parts) < 5 or parts[1] in ("", "?"):
        return {"file_index": file_index}
    return {
        "file_index": file_index,
        "start": {"line": int(parts[1]), "column": int(parts[2]) - 1},
        "end": {"line": int(parts[3]), "column": int(parts[4]) - 1},
    }


def _cmp_lc(a: dict[str, int], b: dict[str, int]) -> int:
    if a["line"] != b["line"]:
        return a["line"] - b["line"]
    return a["column"] - b["column"]


def loc_key(file_names: list[str], parsed: dict[str, Any]) -> str:
    """Range key: ``startLine:startCol(1-based):endLine:endCol``. No file prefix —
    annotator analyzes a single JS file, so the path is always the same. (When
    exporting priors for Jelly the file is prepended again, since Jelly's
    locKey is file-prefixed.)"""
    if "start" not in parsed:
        return "?:?:?:?"
    start, end = parsed["start"], parsed["end"]
    return f"{start['line']}:{start['column'] + 1}:{end['line']}:{end['column'] + 1}"


@dataclass
class _Entry:
    """A function or callsite entry in the rebuilt model."""

    loc_key: str
    file_index: int
    file: str
    start: dict[str, int] | None
    end: dict[str, int] | None


@dataclass
class EffectiveGraph:
    """The override-applied call2fun view, shared by queries and heat."""

    call2fun_by_call: dict[int, set[int]]
    edges: list[dict[str, Any]]
    stats: dict[str, int]
    unresolved_includes: list[dict[str, str]]


@dataclass
class CallGraphModel:
    """In-memory Jelly call graph, keyed by stable loc keys."""

    file_names: list[str]
    functions: dict[int, _Entry]
    calls: dict[int, _Entry]
    fun_by_loc_key: dict[str, int] = field(default_factory=dict)
    call_by_loc_key: dict[str, int] = field(default_factory=dict)
    fun2fun: list[tuple[int, int]] = field(default_factory=list)
    call2fun_by_call: dict[int, set[int]] = field(default_factory=dict)
    call2caller: dict[int, int] = field(default_factory=dict)
    module_funs: set[int] = field(default_factory=set)
    entries: set[int] = field(default_factory=set)
    meta: dict[str, Any] = field(default_factory=dict)


def _map_calls_to_functions(
    functions: dict[int, _Entry], calls: dict[int, _Entry]
) -> dict[int, int]:
    """callsite -> innermost containing function.

    Mirrors src/misc/util.ts mapCallsToFunctions (containment by start point,
    innermost = smallest end). O(calls*funs); fine for the sizes annotator
    targets, easy to reason about.
    """
    call2fun: dict[int, int] = {}
    for call_index, call in calls.items():
        if call.start is None:
            continue
        best_index: int | None = None
        best_end: dict[str, int] | None = None
        for fun_index, fun in functions.items():
            if fun.start is None or fun.end is None:
                continue
            if (
                _cmp_lc(fun.start, call.start) <= 0
                and _cmp_lc(call.start, fun.end) <= 0
                and (best_end is None or _cmp_lc(fun.end, best_end) < 0)
            ):
                best_index = fun_index
                best_end = fun.end
        if best_index is not None:
            call2fun[call_index] = best_index
    return call2fun


def _identify_module_funs(functions: dict[int, _Entry]) -> set[int]:
    """Synthetic per-file module function: start (1,0) with the widest span."""
    file_to_mod: dict[int, tuple[int, dict[str, int]]] = {}
    for fun_index, fun in functions.items():
        if fun.start is None or fun.end is None:
            continue
        if fun.start["line"] != 1 or fun.start["column"] != 0:
            continue
        prev = file_to_mod.get(fun.file_index)
        if prev is None or _cmp_lc(fun.end, prev[1]) > 0:
            file_to_mod[fun.file_index] = (fun_index, fun.end)
    return {idx for idx, _ in file_to_mod.values()}


def _identify_entries(
    cg: dict[str, Any],
    functions: dict[int, _Entry],
    module_funs: set[int],
) -> set[int]:
    """Entry functions: the module function of each entry file (cg.entries), or
    of every non-node_modules file when entries are absent."""
    file_to_mod: dict[int, int] = {}
    for fun_index in module_funs:
        fun = functions[fun_index]
        if fun.start is not None:
            file_to_mod[fun.file_index] = fun_index

    entry_files: set[int] = set()
    entries = cg.get("entries") or []
    if entries:
        path_to_index = {f: i for i, f in enumerate(cg.get("files", []))}
        for e in entries:
            fi = path_to_index.get(e)
            if fi is not None:
                entry_files.add(fi)
    else:
        for i, f in enumerate(cg.get("files", [])):
            if "node_modules/" not in f:
                entry_files.add(i)

    return {file_to_mod[fi] for fi in entry_files if fi in file_to_mod}


def build_model(cg: dict[str, Any]) -> CallGraphModel:
    """Rebuild a :class:`CallGraphModel` from a Jelly call-graph dict."""
    file_names: list[str] = list(cg.get("files", []))
    functions: dict[int, _Entry] = {}
    calls: dict[int, _Entry] = {}
    fun_by_loc_key: dict[str, int] = {}
    call_by_loc_key: dict[str, int] = {}

    for idx, loc in (cg.get("functions") or {}).items():
        i = int(idx)
        p = parse_loc(loc)
        entry = _Entry(
            loc_key(file_names, p),
            p["file_index"],
            file_names[p["file_index"]],
            p.get("start"),
            p.get("end"),
        )
        functions[i] = entry
        if entry.start is not None:
            fun_by_loc_key[entry.loc_key] = i

    for idx, loc in (cg.get("calls") or {}).items():
        i = int(idx)
        p = parse_loc(loc)
        entry = _Entry(
            loc_key(file_names, p),
            p["file_index"],
            file_names[p["file_index"]],
            p.get("start"),
            p.get("end"),
        )
        calls[i] = entry
        if entry.start is not None:
            call_by_loc_key[entry.loc_key] = i

    fun2fun = [(int(a), int(b)) for a, b in (cg.get("fun2fun") or [])]
    call2fun_by_call: dict[int, set[int]] = {}
    for a, b in (cg.get("call2fun") or []):
        call_index, fun_index = int(a), int(b)
        if call_index in calls and fun_index in functions:
            call2fun_by_call.setdefault(call_index, set()).add(fun_index)

    call2caller = _map_calls_to_functions(functions, calls)
    module_funs = _identify_module_funs(functions)
    entries = _identify_entries(cg, functions, module_funs)

    return CallGraphModel(
        file_names=file_names,
        functions=functions,
        calls=calls,
        fun_by_loc_key=fun_by_loc_key,
        call_by_loc_key=call_by_loc_key,
        fun2fun=fun2fun,
        call2fun_by_call=call2fun_by_call,
        call2caller=call2caller,
        module_funs=module_funs,
        entries=entries,
        meta={
            "time": cg.get("time"),
            "ignore_dependencies": cg.get("ignoreDependencies"),
            "include_packages": cg.get("includePackages"),
            "exclude_packages": cg.get("excludePackages"),
        },
    )


def summarize(model: CallGraphModel) -> dict[str, int]:
    return {
        "files": len(model.file_names),
        "functions": len(model.functions),
        "calls": len(model.calls),
        "fun2fun": len(model.fun2fun),
        "call2fun": sum(len(s) for s in model.call2fun_by_call.values()),
        "entries": len(model.entries),
        "module_functions": len(model.module_funs),
    }


# --------------------------------------------------------------------------- #
# Manual edge overrides
# --------------------------------------------------------------------------- #


class CallEdgeOverrides:
    """Session-level (force include / force exclude) edge overrides, keyed by
    ``(callsite loc key, callee loc key)``.

    Only the rebuilt graph is affected (see module docstring).
    """

    def __init__(self) -> None:
        self._map: dict[str, dict[str, str]] = {}

    def set(self, callsite_loc_key: str, callee_loc_key: str, mode: str) -> str | None:
        if mode not in ("include", "exclude"):
            raise ValueError(f'mode must be "include" or "exclude", got: {mode}')
        inner = self._map.setdefault(callsite_loc_key, {})
        prev = inner.get(callee_loc_key)
        inner[callee_loc_key] = mode
        return prev

    def delete(self, callsite_loc_key: str, callee_loc_key: str) -> bool:
        inner = self._map.get(callsite_loc_key)
        if not inner:
            return False
        ok = inner.pop(callee_loc_key, None) is not None
        if ok and not inner:
            self._map.pop(callsite_loc_key, None)
        return ok

    def clear(self) -> None:
        self._map.clear()

    def get(self, callsite_loc_key: str, callee_loc_key: str) -> str | None:
        return self._map.get(callsite_loc_key, {}).get(callee_loc_key)

    @property
    def size(self) -> int:
        return sum(len(inner) for inner in self._map.values())

    def list(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for callsite, inner in self._map.items():
            for callee, mode in inner.items():
                out.append({"callsite": callsite, "callee": callee, "mode": mode})
        out.sort(
            key=lambda r: (r["callsite"], r["callee"])
        )
        return out

    def effective_edges(self, model: CallGraphModel) -> EffectiveGraph:
        """Apply overrides to ``model``: drop excluded base edges, add included
        edges, report overrides whose callsite/callee is absent from the
        current analysis as unresolved."""
        included: dict[int, set[int]] = {}
        excluded: dict[int, set[int]] = {}
        unresolved: list[dict[str, str]] = []

        for rule in self.list():
            call_index = model.call_by_loc_key.get(rule["callsite"])
            fun_index = model.fun_by_loc_key.get(rule["callee"])
            if call_index is None or fun_index is None:
                unresolved.append(
                    {
                        "callsite": rule["callsite"],
                        "callee": rule["callee"],
                        "reason": (
                            "callsite not found in current analysis"
                            if call_index is None
                            else "callee function not found in current analysis"
                        ),
                    }
                )
                continue
            target = included if rule["mode"] == "include" else excluded
            target.setdefault(call_index, set()).add(fun_index)

        call2fun_by_call: dict[int, set[int]] = {}
        edges: list[dict[str, Any]] = []
        base = inc = exc = 0
        for call_index, callees in model.call2fun_by_call.items():
            ex_set = excluded.get(call_index)
            acc: set[int] = set()
            for fun_index in callees:
                if ex_set and fun_index in ex_set:
                    exc += 1
                    edges.append(
                        {"call_index": call_index, "fun_index": fun_index, "source": "excluded"}
                    )
                    continue
                acc.add(fun_index)
                edges.append(
                    {"call_index": call_index, "fun_index": fun_index, "source": "base"}
                )
                base += 1
            call2fun_by_call[call_index] = acc

        for call_index, fun_indices in included.items():
            acc = call2fun_by_call.setdefault(call_index, set())
            for fun_index in fun_indices:
                if fun_index in acc:
                    continue
                acc.add(fun_index)
                edges.append(
                    {"call_index": call_index, "fun_index": fun_index, "source": "included"}
                )
                inc += 1

        return EffectiveGraph(
            call2fun_by_call=call2fun_by_call,
            edges=edges,
            stats={"base": base, "included": inc, "excluded": exc},
            unresolved_includes=unresolved,
        )


# --------------------------------------------------------------------------- #
# Loop depth (tree-sitter)
# --------------------------------------------------------------------------- #


def compute_loop_depths(
    model: CallGraphModel, root: Path, include_deps: bool = False
) -> dict[int, int]:
    """Per-callsite lexical loop-nesting depth, matched by (file, line).

    Iterative preorder DFS (safe on large/minified files): each frame carries
    the loop depth its children inherit; a function resets it to 0, a loop
    increments it. Byte offsets — never ``start_point`` — are turned into line
    numbers via :func:`utils.build_line_starts` (``.start_point`` segfaults the
    binding on some files, e.g. box2d.js). Files under node_modules are skipped
    unless ``include_deps``.
    """
    # (file_index, 1-based line) -> max loop depth on that line.
    line_depth: dict[tuple[int, int], int] = {}
    files_parsed = files_skipped = 0

    parser = _get_parser()
    for file_index, rel in enumerate(model.file_names):
        if not include_deps and "node_modules/" in rel:
            files_skipped += 1
            continue
        path = root / rel
        try:
            data = path.read_bytes()
        except OSError:
            continue
        try:
            tree = parser.parse(data)
        except Exception:  # tree-sitter raises native errors on broken input
            continue
        files_parsed += 1

        line_starts = build_line_starts(data)

        def row(byte: int) -> int:
            idx = bisect.bisect_right(line_starts, byte) - 1
            return (idx if idx >= 0 else 0) + 1  # 1-based

        # Iterative DFS: [node, next_child_index, depth_children_inherit].
        stack: list[list[Any]] = [[tree.root_node, 0, 0]]
        while stack:
            frame = stack[-1]
            node = frame[0]
            kids = node.children
            if frame[1] < len(kids):
                child = kids[frame[1]]
                frame[1] += 1
                own_depth = frame[2]
                if child.type in _CALL_TYPES:
                    line = row(child.start_byte)
                    key = (file_index, line)
                    if own_depth > line_depth.get(key, -1):
                        line_depth[key] = own_depth
                if child.type in _FUNC_TYPES:
                    child_depth = 0
                elif child.type in _LOOP_TYPES:
                    child_depth = own_depth + 1
                else:
                    child_depth = own_depth
                stack.append([child, 0, child_depth])
            else:
                stack.pop()

    depths: dict[int, int] = {}
    for call_index, entry in model.calls.items():
        if entry.start is None:
            continue
        depths[call_index] = line_depth.get((entry.file_index, entry.start["line"]), 0)
    return depths


# --------------------------------------------------------------------------- #
# Heat
# --------------------------------------------------------------------------- #


@dataclass
class HeatAssumptions:
    """User-supplied heat inputs, all keyed by stable loc keys."""

    function_hot: dict[str, float] = field(default_factory=dict)  # set_hot_value
    exec_expt: dict[str, float] = field(default_factory=dict)  # set_exec_expt (callsite)
    target_prob: dict[str, dict[str, float]] = field(default_factory=dict)  # callsite -> {callee: p}


@dataclass
class HeatParams:
    loop_weight: float = 10.0
    eps: float = 1e-6
    max_iter: int = 200


def _build_weighted(
    model: CallGraphModel,
    effective: EffectiveGraph,
    assumptions: HeatAssumptions,
    loop_depths: dict[int, int],
    params: HeatParams,
) -> tuple[dict[int, dict[int, float]], list[dict[str, Any]]]:
    """Aggregate ``weighted[caller][callee] = sum_s E(s)*P(s,f)`` over effective
    edges, validating target-probability constraints (finite, non-negative,
    per-callsite sum <= 1)."""
    weighted: dict[int, dict[int, float]] = {}
    reports: list[dict[str, Any]] = []

    for call_index, targets in effective.call2fun_by_call.items():
        caller_index = model.call2caller.get(call_index)
        if caller_index is None:
            continue
        call_entry = model.calls.get(call_index)
        call_loc_key = call_entry.loc_key if call_entry else None

        valid_targets = [f for f in targets if f not in model.module_funs]
        if not valid_targets:
            continue

        depth = loop_depths.get(call_index, 0)
        e = (
            assumptions.exec_expt[call_loc_key]
            if call_loc_key and call_loc_key in assumptions.exec_expt
            else params.loop_weight ** depth
        )

        explicit: dict[int, float] = {}
        sum_explicit = 0.0
        prob_map = assumptions.target_prob.get(call_loc_key) if call_loc_key else None
        if prob_map:
            for callee_loc_key, p in prob_map.items():
                if not math.isfinite(p) or p < 0:
                    raise ValueError(
                        f"invalid target probability {p} at callsite {call_loc_key}"
                    )
                f_idx = model.fun_by_loc_key.get(callee_loc_key)
                if f_idx is None or f_idx not in targets:
                    continue
                explicit[f_idx] = p
                sum_explicit += p
        if sum_explicit > 1 + 1e-9:
            raise ValueError(
                f"target probability sum {sum_explicit} > 1 at callsite {call_loc_key}"
            )

        unscaled = len(valid_targets) - len(explicit)
        remaining = 1 - sum_explicit
        each = remaining / unscaled if unscaled > 0 else 0.0

        for f in valid_targets:
            p = explicit[f] if f in explicit else each
            w = e * p
            if not w:
                continue
            weighted.setdefault(caller_index, {})
            weighted[caller_index][f] = weighted[caller_index].get(f, 0.0) + w

        reports.append(
            {
                "callsite": call_loc_key,
                "exec_expt": e,
                "loop_depth": depth,
                "targets": len(valid_targets),
                "explicit": len(explicit),
                "sum_explicit": sum_explicit,
                "unscaled": unscaled,
                "remaining": remaining,
            }
        )

    return weighted, reports


def _solve(
    n: int,
    weighted: dict[int, dict[int, float]],
    base: list[float],
    bound_value: dict[int, float],
    eps: float,
    max_iter: int,
) -> dict[str, Any]:
    bound = bound_value.__contains__
    v = [0.0] * n
    iterations = 0
    converged = False
    residual = 0.0
    divergent = False

    for iterations in range(1, max_iter + 1):
        nxt = [bound_value[i] if bound(i) else base[i] for i in range(n)]
        for a, succ in weighted.items():
            if a >= n:
                continue
            va = bound_value[a] if bound(a) else v[a]
            if not va:
                continue
            for b, w in succ.items():
                if b >= n or bound(b):
                    continue
                nxt[b] += va * w
        if any(math.isinf(x) or math.isnan(x) for x in nxt):
            divergent = True
            break
        residual = sum(abs(nxt[i] - v[i]) for i in range(n))
        v = nxt
        if residual < eps:
            converged = True
            break

    return {
        "v": v,
        "iterations": iterations,
        "converged": converged,
        "residual": residual,
        "divergent": divergent,
        "capped": not converged and not divergent,
    }


def compute_heat(
    model: CallGraphModel,
    effective: EffectiveGraph,
    assumptions: HeatAssumptions,
    params: HeatParams,
    loop_depths: dict[int, int],
) -> dict[str, Any]:
    """Estimate per-function heat (expected calls per entry execution).

    ``set_hot_value`` is a *hard* override: that function is fixed to the given
    value, its outbound contributions use that value, and inbound contributions
    to it are ignored. Recursive positive-weight cycles may diverge; such
    functions surface ``status: "divergent"`` (or ``"capped"`` when iteration
    hit the cap without divergence) rather than a misleading finite ranking.
    """
    weighted, reports = _build_weighted(
        model, effective, assumptions, loop_depths, params
    )

    max_index = max(model.functions, default=-1)
    n = max_index + 1
    base = [1.0 if i in model.entries else 0.0 for i in range(n)]

    bound_value: dict[int, float] = {}
    for loc_key, value in assumptions.function_hot.items():
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"invalid hot value {value} for function {loc_key}")
        f_idx = model.fun_by_loc_key.get(loc_key)
        if f_idx is not None:
            bound_value[f_idx] = value

    sol = _solve(n, weighted, base, bound_value, params.eps, params.max_iter)
    v = sol["v"]
    divergent = sol["divergent"]
    capped = sol["capped"]

    # Reachability from entries along the effective weighted graph.
    adj = {a: list(succ) for a, succ in weighted.items()}
    reachable = set(model.entries)
    stack = list(model.entries)
    while stack:
        a = stack.pop()
        for b in adj.get(a, []):
            if b not in reachable:
                reachable.add(b)
                stack.append(b)

    in_degree = [0] * n
    max_loop_depth = [0] * n
    for succ in weighted.values():
        for b in succ:
            in_degree[b] += 1
    for call_index, callees in effective.call2fun_by_call.items():
        d = loop_depths.get(call_index, 0)
        for f in callees:
            if f not in model.module_funs and d > max_loop_depth[f]:
                max_loop_depth[f] = d

    def status_for(fun_index: int) -> str:
        val = v[fun_index] if fun_index < n else 0.0
        if divergent and (math.isinf(val) or math.isnan(val)):
            return "divergent"
        if divergent or capped:
            return "capped"
        return "finite"

    per_function: list[dict[str, Any]] = []
    for fun_index, entry in model.functions.items():
        val = v[fun_index] if fun_index < n else 0.0
        per_function.append(
            {
                "loc_key": entry.loc_key,
                "file": entry.file,
                "line": entry.start["line"] if entry.start else None,
                "start_line": entry.start["line"] if entry.start else None,
                "end_line": entry.end["line"] if entry.end else None,
                "hot": val if math.isfinite(val) else None,
                "is_bound": fun_index in bound_value,
                "is_entry": fun_index in model.entries,
                "is_reachable": fun_index in reachable,
                "is_module_function": fun_index in model.module_funs,
                "inbound_contribution": (
                    None
                    if fun_index in bound_value
                    else max(0.0, val - base[fun_index])
                ),
                "in_degree": in_degree[fun_index],
                "max_loop_depth": max_loop_depth[fun_index],
                "status": status_for(fun_index),
            }
        )

    per_function.sort(key=lambda r: (r["hot"] if r["hot"] is not None else -1.0), reverse=True)
    for i, r in enumerate(per_function):
        r["rank"] = i + 1

    return {
        "model": "expected-call-count",
        "status": "divergent" if divergent else ("capped" if capped else "converged"),
        "params": {
            "loop_weight": params.loop_weight,
            "eps": params.eps,
            "max_iter": params.max_iter,
            "functions": len(model.functions),
            "entries": len(model.entries),
            "reachable": len(reachable),
            "iterations": sol["iterations"],
            "residual": sol["residual"],
        },
        "override_stats": effective.stats,
        "assumptions": {
            "hot_value_overrides": len(assumptions.function_hot),
            "exec_expt_overrides": len(assumptions.exec_expt),
            "target_prob_callsites": len(assumptions.target_prob),
        },
        "per_function": per_function,
        "callsite_reports": reports,
    }
