"""Prompt construction for agent-generated annotations."""

from __future__ import annotations

import json
from pathlib import Path


SUPPORTED_TYPES = {
    "number",
    "string",
    "boolean",
    "null",
    "undefined",
    "closure",
}

ABOUT_ANNOTATIONS_FILENAME = ".about_annotations.md"
ABOUT_ANNOTATIONS_PATH = f"/work/{ABOUT_ANNOTATIONS_FILENAME}"


def concrete_type_union() -> str:
    """TypeScript union of supported concrete types, e.g. '"number" | "string" | ...'."""
    return " | ".join(f'"{t}"' for t in sorted(SUPPORTED_TYPES))


_EXAMPLE_SOURCE = """\
  L1:  function Point(x, y) { this.x = x; this.y = y; }
  L3:  Point.prototype.scale = function(k) { this.x *= k; this.y *= k; };
  L5:  const opts = { get tag() { return "p"; }, inner: { n: 3 } };
  L7:  function process(p, k, cb) {
  L8:    p.scale(k);
  L9:    const r = p.x + opts.inner.n;
  L10:   if (cb) cb(r);
  L11:   return opts.tag + r;
  L12: }"""

def _call(kind: str, body: dict, shape: str | None = None) -> str:
    """Render one add_annotation call as a compact one-liner for the example."""
    args = {"kind": kind, "annotation": body}
    if shape is not None:
        args["shape"] = shape
    return "add_annotation(" + json.dumps(args, ensure_ascii=False) + ")"


# The worked example as a sequence of add_annotation calls — shapes first (each
# before any guard/binding that names it), then bindings, guards, type guards.
_EXAMPLE_CALLS = "\n".join(
    [
        _call("static_shape", {"properties": [
            {"name": "x", "type": "number"},
            {"name": "y", "type": "number"},
        ]}, shape="Point"),
        _call("static_shape", {"properties": [
            {"name": "constructor", "flags off": ["enumerable"]},
            {"name": "scale", "type": "closure", "target function": {
                "start": {"line": 3, "column": 25}, "end": {"line": 3, "column": 66}}},
        ]}, shape="PointProto"),
        _call("static_shape", {"properties": [
            {"name": "tag", "kind": "accessor"},
            {"name": "inner"},
        ]}, shape="Opts"),
        _call("static_shape", {"properties": [
            {"name": "n", "type": "number"},
        ]}, shape="Inner"),
        _call("shape_binding", {
            "target range": {"start": {"line": 1, "column": 36}, "end": {"line": 1, "column": 40}},
            "shape": "Point"}),
        _call("shape_binding", {
            "target range": {"start": {"line": 3, "column": 1}, "end": {"line": 3, "column": 16}},
            "shape": "PointProto"}),
        _call("shape_binding", {
            "target range": {"start": {"line": 5, "column": 14}, "end": {"line": 5, "column": 60}},
            "shape": "Opts"}),
        _call("shape_binding", {
            "target range": {"start": {"line": 5, "column": 50}, "end": {"line": 5, "column": 58}},
            "shape": "Inner"}),
        _call("shape_guard", {
            "target range": {"start": {"line": 7, "column": 18}, "end": {"line": 7, "column": 19}},
            "shape": "Point", "prototype shape": "PointProto"}),
        _call("shape_guard", {
            "target range": {"start": {"line": 9, "column": 13}, "end": {"line": 9, "column": 14}},
            "shape": "Point", "prototype shape": "PointProto"}),
        _call("shape_guard", {
            "target range": {"start": {"line": 9, "column": 17}, "end": {"line": 9, "column": 21}},
            "shape": "Opts"}),
        _call("shape_guard", {
            "target range": {"start": {"line": 9, "column": 17}, "end": {"line": 9, "column": 27}},
            "shape": "Inner"}),
        _call("type_guard", {
            "target range": {"start": {"line": 3, "column": 34}, "end": {"line": 3, "column": 35}},
            "type": "number"}),
        _call("type_guard", {
            "target range": {"start": {"line": 7, "column": 24}, "end": {"line": 7, "column": 26}},
            "type": ["null", "undefined"]}),
        _call("type_guard", {
            "target range": {"start": {"line": 11, "column": 8}, "end": {"line": 11, "column": 16}},
            "type": "string"}),
    ]
)

