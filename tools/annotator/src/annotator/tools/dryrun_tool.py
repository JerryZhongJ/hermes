"""In-process MCP dry-run tools: feedback on annotation effects.

One tool over the host-side ``annotation-dryrun`` binary (hermes stays on the
host; the agent talks to it via a file protocol over the bind-mounted workdir):

- ``dryrun``: compile the source against the CURRENT in-memory annotation
  draft and return a whole-file summary plus per-annotation optimized /
  killed-by / unoptimized / no-effect feedback, optionally filtered by scope and
  feedback type.

Compilations go through a shared content-fingerprinted report cache (see
:class:`ReportCache`), so an unchanged draft never recompiles: ``dryrun``,
``list_checklist``, and the coverage follow-up hook all reuse the same cached
report. Fresh results are also persisted under
``workdir/.feedback/cache/<run_id>.json``.

The C++ tool only emits raw data (annotation range/kind/detail + per-effect
location + IR instruction name). This module owns all classification
(numeric/generic, property read/write) and rendering — never shows annotationId
or IR instruction names to the agent.

Unmatched annotations (target range that emitted no annotation IR, so they
never leave a trace in the IR) are auto-pruned from the draft after each
compile and reported — see :func:`_prune_unmatched`.
"""


from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import uuid
from collections.abc import Awaitable, Set
from pathlib import Path
from typing import Any

# An awaitable that runs one annotation-dryrun against the current draft
# snapshot and returns the parsed report dict (raising on host/compile failure).
CompileFn = Awaitable[dict[str, Any]]

from claude_agent_sdk import create_sdk_mcp_server, tool

from ..annotation_drafts import DraftsError, drafts

from .functions import ScopeSelection, resolve_scope
from .utils import _err, atomic_write_json

PROMPT = (
    "- After changing annotations via add_annotation/batch_add_guards/delete_annotation, call `dryrun` to check their effect — it compiles the file (trimmed pipeline, no execution) against the CURRENT in-memory draft (pass draft= when several are available to you) and returns a whole-file summary (optimized / killed / no-effect) plus per-annotation detail, optionally narrowed by a scope — a function loc_key like \"31:1\" means that function's DIRECT statements only (nested functions are independent scopes, pass their own loc_keys), \"<top-level>\" addresses module-level annotations, a list of loc_keys, a line range like \"31-45\" (items whose own line falls inside), or \"file\" — and `feedback_types=[\"effect\", \"killed\", \"unoptimized\"]` (`effect` = optimized only; `unoptimized` = a property access this shape guard reaches that did NOT become a fast-path access — empty without shape guards; omit for all). Two diagnostics are ALWAYS shown for annotations in scope regardless of feedback_types: \"✗ no effect\" (the annotation produced no optimization anywhere) and missing-binding — so an annotation absent from the detail list means only that your scope does not cover it. Compiles automatically on demand: unchanged annotations reuse the last compile, so it is cheap to re-query after each add/delete. Per annotation it also reports independent load/binding failures; out-of-scope selected feedback shows as \"somewhere else\". Annotations whose target range matched no IR (unmatched) are auto-pruned — deleted from the draft and reported — because they never reach the IR; re-add one only with a corrected target range. Iterate until no failures and no surprising kills."
)

FEEDBACK_SUBDIR = ".feedback"
CACHE_SUBDIR = ".feedback/cache"
REQUESTS_SUBDIR = "requests"
RESPONSES_SUBDIR = "responses"
SNAPSHOTS_SUBDIR = "snapshots"
POLL_INTERVAL_S = 0.1
# Allow one running and several queued host jobs; each host run is capped at 30s.
TIMEOUT_S = 180
FEEDBACK_TYPES = ("effect", "killed", "unoptimized")


# --- classification (IR instruction name -> human category) ---

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


# --- unmatched-annotation auto-prune --------------------------------------- #
#
# AnnotationLoader warns when an annotation's target range covers no mountable
# instruction: the annotation never reaches the IR, so it is pure dead weight.
# Agents clean these warnings inconsistently, so ``dryrun`` deletes them from
# the draft itself and reports the deletions — an agent re-adds one only with a
# corrected target range.

