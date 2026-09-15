"""In-process MCP annotation tools over an in-memory document.

Unlike ``locate`` / ``fold`` / ``dryrun`` (read-only views), this module owns
the annotation document the agent is building. The agent NEVER writes
``annotation.json`` — it maintains the document through the list, add, delete,
and update MCP tools. The document lives in memory for the whole agent run; the
orchestrator flushes it
to disk once the run is over (see the workflow's build module under
:mod:`annotator.pipeline`). ``dryrun`` reads the current snapshot
in-process via :meth:`AnnotationDocument.to_dict` instead of parsing the file.

The persisted schema is unchanged — the same four top-level sections the
``AnnotationLoader`` expects::

    {
      "static shapes": {name: {"properties": [...]}},
      "shape guards": [...],
      "shape bindings": [...],
      "type guards": [...]
    }

Addressing is CONTENT-BASED: a static_shape is addressed by its name, every
guard/binding by its kind plus target range. Addresses never go stale, so
delete/update need no prior list call.
"""


from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..annotation_drafts import DraftsError
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from .functions import ScopeSelection, _get_parser, resolve_scope
from .locate_tool import byte_to_line_col
from .utils import _err, build_line_starts

PROMPT = (
    "- Build the annotation set ONLY through `list_annotations`, `add_annotation`, `batch_add_guards`, `update_annotation`, and `delete_annotation`. There is no annotation file — the set is held in memory and finalized for you when the run ends. If several annotation drafts are available to you, pass `draft=`; with a single draft, omit it. `create_draft(draft)` creates a new empty draft by name (idempotent) — call it before any other call that names that draft.\n"
    "- Every range — a `target range`, a closure's `target function`, any range inside an annotation body or patch — is a range_key string \"sl:sc:el:ec\" (1-based lines/columns, end column EXCLUSIVE), e.g. \"31:19:31:24\". Do NOT confuse it with a function loc_key \"31:1\" (two parts, identifies ONE function — an ID from fold/list_checklist, not a coordinate range); a range_key addresses an arbitrary expression range. dict-style range objects are not accepted.\n"
    "- `copy_annotations(source, scope?, dest?)` copies another draft's annotations into dest (default: your own), ALL OR NOTHING: any conflict fails the whole copy and NOTHING is applied — resolve the reported conflicts on your draft, then retry. Two conflict kinds: a different annotation on the same range, and a static shape whose NAME exists in both drafts with DIFFERENT properties (the drafts disagreed about that shape — do NOT let both survive silently; delete one set or `rename_shape` one side, then retry). Structurally identical shapes still fold (reported in the output — check the fold is what you meant). `scope` restricts the copy (\"file\" | one function loc_key like \"31:1\" — that function's DIRECT statements only, nested functions are independent scopes | \"<top-level>\" for module-level code | a list of them | a line range like \"31-45\", items whose own line falls inside); referenced static shapes come along. Re-run dryrun after copying.\n"
    "- `list_annotations(kinds?, shape?, scope?)` shows current annotations; filter by kind (static_shape/shape_binding/shape_guard/type_guard), by shape name, or by a scope (\"file\"/omitted for the whole file, ONE function loc_key like \"31:1\" — that function's DIRECT statements only, nested functions are independent scopes, pass their own loc_keys; \"<top-level>\" for module-level code; a list of them; or a line range like \"31-45\", items whose own line falls inside). Each row shows its address (static_shape: the shape name; others: kind + target_range as a range_key) — copy it for update/delete. Static shapes have no source range, so a scope filter hides them.\n"
    "- `add_annotation(kind, annotation, shape?)` appends one annotation; duplicates and references to unknown shapes are rejected. Range fields inside `annotation` are range_key strings. Always add the static shape BEFORE any guard/binding that uses it.\n"
    "- `batch_add_guards(scope, expression, shape?, prototype_shape?, type?, target_function?)` AST-matches one identifier/member expression throughout a scope and atomically adds ordinary independent guards. Formatting is ignored. Pass `shape` (+ optional `prototype_shape`) for shape guards or `type` (a concrete type, union array, or 'closure') for type guards — exactly one of the two; `target_function` (a range_key) is required for type 'closure' and names the closure's defining function. `scope` follows the shared contract: \"file\", one function loc_key like \"31:1\" (that function's DIRECT statements only — nested functions are independent scopes, pass their own loc_keys), \"<top-level>\", a list of them, or an inclusive line range like \"31-45\". Run dryrun afterward.\n"
    "- `update_annotation(kind, shape?, target_range?, patch)` merges a partial body into one annotation in place — PREFER this over delete+add for corrections (e.g. fixing a range or a closure `target function`). Address the item by content: static_shape by `shape` name, others by `kind` + `target_range` (the range_key from list_annotations). Range fields inside `patch` (target range, target function) are range_key strings too. For static_shape, patch `property` {name, ...fields} to fix one property.\n"
    "- `delete_annotation(kind, shape?, target_range?)` removes one annotation, addressed by content exactly like update_annotation (no list call needed first; `target_range` is the range_key from list_annotations). A static shape still used by a guard/binding cannot be deleted.\n"
    "- `rename_shape(shape, new_name)` renames a static shape and rewrites EVERY reference to it (shape guards' `shape`/`prototype shape` fields, shape bindings' `shape` field). Use it when merging drafts where two shapes share a name but describe different objects and one must move aside, or just to give a shape a clearer name. The new name must not collide with an existing shape.\n"
)

# --- constants ------------------------------------------------------------ #

SHAPES_KEY = "static shapes"
SHAPE_GUARDS_KEY = "shape guards"
SHAPE_BINDINGS_KEY = "shape bindings"
TYPE_GUARDS_KEY = "type guards"