_EXAMPLE_EXPLANATION = """\
This scenario exercises most features. Here is why each annotation is written
the way it is, and what it buys:

Shapes
- Point {x:number, y:number}: a 2D point; typing x/y `number` lets arithmetic
  on them (e.g. `*=` in `scale`) skip ToPrimitive and take the number fast path.
- PointProto (the prototype object):
  - `constructor`: typed `any` (not on a hot arithmetic path) with `flags off:
    ["enumerable"]`, since every prototype has a non-enumerable constructor by
    JS default.
  - `scale`: typed `closure` with its target function (the L3 definition), so
    `p.scale(k)` can be inlined.
- Opts {tag:accessor, inner:any}: an all-`any` shape (no write guard, since no
  property is non-`any`). `tag` is a getter, hence `accessor` (accessors are always `any`);
  `inner` is another object with its own shape (Inner). Field accesses still go
  through the shape fast path (direct slot offset) even with every property
  `any`.
- Inner {n:number}: the object nested inside `opts`; typing `n` number lets the
  `+` into `r` take the number fast path.

Bindings (one-time cost each; every later guard on the same object benefits)
- The `this` receiver in the final `this.y = y` write → Point: the constructor
  writes this.x then this.y one by one, so select the object expression in the
  write that completes the shape, not the whole assignment.
- The `Point.prototype` receiver in the L3 method write → PointProto: select the
  object expression in the write that completes the prototype shape, so a later
  prototype-shape guard on Point instances can pass.
- `opts` → Opts: a plain object literal (not `this`, not a prototype) bound so
  its fields can be shape-accessed.
- `opts.inner` → Inner: the nested literal {n:3} is bound too, so a shape guard
  on `opts.inner` can pass.

Type guards
- `k` (scale's parameter): number — lets `*=` inside `scale` take the number
  fast path.
- `cb`: ["null","undefined"] — cb is an optional callback, usually absent/null;
  this lets `if (cb)` (L10) be folded away on the no-callback path (both falsy).
- `opts.tag`: string — `tag` is an accessor (a getter), so its value is `any`
  in the shape (accessors always are) and unknown to the compiler; the guard
  narrows the getter's return at this use so the `+ r` concat takes the string
  fast path.

Shape guards
- `p` (L7) → Point + PointProto: verifies p's hidden class is Point's; on pass,
  `p.scale(k)` (L8) takes the shape fast path and `scale` can inline.
- `p` (L9) → Point + PointProto: the `p.scale(k)` call on L8 kills the shape
  fact (a call may mutate shape), so the `p.x` read on L9 needs its own fresh
  guard here to stay fast.
- `opts` (L9) → Opts (no prototype shape): on pass, the `inner` field is a
  direct slot read (`tag` is an accessor, so it still runs the getter).
- `opts.inner` (L9) → Inner: `inner` holds another object with its own shape,
  so reading `opts.inner.n` needs this SECOND guard — the one on `opts` only
  yields the `inner` reference, not its fields. Note its target is the
  expression `opts.inner`; a shape guard can target any expression that
  evaluates to the object."""