# /path/file.js:LINE:COL: warning: annotation [KIND "NAME"] unmatched: ...
# The loc is the annotation's target-range start; the name cites the item
# field listed in _UNMATCHED_KINDS. "prototype shape guard" must precede
# "shape guard" in the alternation.
_UNMATCHED_RE = re.compile(
    r":(?P<line>\d+):(?P<col>\d+): warning: annotation \["
    r"(?P<kind>prototype shape guard|shape guard|shape binding|type guard)"
    r' "(?P<name>[^"]*)"\] unmatched:'
)

# warning kind text -> (document kind, item field the warning's name cites)
_UNMATCHED_KINDS = {
    "shape guard": ("shape_guard", "shape"),
    "prototype shape guard": ("shape_guard", "prototype shape"),
    "shape binding": ("shape_binding", "shape"),
    "type guard": ("type_guard", "type"),
}

def _unmatched_candidates(stderr: str) -> list[tuple[str, str, int, int]]:
    """(kind text, name, line, column) for each unmatched-annotation warning."""
    out: list[tuple[str, str, int, int]] = []
    for line in stderr.splitlines():
        m = _UNMATCHED_RE.search(_ANSI_RE.sub("", line))
        if m:
            out.append((m["kind"], m["name"], int(m["line"]), int(m["col"])))
    return out


def _strip_unmatched(stderr: str) -> str:
    """stderr minus the unmatched lines — they move to the prune section."""
    return "\n".join(
        line
        for line in stderr.splitlines()
        if not _UNMATCHED_RE.search(_ANSI_RE.sub("", line))
    )


def _cited_name(value: Any) -> Any:
    """How AnnotationLoader renders a cited field inside the warning name."""
    return "|".join(value) if isinstance(value, list) else value


def _prune_unmatched(draft: str, stderr: str) -> tuple[list[str], list[str]]:
    """Delete the draft annotations this compile flagged as unmatched.

    A warning's loc equals the annotation's target-range start and its name
    cites the item's ``shape`` / ``prototype shape`` / ``type`` field — enough
    to address the item exactly like ``delete_annotation`` does. An address
    that still resolves to several items is left untouched and reported for
    manual handling; zero hits (already deleted by hand) is silently skipped.
    Deletion goes through the document's validated ``delete_array_item``.
    Returns ``(pruned labels, unresolved labels)``.
    """
    from .annotation_tool import (
        KIND_SHAPE_BINDING,
        KIND_SHAPE_GUARD,
        KIND_TYPE_GUARD,
    )

    arrays = {
        KIND_SHAPE_GUARD: "shape_guards",
        KIND_SHAPE_BINDING: "shape_bindings",
        KIND_TYPE_GUARD: "type_guards",
    }
    candidates = _unmatched_candidates(stderr)
    if not candidates:
        return [], []
    pruned: list[str] = []
    unresolved: list[str] = []
    doomed: dict[str, list[int]] = {}
    with drafts().lock(draft):
        doc = drafts().get(draft)
        for kind_text, want, line, col in candidates:
            kind, field = _UNMATCHED_KINDS[kind_text]
            array = getattr(doc, arrays[kind])
            hits = [
                i
                for i, item in enumerate(array)
                if item["target range"]["start"]["line"] == line
                and item["target range"]["start"]["column"] == col
            ]
            if not hits:
                continue  # already gone (deleted by hand): nothing to do
            named = [i for i in hits if _cited_name(array[i].get(field)) == want]
            # Disambiguate by the warning's name; fall back to the sole
            # range-start hit only when the name matched nothing.
            if len(named) == 1:
                chosen = named
            elif not named and len(hits) == 1:
                chosen = hits
            else:
                unresolved.append(f'{kind} "{want}" @{line}:{col}')
                continue
            doomed.setdefault(kind, []).append(chosen[0])
            pruned.append(f'{kind} "{want}" @{line}:{col}')
        # Highest index first: earlier indices stay valid while popping.
        for kind, indices in doomed.items():
            for i in sorted(set(indices), reverse=True):
                doc.delete_array_item(kind, i)
    return pruned, unresolved


