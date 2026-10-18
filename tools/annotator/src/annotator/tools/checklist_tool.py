"""Compiler-derived checklist: the optimization checklist's read and write side.

The checklist answers exactly two questions, both measured by the compiler:

1. Which generic instructions (arithmetic ops, named property accesses) could
   be optimized by annotations?
2. After annotating, are those positions still generic?

Coverage is recomputed from the latest ``annotation-dryrun`` report on every
query — served by the shared report cache in :mod:`dryrun_tool` (one compile
per draft content change, reused by ``dryrun`` and this checklist alike).
The only manual state is the reasons recorded for sites that stayed
not-optimized (``check``/``uncheck``), held per draft in this module's
reason store — separate from the annotation document, which carries only
compiler annotations. Scoping reuses the ``function_loc_key`` universe from
:mod:`functions`: one function, several, or the whole file.
"""


from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from .functions import (
    TOP_LEVEL_KEY,
    function_records,
    innermost_owner,
    resolve_scope,
)
from .utils import _err

__all__ = [
    "PROMPT",
    "CHECKLIST_KINDS",
    "REASON_ENUM",
    "REASONS_KEY",
    "ReasonError",
    "build_checklist_tools",
    "coverage_snapshot",
    "make_checklist_server",
    "reasons",
]

PROMPT = (
    "- `list_checklist(scope?, only_uncovered?, draft?)` lists the optimization checklist (generic arithmetic operations, named property accesses, and dynamic calls) for a scope — a function loc_key (e.g. \"31:1\" — identifies ONE function, an ID not a coordinate range), a list of them, a line range (e.g. \"31-45\", for any arbitrary region: only items whose OWN source line falls inside the range are listed — never the whole surrounding function), or \"file\" for the whole source file (the default when omitted). Each item carries a stable id, kind, location, owning function_loc_key, and optimized/not-optimized outcome computed from the current annotation snapshot. An item is optimized when its speculative-path instruction got strength-reduced (specialized form) or eliminated. `summary` reports total/optimized/reasoned/uncovered counts — `uncovered` (not-optimized, no recorded reason) is the remaining work, and uncovered == 0 is the completion criterion. Set `only_uncovered=true` to list just those items. Pass `draft` when several drafts exist. Read-only: results change only when annotations or reasons change — re-query to see the new state.\n"
    "- `check(reason, location?, items?, kind?, property?, note?)` checks off checklist items by recording why the site(s) cannot be optimized (reasons: object-source-not-found / ambiguous-shape / maybe-not-number / no-closure-target / unsupported-property-type / other). `other` and `unsupported-property-type` require `note` (for the latter, note the attempted type). A bare `location` ('line:col') suffices when it identifies exactly one item; `kind`/`property` disambiguate a shared location. For several sites blocked by the SAME cause, pass `items` (a list of {location[, kind][, property]}). Sites are verified against the current checklist — unknown or ambiguous ones are rejected listing candidates. Use only after genuinely failing to optimize the sites — never as a shortcut.\n"
    "- `list_reasons()` lists all recorded reasons; `uncheck(location, kind?, property?)` removes one when you found a way to optimize it after all (same single-key addressing as check).\n"
    "- `copy_reasons(source, dest?)` copies another draft's recorded reasons into dest (default: your own; sites already reasoned in the target are kept); a plain union by source location. Pair it with copy_annotations when merging drafts."
)

CHECKLIST_KINDS = frozenset(
    {"arithmetic", "property_load", "property_store", "call"}
)

# The `checklist` detail list is capped at this many items per query (the
# summary stays complete — the uncovered==0 completion criterion is always
# decidable). Single point of adjustment.
CHECKLIST_ITEM_CAP = 50

_TRUNCATION_HINT = (
    f"checklist capped at {CHECKLIST_ITEM_CAP} items; narrow scope "
    "(one function loc_key or a line range like '12-40') or resolve "
    "shown items then re-query"
)

# The persisted json section for recorded reasons (kept stable: seeded
# drafts and saved products from before the split carry it inline).
REASONS_KEY = "uncovered_reasons"

