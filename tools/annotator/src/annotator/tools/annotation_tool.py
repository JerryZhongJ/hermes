"""In-process MCP annotation tools over an in-memory document.

Unlike ``locate`` / ``fold`` / ``dryrun`` (read-only views), this module owns
the annotation document the agent is building. The agent NEVER writes
``annotation.json`` — it maintains the document through the list, add, delete,
and update MCP tools. The document lives in memory for the whole agent run; the
orchestrator flushes it
to disk once the run is over (see :mod:`annotator.agent_worker` /
:mod:`annotator.pipeline`). ``dryrun_annotation`` reads the current snapshot
in-process via :meth:`AnnotationDocument.to_dict` instead of parsing the file.

The persisted schema is unchanged — the same four top-level sections the
``AnnotationLoader`` expects::

    {
      "static shapes": {name: {"properties": [...]}},
      "shape guards": [...],
      "shape bindings": [...],
      "type guards": [...]
    }

Identifiers are SHORT-LIVED (valid only for the current revision): an item's
``id`` is ``<kind>:<index>:<revision>``. ``list`` returns ids, ``delete``
takes one. Because revision bumps on every mutation, a stale id from an old
``list`` is rejected rather than silently deleting the wrong element.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from .utils import _err

# --- constants ------------------------------------------------------------ #

SHAPES_KEY = "static shapes"
SHAPE_GUARDS_KEY = "shape guards"
SHAPE_BINDINGS_KEY = "shape bindings"
TYPE_GUARDS_KEY = "type guards"

# Canonical kind tags used everywhere (tool args, ids, list output).
KIND_STATIC_SHAPE = "static_shape"
KIND_SHAPE_BINDING = "shape_binding"
KIND_SHAPE_GUARD = "shape_guard"
KIND_TYPE_GUARD = "type_guard"
_ARRAY_KINDS = {
    KIND_SHAPE_BINDING: SHAPE_BINDINGS_KEY,
    KIND_SHAPE_GUARD: SHAPE_GUARDS_KEY,
    KIND_TYPE_GUARD: TYPE_GUARDS_KEY,
}
_ALL_KINDS = [KIND_STATIC_SHAPE, KIND_SHAPE_BINDING, KIND_SHAPE_GUARD, KIND_TYPE_GUARD]

CONCRETE_TYPES = {"number", "string", "boolean", "null", "undefined", "closure"}
FLAG_NAMES = {"writable", "enumerable", "configurable"}


# --- exceptions ------------------------------------------------------------ #


class AnnotationError(ValueError):
    """Raised for any validation failure. The handler maps it to an MCP error."""


# --- AnnotationDocument (the single source of truth for one run) ---------- #


@dataclass
class AnnotationDocument:
    """In-memory annotation document. Mutated only through validated helpers.

    ``revision`` bumps on every successful mutation; ids embed it so a stale
    id from an earlier ``list`` cannot address an item after the doc changed.
    """

    static_shapes: dict[str, dict[str, Any]] = field(default_factory=dict)
    shape_bindings: list[dict[str, Any]] = field(default_factory=list)
    shape_guards: list[dict[str, Any]] = field(default_factory=list)
    type_guards: list[dict[str, Any]] = field(default_factory=list)
    revision: int = 0

    # --- construction / serialization ------------------------------------ #

    @classmethod
    def empty(cls) -> "AnnotationDocument":
        return cls()

    def to_dict(self) -> dict[str, Any]:
        """Return an independent snapshot in the persisted schema."""
        return {
            SHAPES_KEY: _deep_copy_shapes(self.static_shapes),
            SHAPE_GUARDS_KEY: _deep_copy_list(self.shape_guards),
            SHAPE_BINDINGS_KEY: _deep_copy_list(self.shape_bindings),
            TYPE_GUARDS_KEY: _deep_copy_list(self.type_guards),
        }

    def to_json(self) -> str:
        import json

        return json.dumps(self.to_dict(), indent=2) + "\n"

    def load_from_dict(self, document: dict[str, Any]) -> None:
        """Validate and atomically replace all persisted document sections."""
        document = _require_dict(document, "annotation document")
        expected_keys = {
            SHAPES_KEY,
            SHAPE_GUARDS_KEY,
            SHAPE_BINDINGS_KEY,
            TYPE_GUARDS_KEY,
        }
        extra = set(document) - expected_keys
        if extra:
            raise AnnotationError(
                f"annotation document has unknown section(s): {sorted(extra)}"
            )

        shapes = document.get(SHAPES_KEY)
        if not isinstance(shapes, dict):
            raise AnnotationError("load: 'static shapes' missing or not an object")

        raw_arrays: dict[str, list[Any]] = {}
        for key in (SHAPE_BINDINGS_KEY, SHAPE_GUARDS_KEY, TYPE_GUARDS_KEY):
            value = document.get(key)
            if not isinstance(value, list):
                raise AnnotationError(f"load: {key!r} missing or not an array")
            raw_arrays[key] = value

        normalized_shapes: dict[str, dict[str, Any]] = {}
        for name, definition in shapes.items():
            if not isinstance(name, str) or not name:
                raise AnnotationError("load: static shape names must be non-empty strings")
            normalized_shapes[name] = _normalize_shape_definition(
                _require_dict(definition, f"shape {name!r}"), name
            )

        known_shapes = set(normalized_shapes)
        normalized_arrays: dict[str, list[dict[str, Any]]] = {}
        for kind, key in _ARRAY_KINDS.items():
            normalized: list[dict[str, Any]] = []
            seen: set[tuple] = set()
            for item in raw_arrays[key]:
                validated = _validate_array_item(
                    kind,
                    _require_dict(item, f"{kind} annotation"),
                    known_shapes,
                )
                canonical = _canonical_key(kind, validated)
                if canonical in seen:
                    raise AnnotationError(f"load: duplicate {kind} already present")
                seen.add(canonical)
                normalized.append(validated)
            normalized_arrays[key] = normalized

        self.static_shapes = normalized_shapes
        self.shape_bindings = normalized_arrays[SHAPE_BINDINGS_KEY]
        self.shape_guards = normalized_arrays[SHAPE_GUARDS_KEY]
        self.type_guards = normalized_arrays[TYPE_GUARDS_KEY]
        self.revision += 1

    # --- introspection used by list / delete ----------------------------- #

    def _array_for(self, kind: str) -> list[dict[str, Any]] | None:
        if kind == KIND_STATIC_SHAPE:
            return None
        key = _ARRAY_KINDS.get(kind)
        return getattr(self, _attr_for_key(key)) if key else None

    def shape_names(self) -> set[str]:
        return set(self.static_shapes)

    def is_shape_referenced(self, name: str) -> bool:
        """True if any guard/binding cites ``name`` (as ``shape`` or
        ``prototype shape``). Used to block deleting an in-use shape."""
        for item in self.shape_bindings + self.shape_guards:
            if item.get("shape") == name or item.get("prototype shape") == name:
                return True
        return False

    # --- mutation (validated) -------------------------------------------- #

    def add_shape(self, name: str, definition: dict[str, Any]) -> int:
        if name in self.static_shapes:
            raise AnnotationError(f"shape {name!r} already exists")
        self.static_shapes[name] = _normalize_shape_definition(definition, name)
        self.revision += 1
        return self.revision

    def add_array_item(self, kind: str, item: dict[str, Any]) -> int:
        array = self._array_for(kind)
        if array is None:
            raise AnnotationError(f"unknown array kind {kind!r}")
        validated = _validate_array_item(kind, item, self.shape_names())
        canonical = _canonical_key(kind, validated)
        for existing in array:
            if _canonical_key(kind, existing) == canonical:
                raise AnnotationError(f"duplicate {kind} already present")
        array.append(validated)
        self.revision += 1
        return self.revision

    def delete_shape(self, name: str) -> dict[str, Any]:
        if name not in self.static_shapes:
            raise AnnotationError(f"no static shape named {name!r}")
        if self.is_shape_referenced(name):
            raise AnnotationError(
                f"shape {name!r} is referenced by a guard/binding; delete those first"
            )
        removed = self.static_shapes.pop(name)
        self.revision += 1
        return {SHAPES_KEY: {name: removed}}

    def delete_array_item(self, kind: str, index: int) -> dict[str, Any]:
        array = self._array_for(kind)
        if array is None:
            raise AnnotationError(f"unknown array kind {kind!r}")
        if not 0 <= index < len(array):
            raise AnnotationError(f"no {kind} at index {index}")
        removed = array.pop(index)
        self.revision += 1
        return {_ARRAY_KINDS[kind]: removed}

    def update_array_item(self, kind: str, index: int, patch: dict[str, Any]) -> int:
        """Merge a partial patch into one binding/guard/type_guard in place.

        Re-validates the merged result and rejects duplicates (excluding self).
        Patch fields override existing ones; field removal still needs delete+add.
        """
        array = self._array_for(kind)
        if array is None:
            raise AnnotationError(f"unknown array kind {kind!r}")
        if not 0 <= index < len(array):
            raise AnnotationError(f"no {kind} at index {index}")
        merged = {**dict(array[index]), **_item_ranges_to_dict(patch)}
        validated = _validate_array_item(kind, merged, self.shape_names())
        canonical = _canonical_key(kind, validated)
        for i, existing in enumerate(array):
            if i != index and _canonical_key(kind, existing) == canonical:
                raise AnnotationError(f"duplicate {kind} already present")
        array[index] = validated
        self.revision += 1
        return self.revision

    def update_shape(self, name: str, patch: dict[str, Any]) -> int:
        """Patch a static_shape in place.

        ``patch`` may carry ``properties`` (replace the whole list) and/or
        ``property`` (``{name, ...fields}`` merged into one property by name —
        the common case for fixing a closure's ``target function`` range).
        """
        if name not in self.static_shapes:
            raise AnnotationError(f"no static shape named {name!r}")
        current = _deep_copy_shape_def(self.static_shapes[name])
        properties = current.get("properties", [])

        if "properties" in patch:
            raw = patch["properties"]
            if not isinstance(raw, list):
                raise AnnotationError(f"shape {name!r} 'properties' must be an array")
            properties = [_coerce_property_ranges(p) for p in raw]

        if "property" in patch:
            pp = patch["property"]
            if not isinstance(pp, dict) or not isinstance(pp.get("name"), str):
                raise AnnotationError("property patch requires a string 'name'")
            pname = pp["name"]
            properties = [dict(p) for p in properties]
            for p in properties:
                if p.get("name") == pname:
                    p.update(_coerce_property_ranges(pp))
                    break
            else:
                raise AnnotationError(f"shape {name!r} has no property {pname!r}")

        if "properties" not in patch and "property" not in patch:
            raise AnnotationError(
                f"shape {name!r} patch requires 'properties' or 'property'"
            )

        self.static_shapes[name] = _normalize_shape_definition(
            {"properties": properties}, name
        )
        self.revision += 1
        return self.revision


# --- helpers: deep copy / lookup ----------------------------------------- #


def _attr_for_key(key: str) -> str:
    return {
        SHAPES_KEY: "static_shapes",
        SHAPE_GUARDS_KEY: "shape_guards",
        SHAPE_BINDINGS_KEY: "shape_bindings",
        TYPE_GUARDS_KEY: "type_guards",
    }[key]


def _deep_copy_shapes(shapes: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {name: _deep_copy_shape_def(defn) for name, defn in shapes.items()}


def _deep_copy_shape_def(defn: dict[str, Any]) -> dict[str, Any]:
    out = dict(defn)
    props = out.get("properties")
    if isinstance(props, list):
        out["properties"] = []
        for prop in props:
            copied = dict(prop)
            target = copied.get("target function")
            if isinstance(target, dict):
                copied["target function"] = _copy_range(target)
            prop_type = copied.get("type")
            if isinstance(prop_type, list):
                copied["type"] = list(prop_type)
            flags = copied.get("flags off")
            if isinstance(flags, list):
                copied["flags off"] = list(flags)
            out["properties"].append(copied)
    return out


def _deep_copy_list(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    copied_items: list[dict[str, Any]] = []
    for item in items:
        copied = dict(item)
        target = copied.get("target range")
        if isinstance(target, dict):
            copied["target range"] = _copy_range(target)
        item_type = copied.get("type")
        if isinstance(item_type, list):
            copied["type"] = list(item_type)
        copied_items.append(copied)
    return copied_items


def _copy_range(rng: dict[str, Any]) -> dict[str, Any]:
    return {
        "start": dict(rng["start"]),
        "end": dict(rng["end"]),
    }


# --- validation ----------------------------------------------------------- #


def _require_dict(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AnnotationError(f"{what} must be an object")
    return value


def _validate_range(value: Any, what: str) -> dict[str, Any]:
    rng = _require_dict(value, what)
    for half in ("start", "end"):
        point = rng.get(half)
        if not isinstance(point, dict):
            raise AnnotationError(f"{what}.{half} must be an object")
        line = point.get("line")
        col = point.get("column")
        if not isinstance(line, int) or isinstance(line, bool) or line < 1:
            raise AnnotationError(f"{what}.{half}.line must be a positive integer")
        if not isinstance(col, int) or isinstance(col, bool) or col < 1:
            raise AnnotationError(f"{what}.{half}.column must be a positive integer")
    start = rng["start"]
    end = rng["end"]
    # Half-open [start, end): end must be after start in source order.
    if (start["line"], start["column"]) >= (end["line"], end["column"]):
        raise AnnotationError(f"{what} end must be after start (half-open range)")
    return _copy_range(rng)


def _validate_type(value: Any, what: str) -> Any:
    if isinstance(value, str):
        if value not in CONCRETE_TYPES and value != "any":
            raise AnnotationError(
                f"{what} type {value!r} is not one of {sorted(CONCRETE_TYPES)} or 'any'"
            )
        return value
    if isinstance(value, list):
        if not value:
            raise AnnotationError(f"{what} type union cannot be empty")
        if "closure" in value:
            raise AnnotationError("'closure' cannot be part of a type union")
        for t in value:
            if t not in CONCRETE_TYPES or t == "closure":
                raise AnnotationError(
                    f"{what} union element {t!r} must be a concrete non-closure type"
                )
        return list(value)
    raise AnnotationError(f"{what} type must be a string or array of concrete types")


def _normalize_shape_definition(defn: dict[str, Any], name: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    props_raw = defn.get("properties")
    if not isinstance(props_raw, list):
        raise AnnotationError(f"shape {name!r} 'properties' must be an array")
    seen_names: set[str] = set()
    normalized_props: list[dict[str, Any]] = []
    for prop in props_raw:
        prop = _require_dict(prop, f"shape {name!r} property")
        pname = prop.get("name")
        if not isinstance(pname, str) or not pname:
            raise AnnotationError(f"shape {name!r} property 'name' must be a non-empty string")
        if pname in seen_names:
            raise AnnotationError(f"shape {name!r} has duplicate property {pname!r}")
        seen_names.add(pname)
        normalized: dict[str, Any] = {"name": pname}
        if "type" in prop:
            normalized["type"] = _validate_type(prop["type"], f"shape {name!r}.{pname}")
        if "kind" in prop:
            kind = prop["kind"]
            if kind not in ("data", "accessor"):
                raise AnnotationError(
                    f"shape {name!r}.{pname} kind must be 'data' or 'accessor'"
                )
            normalized["kind"] = kind
        if "flags off" in prop:
            flags = prop["flags off"]
            if not isinstance(flags, list):
                raise AnnotationError(
                    f"shape {name!r}.{pname} 'flags off' must be an array"
                )
            bad = [f for f in flags if f not in FLAG_NAMES]
            if bad:
                raise AnnotationError(
                    f"shape {name!r}.{pname} unknown flags {bad}; allowed {sorted(FLAG_NAMES)}"
                )
            normalized["flags off"] = list(flags)
        if "target function" in prop:
            tf = _validate_range(prop["target function"], f"shape {name!r}.{pname} target function")
            normalized["target function"] = tf
        ptype = normalized.get("type", "any")
        is_closure = ptype == "closure"
        has_target = "target function" in normalized
        if is_closure and not has_target:
            raise AnnotationError(
                f"shape {name!r}.{pname} is typed 'closure' but has no 'target function'"
            )
        if has_target and not is_closure:
            raise AnnotationError(
                f"shape {name!r}.{pname} has 'target function' but type is not 'closure'"
            )
        if normalized.get("kind") == "accessor":
            if ptype not in ("any",):
                raise AnnotationError(
                    f"shape {name!r}.{pname} accessor properties must be typed 'any'"
                )
            if "flags off" in normalized and "writable" in normalized["flags off"]:
                raise AnnotationError(
                    f"shape {name!r}.{pname} accessor properties have no 'writable' flag"
                )
        normalized_props.append(normalized)
    out["properties"] = normalized_props
    return out


def _validate_array_item(
    kind: str, item: dict[str, Any], known_shapes: set[str]
) -> dict[str, Any]:
    item = _require_dict(item, f"{kind} annotation")
    out: dict[str, Any] = {}
    if "target range" not in item:
        raise AnnotationError(f"{kind} requires 'target range'")
    out["target range"] = _validate_range(item["target range"], f"{kind} target range")

    if kind == KIND_TYPE_GUARD:
        if "type" not in item:
            raise AnnotationError("type guard requires 'type'")
        out["type"] = _validate_type(item["type"], "type guard")
        _reject_unknown_keys(kind, item, {"target range", "type"})
        return out

    # Shape guards and shape bindings share the required 'shape' field.
    shape = item.get("shape")
    if not isinstance(shape, str) or not shape:
        raise AnnotationError(f"{kind} requires a string 'shape'")
    if shape not in known_shapes:
        raise AnnotationError(f"{kind} references unknown shape {shape!r}")
    out["shape"] = shape

    allowed = {"target range", "shape"}
    if kind == KIND_SHAPE_GUARD:
        proto = item.get("prototype shape")
        if proto is not None:
            if not isinstance(proto, str) or not proto:
                raise AnnotationError("shape guard 'prototype shape' must be a non-empty string")
            if proto not in known_shapes:
                raise AnnotationError(
                    f"shape guard references unknown prototype shape {proto!r}"
                )
            out["prototype shape"] = proto
            allowed.add("prototype shape")
    _reject_unknown_keys(kind, item, allowed)
    return out


def _reject_unknown_keys(kind: str, raw: dict[str, Any], allowed: set[str]) -> None:
    extra = set(raw) - allowed
    if extra:
        raise AnnotationError(f"{kind} has unknown field(s): {sorted(extra)}")


# --- canonical duplicate key ---------------------------------------------- #


def _canonical_range(rng: dict[str, Any]) -> tuple:
    s, e = rng["start"], rng["end"]
    return (s["line"], s["column"], e["line"], e["column"])


def _canonical_key(kind: str, item: dict[str, Any]) -> tuple:
    if kind == KIND_STATIC_SHAPE:
        # name uniqueness is enforced separately; not used for array dedup.
        return ()
    key: tuple = (kind, _canonical_range(item["target range"]))
    if kind == KIND_TYPE_GUARD:
        t = item["type"]
        key += (tuple(t) if isinstance(t, list) else (t,))
    elif kind == KIND_SHAPE_GUARD:
        key += (item["shape"], item.get("prototype shape"))
    return key


# --- range overlap (list line-window filter) ------------------------------ #


def _range_overlaps_window(
    rng: dict[str, Any], from_line: int, to_line: int
) -> bool:
    """Half-open SourceRange vs inclusive line window.

    The annotation range covers [start.line, end.line] at line granularity
    (end.column is exclusive but still on end.line, so end.line is in range).
    Overlap iff ``start.line <= to_line`` and ``end.line >= from_line``.
    """
    start_line = rng["start"]["line"]
    end_line = rng["end"]["line"]
    return start_line <= to_line and end_line >= from_line


# --- listing / id encoding ------------------------------------------------ #


@dataclass
class _Entry:
    kind: str
    index: int  # array index, or 0 for the single shape (name is the key)
    item: dict[str, Any]
    shape: str | None  # for static shapes / shape-bearing items


def _list_entries(
    doc: AnnotationDocument, kinds: list[str]
) -> list[_Entry]:
    entries: list[_Entry] = []
    if KIND_STATIC_SHAPE in kinds:
        for name, defn in doc.static_shapes.items():
            entries.append(_Entry(KIND_STATIC_SHAPE, 0, {name: defn}, name))
    for kind, key in _ARRAY_KINDS.items():
        if kind not in kinds:
            continue
        array = getattr(doc, _attr_for_key(key))
        for i, item in enumerate(array):
            entries.append(_Entry(kind, i, item, item.get("shape")))
    return entries


def _entry_id(entry: _Entry, revision: int) -> str:
    if entry.kind == KIND_STATIC_SHAPE:
        # index 0 is a placeholder; the shape NAME disambiguates (also encoded).
        return f"{KIND_STATIC_SHAPE}:{entry.shape}:{revision}"
    return f"{entry.kind}:{entry.index}:{revision}"


def _parse_id(doc_id: str) -> tuple[str, str | int, int]:
    parts = doc_id.split(":")
    if len(parts) != 3:
        raise AnnotationError(f"malformed id {doc_id!r}")
    kind, raw, rev = parts
    if kind not in _ALL_KINDS:
        raise AnnotationError(f"id has unknown kind {kind!r}")
    try:
        revision = int(rev)
    except ValueError as exc:
        raise AnnotationError(f"id revision is not an integer: {doc_id!r}") from exc
    if kind == KIND_STATIC_SHAPE:
        return kind, raw, revision  # 'raw' is the shape name
    try:
        return kind, int(raw), revision
    except ValueError as exc:
        raise AnnotationError(f"id index is not an integer: {doc_id!r}") from exc


# --- loc_key <-> dict range (interface boundary) -------------------------- #
# Agent-facing ranges are loc_key strings ("sl:sc:el:ec", 1-based, exclusive
# end) — unified with chunk/comment/skip. Internal storage and the flushed
# .annotations.json keep dict ranges (the C++ AnnotationLoader consumes dicts,
# AnnotationLoader.cpp:43-65). Conversion happens at this boundary. loc_key is
# the canonical interface format; a dict range is still accepted (pass-through)
# for robustness.


def parse_loc_key(s: Any) -> dict[str, Any]:
    """loc_key 'sl:sc:el:ec' -> {'start':{...},'end':{...}} (half-open)."""
    if not isinstance(s, str):
        raise AnnotationError(
            f"range must be a loc_key string 'sl:sc:el:ec', got {type(s).__name__}"
        )
    parts = s.split(":")
    if len(parts) != 4:
        raise AnnotationError(
            f"bad loc_key {s!r} (want 'startLine:startCol:endLine:endCol')"
        )
    try:
        sl, sc, el, ec = (int(x) for x in parts)
    except ValueError as exc:
        raise AnnotationError(f"bad loc_key {s!r}: {exc}")
    if sl < 1 or sc < 1 or el < 1 or ec < 1:
        raise AnnotationError(f"loc_key {s!r}: line/column must be >= 1")
    if (sl, sc) >= (el, ec):
        raise AnnotationError(f"loc_key {s!r}: end must be after start (half-open)")
    return {"start": {"line": sl, "column": sc}, "end": {"line": el, "column": ec}}


def format_loc_key(rng: dict[str, Any]) -> str:
    s, e = rng["start"], rng["end"]
    return f"{s['line']}:{s['column']}:{e['line']}:{e['column']}"


def _coerce_range(v: Any) -> Any:
    """loc_key str -> dict; dict -> pass-through; else raise."""
    if isinstance(v, str):
        return parse_loc_key(v)
    return v


def _item_ranges_to_dict(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    for fld in ("target range",):
        if fld in out:
            out[fld] = _coerce_range(out[fld])
    return out


def _shape_ranges_to_dict(shape_annotation: dict[str, Any]) -> dict[str, Any]:
    out = dict(shape_annotation)
    props = out.get("properties")
    if isinstance(props, list):
        out["properties"] = [_coerce_property_ranges(p) for p in props]
    return out


def _coerce_property_ranges(prop: Any) -> Any:
    """Coerce a single shape property's ``target function`` loc_key to a dict."""
    if isinstance(prop, dict) and "target function" in prop:
        return {**prop, "target function": _coerce_range(prop["target function"])}
    return prop


def _item_ranges_to_loc_key(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    for fld in ("target range",):
        if fld in out and isinstance(out[fld], dict):
            out[fld] = format_loc_key(out[fld])
    return out


def _shape_ranges_to_loc_key(shape_def: dict[str, Any]) -> dict[str, Any]:
    out = dict(shape_def)
    props = out.get("properties")
    if isinstance(props, list):
        new_props = []
        for p in props:
            if (
                isinstance(p, dict)
                and "target function" in p
                and isinstance(p["target function"], dict)
            ):
                p = {**p, "target function": format_loc_key(p["target function"])}
            new_props.append(p)
        out["properties"] = new_props
    return out


# --- MCP tools ------------------------------------------------------------ #


def build_annotation_tools(
    source: Path, workdir: Path, doc: AnnotationDocument
) -> list:
    """Build the annotation list/add/delete/update tools bound to ``doc``.

    The tools own no file I/O — the
    orchestrator flushes ``doc`` after the run. Exposed for tests to drive
    handlers directly."""

    @tool(
        "list_annotations",
        "List the annotations in the current document (the single source of "
        "truth — the agent does NOT write annotation.json). Filter by kind, by "
        "shape name, and/or by a 1-based inclusive line window. Each result "
        "carries a short-lived `id` (kind:index:revision) usable with "
        "delete_annotation, a `source_index`, and the full annotation body. "
        "Static shapes have no source range, so a line filter hides them — "
        "re-list without from_line/to_line to see shapes.",
        {
            "type": "object",
            "properties": {
                "kinds": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": _ALL_KINDS,
                    },
                    "description": "subset of kinds to list; omit for all",
                },
                "shape": {
                    "type": "string",
                    "description": "filter: static shape by name, or guards/bindings whose "
                    "'shape'/'prototype shape' equals this name",
                },
                "from_line": {
                    "type": "integer",
                    "description": "1-based start line (inclusive); must pair with to_line",
                },
                "to_line": {
                    "type": "integer",
                    "description": "1-based end line (inclusive); must pair with from_line",
                },
            },
        },
    )
    async def list_annotations(args: dict[str, Any]) -> dict[str, Any]:
        kinds_raw = args.get("kinds")
        if kinds_raw is None:
            kinds = list(_ALL_KINDS)
        elif isinstance(kinds_raw, list):
            kinds = [k for k in kinds_raw if k in _ALL_KINDS]
            if not kinds:
                return _err("no valid 'kinds' given")
        else:
            return _err("'kinds' must be an array")

        shape_filter = args.get("shape")
        if shape_filter is not None and not isinstance(shape_filter, str):
            return _err("'shape' must be a string")

        fl = args.get("from_line")
        tl = args.get("to_line")
        try:
            from_line = int(fl) if fl is not None else None
            to_line = int(tl) if tl is not None else None
        except (TypeError, ValueError):
            return _err("from_line/to_line must be integers")

        has_window = from_line is not None or to_line is not None
        if has_window:
            if from_line is None or to_line is None:
                return _err("specify both from_line and to_line, or neither")
            if from_line < 1 or to_line < from_line:
                return _err(f"line range [{from_line},{to_line}] invalid")
            # Static shapes have no range; drop them silently when windowed.
            kinds = [k for k in kinds if k != KIND_STATIC_SHAPE]

        entries = _list_entries(doc, kinds)
        results: list[dict[str, Any]] = []
        for entry in entries:
            if shape_filter is not None:
                if entry.kind == KIND_STATIC_SHAPE:
                    if entry.shape != shape_filter:
                        continue
                elif entry.shape != shape_filter and entry.item.get("prototype shape") != shape_filter:
                    continue
            if has_window:
                # Narrow for the type checker: has_window implies both set.
                assert from_line is not None and to_line is not None
                rng = entry.item.get("target range")
                if not isinstance(rng, dict) or not _range_overlaps_window(
                    rng, from_line, to_line
                ):
                    continue
            results.append(
                {
                    "id": _entry_id(entry, doc.revision),
                    "kind": entry.kind,
                    "source_index": entry.index if entry.kind != KIND_STATIC_SHAPE else None,
                    "shape": entry.shape,
                    "annotation": entry.item,
                }
            )

        # Stable display order: kind order, then by range, then by source_index.
        kind_order = {k: i for i, k in enumerate(_ALL_KINDS)}

        def sort_key(r: dict[str, Any]) -> tuple:
            rng = r["annotation"].get("target range") if r["kind"] != KIND_STATIC_SHAPE else None
            start = (rng["start"]["line"], rng["start"]["column"]) if rng else (0, 0)
            return (kind_order[r["kind"]], start, r["source_index"] or 0, r["shape"] or "")

        results.sort(key=sort_key)

        # Convert stored dict ranges to loc_key for the agent-facing response.
        for r in results:
            if r["kind"] == KIND_STATIC_SHAPE:
                nm, defn = next(iter(r["annotation"].items()))
                r["annotation"] = {nm: _shape_ranges_to_loc_key(defn)}
            else:
                r["annotation"] = _item_ranges_to_loc_key(r["annotation"])

        totals = {k: 0 for k in _ALL_KINDS}
        for r in results:
            totals[r["kind"]] += 1
        header = f"{len(results)} annotation(s)"
        if has_window:
            header += f"  lines {from_line}-{to_line}"
        if shape_filter is not None:
            header += f"  shape={shape_filter!r}"
        body = _format_listing(results)
        text = header + "\n" + "\n".join(body) if body else header + "\n(no matches)"
        return {"content": [{"type": "text", "text": text}]}

    @tool(
        "add_annotation",
        "Add one annotation to the in-memory document. The document is flushed "
        "to annotation.json automatically when the run ends — do not write that "
        "file yourself. Duplicates and references to unknown shapes are rejected. "
        "Use list_annotations to confirm the add and obtain the new id.",
        {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": _ALL_KINDS,
                    "description": "annotation kind to add",
                },
                "shape": {
                    "type": "string",
                    "description": "static_shape only: the shape name (its key).",
                },
                "annotation": {
                    "type": "object",
                    "description": "the annotation body. For static_shape: {properties: [...]}. "
                    "For shape_guard/shape_binding/type_guard: {target range, ...} "
                    "(see the schema).",
                },
            },
            "required": ["kind", "annotation"],
        },
    )
    async def add_annotation(args: dict[str, Any]) -> dict[str, Any]:
        kind = args.get("kind")
        if kind not in _ALL_KINDS:
            return _err(f"'kind' must be one of {_ALL_KINDS}")
        annotation = args.get("annotation")
        if not isinstance(annotation, dict):
            return _err("'annotation' must be an object")

        try:
            if kind == KIND_STATIC_SHAPE:
                name = args.get("shape")
                if not isinstance(name, str) or not name:
                    return _err("static_shape requires a non-empty 'shape' name")
                doc.add_shape(name, _shape_ranges_to_dict(annotation))
            else:
                doc.add_array_item(kind, _item_ranges_to_dict(annotation))
        except AnnotationError as exc:
            return _err(str(exc))

        text = (
            f"added {kind}"
            + (f" {args.get('shape')!r}" if kind == KIND_STATIC_SHAPE else "")
            + f" (revision {doc.revision}). Use list_annotations to see it."
        )
        return {"content": [{"type": "text", "text": text}]}

    @tool(
        "delete_annotation",
        "Delete one annotation by the id returned from list_annotations. The id "
        "embeds the revision it was issued at; if the document has changed since, "
        "the id is stale and rejected (re-list for a fresh id). Deleting a static "
        "shape still referenced by a guard/binding is rejected.",
        {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "id from a recent list_annotations (kind:index:revision)",
                },
            },
            "required": ["id"],
        },
    )
    async def delete_annotation(args: dict[str, Any]) -> dict[str, Any]:
        doc_id = args.get("id")
        if not isinstance(doc_id, str) or not doc_id:
            return _err("missing 'id'")
        try:
            kind, where, revision = _parse_id(doc_id)
        except AnnotationError as exc:
            return _err(str(exc))
        if revision != doc.revision:
            return _err(
                f"id is stale (revision {revision} != current {doc.revision}); "
                "re-list for a fresh id"
            )
        try:
            if kind == KIND_STATIC_SHAPE:
                name = where  # type: ignore[assignment]
                if not isinstance(name, str):
                    return _err("malformed static_shape id")
                removed = doc.delete_shape(name)
            else:
                removed = doc.delete_array_item(kind, where)  # type: ignore[arg-type]
        except AnnotationError as exc:
            return _err(str(exc))
        text = f"deleted {kind} (revision {doc.revision})."
        return {"content": [{"type": "text", "text": text, "removed": removed}]}  # type: ignore[dict-item]

    @tool(
        "update_annotation",
        "Patch one annotation in place by id (prefer this to delete+add for "
        "corrections). The id embeds the revision it was issued at; if the "
        "document changed since, it is stale — re-list for a fresh id. The "
        "patch merges into the existing body, re-validates, and rejects "
        "duplicates. For shape_binding/shape_guard/type_guard, patch top-level "
        "fields (target range, prototype shape, type). "
        "For static_shape, patch 'properties' (replace the whole list) or "
        "'property' ({name, ...fields} merged into one property — use this to "
        "fix a closure's 'target function' range). Field removal still needs "
        "delete+add.",
        {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "id from a recent list_annotations (kind:index:revision)",
                },
                "patch": {
                    "type": "object",
                    "description": "partial body to merge into the annotation",
                },
            },
            "required": ["id", "patch"],
        },
    )
    async def update_annotation(args: dict[str, Any]) -> dict[str, Any]:
        doc_id = args.get("id")
        if not isinstance(doc_id, str) or not doc_id:
            return _err("missing 'id'")
        patch = args.get("patch")
        if not isinstance(patch, dict):
            return _err("'patch' must be an object")
        try:
            kind, where, revision = _parse_id(doc_id)
        except AnnotationError as exc:
            return _err(str(exc))
        if revision != doc.revision:
            return _err(
                f"id is stale (revision {revision} != current {doc.revision}); "
                "re-list for a fresh id"
            )
        try:
            if kind == KIND_STATIC_SHAPE:
                name = where
                if not isinstance(name, str):
                    return _err("malformed static_shape id")
                doc.update_shape(name, patch)
            else:
                doc.update_array_item(kind, where, patch)  # type: ignore[arg-type]
        except AnnotationError as exc:
            return _err(str(exc))
        text = f"updated {kind} (revision {doc.revision}). Use list_annotations to confirm."
        return {"content": [{"type": "text", "text": text}]}

    return [list_annotations, add_annotation, delete_annotation, update_annotation]


def _format_listing(results: list[dict[str, Any]]) -> list[str]:
    import json

    lines: list[str] = []
    for r in results:
        prefix = f"[{r['id']}] {r['kind']}"
        if r["shape"]:
            prefix += f" shape={r['shape']!r}"
        rng = r["annotation"].get("target range") if r["kind"] != KIND_STATIC_SHAPE else None
        if isinstance(rng, str):
            prefix += f" range {rng}"
        lines.append(prefix)
        lines.append(json.dumps(r["annotation"], ensure_ascii=False, indent=2))
    return lines


def make_annotation_server(
    source: Path, workdir: Path, doc: AnnotationDocument
):
    """Build the in-process MCP server exposing the annotation tools."""
    return create_sdk_mcp_server(
        name="annotations",
        tools=build_annotation_tools(source, workdir, doc),
    )