# Canonical kind tags used everywhere (tool args and list output).
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

    Items are addressed by content: static shapes by name, guards/bindings by
    kind plus target range. There is no revision counter — an address stays
    valid across unrelated mutations.
    """

    static_shapes: dict[str, dict[str, Any]] = field(default_factory=dict)
    shape_bindings: list[dict[str, Any]] = field(default_factory=list)
    shape_guards: list[dict[str, Any]] = field(default_factory=list)
    type_guards: list[dict[str, Any]] = field(default_factory=list)

    # --- construction / serialization ------------------------------------ #

    @classmethod
    def empty(cls) -> "AnnotationDocument":
        return cls()

    def to_dict(self) -> dict[str, Any]:
        """Return an independent snapshot in the persisted schema."""
        out = {
            SHAPES_KEY: _deep_copy_shapes(self.static_shapes),
            SHAPE_GUARDS_KEY: _deep_copy_list(self.shape_guards),
            SHAPE_BINDINGS_KEY: _deep_copy_list(self.shape_bindings),
            TYPE_GUARDS_KEY: _deep_copy_list(self.type_guards),
        }
        return out

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
            type_guard_targets: set[tuple] = set()
            for item in raw_arrays[key]:
                validated = _validate_array_item(
                    kind,
                    _require_dict(item, f"{kind} annotation"),
                    known_shapes,
                )
                if kind == KIND_TYPE_GUARD:
                    target = _canonical_range(validated["target range"])
                    if target in type_guard_targets:
                        raise AnnotationError(
                            "load: type_guard target range already has a guard"
                        )
                    type_guard_targets.add(target)
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

    def add_shape(self, name: str, definition: dict[str, Any]) -> None:
        if name in self.static_shapes:
            raise AnnotationError(f"shape {name!r} already exists")
        self.static_shapes[name] = _normalize_shape_definition(definition, name)

    def add_array_item(self, kind: str, item: dict[str, Any]) -> None:
        array = self._array_for(kind)
        if array is None:
            raise AnnotationError(f"unknown array kind {kind!r}")
        validated = _validate_array_item(kind, item, self.shape_names())
        if kind == KIND_TYPE_GUARD:
            target = _canonical_range(validated["target range"])
            if any(_canonical_range(existing["target range"]) == target for existing in array):
                raise AnnotationError("type_guard target range already has a guard")
        canonical = _canonical_key(kind, validated)
        for existing in array:
            if _canonical_key(kind, existing) == canonical:
                raise AnnotationError(f"duplicate {kind} already present")
        array.append(validated)

    def add_array_items(
        self, kind: str, items: list[dict[str, Any]]
    ) -> tuple[int, int]:
        """Atomically add non-duplicate array annotations.

        Returns ``(added, skipped_existing)``.
        """
        array = self._array_for(kind)
        if array is None:
            raise AnnotationError(f"unknown array kind {kind!r}")

        existing = {_canonical_key(kind, item) for item in array}
        pending: list[dict[str, Any]] = []
        pending_keys: set[tuple] = set()
        skipped = 0
        for item in items:
            validated = _validate_array_item(kind, item, self.shape_names())
            canonical = _canonical_key(kind, validated)
            if canonical in existing or canonical in pending_keys:
                skipped += 1
                continue
            pending.append(validated)
            pending_keys.add(canonical)

        array.extend(pending)
        return len(pending), skipped

    def delete_shape(self, name: str) -> dict[str, Any]:
        if name not in self.static_shapes:
            raise AnnotationError(f"no static shape named {name!r}")
        if self.is_shape_referenced(name):
            raise AnnotationError(
                f"shape {name!r} is referenced by a guard/binding; delete those first"
            )
        removed = self.static_shapes.pop(name)
        return {SHAPES_KEY: {name: removed}}

    def find_array_items(self, kind: str, target_range: dict[str, Any]) -> list[int]:
        """Indices of the ``kind`` items whose target range is exactly
        ``target_range`` (the content address). Normally 0 or 1 entries."""
        array = self._array_for(kind)
        if array is None:
            raise AnnotationError(f"unknown array kind {kind!r}")
        target = _canonical_range(_validate_range(target_range, f"{kind} target range"))
        return [
            i for i, item in enumerate(array)
            if _canonical_range(item["target range"]) == target
        ]

    def delete_array_item(self, kind: str, index: int) -> dict[str, Any]:
        array = self._array_for(kind)
        if array is None:
            raise AnnotationError(f"unknown array kind {kind!r}")
        if not 0 <= index < len(array):
            raise AnnotationError(f"no {kind} at index {index}")
        removed = array.pop(index)
        return {_ARRAY_KINDS[kind]: removed}

    def update_array_item(self, kind: str, index: int, patch: dict[str, Any]) -> None:
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
        if kind == KIND_TYPE_GUARD:
            target = _canonical_range(validated["target range"])
            if any(
                i != index
                and _canonical_range(existing["target range"]) == target
                for i, existing in enumerate(array)
            ):
                raise AnnotationError("type_guard target range already has a guard")
        canonical = _canonical_key(kind, validated)
        for i, existing in enumerate(array):
            if i != index and _canonical_key(kind, existing) == canonical:
                raise AnnotationError(f"duplicate {kind} already present")
        array[index] = validated

    def update_shape(self, name: str, patch: dict[str, Any]) -> None:
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

    def rename_shape(self, name: str, new_name: str) -> int:
        """Rename a static shape and rewrite every guard/binding reference.

        Returns the number of references rewritten. ``new_name`` must not
        collide with another shape (renaming to the current name is a no-op).
        """
        if name not in self.static_shapes:
            raise AnnotationError(f"no static shape named {name!r}")
        if new_name == name:
            return 0
        if new_name in self.static_shapes:
            raise AnnotationError(
                f"cannot rename {name!r} to {new_name!r}: a shape with that "
                f"name already exists"
            )
        names = {name: new_name}
        self.static_shapes = {
            (names.get(k, k)): v for k, v in self.static_shapes.items()
        }
        self.shape_bindings = [
            _rename_shape_refs(item, names) for item in self.shape_bindings
        ]
        self.shape_guards = [
            _rename_shape_refs(item, names) for item in self.shape_guards
        ]
        return _count_shape_refs(self.shape_bindings + self.shape_guards, new_name)


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
        target_function = copied.get("target function")
        if isinstance(target_function, dict):
            copied["target function"] = _copy_range(target_function)
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
        is_closure = out["type"] == "closure"
        has_target = "target function" in item
        if is_closure and not has_target:
            raise AnnotationError(
                "type guard typed 'closure' requires 'target function'"
            )
        if has_target and not is_closure:
            raise AnnotationError(
                "type guard 'target function' is only valid for type 'closure'"
            )
        if has_target:
            out["target function"] = _validate_range(
                item["target function"], "type guard target function"
            )
        _reject_unknown_keys(
            kind, item, {"target range", "type", "target function"}
        )
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


# --- cross-draft copy (compatibility-aware) -------------------------------- #

# Shape structural identity: the full normalized definition (property order
# included — it carries HiddenClass semantics). Two drafts naming the same
# structure can fold; a name shared by different structures must not.
_ShapeStructure = tuple


def _shape_structure(defn: dict[str, Any]) -> _ShapeStructure:
    props = defn.get("properties", [])
    return tuple(
        (
            p.get("name"),
            tuple(p["type"]) if isinstance(p.get("type"), list) else p.get("type"),
            p.get("kind"),
            tuple(p.get("flags off", [])),
            _canonical_range(p["target function"])
            if isinstance(p.get("target function"), dict)
            else None,
        )
        for p in props
    )


def _rename_shape_refs(
    item: dict[str, Any], names: dict[str, str]
) -> dict[str, Any]:
    """Rewrite one annotation's shape references through a copy-time map."""
    out = dict(item)
    if out.get("shape") in names:
        out["shape"] = names[out["shape"]]
    if out.get("prototype shape") in names:
        out["prototype shape"] = names[out["prototype shape"]]
    return out