REASON_ENUM = (
    "object-source-not-found",  # receiver object's shape creation source not found/establishable
    "ambiguous-shape",  # value may come from several objects with different shapes
    "maybe-not-number",  # operand may not be number, arithmetic can't take the F fast path
    "no-closure-target",  # callee cannot be bound to a known function definition
    "constructing-store",  # the store runs while the receiver's shape is still being constructed (namespace assembly, prototype setup, constructor body) — the slot does not exist yet, so there is no fixed slot to write; whether a store is constructing is runtime info, undecidable statically
    "unsupported-property-type",  # property type beyond SH backend support; record attempted type in note
    "other",  # free text; note is mandatory
)


class ReasonError(ValueError):
    """Raised for any reason-record validation failure."""


# --- per-draft reason store (the write side of the checklist) -------------- #
# Split out of AnnotationDocument so the annotation document carries only
# compiler annotations (single responsibility). One process-wide store,
# keyed by the same draft names as the annotation drafts store; each draft's
# reasons have their own revision so the checklist's report cache can
# invalidate on a reason mutation too.


class _DraftReasons:
    """Reasons + a per-draft revision, guarded by the store's global lock."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.revision: int = 0


class ReasonStore:
    """Reasons per draft name; the checklist tools' single source of truth."""

    def __init__(self) -> None:
        self._drafts: dict[str, _DraftReasons] = {}
        self._lock = threading.RLock()

    def _entry(self, name: str) -> _DraftReasons:
        entry = self._drafts.get(name)
        if entry is None:
            raise ReasonError(f"unknown draft {name!r}")
        return entry

    def seed(self, name: str, records: list[dict[str, Any]]) -> None:
        """Replace one draft's reasons (validated) — the load/save bridge."""
        with self._lock:
            self._drafts.setdefault(name, _DraftReasons())
            entry = self._drafts[name]
            entry.records = _normalize_reasons(records)
            entry.revision += 1

    def register(self, name: str) -> None:
        """Create an empty entry; a no-op when one already exists."""
        with self._lock:
            self._drafts.setdefault(name, _DraftReasons())

    def get(self, name: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._entry(name).records]

    def revision(self, name: str) -> int:
        with self._lock:
            return self._entry(name).revision

    def names(self) -> list[str]:
        with self._lock:
            return list(self._drafts)

    def set(self, name: str, items: list[dict[str, Any]], reason: str, note: str = "") -> int:
        """Record (or replace) the same reason for several checklist items.

        ``items`` are {location, kind[, property]} dicts sharing one
        reason/note — for checking off many sites blocked by one cause.
        Key = (location, kind, property); identical to the dryrun report's
        checklist item key so coverage accounting can join on it.
        """
        if not items:
            raise ReasonError("check: 'items' must not be empty")
        for item in items:
            if not isinstance(item, dict) or not item.get("location") or not item.get("kind"):
                raise ReasonError("check: each item needs 'location' and 'kind'")
        records = _normalize_reasons(
            [
                {
                    "location": item["location"],
                    "kind": item["kind"],
                    "reason": reason,
                    "note": note,
                    **({"property": item["property"]} if item.get("property") else {}),
                }
                for item in items
            ]
        )
        keys = {(r["location"], r["kind"], r.get("property", "")) for r in records}
        with self._lock:
            entry = self._entry(name)
            entry.records = [
                r
                for r in entry.records
                if (r["location"], r["kind"], r.get("property", "")) not in keys
            ] + records
            entry.revision += 1
            return entry.revision

    def clear(self, name: str, location: str, kind: str, property_: str = "") -> int:
        key = (location, kind, property_)
        with self._lock:
            entry = self._entry(name)
            before = len(entry.records)
            entry.records = [
                r
                for r in entry.records
                if (r["location"], r["kind"], r.get("property", "")) != key
            ]
            if len(entry.records) != before:
                entry.revision += 1
            return entry.revision

    def drop(self, name: str) -> None:
        with self._lock:
            self._drafts.pop(name, None)


_SINGLETON = ReasonStore()


def reasons() -> ReasonStore:
    """The process-wide reason store shared by checklist tools and hooks."""
    return _SINGLETON