def _prune_section(pruned: list[str], unresolved: list[str]) -> str:
    """The report tail telling the agent what was auto-deleted (and what not)."""
    lines: list[str] = []
    if pruned:
        lines.append(
            f"Auto-pruned {_count(len(pruned), 'annotation')} that matched no "
            "IR (unmatched target ranges are useless and never reach the IR):"
        )
        lines.extend(f"  - {p}" for p in pruned)
    if unresolved:
        lines.append("could not prune (ambiguous) — fix or delete these by hand:")
        lines.extend(f"  ? {u}" for u in unresolved)
    return "\n".join(lines)


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


# --- scope filtering --------------------------------------------------------- #
#
# Scope selection is delegated to the shared ownership resolver
# (functions.ScopeSelection): feedback points ("line:col" instruction sites)
# via owns_loc, annotation entries via selects_range on their target range.
# A line-range scope keeps the historical point-in-window / range-overlap
# behavior; loc_key scopes now mean the owning function's DIRECT statements
# only (nested functions are independent scopes).

def _is_no_effect(a: dict[str, Any]) -> bool:
    """The guard had neither an optimization nor an uncovered property use."""
    return not a.get("optimizations") and not a.get("miss") and not a.get(
        "missingBinding"
    )


def _filter_annotations(
    data: dict[str, Any],
    selection: ScopeSelection,
    feedback_types: Set[str],
) -> list[dict[str, Any]]:
    """Project annotations to the selected feedback types and scope."""
    out: list[dict[str, Any]] = []
    for a in data.get("annotations", []):
        orig_opt = a.get("optimizations", [])
        orig_blk = a.get("blockages", [])
        orig_miss = a.get("miss", [])
        opt_in = (
            [o for o in orig_opt if selection.owns_loc(o.get("location"))]
            if "effect" in feedback_types
            else []
        )
        blk_in = (
            [b for b in orig_blk if selection.owns_loc(b.get("location"))]
            if "killed" in feedback_types
            else []
        )
        miss_in = (
            [p for p in orig_miss if selection.owns_loc(p.get("location"))]
            if "unoptimized" in feedback_types
            else []
        )
        a_in = selection.selects_range(a.get("range"))
        unopt_binding_selects = a_in and bool(a.get("missingBinding"))
        selected_at_annotation = a_in and (
            ("effect" in feedback_types and bool(orig_opt))
            or ("killed" in feedback_types and bool(orig_blk))
            or ("unoptimized" in feedback_types and bool(orig_miss))
        )
        owner_selected = bool(
            selected_at_annotation
            or unopt_binding_selects
            or opt_in
            or blk_in
            or miss_in
        )
        # no-effect is an always-on diagnostic (like missing-binding): an
        # annotation in scope with no feedback of any kind must still show,
        # regardless of the requested feedback types — otherwise "absent"
        # silently means "did nothing" and the agent cannot tell the two
        # apart.
        no_effect_in = _is_no_effect(a) and (a_in or owner_selected)
        selected = owner_selected or no_effect_in
        if not selected:
            continue
        out.append(
            {
                **a,
                "opt_in": opt_in,
                "blk_in": blk_in,
                "miss_in": miss_in,
                "opt_out": len(orig_opt) - len(opt_in)
                if "effect" in feedback_types
                else 0,
                "blk_out": len(orig_blk) - len(blk_in)
                if "killed" in feedback_types
                else 0,
                "miss_out": len(orig_miss) - len(miss_in)
                if "unoptimized" in feedback_types
                else 0,
                "no_effect_in": no_effect_in,
                # Independent diagnostic: once the owner is selected by its range
                # or a visible feedback point, always explain that its guard fails.
                "missing_binding_in": bool(a.get("missingBinding")),
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


def _render(
    filtered: list[dict[str, Any]], stderr: str, feedback_types: Set[str]
) -> str:
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
        if a["missing_binding_in"]:
            body.append(
                f'  ⚠ no shape binding for "{a["missingBinding"]}" — guard always fails'
            )
        for o in opt_in:
            body.append(_desc(o, True))
        if a["no_effect_in"]:
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
    summary = []
    if "effect" in feedback_types:
        summary.append(f"{no} optimized")
    if "killed" in feedback_types:
        summary.append(_count(nb, "kill"))
    if "effect" in feedback_types:
        summary.append(f"{nu} no-effect")
    if "unoptimized" in feedback_types:
        summary.append(f"{nmiss} unoptimized")
    lines.append("Summary: " + "  ".join(summary))
    return "\n".join(lines)


# --- host file protocol (run annotation-dryrun on the host) ---

def _request(fb: Path, req_id: str, annotation_rel: str) -> dict[str, Any] | None:
    """Atomically publish one request and wait only for its response file."""
    req_path = fb / REQUESTS_SUBDIR / f"{req_id}.json"
    res_path = fb / RESPONSES_SUBDIR / f"{req_id}.json"
    try:
        atomic_write_json(
            req_path,
            {"req_id": req_id, "annotation": annotation_rel},
        )
    except OSError as exc:
        raise RuntimeError(f"could not write request: {exc}")

    deadline = time.monotonic() + TIMEOUT_S
    while time.monotonic() < deadline:
        if res_path.exists():
            try:
                res = json.loads(res_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                time.sleep(POLL_INTERVAL_S)
                continue
            res_path.unlink(missing_ok=True)
            if not isinstance(res, dict) or res.get("req_id") != req_id:
                raise RuntimeError("host returned a mismatched request id")
            return res
        time.sleep(POLL_INTERVAL_S)
    return None


# --- shared report cache (content fingerprint -> compiled report) --------- #


def _draft_stamp(draft: str | None) -> str | None:
    """One draft's content fingerprint: JSON of its document + reason revision.

    None when the draft cannot be resolved (callers then always recompile —
    the safe fallback). Reasons ride along so a ``check``/``uncheck`` mutation
    invalidates the stamp even though the document itself did not change.
    """
    if draft is None:
        return None
    try:
        from ..annotation_drafts import drafts
        from .checklist_tool import reasons

        with drafts().lock(draft):
            doc_stamp = json.dumps(drafts().get(draft).to_dict(), sort_keys=True)
        return f"{doc_stamp}\nrev={reasons().revision(draft)}"
    except Exception:  # noqa: BLE001 — best-effort fingerprint
        return None


class _Flight:
    """One in-flight compile; concurrent same-stamp askers wait on the event."""

    def __init__(self) -> None:
        self.event = threading.Event()
        self.error: BaseException | None = None


class ReportCache:
    """One dryrun report per draft content fingerprint, shared by every caller.

    ``dryrun`` (the MCP tool), ``list_checklist``, and the coverage follow-up
    hook all ask here: while the chosen draft's fingerprint (document content +
    reason revision) is unchanged, the last report is returned without
    touching the host compile service; any mutation invalidates it and the
    next ask compiles once, persists the result under
    ``workdir/.feedback/cache/``, and serves every caller again. Concurrent
    asks for the same stamp single-flight onto one compile (waiters block a
    worker thread on an event, never the shared event loop).
    """

    def __init__(self, workdir: Path) -> None:
        self._workdir = workdir
        self._cache_dir = workdir / CACHE_SUBDIR
        self._entries: dict[str, dict[str, Any]] = {}
        self._inflight: dict[tuple[str, str | None], _Flight] = {}
        self._lock = threading.Lock()

    def stderr(self, draft: str | None) -> str:
        """The stderr captured with ``draft``'s current cached report."""
        with self._lock:
            return self._entries.get(draft or "", {}).get("stderr", "")

    async def report(
        self, compile: CompileFn, draft: str | None
    ) -> dict[str, Any]:
        """The current report for ``draft``, compiling via ``compile`` on miss.

        Raises whatever ``compile`` raises (host timeout / compile failure).
        """
        key = draft or ""
        while True:
            with self._lock:
                stamp = _draft_stamp(draft)
                entry = self._entries.get(key)
                if entry is not None and entry["stamp"] == stamp:
                    return entry["data"]
                flight = self._inflight.get((key, stamp))
                owner = flight is None
                if owner:
                    flight = self._inflight[(key, stamp)] = _Flight()
            if not owner:
                await asyncio.to_thread(flight.event.wait)
                if flight.error is not None:
                    raise flight.error
                continue  # re-check: the store happened (or the stamp moved)
            try:
                data, stderr = await compile()
            except BaseException as exc:
                with self._lock:
                    self._inflight.pop((key, stamp), None)
                flight.error = exc
                flight.event.set()
                raise
            with self._lock:
                self._entries[key] = {
                    "stamp": stamp,
                    "data": data,
                    "stderr": stderr,
                }
                self._inflight.pop((key, stamp), None)
            flight.event.set()
            return data

    def persist(self, data: dict[str, Any], stderr: str) -> None:
        """Append one fresh report to the on-disk cache (best effort)."""
        run_id = uuid.uuid4().hex
        try:
            atomic_write_json(
                self._cache_dir / f"{run_id}.json",
                {
                    "run_id": run_id,
                    "data": data,
                    "stderr": stderr,
                    "annotation": "",
                },
            )
        except OSError:
            pass  # the on-disk cache is a diagnostic trail, never a gate


def shared_report_cache(workdir: Path) -> ReportCache:
    """The one ReportCache per workdir (process-wide, created on first use)."""
    with _CACHES_LOCK:
        cache = _CACHES.get(workdir)
        if cache is None:
            cache = _CACHES[workdir] = ReportCache(workdir)
        return cache


_CACHES: dict[Path, ReportCache] = {}
_CACHES_LOCK = threading.Lock()


def _sole_draft_name():
    """The store's only draft name (open-access checklist callers have one)."""
    from ..annotation_drafts import DraftsError, drafts

    names = drafts().names()
    if len(names) != 1:
        raise DraftsError(
            f"pass an explicit draft (store has {len(names)} drafts)"
        )
    return names[0]


def make_compile_fn(workdir: Path, name: str | None) -> Any:
    """Build the awaitable that runs ONE host compile against a live draft.

    The draft is resolved lazily inside the call so every compile sees the
    live document; ``None`` resolves to the store's only draft (open-access
    callers). The blocking request/file protocol runs in a worker thread via
    ``asyncio.to_thread`` so the shared event loop is never blocked. Returns
    ``(report dict, stderr str)``; raises RuntimeError on host/compile
    failure. No caching here — pass the result through
    :meth:`ReportCache.report`.
    """
    fb = workdir / FEEDBACK_SUBDIR

    def _run() -> tuple[dict[str, Any], str]:
        req_id = uuid.uuid4().hex
        annotation_rel = f"{FEEDBACK_SUBDIR}/{SNAPSHOTS_SUBDIR}/{req_id}.json"
        from ..annotation_drafts import drafts

        resolved = name if name is not None else _sole_draft_name()
        with drafts().lock(resolved):
            snapshot = drafts().get(resolved).to_json()
        atomic_write_json(workdir / annotation_rel, json.loads(snapshot))
        res = _request(fb, req_id, annotation_rel)
        if res is None:
            raise RuntimeError("timeout waiting for host feedback service")
        if not res.get("ok"):
            raise RuntimeError(
                "annotation-dryrun failed: " + (res.get("stderr") or "")[:400]
            )
        data = json.loads(res.get("stdout") or "{}")
        _dedup(data)
        return data, res.get("stderr") or ""

    async def _run_async() -> tuple[dict[str, Any], str]:
        return await asyncio.to_thread(_run)

    return _run_async


def run_dryrun_sync(workdir: Path, name: str | None) -> Any:
    """Build the shared-cache awaitable producing the draft's current report.

    The composition used everywhere except the ``dryrun`` MCP tool itself:
    the shared :class:`ReportCache` short-circuits when the draft's content
    fingerprint is unchanged, otherwise one host compile runs via
    :func:`make_compile_fn`. Returns the report dict (stderr stays in the
    cache for the tool's renderer). The awaitable takes an optional draft
    name overriding ``name`` (the checklist's open-access mode passes the
    caller's explicit ``draft=``); ``None`` falls back to ``name``.
    """
    cache = shared_report_cache(workdir)

    async def _report(override: str | None = None) -> dict[str, Any]:
        resolved = override if override is not None else name
        return await cache.report(make_compile_fn(workdir, resolved), resolved)

    return _report


def _full_summary(data: dict[str, Any]) -> str:
    summary = data.get("summary")
    # "opportunities" is the annotation-dryrun report's JSON key (external
    # C++ contract) — not renamed with the checklist tooling.
    if isinstance(summary, dict) and "opportunities" in summary:
        return (
            f"{summary.get('covered', 0)}/{summary.get('opportunities', 0)} "
            "checklist items covered"
        )
    anns = data.get("annotations", [])
    no = sum(len(a.get("optimizations", [])) for a in anns)
    nb = sum(len(a.get("blockages", [])) for a in anns)
    nmiss = sum(len(a.get("miss", [])) for a in anns)
    nu = sum(1 for a in anns if _is_no_effect(a))
    return (
        f"{no} optimized  {_count(nb, 'kill')}  "
        f"{nu} no-effect  {nmiss} unoptimized"
    )


# --- the MCP tool ---

def build_dryrun_tools(
    workdir: Path, names: list[str] | None = None, default: str | None = None
) -> list:
    """Build the ``dryrun`` tool, bound to ``workdir`` (request dropbox +
    shared report cache) and the named drafts.

    ``names`` are the drafts this agent may dryrun and ``default`` the one
    used when the optional ``draft`` argument is omitted; ``names=None``
    means open access (any draft in the store — the coordinator). The
    source file is NOT bound here — it is fixed at the host dryrun_service.
    The annotation is NOT read from a shared file: a fresh compile publishes
    the live snapshot of the chosen draft under
    ``.feedback/snapshots/<req_id>.json``.

    Exposed for tests to drive handlers directly with a fake host service.
    """
    cache = shared_report_cache(workdir)
    if names is None:
        default_name = default
    else:
        default_name = default if default is not None else (
            names[0] if len(names) == 1 else None
        )

    def _source_bytes() -> bytes:
        """The workdir's single JS source (the host service's namespace copy)."""
        candidates = sorted(workdir.glob("*.js"))
        if len(candidates) != 1:
            raise OSError(f"expected exactly one .js source in {workdir}")
        return candidates[0].read_bytes()

    @tool(
        "dryrun",
        "Check annotation effects: compiles the source (trimmed pipeline, "
        "no execution) against the CURRENT in-memory annotation draft and "
        "returns a whole-file summary (optimized / kills / no-effect / "
        "unoptimized) plus per-annotation detail, optionally filtered to a "
        "scope and feedback types: effect (optimized only), killed, or "
        "unoptimized (a property access a shape guard reaches that stayed generic). The scope: \"file\"/omitted for the whole file, "
        "ONE function loc_key like \"31:1\" (that function's DIRECT statements only — nested functions are independent scopes, pass their own loc_keys), "
        "\"<top-level>\" for module-level annotations, a list of loc_keys, or an inclusive line range like \"31-45\" (items whose own line falls inside); "
        "omit feedback_types for all "
        "three. Two diagnostics are ALWAYS shown for in-scope annotations "
        "regardless of feedback_types: \"✗ no effect\" and missing-binding — "
        "so an annotation absent from the detail list means your scope does "
        "not cover it. Out-of-scope feedback is summarized as 'somewhere else'. "
        "Compiles automatically on demand: unchanged annotations reuse the "
        "last compile. The draft is the one maintained via "
        "list/add/delete_annotation; pass draft= only when several drafts "
        "are available to you. Annotations whose target range matched no IR "
        "(unmatched) are auto-pruned — deleted from the draft and reported — "
        "because they never reach the IR; re-add one only with a corrected "
        "target range.",
        {
            "type": "object",
            "properties": {
                "draft": {
                    "type": "string",
                    "description": "annotation draft to compile; omit when "
                    "you have exactly one"
                    + ("" if names is None else " (one of the enum)"),
                    **({} if names is None else {"enum": list(names)}),
                },
                "scope": {
                    "type": ["string", "array"],
                    "description": "\"file\" (default), ONE function loc_key like \"31:1\" (that function's DIRECT statements only — nested functions are independent scopes, pass their own loc_keys), \"<top-level>\" for module-level annotations, a list of loc_keys like [\"31:1\", \"35:1\"], or an inclusive line range like \"31-45\" (items whose own line falls inside)",
                    "items": {"type": "string"},
                },
                "feedback_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(FEEDBACK_TYPES)},
                    "minItems": 1,
                    "uniqueItems": True,
                    "description": "types to show: effect, killed, unoptimized; omit for all",
                },
            },
        },
    )
    async def dryrun(args: dict[str, Any]) -> dict[str, Any]:
        if not set(args) <= {"draft", "scope", "feedback_types"}:
            return _err(
                "unexpected argument(s): "
                + ", ".join(sorted(set(args) - {"draft", "scope", "feedback_types"}))
            )
        try:
            name = args.get("draft") or default_name
            if name is None:
                raise DraftsError(
                    "several drafts available, pass draft= (one of: "
                    + (", ".join(names) if names is not None else "the store")
                    + ")"
                )
            drafts().get(name)
        except DraftsError as exc:
            return _err(str(exc))

        scope = args.get("scope", "file")
        selection = ScopeSelection()
        if scope is not None and scope != "file":
            try:
                data_bytes = await asyncio.to_thread(_source_bytes)
                selection = resolve_scope(scope, data_bytes)
            except ValueError:
                return _err(f"unknown or malformed scope {scope!r}")
            except OSError:
                return _err("could not read the source file for scope resolution")

        requested_types = args.get("feedback_types")
        if requested_types is None:
            feedback_types = set(FEEDBACK_TYPES)
        elif not isinstance(requested_types, list) or not requested_types:
            return _err("feedback_types must be a non-empty array")
        elif any(not isinstance(kind, str) for kind in requested_types):
            return _err("feedback_types entries must be strings")
        elif len(set(requested_types)) != len(requested_types):
            return _err("feedback_types entries must be unique")
        else:
            unknown = set(requested_types) - set(FEEDBACK_TYPES)
            if unknown:
                return _err(
                    "unknown feedback_types: " + ", ".join(sorted(unknown))
                )
            feedback_types = set(requested_types)

        async def _one_compile() -> tuple[dict[str, Any], str]:
            """One host compile (report, stderr), persisted to the on-disk trail."""
            data, stderr = await make_compile_fn(workdir, name)()
            cache.persist(data, stderr)
            return data, stderr

        try:
            data = await cache.report(_one_compile, name)
        except RuntimeError as exc:
            return _err(str(exc))

        filtered = _filter_annotations(data, selection, feedback_types)
        stderr = cache.stderr(name)
        # Prune runs against the report's OWN compile (the cached entry's
        # stamp equals the draft's pre-deletion content), so the report body
        # below stays the compile-time truth; the deletion invalidates the
        # stamp, so the next dryrun recompiles the pruned draft.
        pruned, unresolved = _prune_unmatched(name, stderr)
        body = _render(filtered, _strip_unmatched(stderr), feedback_types)
        tail = _prune_section(pruned, unresolved)
        if tail:
            body += "\n" + tail
        header = f"Whole file: {_full_summary(data)}"
        if selection.window is not None:
            header += f"  lines {selection.window[0]}-{selection.window[1]}"
        elif not selection.is_whole_file:
            header += f"  (scope {scope!r})"
        if requested_types is not None:
            selected = [kind for kind in FEEDBACK_TYPES if kind in feedback_types]
            header += "  types " + ",".join(selected)
        return {"content": [{"type": "text", "text": header + "\n" + body}]}

    return [dryrun]


def make_dryrun_server(workdir: Path, names: list[str] | None = None, default: str | None = None):
    """Build an in-process MCP server exposing the ``dryrun`` tool.

    ``names=None`` is OPEN ACCESS — any draft in the store by name (the
    parallel coordinators and their workers, whose draft names are only
    known at fan-out time); every call must then pass ``draft=``.
    """
    return create_sdk_mcp_server(
        name="dryrun",
        tools=build_dryrun_tools(workdir, names, default),
    )


def host_setup(attempt_dir: Path, source_name: str, config, stop_event) -> list:
    """Host-side: start the dryrun feedback service if its binary is configured.

    Returns a list with one un-started Thread (the orchestrator starts/joins it),
    or [] when feedback_bin_dir / annotation-dryrun is absent.
    """
    import threading
    from .services.dryrun_service import serve
    d = getattr(config, "feedback_bin_dir", None)
    if d is None:
        return []
    binary = Path(d) / "annotation-dryrun"
    if not binary.exists():
        return []
    return [threading.Thread(
        target=serve, args=(attempt_dir, source_name, binary, stop_event),
        daemon=True, name="dryrun_service",
    )]