def _count_shape_refs(items: list[dict[str, Any]], name: str) -> int:
    """How many guards/bindings cite ``name`` (as ``shape`` or prototype)."""
    return sum(
        1
        for item in items
        if item.get("shape") == name or item.get("prototype shape") == name
    )


def _shape_property_names(defn: dict[str, Any]) -> list[str]:
    """Ordered property names of one shape definition (conflict reports)."""
    return [p.get("name", "?") for p in defn.get("properties", [])]


def plan_copy(
    dest: "AnnotationDocument",
    source: "AnnotationDocument",
    selects: Any = None,
) -> dict[str, Any]:
    """Plan (without mutating) copying ``source`` into ``dest``.

    ``selects(item) -> bool`` restricts the copy to the array annotations it
    accepts (the scope's selection predicate; None copies the whole draft);
    the static shapes the selected annotations reference are pulled in as
    dependencies. Returns
    the plan dict: a ``report`` (shapes_added/mapped, skipped,
    conflicts, counts), the blocking ``errors`` (any conflict — same range
    with a different annotation, or a shape name claimed by a different
    structure — or missing shape dependency; the copy is all-or-nothing), and
    the private payload :func:`apply_copy` consumes. An empty ``errors``
    means the plan applies atomically.
    """
    report: dict[str, Any] = {
        "shapes_added": [],
        "shapes_mapped": [],
        "skipped": [],
        "conflicts": [],
        "counts": {"bindings": 0, "guards": 0, "type_guards": 0},
    }
    errors: list[AnnotationError] = []
    # Pass 0 — select the source's array annotations (whole draft, or the
    # scope's selection) and collect the shapes they reference.
    selected: dict[str, list[dict[str, Any]]] = {}
    needed_shapes: set[str] = set()
    for kind in (KIND_SHAPE_BINDING, KIND_SHAPE_GUARD, KIND_TYPE_GUARD):
        items = source._array_for(kind) or []
        if selects is not None:
            items = [i for i in items if selects(i)]
        selected[kind] = items
        for item in items:
            for field in ("shape", "prototype shape"):
                if isinstance(item.get(field), str):
                    needed_shapes.add(item[field])

    # Pass 1 — shapes: plan the name map (source name -> dest name) for the
    # needed shapes only. Structural identity folds (dest name wins); a name
    # claimed by a DIFFERENT structure is a conflict the agent must arbitrate
    # — the drafts disagreed about what that shape is, and silently keeping
    # both (e.g. under an auto-generated alias) ships guards that can never
    # pass. The copy is all-or-nothing, so the conflict blocks the plan.
    dest_structures: dict[_ShapeStructure, str] = {
        _shape_structure(defn): name for name, defn in dest.static_shapes.items()
    }
    name_map: dict[str, str] = {}
    shapes_to_add: dict[str, dict[str, Any]] = {}
    for src_name in sorted(needed_shapes):
        src_defn = source.static_shapes.get(src_name)
        if src_defn is None:  # pragma: no cover — validated documents
            errors.append(
                AnnotationError(
                    f"copied annotation references unknown shape {src_name!r}"
                )
            )
            continue
        structure = _shape_structure(src_defn)
        existing = dest_structures.get(structure)
        if existing is not None:
            # Same definition: fold (also when the name itself matches).
            name_map[src_name] = existing
            if existing != src_name:
                report["shapes_mapped"].append({"from": src_name, "to": existing})
            continue
        if src_name in dest.static_shapes:
            dest_defn = dest.static_shapes[src_name]
            conflict = {
                "shape": src_name,
                "dest_properties": _shape_property_names(dest_defn),
                "source_properties": _shape_property_names(src_defn),
                "dest_references": _count_shape_refs(
                    dest.shape_bindings + dest.shape_guards, src_name
                ),
                "source_references": _count_shape_refs(
                    source.shape_bindings + source.shape_guards, src_name
                ),
            }
            report["conflicts"].append(conflict)
            errors.append(
                AnnotationError(
                    f"shape name conflict on {src_name!r}: both drafts define "
                    f"this name with DIFFERENT properties (dest: "
                    f"{conflict['dest_properties']}, source: "
                    f"{conflict['source_properties']}); dest guards/bindings "
                    f"referencing it: {conflict['dest_references']}, source: "
                    f"{conflict['source_references']}. The drafts likely "
                    f"disagree about what {src_name!r} is — decide which "
                    f"definition wins: delete one side's shape and its "
                    f"guards/bindings, or rename_shape one side first, then "
                    f"retry the copy"
                )
            )
            continue
        shapes_to_add[src_name] = _deep_copy_shape_def(src_defn)
        dest_structures[structure] = src_name
        name_map[src_name] = src_name
        report["shapes_added"].append(src_name)

    # Pass 2 — array annotations: skip identical, record conflicts (the
    # copy is all-or-nothing, so any conflict blocks the whole plan).
    to_apply: dict[str, list[dict[str, Any]]] = {}
    for kind in (KIND_SHAPE_BINDING, KIND_SHAPE_GUARD, KIND_TYPE_GUARD):
        existing_by_range: dict[tuple, dict[str, Any]] = {
            _canonical_range(item["target range"]): item
            for item in (dest._array_for(kind) or [])
        }
        pending: list[dict[str, Any]] = []
        for src_item in selected[kind]:
            key = _canonical_range(src_item["target range"])
            dest_item = existing_by_range.get(key)
            if dest_item is None:
                pending.append(_rename_shape_refs(src_item, name_map))
                continue
            if _canonical_key(kind, dest_item) == _canonical_key(
                kind, _rename_shape_refs(src_item, name_map)
            ):
                report["skipped"].append(
                    {"kind": kind, "location": format_range_key(src_item["target range"])}
                )
            else:
                conflict = {
                    "kind": kind,
                    "location": format_range_key(src_item["target range"]),
                    "dest": _item_ranges_to_range_key(dest_item),
                    "source": _item_ranges_to_range_key(
                        _rename_shape_refs(src_item, name_map)
                    ),
                }
                report["conflicts"].append(conflict)
                errors.append(
                    AnnotationError(
                        f"conflict at {conflict['location']}: dest has "
                        f"{dest_item.get('shape') or dest_item.get('type')}, "
                        f"source has "
                        f"{src_item.get('shape') or src_item.get('type')}"
                    )
                )
        to_apply[kind] = pending
        report["counts"][
            {
                KIND_SHAPE_BINDING: "bindings",
                KIND_SHAPE_GUARD: "guards",
                KIND_TYPE_GUARD: "type_guards",
            }[kind]
        ] = len(pending)

    return {
        "report": report,
        "errors": errors,
        "shapes_to_add": shapes_to_add,
        "to_apply": to_apply,
    }


