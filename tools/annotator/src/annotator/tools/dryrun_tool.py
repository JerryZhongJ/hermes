"""In-process MCP dry-run tools: feedback on annotation effects.

Two tools over the host-side ``annotation-dryrun`` binary (hermes stays on the
host; the agent talks to it via a file protocol over the bind-mounted workdir):

- ``dryrun_annotation`` (run): compile the source + annotation, cache the full
  result, return a run id + summary. One run can be queried many times.
- ``query_feedback`` (query): read a cached run (default latest; ``run=-2`` for
  the previous run, etc.), filter to a line range, render per-annotation
  optimized / killed-by / no-effect feedback.

Run results are cached under ``workdir/.feedback/cache/<run_id>.json`` so the
agent can re-query a range or compare against history without recompiling.

The C++ tool only emits raw data (annotation range/kind/detail + per-effect
location + IR instruction name). This module owns all classification
(numeric/generic, property read/write) and rendering — never shows annotationId
or IR instruction names to the agent.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from .utils import _err, resolve_in_workdir

FEEDBACK_SUBDIR = ".feedback"
CACHE_SUBDIR = ".feedback/cache"
REQ_FILE = "req.json"
RES_FILE = "res.json"
POLL_INTERVAL_S = 0.1
# Host poll latency (0.1s) + worst-case annotation-dryrun run (30s) + slack.
TIMEOUT_S = 60


# --- classification (IR instruction name -> human category) ---

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _count(n: int, word: str) -> str:
    """1 kill / 6 kills — singular/plural noun count."""
    return f"{n} {word}{'s' if n != 1 else ''}"


def _categorize(inst: str) -> str:
    if inst.startswith("PrLoad"):
        return "property read"
    if inst.startswith("PrStore"):
        return "property write"
    if inst.startswith("LoadProperty"):
        return "property read (unknown shape)"
    if inst.startswith("StoreProperty") or inst.startswith("StoreOwnProperty"):
        return "property write (unknown shape)"
    # Global property load/store (Math.sqrt's Math, custom globals, …).
    # These read/write the global object and conservatively pollute shape facts
    # (getter side effects / mutable global), so they surface as blockages.
    if inst.startswith("TryLoadGlobalProperty") or inst.startswith(
        "LoadGlobalProperty"
    ):
        return "global property read"
    if inst.startswith("TryStoreGlobalProperty") or inst.startswith(
        "StoreGlobalProperty"
    ):
        return "global property write"
    if inst.startswith("Call"):
        return "call"
    # arithmetic / comparison / unary — all operations whose side effect
    # depends on operand types; one "operation" label (matches the prompt).
    # F-prefix = numeric specialization (side-effect-free); otherwise generic
    # (may run valueOf/toString, kills shape).
    is_numeric = inst.startswith("F")
    if any(
        k in inst
        for k in (
            "Add",
            "Subtract",
            "Multiply",
            "Divide",
            "Modulo",
            "Exp",
            "Bitwise",
            "Shift",
            "Negate",
            "Minus",
            "Plus",
            "Less",
            "Greater",
            "Equal",
            "Compare",
            "UnaryMath",  # FUnaryMathInst: numeric unary (e.g. FNegate)
        )
    ):
        return "numeric operation" if is_numeric else "generic operation"
    return inst  # fallback: show raw name


def _desc(e: dict, optimize: bool) -> str:
    cat = _categorize(e.get("instruction", ""))
    prop = e.get("property")
    ps = f" .{prop}" if prop else ""
    loc = e.get("location", "?")  # IR instruction site (single point)
    if optimize:
        return f"  ✓ optimized {loc} {cat}{ps}"
    return f"  ! killed by {loc} {cat}{ps}"


def _desc_miss(e: dict) -> str:
    # miss: a property access on the guarded object that stayed on the generic
    # path (LoadProperty/StoreProperty, not optimized into PrLoad/PrStore).
    inst = e.get("instruction", "")
    cat = "property write" if inst.startswith("Store") else "property read"
    prop = e.get("property")
    ps = f" .{prop}" if prop else ""
    loc = e.get("location", "?")
    return f"  ? {loc} {cat}{ps} not optimized"


# --- line-range filtering ---

def _line_of(loc: str | None) -> int | None:
    """Leading 1-based line from 'line:col' or 'line:col-line:col'."""
    if not loc or loc == "?":
        return None
    s = loc.split("-")[0].split(":")[0]
    try:
        return int(s)
    except ValueError:
        return None


def _in_range(loc: str | None, from_line: int | None, to_line: int | None) -> bool:
    if from_line is None and to_line is None:
        return True
    line = _line_of(loc)
    if line is None:
        return False
    if from_line is not None and line < from_line:
        return False
    if to_line is not None and line > to_line:
        return False
    return True


def _filter_annotations(
    data: dict[str, Any], from_line: int | None, to_line: int | None
) -> list[dict[str, Any]]:
    """Pick annotations + effects visible in the range.

    A annotation header shows iff the annotation's own range is in range OR any
    of its effects is in range (so an effect always has its owner shown, and an
    in-range no-effect annotation isn't dropped). Effects show iff in range;
    out-of-range effects are counted into ``opt_out``/``blk_out`` for the
    "... somewhere else" hint.
    """
    out: list[dict[str, Any]] = []
    for a in data.get("annotations", []):
        orig_opt = a.get("optimizations", [])
        orig_blk = a.get("blockages", [])
        orig_miss = a.get("miss", [])
        opt_in = [o for o in orig_opt if _in_range(o.get("location"), from_line, to_line)]
        blk_in = [b for b in orig_blk if _in_range(b.get("location"), from_line, to_line)]
        miss_in = [p for p in orig_miss if _in_range(p.get("location"), from_line, to_line)]
        a_in = _in_range(a.get("range"), from_line, to_line)
        if not (a_in or opt_in or blk_in or miss_in):
            continue
        out.append(
            {
                **a,
                "opt_in": opt_in,
                "blk_in": blk_in,
                "miss_in": miss_in,
                "opt_out": len(orig_opt) - len(opt_in),
                "blk_out": len(orig_blk) - len(blk_in),
                "miss_out": len(orig_miss) - len(miss_in),
                "had_opt": bool(orig_opt),
                "had_miss": bool(orig_miss),
            }
        )
    return out


def _dedup_effects(
    effects: list[dict[str, Any]], skip: set[str] | None = None
) -> list[dict[str, Any]]:
    """Keep the first effect per source location, dropping any whose location is
    in ``skip``. The C++ tool scans the whole function (including InsertGuard's
    spec/generic duplicated paths), so one source point can surface several
    times — collapse to one."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for e in effects:
        loc = e.get("location") or ""
        if skip and loc in skip:
            continue
        if loc in seen:
            continue
        seen.add(loc)
        out.append(e)
    return out


def _dedup(data: dict[str, Any]) -> None:
    """Presentation-layer cleanup, in place:
    - blockages: one per source location (spec/generic both pollute);
    - miss: a location already optimized (PrLoad/PrStore) is not missing, then
      one per location."""
    for a in data.get("annotations", []):
        a["blockages"] = _dedup_effects(a.get("blockages", []))
        opt_locs = {e.get("location") or "" for e in a.get("optimizations", [])}
        a["miss"] = _dedup_effects(a.get("miss", []), skip=opt_locs)


def _render(filtered: list[dict[str, Any]], stderr: str) -> str:
    lines: list[str] = []
    if stderr.strip():
        lines.append("Warnings:")
        for line in stderr.splitlines():
            clean = _ANSI_RE.sub("", line).rstrip()
            if clean:
                lines.append("  " + clean)
    # optimized / no-effect are one dimension (per annotation); killed-by is the
    # other; unoptimized is a third (shape guards only). The three are
    # independent — an annotation can be optimized in some places, killed in
    # others, and have uncovered properties.
    no = nb = nu = nmiss = 0
    body: list[str] = []
    for a in filtered:
        opt_in = a["opt_in"]
        blk_in = a["blk_in"]
        miss_in = a["miss_in"]
        no += len(opt_in)
        nb += len(blk_in)
        nmiss += len(miss_in)
        body.append(
            f'[{a.get("range", "?")}] {a.get("kind", "?")} "{a.get("detail", "")}":'
        )
        if a["had_opt"]:
            for o in opt_in:
                body.append(_desc(o, True))
        elif not a["had_miss"]:
            # only truly idle when it optimized nothing AND found no missing
            # property; otherwise the guard still revealed coverage info.
            nu += 1
            body.append("  ✗ no effect")
        for p in miss_in:
            body.append(_desc_miss(p))
        for b in blk_in:
            body.append(_desc(b, False))
        opt_out = a["opt_out"]
        blk_out = a["blk_out"]
        miss_out = a["miss_out"]
        if opt_out or blk_out or miss_out:
            parts = []
            if opt_out:
                parts.append(f"{opt_out} optimized")
            if miss_out:
                parts.append(f"{miss_out} unoptimized")
            if blk_out:
                parts.append(_count(blk_out, "kill"))
            body.append(f"  … {' / '.join(parts)} somewhere else")
    if body:
        lines.append("Effects:")
        lines.extend(body)
    lines.append(
        f"Summary: {no} optimized  {_count(nb, 'kill')}  "
        f"{nu} no-effect  {nmiss} unoptimized"
    )
    return "\n".join(lines)


# --- host file protocol (run annotation-dryrun on the host) ---

def _request(
    fb: Path, annotation_rel: str | None
) -> dict[str, Any] | None:
    """Write req.json, poll res.json, return the raw host result (or None on
    timeout). No from_line/to_line — the run is always whole-file; filtering is
    done at query time over the cached result.

    The request carries only the (variable) annotation path, relative to the
    workdir — never the source file (fixed for the run, bound at the host
    dryrun_service) and never absolute /work container paths."""
    req_id = uuid.uuid4().hex
    req: dict[str, Any] = {"req_id": req_id}
    if annotation_rel:
        req["annotation"] = annotation_rel
    try:
        fb.mkdir(parents=True, exist_ok=True)
        (fb / REQ_FILE).write_text(json.dumps(req), encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"could not write request: {exc}")
    res_path = fb / RES_FILE
    deadline = time.time() + TIMEOUT_S
    while time.time() < deadline:
        if res_path.exists():
            try:
                res = json.loads(res_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                time.sleep(POLL_INTERVAL_S)
                continue
            if res.get("req_id") == req_id:
                res_path.unlink(missing_ok=True)
                return res
        time.sleep(POLL_INTERVAL_S)
    return None


# --- run cache ---

def _run_ids(cache_dir: Path) -> list[int]:
    return sorted(
        int(f.stem) for f in cache_dir.glob("*.json") if f.stem.isdigit()
    )


def _next_run_id(cache_dir: Path) -> int:
    ids = _run_ids(cache_dir)
    return (ids[-1] + 1) if ids else 1


def _save_run(
    cache_dir: Path, run_id: int, data: dict, stderr: str, annotation: str
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{run_id}.json").write_text(
        json.dumps(
            {"run_id": run_id, "data": data, "stderr": stderr, "annotation": annotation}
        ),
        encoding="utf-8",
    )


def _load_run(cache_dir: Path, run: int | None) -> dict[str, Any] | None:
    """Resolve a run: None/-1 = latest, -n = nth-from-latest, k>0 = run id k."""
    ids = _run_ids(cache_dir)
    if not ids:
        return None
    if run is None or run == -1:
        target = ids[-1]
    elif run < 0:
        idx = len(ids) + run  # -1 -> len-1 (latest), -2 -> len-2, ...
        if not 0 <= idx < len(ids):
            return None
        target = ids[idx]
    else:
        target = run if run in ids else None
    if target is None:
        return None
    try:
        return json.loads((cache_dir / f"{target}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _full_summary(data: dict[str, Any]) -> str:
    anns = data.get("annotations", [])
    no = sum(len(a.get("optimizations", [])) for a in anns)
    nb = sum(len(a.get("blockages", [])) for a in anns)
    nmiss = sum(len(a.get("miss", [])) for a in anns)
    nu = sum(1 for a in anns if not a.get("optimizations") and not a.get("miss"))
    return (
        f"{no} optimized  {_count(nb, 'kill')}  "
        f"{nu} no-effect  {nmiss} unoptimized"
    )


# --- the two MCP tools ---

def build_dryrun_tools(workdir: Path) -> list:
    """Build ``dryrun_annotation`` + ``query_feedback``, bound to ``workdir``
    (cache + request dropbox). The source file is NOT bound here — it is fixed
    at the host dryrun_service; the request carries only the annotation.

    Exposed for tests to drive handlers directly with a fake host service.
    """
    workdir_resolved = workdir.resolve()
    fb = workdir / FEEDBACK_SUBDIR
    cache_dir = workdir / CACHE_SUBDIR

    @tool(
        "dryrun_annotation",
        "Compile the source with your annotation file and cache the result. "
        "Returns a run id + whole-file summary (optimized / kills / no-effect / "
        "unoptimized). Cheap to re-run after each annotation edit. Use "
        "query_feedback to inspect a line range or compare against a previous run.",
        {
            "type": "object",
            "properties": {
                "annotation": {
                    "type": "string",
                    "description": "annotation JSON filename relative to the workdir",
                },
            },
            "required": ["annotation"],
        },
    )
    async def dryrun_annotation(args: dict[str, Any]) -> dict[str, Any]:
        ann_arg = args.get("annotation")
        if not isinstance(ann_arg, str) or not ann_arg:
            return _err("missing 'annotation'")
        err = resolve_in_workdir(workdir_resolved, ann_arg)[1]
        if err is not None:
            return err

        try:
            res = _request(fb, ann_arg)
        except RuntimeError as exc:
            return _err(str(exc))
        if res is None:
            return _err("timeout waiting for host feedback service (is it running?)")
        if not res.get("ok"):
            return _err(
                "annotation-dryrun failed: " + (res.get("stderr") or "")[:400]
            )
        try:
            data = json.loads(res.get("stdout") or "{}")
        except ValueError:
            return _err("annotation-dryrun produced non-JSON output")
        _dedup(data)
        stderr = res.get("stderr") or ""

        run_id = _next_run_id(cache_dir)
        _save_run(cache_dir, run_id, data, stderr, ann_arg)
        text = (
            f"run #{run_id} cached. Summary: {_full_summary(data)}.\n"
            f"Use query_feedback to inspect (optionally run= / from_line= / to_line=)."
        )
        return {"content": [{"type": "text", "text": text}]}

    @tool(
        "query_feedback",
        "Inspect cached dryrun feedback, optionally filtered to a line range. "
        "Per annotation: optimized points (✓), killed-by points (! the polluter), "
        "unoptimized points (? a property access the guard didn't reach — "
        "generic LoadProperty/StoreProperty), or 'no effect'. "
        "Out-of-range "
        "effects are summarized as 'somewhere else'. "
        "run: omit or -1 = latest, -2 = previous run, … k>0 = run id k.",
        {
            "type": "object",
            "properties": {
                "run": {
                    "type": "integer",
                    "description": "which run: -1/omit = latest, -2 = previous, k>0 = run id k",
                },
                "from_line": {
                    "type": "integer",
                    "description": "1-based start line (inclusive); omit for whole file",
                },
                "to_line": {
                    "type": "integer",
                    "description": "1-based end line (inclusive); omit for whole file",
                },
            },
        },
    )
    async def query_feedback(args: dict[str, Any]) -> dict[str, Any]:
        try:
            run = args.get("run")
            run = int(run) if run is not None else None
            fl = args.get("from_line")
            tl = args.get("to_line")
            from_line = int(fl) if fl is not None else None
            to_line = int(tl) if tl is not None else None
        except (TypeError, ValueError):
            return _err("run/from_line/to_line must be integers")

        rec = _load_run(cache_dir, run)
        if rec is None:
            return _err(
                f"no cached run for run={run}; call dryrun_annotation first"
            )
        _dedup(rec["data"])  # idempotent: covers runs cached before _dedup existed
        filtered = _filter_annotations(rec["data"], from_line, to_line)
        body = _render(filtered, rec.get("stderr", ""))
        header = f"run #{rec['run_id']}"
        if from_line is not None or to_line is not None:
            header += (
                f"  lines {from_line if from_line is not None else 1}"
                f"-{to_line if to_line is not None else 'end'}"
            )
        return {"content": [{"type": "text", "text": header + "\n" + body}]}

    return [dryrun_annotation, query_feedback]


def make_dryrun_server(workdir: Path):
    """Build an in-process MCP server exposing dryrun_annotation + query_feedback."""
    return create_sdk_mcp_server(
        name="dryrun",
        tools=build_dryrun_tools(workdir),
    )