def _normalize_reasons(raw: Any) -> list[dict[str, Any]]:
    """Validate reason records: (location, kind[, property]) key + enum reason.

    ``other`` and ``unsupported-property-type`` require a note (for the
    latter the note records the attempted property type).
    """
    if not isinstance(raw, list):
        raise ReasonError("reasons must be an array")
    out: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for item in raw:
        rec = item if isinstance(item, dict) else None
        if rec is None:
            raise ReasonError("reason record must be an object")
        location = rec.get("location")
        if not isinstance(location, str) or not location:
            raise ReasonError("reason: 'location' must be a non-empty string")
        kind = rec.get("kind")
        if kind not in CHECKLIST_KINDS:
            raise ReasonError(f"reason: 'kind' must be one of {sorted(CHECKLIST_KINDS)}")
        reason = rec.get("reason")
        if reason not in REASON_ENUM:
            raise ReasonError(f"reason: unknown reason {reason!r}")
        property_ = rec.get("property", "")
        if not isinstance(property_, str):
            raise ReasonError("reason: 'property' must be a string")
        note = rec.get("note", "")
        if not isinstance(note, str):
            raise ReasonError("reason: 'note' must be a string")
        if reason in ("other", "unsupported-property-type") and not note.strip():
            raise ReasonError(f"reason: {reason!r} requires a non-empty 'note'")
        key = (location, kind, property_)
        if key in seen:
            raise ReasonError(f"reason: duplicate record for {location}")
        seen.add(key)
        normalized: dict[str, Any] = {
            "location": location,
            "kind": kind,
            "reason": reason,
        }
        if property_:
            normalized["property"] = property_
        if note:
            normalized["note"] = note
        out.append(normalized)
    return out

# Report v3 says optimized/not-optimized; v2 said covered/uncovered (same
# semantics minus the elimination rule). Accept both spellings.
_OPTIMIZED = frozenset({"optimized", "covered"})


def _parse_loc(location: str) -> tuple[int, int] | None:
    parts = location.split(":")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _checklist_item_id(kind: str, location: str, property_: str) -> str:
    digest = hashlib.sha256(
        f"{kind}|{location}|{property_}".encode("utf-8")
    ).hexdigest()[:20]
    return f"item_{digest}"