def apply_copy(dest: "AnnotationDocument", plan: dict[str, Any]) -> dict[str, Any]:
    """Apply a :func:`plan_copy` plan atomically (all or nothing).

    Raises the first blocking error when the plan has any — ``dest`` stays
    untouched. A successful apply mutates ``dest`` and returns the report.
    """
    if plan["errors"]:
        raise plan["errors"][0]
    for name, defn in plan["shapes_to_add"].items():
        dest.add_shape(name, defn)
    for kind, items in plan["to_apply"].items():
        if items:
            dest.add_array_items(kind, items)
    return plan["report"]


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
        target_function = item.get("target function")
        if isinstance(target_function, dict):
            key += (_canonical_range(target_function),)
    elif kind == KIND_SHAPE_GUARD:
        key += (item["shape"], item.get("prototype shape"))
    return key


# --- AST expression matching ---------------------------------------------- #


_BATCH_EXPRESSION_TYPES = frozenset(
    {"identifier", "member_expression", "subscript_expression"}
)


def _ast_key(node, data: bytes) -> tuple:
    """Formatting-insensitive structural identity for one expression node."""
    children = [child for child in node.children if child.type != "comment"]
    if not children:
        text = data[node.start_byte:node.end_byte].decode("utf-8", "replace")
        return node.type, text
    return node.type, tuple(_ast_key(child, data) for child in children)


def _parse_batch_expression(expression: str) -> tuple[str, tuple]:
    stripped = expression.strip()
    if not stripped:
        raise AnnotationError("'expression' must be non-empty")
    data = stripped.encode("utf-8")
    tree = _get_parser().parse(data)
    root = tree.root_node
    if root.has_error or len(root.named_children) != 1:
        raise AnnotationError("'expression' must be one valid JavaScript expression")
    statement = root.named_children[0]
    if statement.type != "expression_statement" or len(statement.named_children) != 1:
        raise AnnotationError("'expression' must be one valid JavaScript expression")
    expr = statement.named_children[0]
    if expr.start_byte != 0 or expr.end_byte != len(data):
        raise AnnotationError("'expression' must not include an extra statement or semicolon")
    if expr.type not in _BATCH_EXPRESSION_TYPES:
        raise AnnotationError(
            "'expression' must be an identifier or member expression"
        )
    return expr.type, _ast_key(expr, data)


def _matching_expression_matches(
    source: Path,
    selection: ScopeSelection,
    expression: str,
) -> list[tuple[dict[str, Any], bool]]:
    """Structural matches of ``expression`` selected by ``selection``.

    Returns ``(range, is_declaration)`` pairs; a declaration is an identifier
    directly under a ``formal_parameters`` node (a parameter name).
    """
    data = source.read_bytes()
    line_starts = build_line_starts(data)
    tree = _get_parser().parse(data)
    if tree.root_node.has_error:
        raise AnnotationError("source contains JavaScript parse errors")
    wanted_type, wanted_key = _parse_batch_expression(expression)

    matches: list[tuple[dict[str, Any], bool]] = []
    stack: list[tuple[Any, bool]] = [(tree.root_node, False)]
    while stack:
        node, in_params = stack.pop()
        is_params = node.type == "formal_parameters"
        if node.type == wanted_type and _ast_key(node, data) == wanted_key:
            sl, sc = byte_to_line_col(node.start_byte, line_starts, data)
            if selection.owns(sl, sc):
                el, ec = byte_to_line_col(node.end_byte, line_starts, data)
                matches.append(
                    (
                        {
                            "start": {"line": sl, "column": sc},
                            "end": {"line": el, "column": ec},
                        },
                        in_params,
                    )
                )
        stack.extend(reversed([(c, is_params) for c in node.children]))
    return matches


# --- listing ---------------------------------------------------------------- #


@dataclass
class _Entry:
    kind: str
    item: dict[str, Any]
    shape: str | None  # for static shapes / shape-bearing items


def _list_entries(
    doc: AnnotationDocument, kinds: list[str]
) -> list[_Entry]:
    entries: list[_Entry] = []
    if KIND_STATIC_SHAPE in kinds:
        for name, defn in doc.static_shapes.items():
            entries.append(_Entry(KIND_STATIC_SHAPE, {name: defn}, name))
    for kind, key in _ARRAY_KINDS.items():
        if kind not in kinds:
            continue
        array = getattr(doc, _attr_for_key(key))
        for item in array:
            entries.append(_Entry(kind, item, item.get("shape")))
    return entries


# --- range_key <-> dict range (interface boundary) ------------------------ #
# The ONLY agent-facing range format is the range_key string "sl:sc:el:ec"
# (1-based, exclusive end): every range-like tool argument, annotation-body
# field, patch field, and rendered output carries it — dict ranges are never
# accepted nor emitted at the interface. A FUNCTION loc_key ("sl:sc", two
# parts) is a different key: it identifies one function, not an arbitrary
# expression range. Internal storage and the flushed .annotations.json keep
# dict ranges (the C++ AnnotationLoader consumes dicts,
# AnnotationLoader.cpp:43-65). Conversion happens only here.


def parse_range_key(s: Any) -> dict[str, Any]:
    """range_key 'sl:sc:el:ec' -> {'start':{...},'end':{...}} (half-open).

    Distinct from a FUNCTION loc_key ("sl:sc", the start-point function ID);
    a range_key addresses an arbitrary expression range."""
    if not isinstance(s, str):
        raise AnnotationError(
            f"range must be a range_key string 'sl:sc:el:ec', got {type(s).__name__}"
        )
    parts = s.split(":")
    if len(parts) != 4:
        raise AnnotationError(
            f"bad range_key {s!r} (want 'startLine:startCol:endLine:endCol')"
        )
    try:
        sl, sc, el, ec = (int(x) for x in parts)
    except ValueError as exc:
        raise AnnotationError(f"bad range_key {s!r}: {exc}")
    if sl < 1 or sc < 1 or el < 1 or ec < 1:
        raise AnnotationError(f"range_key {s!r}: line/column must be >= 1")
    if (sl, sc) >= (el, ec):
        raise AnnotationError(f"range_key {s!r}: end must be after start (half-open)")
    return {"start": {"line": sl, "column": sc}, "end": {"line": el, "column": ec}}


def format_range_key(rng: dict[str, Any]) -> str:
    s, e = rng["start"], rng["end"]
    return f"{s['line']}:{s['column']}:{e['line']}:{e['column']}"


def _item_ranges_to_dict(item: dict[str, Any]) -> dict[str, Any]:
    """Convert one annotation body's range fields (agent strings) to dicts."""
    out = dict(item)
    for fld in ("target range", "target function"):
        if fld in out:
            out[fld] = parse_range_key(out[fld])
    return out


def _shape_ranges_to_dict(shape_annotation: dict[str, Any]) -> dict[str, Any]:
    out = dict(shape_annotation)
    props = out.get("properties")
    if isinstance(props, list):
        out["properties"] = [_coerce_property_ranges(p) for p in props]
    return out