def build_about_annotations_markdown() -> str:
    """Build the shared explanation of annotation meaning and mechanics.

    Every agent role reads this per-attempt snapshot instead of relying on prompt
    inheritance or maintaining a separate summary of the annotation model.
    """
    return f"""# About annotations

These annotations insert runtime checks that let the compiler specialize hot
JavaScript while preserving normal behavior on every failed check. On a pass the
specialized fast path runs; on a fail normal unoptimized behavior runs. A wrong
guard is therefore safe but useless, not a correctness failure.

## Concepts

- **Target expression** identifies the value an annotation describes. Parameter
  declarations and actual `this` expressions can be targets too.
- **Type** is a concrete type, a union, or `any`. Concrete types are
  {", ".join(sorted(SUPPORTED_TYPES))}. `any` means unknown, not absent.
  `closure` represents one known target function and cannot be in a union.
- **Static shape** describes an object's own properties, in order: their type,
  data/accessor kind, descriptor flags, and a target function for a closure.
  It does NOT cover inherited properties — those live on the prototype object
  and need their own prototype shape (see Prototype shapes below).
- At runtime a static shape corresponds to a hidden class. A known shape fixes
  data-property slot offsets and bypasses inline caches even when every property
  type is `any`. Concrete property types additionally enable typed operations,
  checked typed stores, and closure-call inlining.

## Shape and type mechanisms

A **shape binding** is the only operation that attempts to give an object a
static shape. It validates the object then sets its matching hidden class. A
binding is a one-time cost that can benefit later consumers of the same object.
A binding automatically creates its immediate shape guard; never rely on a bare
binding as a fast-path fact. The target range always covers the expression that
produces the object, never an enclosing assignment. When construction is
completed by a property write, target that write's receiver; do not put bindings
on receivers that are only read.

A **shape guard** verifies that an object already has a shape established by a
binding. Given a `prototype shape`, it additionally verifies the object's
direct prototype carries that prototype's shape — so the prototype must be
bound too, or the prototype half always fails. A guard cannot create a shape:
guarding an unbound object always fails. Guard facts are local to their
containing function: a callee needs its own guard even when the caller guarded
the corresponding argument. A binding, conversely, changes the object's hidden
class and can be consumed in any later function.

A **type guard** is independent of shapes. It narrows a target expression so
arithmetic, string, and comparison operations can avoid generic dispatch and
coercion.

## Shape facts, effects, and costs

A shape fact reaches a use only when every path to that use preserves it.
Function calls, global-property loads, `in`, and `instanceof` always remain
side-effecting. Unknown generic operations and unknown-shape property accesses
can become side-effect-free only after suitable type/shape knowledge. A later
guard may re-establish a fact after a compiler-conservative kill.

A shape guard enables direct data-property slot access — on the object, and on
its direct prototype when a `prototype shape` is given. Accessors still invoke
their getter/setter. Concrete property types also let downstream operations use
typed paths.

A `closure` property is the highest-value annotation: it carries one known
target function, so a call to that property can be **inlined**. Inlining
removes the call entirely (no dispatch, no argument shuffling, no frame setup)
and folds the callee body into the caller, so constant folding, CSE,
dead-code elimination, and register allocation all cross the old call
boundary. For hot small helpers — math/vector ops, getters, predicate
callbacks — this is often the largest win any annotation can buy, and a type
guard alone can never produce it. So prefer `closure` whenever a property
holds a function whose definition is statically known.

A binding creates a write guard only if its shape has at least one non-`any`
property (`closure` counts). A fully-`any` shape still gets direct slot access
but has no typed write-guard overhead. Typed property writes are checked unless
both a shape guard covers the write and the stored type is proven compatible;
a mismatch silently degrades that property to untyped rather than throwing.
Choose typed shapes only where their extra optimization benefit outweighs this
per-write cost.

## Property and prototype constraints

- Accessor properties are always type `any`.
- A prototype shape begins with a non-enumerable `constructor` data property of
  type `any`.
- A known closure property must be `data`, type `closure`, and name its target
  function range. A method assigned as `Cls.prototype.m = function (...) {...}`
  is exactly a `data`/`closure` property — its `target function` is the range of
  that function expression.
- Add a `prototype shape` to a guard only when the guarded code reads a data
  property (including a `closure` method) on the object's DIRECT prototype, and
  that prototype has its own binding to the prototype shape. Omit it when only
  own properties are touched; chains deeper than the direct prototype are
  unsupported.

## Prototype shapes and method inlining

A prototype object (`Cls.prototype`, `Cls.prototype.sub = {...}`, etc.) is just
another object — it gets its own `static_shape` and `shape_binding`. The recipe
for a prototype with a method `m`:

1. Define the prototype shape: a non-enumerable `constructor` property (type
   `any`), then each hot method as `{{"name": "m", "type": "closure",
   "target function": <range of the function expression>}}`.
2. Bind it with a `shape_binding` targeting the expression that produces the
   prototype object. For `Cls.prototype.m = function...`, target the LHS receiver
   `Cls.prototype`, not the whole assignment; the binding is applied after the
   method store. For `Cls.prototype = {...}`, target the object literal.
3. Guard hot instances with both `shape` (the instance shape) and
   `prototype shape`. On pass, prototype property reads become direct slot
   access and calls to `closure` methods inline.

This is what makes prototype method dispatch on hot instances fast — look for
`X.prototype.method = function` patterns (very common in ported/compiled JS)
and apply the recipe to the hot ones.

## Annotation schema

Each `add_annotation` call takes a kind and one annotation body:

- `static_shape`: `{{"properties": [Property, ...]}}`; pass the shape name as
  the separate `shape` argument. Add the shape before references to it.
- `shape_binding`: `{{"target range": SourceRange, "shape": string}}`.
- `shape_guard`: `{{"target range": SourceRange, "shape": string,
  "prototype shape"?: string}}`.
- `type_guard`: `{{"target range": SourceRange, "type": TypeName}}`.

`SourceRange` is 1-based and half-open: `{{"start": {{"line": number,
"column": number}}, "end": {{"line": number, "column": number}}}}`.
`TypeName` is one concrete type ({concrete_type_union()}), `"any"`, or an array
of concrete types. `Property` supports `name`, optional `type`, optional
`kind` (`data` or `accessor`), optional `flags off`, and `target function` only
for a `closure`. Types default to `any`, kinds default to `data`, and descriptor
flags default to enabled.

For a parameter target range use its declaration. For `this`, target an actual
`this` expression at the operation you want to optimize. Use source-tool ranges
exactly: end columns are exclusive.

## Worked example

Source:
{_EXAMPLE_SOURCE}

Create shapes first, then bindings, shape guards, and type guards:
```
{_EXAMPLE_CALLS}
```

{_EXAMPLE_EXPLANATION}
"""