def _scope_checklist(
    report: dict[str, Any],
    source_data: bytes,
    reasons_by_key: dict[tuple[str, str, str], dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Group report checklist items by owning function loc_key.

    Items outside every function belong to ``TOP_LEVEL_KEY``. Function-scope
    queries never select that key, but the whole-file snapshot aggregates it.
    ``reasons_by_key`` (optional) maps (location, kind, property) to a
    recorded reason record; matching entries get a ``reason`` field.
    """
    functions = function_records(source_data)
    scoped: dict[str, list[dict[str, Any]]] = {}
    # "opportunities" is the annotation-dryrun report's JSON key (external
    # C++ contract) — not renamed with the checklist tooling.
    for item in report.get("opportunities", []):
        parsed = _parse_loc(str(item.get("location", "")))
        if parsed is None:
            continue
        owner = innermost_owner(parsed[0], parsed[1], functions)
        owner_key = TOP_LEVEL_KEY if owner is None else owner["loc_key"]
        rec = {
            "id": _checklist_item_id(
                str(item.get("kind", "")),
                str(item.get("location", "")),
                str(item.get("property", "")),
            ),
            "kind": item.get("kind"),
            "location": item.get("location"),
            "function_loc_key": owner_key,
            "property": item.get("property", ""),
            "outcome": item.get("outcome", "not-optimized"),
        }
        if reasons_by_key is not None:
            key = (rec["location"], rec["kind"], rec["property"])
            if key in reasons_by_key:
                rec["reason"] = reasons_by_key[key]
        scoped.setdefault(owner_key, []).append(rec)
    return scoped


def _reason_index(draft: str) -> dict[tuple[str, str, str], dict[str, Any]]:
    """(location, kind, property) -> reason record for one draft."""
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for rec in reasons().get(draft):
        out[(rec["location"], rec["kind"], rec.get("property", ""))] = rec
    return out


def _summary(items: list[dict[str, Any]]) -> dict[str, int]:
    """Counts only — no ratio: the raw uncovered count is the actionable bit."""
    not_optimized = [i for i in items if i["outcome"] not in _OPTIMIZED]
    reasoned = [i for i in not_optimized if "reason" in i]
    return {
        "total": len(items),
        "optimized": len(items) - len(not_optimized),
        "reasoned": len(reasoned),
        "uncovered": len(not_optimized) - len(reasoned),
    }


def _scoped_items(
    selection: Any, scoped: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """The checklist items a resolved scope selects, site by site.

    One rule for every scope form (:meth:`ScopeSelection.owns_loc` on each
    item's "line:col" location): a function loc_key keeps every direct site
    the function owns (never a nested function's), ``"<top-level>"`` the
    module-level sites, ``"file"`` everything, and a line window only items
    whose own location line falls inside it — a region, never the whole
    function around it (the documented "any arbitrary region" contract; the
    truncation hint tells agents to narrow this way, so the narrowing has to
    actually narrow).
    """
    return [
        i
        for items in scoped.values()
        for i in items
        if selection.owns_loc(str(i.get("location", "")))
    ]


def coverage_snapshot(
    report: dict[str, Any],
    source_bytes: bytes,
    scope: Any,
    reasons_by_key: dict[tuple[str, str, str], dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """The host-side completion check for a scope, from a raw dryrun report.

    ``scope`` is the ``list_checklist`` scope: "file", one function loc_key,
    a list of loc_keys, or a line range (filtered site by site, same rule as
    ``list_checklist`` so the query and the completion criterion always
    agree). Returns the same ``summary`` shape plus the uncovered item list,
    or None when the scope is malformed/unknown.
    Module-level so the coverage follow-up turn hooks can reuse it without
    an MCP context.
    """
    try:
        selection = resolve_scope(scope, source_bytes)
    except ValueError:
        return None
    scoped = _scope_checklist(report, source_bytes, reasons_by_key)
    items = _scoped_items(selection, scoped)
    summary = _summary(items)
    uncovered_items = [
        i for i in items
        if i["outcome"] not in _OPTIMIZED and "reason" not in i
    ]
    return {**summary, "uncovered_items": uncovered_items}


def build_checklist_tools(
    source: Path,
    run_dryrun,
    draft: str | None = None,
) -> list:
    """Build the checklist tools: read-only ``list_checklist`` plus the
    check/uncheck/list_reasons write side over the per-draft reason store.

    ``run_dryrun(name)`` (awaitable, optional draft-name argument) returns
    that draft's current dryrun report (raising RuntimeError on failure);
    ``None`` selects this server's bound default. Callers pass the
    shared-cache composition from :func:`dryrun_tool.run_dryrun_sync`, so an
    unchanged draft fingerprint never recompiles and the result is shared
    with the ``dryrun`` MCP tool; a fake can be injected for tests.

    ``draft`` (optional name) selects the reason store's draft and the
    fingerprint key of the shared report cache. Without a draft name every
    tool call must pass ``draft=`` explicitly (open-access mode).
    """
    from ..annotation_drafts import drafts

    source_resolved = source.resolve()

    def _reasons(name: str | None = None) -> dict[tuple[str, str, str], dict[str, Any]]:
        """Reason records from the store (empty without a draft name)."""
        target = name if name is not None else draft
        if target is None:
            return {}
        try:
            return _reason_index(target)
        except Exception:  # noqa: BLE001
            return {}

    async def scoped_report(scope: Any, name: str | None = None) -> dict[str, Any]:
        """The checklist items of ``scope`` from the draft's current report.

        Raises ValueError on a malformed/unknown scope (the handler maps it
        to the shared error). Zero-checklist functions are valid targets:
        their absence from the report simply yields an empty item list.
        """
        report = await run_dryrun(name)
        data = await asyncio.to_thread(source_resolved.read_bytes)
        selection = resolve_scope(scope, data)
        scoped = _scope_checklist(report, data, _reasons(name))
        return {"checklist": _scoped_items(selection, scoped)}

    async def _resolve_sites(
        sites: list[dict[str, Any]], name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Expand ``{location[, kind][, property]}`` sites to full checklist
        keys against the current report.

        A bare ``location`` identifies the site when exactly one checklist
        item carries it; ``kind``/``property`` narrow an ambiguous one. Also
        validates the site exists. Raises ValueError naming the first site
        that does not resolve to exactly one item (nothing is recorded).
        """
        try:
            report = await run_dryrun(name)
        except RuntimeError as exc:
            raise ValueError(f"cannot verify sites, dryrun failed: {exc}") from exc
        universe: dict[tuple[str, str, str], None] = {}
        for item in report.get("opportunities", []):
            universe.setdefault(
                (
                    str(item.get("location", "")),
                    str(item.get("kind", "")),
                    str(item.get("property", "")),
                )
            )
        resolved: list[dict[str, Any]] = []
        for site in sites:
            loc = str(site.get("location", ""))
            cands = [
                key
                for key in universe
                if key[0] == loc
                and (not site.get("kind") or key[1] == site["kind"])
                and (not site.get("property") or key[2] == site["property"])
            ]
            if len(cands) != 1:
                shown = ", ".join(
                    " ".join(part for part in key if part) for key in cands[:10]
                )
                if cands:
                    raise ValueError(
                        f"location {loc!r} matches {len(cands)} checklist "
                        f"items ({shown}); pass kind/property to disambiguate"
                    )
                raise ValueError(f"no checklist item at location {loc!r}")
            r_loc, kind, prop = cands[0]
            resolved.append(
                {"location": r_loc, "kind": kind, **({"property": prop} if prop else {})}
            )
        return resolved

    @tool(
        "list_checklist",
        "List the compiler-measured optimization checklist for a scope: "
        "\"file\" (the default) for the whole source file, ONE function "
        "loc_key like \"31:1\" (an ID identifying one function — copy "
        "from fold/list_checklist, not an arbitrary coordinate range), a "
        "list of loc_keys, \"<top-level>\" for module-level code (top-level "
        "statements outside every function), or an inclusive line range like "
        "\"31-45\" for any arbitrary region (site-level: only items whose "
        "OWN source line falls inside the range are listed — never the "
        "whole surrounding function). A function loc_key's scope "
        "covers only that function's DIRECT statements — sites inside a "
        "nested/inner function belong to the inner function's own loc_key "
        "and never appear in the outer scope. — generic arithmetic operations, named property "
        "accesses, and dynamic calls that annotations could optimize. Each "
        "item carries a stable id, kind "
        "(arithmetic/property_load/property_store/call), source location, "
        "owning function_loc_key, optional property (callee name for calls), "
        "and outcome (optimized/not-optimized — optimized means "
        "strength-reduced or eliminated on the speculative path) computed "
        "from the current annotation snapshot. Items with a recorded reason "
        "carry it inline. Set only_uncovered=true to return just the "
        "remaining work (not-optimized, no reason yet). The detail list is "
        f"capped at {CHECKLIST_ITEM_CAP} items per query (applied after the only_uncovered "
        "filter, same rule for every scope): beyond the cap the response "
        f"carries only the first {CHECKLIST_ITEM_CAP} items plus truncated/shown/total and a "
        "hint — narrow the scope (one function loc_key or a line range like "
        "'12-40') to get full details. `summary` is never capped, and "
        "`summary.uncovered` 0 is the completion criterion; zero-checklist "
        "functions are complete. Read-only: results change only when "
        "annotations or reasons change.",
        {
            "type": "object",
            "properties": {
                "scope": {
                    "type": ["string", "array"],
                    "description": "\"file\" (default), ONE function loc_key like \"31:1\" (an ID identifying one function — copy from fold/list_checklist, not an arbitrary coordinate range; covers only that function's direct statements, not nested functions' bodies), a list of loc_keys like [\"31:1\", \"35:1\"], \"<top-level>\" for module-level code, or an inclusive line range like \"31-45\" for any arbitrary region (only items whose OWN source line falls inside)",
                    "items": {"type": "string"},
                },
                "only_uncovered": {
                    "type": "boolean",
                    "description": "return only not-optimized items with no recorded reason (default false)",
                },
                "draft": {"type": "string", "description": "target draft (default: your own)"},
            },
            "additionalProperties": False,
        },
    )
    async def list_checklist(args: dict[str, Any]) -> dict[str, Any]:
        if not set(args) <= {"scope", "only_uncovered", "draft"}:
            return _err("expected only optional 'scope', 'only_uncovered', and 'draft'")
        only_uncovered = args.get("only_uncovered", False)
        if not isinstance(only_uncovered, bool):
            return _err("'only_uncovered' must be a boolean")
        scope = args.get("scope", "file")
        name = _resolve_draft(args) or _sole_draft()
        if name is None:
            return _err("several drafts available, pass draft=")
        try:
            result = await scoped_report(scope, name)
        except ValueError:
            return _err(f"unknown or malformed scope {scope!r}")
        except (OSError, RuntimeError) as exc:
            return _err(str(exc))
        items = result["checklist"]
        shown = (
            [
                i for i in items
                if i["outcome"] not in _OPTIMIZED and "reason" not in i
            ]
            if only_uncovered
            else items
        )
        payload: dict[str, Any] = {
            "scope": scope,
            "summary": _summary(items),
            "checklist": shown[:CHECKLIST_ITEM_CAP],
        }
        if len(shown) > CHECKLIST_ITEM_CAP:
            payload["truncated"] = True
            payload["shown"] = CHECKLIST_ITEM_CAP
            payload["total"] = len(shown)
            payload["hint"] = _TRUNCATION_HINT
        return {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}]}

    # --- the write side: check / uncheck / list_reasons ------------------- #

    def _resolve_draft(args: dict[str, Any]) -> str | None:
        """The target draft name, or None for the open-access (no-default) mode."""
        name = args.get("draft")
        if isinstance(name, str) and name:
            return name
        return draft

    def _sole_draft() -> str | None:
        """The store's only draft, when there is exactly one (implicit target).

        ``None`` means several drafts exist — the caller must pass ``draft=``.
        """
        try:
            names = drafts().names()
        except Exception:  # noqa: BLE001 — never block on store failures
            return None
        return names[0] if len(names) == 1 else None

    @tool(
        "check",
        "Check off one or several checklist items: record why the "
        "not-optimized site(s) cannot be optimized. Pass either "
        "`location` ('line:col' from the checklist report — when it "
        "identifies exactly one item that's all you need; kind/property "
        "disambiguate a location carrying several items), or `items` — a "
        "list of {location[, kind][, property]} — to check off several "
        "sites sharing one cause in a single call. Every site must exist in "
        "the current checklist; unknown or still-ambiguous sites are "
        "rejected listing the candidates. Use only after genuinely trying "
        "to optimize the sites: first attempt annotations, then record the "
        "reason when they cannot work. reasons: object-source-not-found | "
        "ambiguous-shape | maybe-not-number | no-closure-target | "
        "unsupported-property-type (note the attempted type) | other (note "
        "is mandatory).",
        {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "'line:col' from the checklist report; "
                    "kind/property disambiguate when several items share it",
                },
                "kind": {
                    "type": "string",
                    "enum": ["arithmetic", "property_load", "property_store", "call"],
                    "description": "optional disambiguator",
                },
                "items": {
                    "type": "array",
                    "description": "batch alternative to location/kind/property: "
                    "several {location[, kind][, property]} sites sharing the "
                    "same reason",
                    "items": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"},
                            "kind": {
                                "type": "string",
                                "enum": [
                                    "arithmetic",
                                    "property_load",
                                    "property_store",
                                    "call",
                                ],
                            },
                            "property": {"type": "string"},
                        },
                        "required": ["location"],
                        "additionalProperties": False,
                    },
                },
                "reason": {"type": "string", "enum": list(REASON_ENUM)},
                "property": {
                    "type": "string",
                    "description": "property/callee name when the report entry has one",
                },
                "note": {"type": "string", "description": "required for other/unsupported-property-type"},
                "draft": {"type": "string", "description": "target draft (default: your own)"},
            },
            "required": ["reason"],
            "additionalProperties": False,
        },
    )
    async def check(args: dict[str, Any]) -> dict[str, Any]:
        batch = "items" in args
        single = "location" in args
        if single and batch:
            return _err("pass either location/kind/property or items, not both")
        if batch:
            sites = args["items"]
            if not isinstance(sites, list) or not sites:
                return _err("'items' must be a non-empty array")
        elif single:
            sites = [{k: args[k] for k in ("location", "kind", "property") if k in args}]
        else:
            return _err("expected location, or items")
        name = _resolve_draft(args)
        if name is None:
            return _err("several drafts available, pass draft=")
        try:
            items = await _resolve_sites(sites, name)
        except ValueError as exc:
            return _err(str(exc))
        try:
            reasons().set(name, items, args["reason"], args.get("note", ""))
        except ReasonError as exc:
            return _err(str(exc))
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "checked": len(items),
                            "items": items,
                            "reason": args["reason"],
                        }
                    ),
                }
            ]
        }

    @tool(
        "list_reasons",
        "List all recorded not-optimized reasons in the current draft.",
        {
            "type": "object",
            "properties": {
                "draft": {"type": "string", "description": "target draft (default: your own)"},
            },
        },
    )
    async def list_reasons(args: dict[str, Any]) -> dict[str, Any]:
        name = _resolve_draft(args)
        if name is None:
            return _err("several drafts available, pass draft=")
        try:
            records = reasons().get(name)
        except ReasonError as exc:
            return _err(str(exc))
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"count": len(records), "reasons": records},
                        ensure_ascii=False,
                        indent=2,
                    ),
                }
            ]
        }

    @tool(
        "uncheck",
        "Uncheck one item: remove its recorded reason (when the site got "
        "optimized after all). `location` alone when it identifies exactly "
        "one checklist item; kind/property disambiguate otherwise.",
        {
            "type": "object",
            "properties": {
                "location": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": ["arithmetic", "property_load", "property_store", "call"],
                    "description": "optional disambiguator",
                },
                "property": {"type": "string"},
                "draft": {"type": "string", "description": "target draft (default: your own)"},
            },
            "required": ["location"],
            "additionalProperties": False,
        },
    )
    async def uncheck(args: dict[str, Any]) -> dict[str, Any]:
        name = _resolve_draft(args)
        if name is None:
            return _err("several drafts available, pass draft=")
        try:
            (item,) = await _resolve_sites(
                [{k: args[k] for k in ("location", "kind", "property") if k in args}],
                name,
            )
        except ValueError as exc:
            return _err(str(exc))
        try:
            reasons().clear(
                name, item["location"], item["kind"], item.get("property", "")
            )
        except ReasonError as exc:
            return _err(str(exc))
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"cleared reason for {item['location']} {item['kind']} "
                    f"{item.get('property', '')}".rstrip(),
                }
            ]
        }

    @tool(
        "copy_reasons",
        "Copy another draft's recorded reasons into yours: sites already "
        "carrying a reason in the target are kept (the source's is skipped), "
        "the rest are copied verbatim. The reason keys are source locations, "
        "so this is a plain union — no compatibility decisions involved. "
        "Used when merging drafts (pair it with copy_annotations).",
        {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "draft name to copy reasons FROM",
                },
                "dest": {"type": "string", "description": "destination draft to copy reasons INTO (default: your own)"},
            },
            "required": ["source"],
        },
    )
    async def copy_reasons(args: dict[str, Any]) -> dict[str, Any]:
        from ..annotation_drafts import DraftsError, drafts

        if not set(args) <= {"source", "dest"}:
            return _err("expected only 'source' and 'dest'")
        dest = args.get("dest") or draft
        if dest is None:
            return _err("several drafts available, pass dest=")
        src = args.get("source")
        if not isinstance(src, str) or not src:
            return _err("'source' must be a non-empty draft name")
        if src == dest:
            return _err("cannot copy a draft's reasons into itself")
        # Both drafts must exist in the store (the reason store keys by the
        # same names); visibility is enforced by the drafts store itself.
        try:
            drafts().get(src)
        except DraftsError as exc:
            return _err(str(exc))
        try:
            src_records = reasons().get(src)
        except ReasonError:
            src_records = []
        try:
            dest_records = reasons().get(dest)
        except ReasonError as exc:
            return _err(str(exc))
        merged = {
            (r["location"], r["kind"], r.get("property", "")): r
            for r in dest_records
        }
        copied = 0
        for rec in src_records:
            key = (rec["location"], rec["kind"], rec.get("property", ""))
            if key not in merged:
                merged[key] = rec
                copied += 1
        if copied:
            reasons().seed(dest, list(merged.values()))
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"copied {copied} reason(s) from {src!r} to {dest!r} "
                    f"({len(merged)} total)",
                }
            ]
        }

    return [list_checklist, check, list_reasons, uncheck, copy_reasons]


def make_checklist_server(
    source: Path,
    run_dryrun,
    draft: str | None = None,
):
    """Build the in-process MCP server projecting the dryrun checklist."""
    return create_sdk_mcp_server(
        name="checklist",
        tools=build_checklist_tools(source, run_dryrun, draft),
    )