def _coerce_property_ranges(prop: Any) -> Any:
    """Convert one shape property's ``target function`` range_key to a dict."""
    if isinstance(prop, dict) and "target function" in prop:
        return {**prop, "target function": parse_range_key(prop["target function"])}
    return prop


def _item_ranges_to_range_key(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    for fld in ("target range", "target function"):
        if fld in out and isinstance(out[fld], dict):
            out[fld] = format_range_key(out[fld])
    return out


def _shape_ranges_to_range_key(shape_def: dict[str, Any]) -> dict[str, Any]:
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
                p = {**p, "target function": format_range_key(p["target function"])}
            new_props.append(p)
        out["properties"] = new_props
    return out


# --- MCP tools ------------------------------------------------------------ #


def build_annotation_tools(
    source: Path,
    workdir: Path,
    names: list[str] | None = None,
    default: str | None = None,
) -> list:
    """Build the annotation list/add/delete/update tools over named drafts.

    ``names`` are the drafts this agent may use and ``default`` the one used
    when the optional ``draft`` argument is omitted (the single-draft agent
    never passes it). ``names=None`` means open access: any draft in the
    store by name (the coordinator, whose jobs' draft names are only known
    at launch time). The tools own no file I/O — the orchestrator flushes
    the drafts after the run. Exposed for tests to drive handlers
    directly."""

    from ..annotation_drafts import drafts

    if names is None:
        default_name = default
    else:
        default_name = default if default is not None else (
            names[0] if len(names) == 1 else None
        )

    def _draft_prop() -> dict[str, Any]:
        # Only meaningful when the agent sees several drafts; omitting it
        # selects the default one.
        prop: dict[str, Any] = {
            "type": "string",
            "description": "annotation draft this call applies to; omit when "
            "you have exactly one",
        }
        if names is not None:
            prop["enum"] = list(names)
        else:
            prop["description"] += " (a draft name from the store)"
        return prop

    def _resolve_read(args: dict[str, Any]):
        name = args.get("draft") or default_name
        if not isinstance(name, str):
            return _err(
                "several drafts available, pass draft= (one of: "
                + (", ".join(names) if names is not None else "the store")
                + ")"
            )
        try:
            return drafts().get(name)
        except DraftsError as exc:
            return _err(str(exc))

    def _resolve_write(args: dict[str, Any]):
        return _resolve_read(args)

    @tool(
        "list_annotations",
        "List the annotations in the current draft (the single source of "
        "truth — the agent does NOT write annotation.json). Filter by kind, by "
        "shape name, and/or by a scope: \"file\" (default), ONE function "
        "loc_key like \"31:1\" (that function's DIRECT statements only — "
        "nested functions are independent scopes, pass their own loc_keys), "
        "\"<top-level>\" for module-level code, a list of loc_keys, or a "
        "line range like \"31-45\" (annotations whose target range overlaps "
        "it). Each result shows the full "
        "annotation body with its content address: the shape name for "
        "static_shape, the target_range (a range_key 'sl:sc:el:ec', 1-based, "
        "end column exclusive) for shape_guard/shape_binding/"
        "type_guard — pass that to delete_annotation/update_annotation. "
        "Static shapes have no source range, so a scope filter hides them — "
        "re-list with scope \"file\" to see shapes.",
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
                "scope": {
                    "type": ["string", "array"],
                    "description": "\"file\" (default), ONE function loc_key like \"31:1\" (that function's DIRECT statements only — nested functions are independent scopes, pass their own loc_keys), \"<top-level>\" for module-level code, a list of loc_keys like [\"31:1\", \"35:1\"], or an inclusive line range like \"31-45\" (annotations whose target range overlaps it)",
                    "items": {"type": "string"},
                },
                "draft": _draft_prop(),
            },
        },
    )
    async def list_annotations(args: dict[str, Any]) -> dict[str, Any]:
        doc = _resolve_read(args)
        if isinstance(doc, dict):
            return doc
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

        scope = args.get("scope", "file")
        try:
            selection = resolve_scope(scope, source.read_bytes())
        except ValueError:
            return _err(f"unknown or malformed scope {scope!r}")
        except OSError:
            return _err("could not read the source file for scope resolution")
        has_scope = not selection.is_whole_file
        if has_scope:
            # Static shapes have no range; drop them silently when scoped.
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
            if has_scope:
                rng = entry.item.get("target range")
                if not isinstance(rng, dict) or not selection.selects_range(rng):
                    continue
            results.append(
                {
                    "kind": entry.kind,
                    "shape": entry.shape,
                    "target_range": format_range_key(entry.item["target range"])
                    if entry.kind != KIND_STATIC_SHAPE
                    else None,
                    "annotation": entry.item,
                }
            )

        # Stable display order: kind order, then by range, then by shape name.
        kind_order = {k: i for i, k in enumerate(_ALL_KINDS)}

        def sort_key(r: dict[str, Any]) -> tuple:
            rng = r["annotation"].get("target range") if r["kind"] != KIND_STATIC_SHAPE else None
            start = (rng["start"]["line"], rng["start"]["column"]) if rng else (0, 0)
            return (kind_order[r["kind"]], start, r["shape"] or "")

        results.sort(key=sort_key)

        # Convert stored dict ranges to loc_key for the agent-facing response.
        for r in results:
            if r["kind"] == KIND_STATIC_SHAPE:
                nm, defn = next(iter(r["annotation"].items()))
                r["annotation"] = {nm: _shape_ranges_to_range_key(defn)}
            else:
                r["annotation"] = _item_ranges_to_range_key(r["annotation"])

        totals = {k: 0 for k in _ALL_KINDS}
        for r in results:
            totals[r["kind"]] += 1
        header = f"{len(results)} annotation(s)"
        if selection.window is not None:
            header += f"  lines {selection.window[0]}-{selection.window[1]}  (scope {scope!r})"
        elif has_scope:
            header += f"  (scope {scope!r})"
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
        "Use list_annotations to confirm the add.",
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
                    "description": "the annotation body. For static_shape: {properties: [...]} "
                    "(a closure property's 'target function' is a range_key string "
                    "'sl:sc:el:ec'). For shape_guard/shape_binding/type_guard: "
                    "{'target range': 'sl:sc:el:ec', ...} — every range field is a "
                    "range_key string (1-based, end column exclusive), NOT a dict "
                    "(see the schema).",
                },
                "draft": _draft_prop(),
            },
            "required": ["kind", "annotation"],
        },
    )
    async def add_annotation(args: dict[str, Any]) -> dict[str, Any]:
        doc = _resolve_write(args)
        if isinstance(doc, dict):
            return doc
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
            + ". Use list_annotations to see it."
        )
        return {"content": [{"type": "text", "text": text}]}

    @tool(
        "batch_add_guards",
        "Add a guard to every structurally matching identifier or member "
        "expression in a scope. Matching is AST-based and ignores formatting; "
        "comments and strings do not match. Pass `shape` (with optional "
        "`prototype_shape`) for shape guards or `type` for type guards — "
        "exactly one of the two; type 'closure' also requires `target_function` "
        "(a range_key naming the closure's defining function). `scope` follows "
        "the shared contract: \"file\", one function loc_key (that function's "
        "DIRECT statements only — nested functions are independent scopes, "
        "pass their own loc_keys), \"<top-level>\", a list of them, or an "
        "inclusive line range. Each match is stored as an ordinary "
        "independent guard; the persisted schema does not change. Existing "
        "identical guards are skipped idempotently.",
        {
            "type": "object",
            "properties": {
                "scope": {
                    "type": ["string", "array"],
                    "description": "\"file\" (default), ONE function loc_key like \"31:1\" (that function's DIRECT statements only — nested functions are independent scopes, pass their own loc_keys), \"<top-level>\", a list of loc_keys, or an inclusive line range like \"31-45\"",
                    "items": {"type": "string"},
                },
                "expression": {
                    "type": "string",
                    "description": "one identifier or member expression to match structurally",
                },
                "shape": {
                    "type": "string",
                    "description": "existing static shape for every generated shape_guard",
                },
                "prototype_shape": {
                    "type": "string",
                    "description": "optional existing prototype shape (shape guards only)",
                },
                "type": {
                    "description": "type for every generated type_guard: a concrete type "
                    "(number/string/boolean/null/undefined/closure) or a union array",
                    "anyOf": [
                        {
                            "type": "string",
                            "enum": sorted(CONCRETE_TYPES),
                        },
                        {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    ],
                },
                "target_function": {
                    "type": "string",
                    "description": "type 'closure' only (required): the range_key of the "
                    "closure's defining function",
                },
                "draft": _draft_prop(),
            },
            "required": ["expression"],
        },
    )
    async def batch_add_guards(args: dict[str, Any]) -> dict[str, Any]:
        doc = _resolve_write(args)
        if isinstance(doc, dict):
            return doc
        expression = args.get("expression")
        scope = args.get("scope", "file")
        shape = args.get("shape")
        prototype_shape = args.get("prototype_shape")
        item_type = args.get("type")
        target_function = args.get("target_function")
        if not isinstance(expression, str):
            return _err("'expression' must be a string")
        if shape is None and item_type is None:
            return _err("pass exactly one of 'shape' or 'type'")
        if shape is not None and item_type is not None:
            return _err("'shape' and 'type' are mutually exclusive")

        try:
            selection = resolve_scope(scope, source.read_bytes())
            if shape is not None:
                kind = KIND_SHAPE_GUARD
                if not isinstance(shape, str) or not shape:
                    raise AnnotationError("'shape' must be a non-empty string")
                if prototype_shape is not None and (
                    not isinstance(prototype_shape, str) or not prototype_shape
                ):
                    raise AnnotationError(
                        "'prototype_shape' must be a non-empty string"
                    )
                if shape not in doc.shape_names():
                    raise AnnotationError(
                        f"shape guard references unknown shape {shape!r}"
                    )
                if (
                    prototype_shape is not None
                    and prototype_shape not in doc.shape_names()
                ):
                    raise AnnotationError(
                        "shape guard references unknown prototype shape "
                        f"{prototype_shape!r}"
                    )
            else:
                kind = KIND_TYPE_GUARD
                # Reuse add_annotation's body validation (type value, closure
                # <-> target_function pairing) with a placeholder range.
                _validate_array_item(
                    kind,
                    {
                        "target range": {
                            "start": {"line": 1, "column": 1},
                            "end": {"line": 1, "column": 2},
                        },
                        "type": item_type,
                        **(
                            {"target function": parse_range_key(target_function)}
                            if target_function is not None
                            else {}
                        ),
                    },
                    set(),
                )
            matches = _matching_expression_matches(
                source, selection, expression
            )
            guards = []
            for target_range, _is_declaration in matches:
                guard: dict[str, Any] = {"target range": target_range}
                if kind == KIND_SHAPE_GUARD:
                    guard["shape"] = shape
                    if prototype_shape is not None:
                        guard["prototype shape"] = prototype_shape
                else:
                    guard["type"] = item_type
                    if target_function is not None:
                        guard["target function"] = parse_range_key(target_function)
                guards.append(guard)
            added, skipped = doc.add_array_items(kind, guards)
        except (AnnotationError, OSError, ValueError) as exc:
            return _err(str(exc))

        declarations = sum(1 for _, d in matches if d)
        label = "shape_guard" if kind == KIND_SHAPE_GUARD else "type_guard"
        text = (
            f"matched {len(matches)} (declarations {declarations}, "
            f"uses {len(matches) - declarations}); added {added} {label}(s); "
            f"skipped {skipped} existing duplicate(s)."
        )
        return {
            "content": [
                {
                    "type": "text",
                    "text": text,
                    "ranges": [format_range_key(rng) for rng, _ in matches],
                }
            ]
        }

    def _resolve_index(
        doc: AnnotationDocument, kind: str, args: dict[str, Any]
    ) -> int | str | dict[str, Any]:
        """Resolve a content address (tool args) to the target item.

        static_shape resolves to the shape name; array kinds resolve to the
        unique index behind kind + target range — with the optional ``shape``
        filter narrowing same-range shape guards. Raises on none/ambiguous.
        """
        if kind == KIND_STATIC_SHAPE:
            name = args.get("shape")
            if not isinstance(name, str) or not name:
                raise AnnotationError("static_shape requires 'shape' (the name)")
            return name
        raw = args.get("target_range")
        if not isinstance(raw, str) or not raw:
            raise AnnotationError(f"{kind} requires 'target_range' (a range_key 'sl:sc:el:ec')")
        try:
            target = parse_range_key(raw)
        except AnnotationError as exc:
            raise AnnotationError(f"bad target_range: {exc}") from exc
        matches = doc.find_array_items(kind, target)
        shape_filter = args.get("shape")
        if shape_filter is not None and shape_filter:
            matches = [
                i
                for i in matches
                if (doc._array_for(kind) or [])[i].get("shape") == shape_filter
            ]
        if not matches:
            hint = (
                f" with shape {shape_filter!r}" if shape_filter else ""
            )
            raise AnnotationError(
                f"no {kind} with target range {raw!r}{hint} — run "
                "list_annotations to see current addresses"
            )
        if len(matches) > 1:
            raise AnnotationError(
                f"{kind} with target range {raw!r} is ambiguous "
                f"({len(matches)} entries); pass 'shape' to disambiguate — "
                "run list_annotations to inspect"
            )
        return matches[0]

    @tool(
        "delete_annotation",
        "Delete one annotation, addressed by content (no list call needed "
        "first): static_shape by `shape` name; shape_guard/shape_binding/"
        "type_guard by `kind` + `target_range` (the range_key shown by "
        "list_annotations). Deleting a static shape still referenced by a "
        "guard/binding is rejected.",
        {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": _ALL_KINDS,
                    "description": "annotation kind to delete",
                },
                "shape": {
                    "type": "string",
                    "description": "static_shape: the shape name (its key). "
                    "shape_guard/shape_binding with a shared target_range: "
                    "optional filter by shape name to disambiguate.",
                },
                "target_range": {
                    "type": "string",
                    "description": "non-static kinds only: the target range "
                    "range_key 'sl:sc:el:ec' (1-based, end column exclusive; NOT "
                    "a function loc_key 'sl:sc' and not a dict)",
                },
                "draft": _draft_prop(),
            },
            "required": ["kind"],
        },
    )
    async def delete_annotation(args: dict[str, Any]) -> dict[str, Any]:
        doc = _resolve_write(args)
        if isinstance(doc, dict):
            return doc
        kind = args.get("kind")
        if kind not in _ALL_KINDS:
            return _err(f"'kind' must be one of {_ALL_KINDS}")
        try:
            where = _resolve_index(doc, kind, args)
            if kind == KIND_STATIC_SHAPE:
                removed = doc.delete_shape(where)
                removed = {
                    key: {name: _shape_ranges_to_range_key(defn)}
                    for key, shapes in removed.items()
                    for name, defn in shapes.items()
                }
            else:
                removed = doc.delete_array_item(kind, where)
                removed = {
                    key: _item_ranges_to_range_key(item)
                    for key, item in removed.items()
                }
        except AnnotationError as exc:
            return _err(str(exc))
        return {"content": [{"type": "text", "text": f"deleted {kind}.", "removed": removed}]}  # type: ignore[dict-item]

    @tool(
        "update_annotation",
        "Patch one annotation in place (prefer this to delete+add for "
        "corrections), addressed by content exactly like delete_annotation: "
        "static_shape by `shape` name; other kinds by `kind` + `target_range`. "
        "The patch merges into the existing body, re-validates, and rejects "
        "duplicates. For shape_binding/shape_guard/type_guard, patch top-level "
        "fields (target range, prototype shape, type). "
        "For static_shape, patch 'properties' (replace the whole list) or "
        "'property' ({name, ...fields} merged into one property — use this to "
        "fix a closure's 'target function' range). Any range field inside the "
        "patch (target range, target function) is a range_key string "
        "'sl:sc:el:ec', never a dict. Field removal still needs delete+add.",
        {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": _ALL_KINDS,
                    "description": "annotation kind to update",
                },
                "shape": {
                    "type": "string",
                    "description": "static_shape: the shape name (its key). "
                    "shape_guard/shape_binding with a shared target_range: "
                    "optional filter by shape name to disambiguate.",
                },
                "target_range": {
                    "type": "string",
                    "description": "non-static kinds only: the target range "
                    "range_key 'sl:sc:el:ec' (1-based, end column exclusive; NOT "
                    "a function loc_key 'sl:sc' and not a dict)",
                },
                "patch": {
                    "type": "object",
                    "description": "partial body to merge into the annotation; "
                    "range fields ('target range', 'target function') are "
                    "range_key strings 'sl:sc:el:ec', not dicts",
                },
                "draft": _draft_prop(),
            },
            "required": ["kind", "patch"],
        },
    )
    async def update_annotation(args: dict[str, Any]) -> dict[str, Any]:
        doc = _resolve_write(args)
        if isinstance(doc, dict):
            return doc
        kind = args.get("kind")
        if kind not in _ALL_KINDS:
            return _err(f"'kind' must be one of {_ALL_KINDS}")
        patch = args.get("patch")
        if not isinstance(patch, dict):
            return _err("'patch' must be an object")
        try:
            where = _resolve_index(doc, kind, args)
            if kind == KIND_STATIC_SHAPE:
                doc.update_shape(where, patch)
            else:
                doc.update_array_item(kind, where, patch)
        except AnnotationError as exc:
            return _err(str(exc))
        text = f"updated {kind}. Use list_annotations to confirm."
        return {"content": [{"type": "text", "text": text}]}

    @tool(
        "save_annotations",
        "Persist one draft to a file named after it in your working directory "
        "(e.g. draft 'hotspot:2' -> 'hotspot:2.json'). Saving "
        "is YOUR job — an unsaved draft is not a product and is lost when "
        "the session ends; the host ships only what you saved. Call this "
        "when your work is finished (the host prompts you if you forget).",
        {
            "type": "object",
            "properties": {
                "draft": _draft_prop(),
            },
        },
    )
    async def save_annotations(args: dict[str, Any]) -> dict[str, Any]:
        try:
            name = args.get("draft") or default_name
            if name is None:
                raise DraftsError(
                    "several drafts available, pass draft= (one of: "
                    + (", ".join(names) if names is not None else "the store")
                    + ")"
                )
            doc = drafts().get(name)
        except DraftsError as exc:
            return _err(str(exc))
        import json

        from .checklist_tool import REASONS_KEY, reasons
        from .utils import atomic_write_json

        payload = json.loads(doc.to_json())
        # Bridge the split reason store back into the saved product so the
        # persisted schema (and re-seeded drafts) keep their reasons.
        try:
            records = reasons().get(name)
        except Exception:  # noqa: BLE001 — no reasons for this draft
            records = []
        if records:
            payload[REASONS_KEY] = records
        path = workdir / f"{name}.json"
        atomic_write_json(path, payload)
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"saved draft {name!r} to {path.name}",
                }
            ]
        }

    @tool(
        "copy_annotations",
        "Copy annotations from another draft into yours — ALL OR NOTHING: "
        "either everything in scope copies cleanly or NOTHING is copied and "
        "every conflict is reported for you to resolve first "
        "(update_annotation/delete on YOUR draft, then retry). Two conflict "
        "kinds: a different annotation on the same target range, and a "
        "static shape whose NAME exists in both drafts with DIFFERENT "
        "properties — the drafts disagreed about that shape; do NOT let both "
        "survive silently (delete one side's shape and its guards/bindings, "
        "or rename_shape one side, then retry). Structurally identical shapes "
        "fold under the dest name; the response reports every fold — if you "
        "expected the folded shapes to be DIFFERENT objects, review. Optional "
        "`scope` (\"file\"/omitted for the whole file, ONE function loc_key "
        "like \"31:1\" — that function's DIRECT statements only, nested "
        "functions are independent scopes; \"<top-level>\" for module-level "
        "code; a list of them; or a line range like \"31-45\", items whose "
        "own line falls inside) restricts the copy "
        "to the annotations it selects; static shapes the "
        "selected annotations reference come along automatically. "
        "Annotations already present verbatim are skipped. "
        "On success returns the per-section report; re-run dryrun after.",
        {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "draft name to copy FROM",
                },
                "scope": {
                    "type": ["string", "array"],
                    "description": "\"file\" (default), ONE function loc_key "
                    "like \"31:1\" (that function's DIRECT statements only — "
                    "nested functions are independent scopes, pass their own "
                    "loc_keys), \"<top-level>\" for module-level code, a list "
                    "of loc_keys like [\"31:1\", \"35:1\"], or an inclusive "
                    "line range like \"31-45\" (items whose own line falls "
                    "inside)",
                    "items": {"type": "string"},
                },
                "dest": {
                    "type": "string",
                    "description": "destination draft to copy INTO "
                    "(default: your own)",
                },
            },
            "required": ["source"],
        },
    )
    async def copy_annotations(args: dict[str, Any]) -> dict[str, Any]:
        import json

        from ..annotation_drafts import DraftsError, drafts

        if not set(args) <= {"source", "scope", "dest"}:
            return _err("expected only 'source', 'scope', 'dest'")
        dest_name = args.get("dest") or default_name
        if dest_name is None:
            return _err(
                "several drafts available, pass draft= (one of: "
                + (", ".join(names) if names is not None else "the store")
                + ")"
            )
        src_name = args.get("source")
        if not isinstance(src_name, str) or not src_name:
            return _err("'source' must be a non-empty draft name")
        if src_name == dest_name:
            return _err("cannot copy a draft into itself")
        if names is not None and src_name not in names:
            return _err(f"'source' must be one of your drafts: {list(names)}")
        try:
            src_doc = drafts().get(src_name)
            dest_doc = drafts().get(dest_name)
        except DraftsError as exc:
            return _err(str(exc))
        scope = args.get("scope", "file")
        selects = None
        if scope is not None and scope != "file":
            try:
                selection = resolve_scope(scope, source.read_bytes())
            except ValueError:
                return _err(f"unknown or malformed scope {scope!r}")
            except OSError:
                return _err("could not read the source file for scope resolution")

            def selects(item: dict[str, Any]) -> bool:
                # The shared rule: a range is selected by its start's owner
                # (a line-window scope overlaps, like every range filter).
                return selection.selects_range(item["target range"])

        dest_lock = drafts().lock(dest_name)
        try:
            with dest_lock, drafts().lock(src_name):
                plan = plan_copy(dest_doc, src_doc, selects)
                report = apply_copy(dest_doc, plan)
        except (AnnotationError, DraftsError) as exc:
            return _err(str(exc))
        payload = {
            "dest": dest_name,
            "source": src_name,
            "scope": scope if scope != "file" else None,
            **report,
        }
        folded = report.get("shapes_mapped") or []
        headline = ""
        if folded:
            pairs = ", ".join(f"{m['from']} -> {m['to']}" for m in folded)
            headline = (
                f"Folded {len(folded)} same-structure shape(s) "
                f"(dest name kept): {pairs}. Both drafts described identical "
                f"property sets, so one shape suffices — but if you expected "
                f"them to be DIFFERENT objects, review this fold now.\n\n"
            )
        return {
            "content": [
                {
                    "type": "text",
                    "text": headline
                    + json.dumps(payload, indent=2, ensure_ascii=False),
                }
            ]
        }

    @tool(
        "rename_shape",
        "Rename a static shape and rewrite every reference to it — shape "
        "guards' `shape` and `prototype shape` fields, shape bindings' "
        "`shape` field. Use when merging drafts where two shapes share a "
        "name but describe different objects and one must move aside (do "
        "this BEFORE retrying copy_annotations), or simply to give a shape "
        "a clearer name. The new name must not collide with an existing "
        "shape; renaming to the current name is a no-op.",
        {
            "type": "object",
            "properties": {
                "shape": {
                    "type": "string",
                    "description": "current name of the static shape",
                },
                "new_name": {
                    "type": "string",
                    "description": "the new shape name (must not exist yet)",
                },
                "draft": _draft_prop(),
            },
            "required": ["shape", "new_name"],
        },
    )
    async def rename_shape(args: dict[str, Any]) -> dict[str, Any]:
        doc = _resolve_write(args)
        if isinstance(doc, dict):
            return doc
        shape = args.get("shape")
        new_name = args.get("new_name")
        if not isinstance(shape, str) or not shape:
            return _err("'shape' must be a non-empty string")
        if not isinstance(new_name, str) or not new_name:
            return _err("'new_name' must be a non-empty string")
        try:
            rewritten = doc.rename_shape(shape, new_name)
        except AnnotationError as exc:
            return _err(str(exc))
        if rewritten == 0 and shape == new_name:
            text = f"shape {shape!r} is already named that; nothing to do."
        else:
            text = (
                f"renamed shape {shape!r} -> {new_name!r}; rewrote "
                f"{rewritten} guard/binding reference(s)."
            )
        return {"content": [{"type": "text", "text": text}]}

    @tool(
        "create_draft",
        "Create an empty annotation draft under an explicit name. Idempotent: "
        "succeeds immediately when the name already exists. Create your draft "
        "BEFORE any other annotation/checklist call that names it.",
        {
            "type": "object",
            "properties": {
                "draft": {
                    "type": "string",
                    "description": "the draft name to create",
                },
            },
            "required": ["draft"],
        },
    )
    async def create_draft(args: dict[str, Any]) -> dict[str, Any]:
        name = args.get("draft")
        if not isinstance(name, str) or not name:
            return _err("'draft' must be a non-empty draft name")
        try:
            if not drafts().has(name):
                drafts().add(name)
        except DraftsError as exc:
            return _err(str(exc))
        return {
            "content": [{"type": "text", "text": f"draft {name!r} ready"}]
        }

    return [
        list_annotations,
        add_annotation,
        batch_add_guards,
        delete_annotation,
        update_annotation,
        save_annotations,
        copy_annotations,
        rename_shape,
        create_draft,
    ]


def _format_listing(results: list[dict[str, Any]]) -> list[str]:
    import json

    lines: list[str] = []
    for r in results:
        prefix = f"[{r['kind']}]"
        if r["shape"]:
            prefix += f" shape={r['shape']!r}"
        if r["kind"] != KIND_STATIC_SHAPE:
            prefix += f" range {r['target_range']}"
        lines.append(prefix)
        lines.append(json.dumps(r["annotation"], ensure_ascii=False, indent=2))
    return lines


def make_annotation_server(
    source: Path,
    workdir: Path,
    names: list[str] | None = None,
    default: str | None = None,
):
    """Build the in-process MCP server exposing the annotation tools."""
    return create_sdk_mcp_server(
        name="annotations",
        tools=build_annotation_tools(source, workdir, names, default),
    )