def build_prompt(
    source_path: Path,
    enabled: list[str] | None = None,
) -> str:
    # Tool sections are assembled from the registry (open/closed): adding a tool
    # only adds a REGISTRY entry — build_prompt never lists specific tools here.
    from .tools import REGISTRY, resolve_enabled

    tool_sections = [
        REGISTRY[n].prompt
        for n in resolve_enabled(enabled)
        if n in REGISTRY and REGISTRY[n].prompt
    ]
    tools_text = "\n".join(tool_sections)
    return f"""# Protocol (five-stage annotation workflow)

Before planning or annotating, Read `{ABOUT_ANNOTATIONS_PATH}`. It is the
shared, authoritative explanation of annotation meaning, compiler/runtime
mechanics, schema, costs, and examples for this run. Every subagent reads the
same file; do not duplicate or contradict it.

This file may be large. Do NOT annotate it end-to-end yourself. Run the five
stages below in order. `.chunks/comments.json` is the primary handoff channel:
all writers use `write_comment`, which serializes and atomically publishes it.
Each stage may read ALL completed earlier-phase comments, not only the directly
previous phase; prefer direct upstream evidence when it exists.

1. PLAN: call `chunk_index()` to get the function universe (loc_keys) and chunk
   plan. Default strategy `auto` re-slices any oversize chunk on fixed line
   windows (a function split across a window is owned by every window it
   intersects); pass `strategy="function-boundary"` to keep function bodies
   intact, or `strategy="fixed-lines"` for pure line windows. Spawn chunk
   subagents in batches that fit your concurrency budget and wait at every
   phase barrier.
2. PHASE 1 — GENERAL UNDERSTANDING (parallel): for every chunk spawn
   `understand-chunk` with its chunk_id (for example, "understand chunk_003").
   It records phase1 comments about semantic roles, input/output data,
   callgraph/heat evidence, and recommended callgraph/heat corrections. Do not
   let subagents mutate callgraph priors concurrently. After the barrier, you
   may serially apply any evidence-backed `add_call_edges`, `delete_call_edges`,
   `set_exec_expt`, or `set_target_prob` adjustments; Jelly refreshes
   asynchronously, so queries may return a stable stale result or `not yet
   ready` rather than blocking.
3. PHASE 2 — SHAPE FACTS (parallel): for every chunk spawn `shape-facts-chunk`.
   It reads relevant phase1 comments and writes phase2 comments for object and
   prototype creation, full-shape certainty, hot consumers, possible flowing
   shapes, frequent writes, and uncertainty. Wait for all subagents.
4. PHASE 3 — CANONICAL STATIC SHAPES: after the phase2 barrier, spawn ONE
   `shape-review` subagent with the instruction `perform phase3`. It reads EVERY
   phase1 and phase2 comment, REVIEWS each for correctness across ALL chunks
   (writing a phase3 verdict only for notes it finds doubtful or wrong, which
   phase4 treats as a logical deletion), reconciles cross-chunk
   evidence, creates canonical
   `static_shape` annotations, and writes phase3 decisions. Wait for it before
   starting phase4; do not make canonical-shape decisions yourself.
5. PHASE 4 — SOURCE ANNOTATIONS (parallel): for every chunk spawn
   `annotate-chunk`. It MUST first list existing `static_shape` annotations,
   then consume relevant phase1–3 comments. It adds only bindings, shape guards,
   type guards, and real `record_skip` decisions for functions it owns; it does
   not create shapes or delete annotations. It records phase4 evidence comments.
   Wait for all subagents.
6. PHASE 5 — REVIEW AND CONVERGENCE: after the phase4 barrier, spawn ONE
   `shape-review` subagent with the instruction `perform phase5`. It reads all
   comments and annotations, runs coverage and available dryrun/feedback tools,
   corrects the live document, closes real coverage gaps, and writes the required
   review comment for EVERY final retained annotation. Wait for it to finish;
   do not perform final annotation mutations yourself.

Coverage goal: EVERY function is EITHER annotated OR explicitly skipped.
Subagents return only one-line summaries; detailed handoffs live in comments and
the shared in-memory annotation document.

---

Read `./{source_path.name}`, analyze it, and build speculative optimization
guards.

Environment (one-shot Docker container, destroyed when you finish):
- Working directory: `/work`, containing the input `{source_path.name}` and
  `{ABOUT_ANNOTATIONS_FILENAME}`.
- Pre-installed: `python3` (with `tree_sitter` and `tree_sitter_javascript`),
  `node`, coreutils.

How you produce annotations:
- Build the annotation set ONLY through the `annotations` MCP tools:
  `list_annotations`, `add_annotation`, `delete_annotation`.
- Add every static shape before a binding or guard that names it. Use
  `list_annotations` to review and `delete_annotation` to correct mistakes.
- The `annotation` argument of `add_annotation` is one body described by
  `{ABOUT_ANNOTATIONS_PATH}`.

# Tool usage

- All enabled tools act on the file being annotated (there's only one file; no
  `file` argument).
{tools_text}
"""
