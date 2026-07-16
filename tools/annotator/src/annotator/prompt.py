"""Prompt construction for agent-generated annotations."""

from __future__ import annotations

from pathlib import Path


SUPPORTED_TYPES = {
    "number",
    "string",
    "boolean",
    "null",
    "undefined",
}


def concrete_type_union() -> str:
    """TypeScript union of supported concrete types, e.g. '"number" | "string" | ...'."""
    return " | ".join(f'"{t}"' for t in sorted(SUPPORTED_TYPES))


def build_prompt(
    source_path: Path,
    annotation_path: Path,
) -> str:
    return f"""Read `./{source_path.name}`, analyze it, and write speculative optimization
guards to `./{annotation_path.name}` — each makes hot JavaScript code run faster by
inserting a runtime check the compiler can specialize around.

Environment: you are running inside a one-shot Docker container. Your working
directory is `/work`, which contains the input file `{source_path.name}`. The
container is destroyed when you finish.
Pre-installed: `python3` (with `tree_sitter` and `tree_sitter_javascript`),
`node`, coreutils. Write your annotations to
`./{annotation_path.name}`.

Basic concepts:
- target expression — where the value is evaluated and where the guard checks it. 
  The loading of a parameter (and of `this`) is such an expression too, evaluated 
  at the function entry.
- type — what kind of value a target expression holds: a concrete type, a
  union of several, or `any`. Supported concrete types: {", ".join(sorted(SUPPORTED_TYPES))}.
  Use any for any type not listed above (e.g. object, bigint, symbol).
- static shape — a description of an object's own properties (not inherited
  from its prototype), in order, each carrying a type, a kind (data or
  accessor) and flags (writable/enumeable/configurable). As opposed to the actual shape an object takes on at runtime
  which is built dynamically, the static shape is determined statically.
  Notice that:
    - An accessor property is always typed `any`.
    - By JS default, a prototype object's shape starts with a non-enumerable `constructor`
      data property that should be typed 'any'.

How guards work:
Each guard is a runtime check inserted by the compiler. The check splits the
guarded code into two paths: on pass, the value is known to have the assumed
type/shape and the fast path is taken; on fail, control falls through to a
general, unoptimized path that behaves exactly as if no guard were present (no
throw, no deopt). So a wrong guard never breaks correctness — it just fails the
check and runs the ordinary code.

This is not free. Two costs, in order of importance:
- Write guard (heaviest; only shape binding introduces it). Once an object is
  bound to a typed shape (a shape whose properties include non-any types), the
  object becomes typed at runtime. From then on every property write to it is
  checked: does the stored value's type match the property's declared type? A
  mismatch does not throw — it silently degrades that property to untyped (so
  later reads of it no longer take the fast path). The check can be skipped
  only when both hold: the write is inside a region covered by a shape guard,
  AND the stored value's type can be statically proven to match. If the object
  ever flows outside shape-guard coverage and is written there, every one of
  those writes is checked (cost grows with the number of writes).
- Check (cheap per hit, but it adds up on hot paths). A single check is a
  comparison or two on a branch predicted to pass, paid each time the guarded
  point runs. On a hot path, if the specialization the guard enables isn't
  enough to outweigh the check, that check becomes a real cost.

The three kinds of guard (what each makes the compiler do):
- TYPE GUARD. Give a target expression and a type. The compiler inserts a type
  check right after the expression; on pass, the arithmetic / string / compare ops on it take the typed fast
  path.
- SHAPE BINDING. Give a target expression and a static shape. The compiler
  tries to set the object to that static shape right after the expression — or
  after "bind after" if given (use it to wait until the shape is fixed, e.g.
  when its properties are written one by one after construction) — and then
  inserts a shape check like a SHAPE GUARD does. It introduces the write guard above.
- SHAPE GUARD. Give a target expression, a static shape, and optionally the
  static shape of the object's direct prototype. The compiler inserts a shape
  check that confirms the object already has that static shape through a
  SHAPE BINDING, and checks the prototype's shape in the same manner if one is
  given; on pass, **data** property accesses on it (and on its direct
  prototype, if a prototype shape is given) take the shape fast path, while
  accessor property accesses go through the runtime. By default the check runs right after the target
  expression; the optional "guard after" delays it until after some other
  point — same meaning as a SHAPE BINDING's "bind after". For example, 
  in `obj.x = sideEffect();` target `obj` and set
  "guard after" to the `sideEffect()` call, because `sideEffect()` will always kill
  the guard for `obj`. The effect of a guard lasts
  only until the compiler suspects the object's shape may change — if an
  operation does not actually change it, emit another shape guard after that
  operation.

How a shape fact propagates:
A shape fact reaches a point iff, on every path from the guard to that point,
no instruction has a side effect that may kill the fact. Such side effects fall 
into three groups:
- Removable by annotation: the side effect exists only because an operand
  type or object shape is unknown, which an annotation can pin down:
  - Generic operation (+ - * / < == ! ~ ...) on unknown/possibly-object operands:
    the op may run arbitrary code and modify objects. A type annotation narrowing
    operands to primitive types makes the op side effect free.
  - Property access on an unknown-shape object: may trigger a
    getter/setter and may modify objects. A shape annotation makes the
    shape known — the access is a direct field read/write without side effect.
- Not removable by annotation: the side effect always exists
  - `in` / `instanceof`, function calls, global-property loads.
- No side effect: pure numeric operation, direct field
  read/write on a known-shape object, strict equality ===/!==.

Where to place them:
Emit a guard only when all three hold:
- Correctness — a guard must be likely true at runtime. For a shape
  guard/binding, "true" means the object's actual shape equals the static
  shape — same properties, same order, same property types. Shape equality is
  all-or-nothing: one extra, missing, or wrongly-typed property and the check
  fails outright (harmless but useless).
- Necessity — only where the compiler can't already derive the type/shape.
- Usefulness — where it actually pays off: the hottest code — loops, nested
  loops, frequently called functions, core data-structure accesses, repeated
  property reads/writes, dense numeric/string work. For shape binding, weigh
  the write-guard cost against the payoff (read/writes under a shape guard
  optimized, and free of the check when the stored type is inferable);
  declare frequently-written, hard-to-infer properties as `any` to skip the
  check.

Output format:
- Output must be pure JSON.
- Top level: "static shapes" (name -> definition), "shape guards", "shape
  bindings", and "type guards".
- The "shape" / "prototype shape" fields name a shape defined under "static shapes".
- `SourceRange` — a 1-based, half-open `[start, end)` span (the end column is
  EXCLUSIVE): {{"start": {{"line": number, "column": number}}, "end": {{"line": number, "column": number}}}}.
- `TypeName` — one of the concrete types ({concrete_type_union()}), `"any"`, or
  an array of concrete types for a union (e.g. ["number", "string"]).
- Static shape: {{"name": string, "type"?: TypeName, "kind"?: "data" | "accessor", "flags off"?: ["writable" | "enumerable" | "configurable"]}}.
  ("type" defaults to "any", "kind" to "data"; JS descriptor flags default to on, so list only the flags to turn off. Accessor properties have no writable flag.)
- Type guard: {{"target range": SourceRange, "type": TypeName}}.
- Shape guard: {{"target range": SourceRange, "shape": string, "guard after"?: SourceRange, "prototype shape"?: string}}.
- Shape binding: {{"target range": SourceRange, "shape": string, "bind after"?: SourceRange}}.
- "target range" (all guards): a source range (not a single point) covering the
  target expression. For a parameter loading, use its declaration range; for
  `this` (which has no declaration), use the function body range — just a format
  convention.

Example (type guard + shape guard + shape binding):
```json
{{
  "static shapes": {{
    "Point": {{
      "properties": [
        {{"name": "x", "type": "number"}},
        {{"name": "y", "type": "number"}}
      ]
    }},
    "PointProto": {{
      "properties": [
        {{"name": "constructor", "flags off": ["enumerable"]}},
        {{"name": "norm", "type": "number"}}
      ]
    }}
  }},
  "type guards": [
    {{
      "target range": {{"start": {{"line": 12, "column": 11}}, "end": {{"line": 12, "column": 16}}}},
      "type": "number"
    }}
  ],
  "shape guards": [
    {{
      "target range": {{"start": {{"line": 10, "column": 8}}, "end": {{"line": 10, "column": 9}}}},
      "shape": "Point"
    }},
    {{
      "target range": {{"start": {{"line": 30, "column": 1}}, "end": {{"line": 30, "column": 4}}}},
      "guard after": {{"start": {{"line": 30, "column": 9}}, "end": {{"line": 30, "column": 21}}}},
      "shape": "Point",
      "prototype shape": "PointProto"
    }}
  ],
  "shape bindings": [
    {{
      "target range": {{"start": {{"line": 4, "column": 9}}, "end": {{"line": 4, "column": 19}}}},
      "shape": "Point"
    }},
    {{
      "target range": {{"start": {{"line": 20, "column": 5}}, "end": {{"line": 20, "column": 9}}}},
      "bind after": {{"start": {{"line": 20, "column": 10}}, "end": {{"line": 20, "column": 20}}}},
      "shape": "Point"
    }}
  ]
}}
```

Tool usage:
- All source tools (`locate`, `fold`, `dryrun_annotation`, `query_feedback`) act on the file being
  annotated — there is no `file` argument; they always read {source_path.name}.
- Use the `locate` tool to get exact source ranges for annotations instead of
  grep/awk or counting columns by hand. Example:
  locate(from_line=2, to_line=5, text="abc")
  It returns each match as `line:startcol-endline:endcol` — 1-based, EXCLUSIVE
  end column, cross-line OK — which matches the annotation format, plus a
  line-numbered context snippet with the match wrapped in »…« so you can tell
  matches apart at a glance. Omit from_line/to_line to search the whole file.
  To pin one occurrence among several, add `following` (literal text that must
  sit just before the match) and/or `followed_by` (literal text just after);
  only whitespace may sit between. e.g. to locate the `obj` in `obj.x = …`
  without folding `.x` into the range: text="obj", followed_by=".x".
  Never guess a column.
- Use the `fold` tool first to get a structural view of large file:
  it folds multi-line blocks into ` … N lines folded …`, and prints
  1-based line numbers. Raise `unfold` (default 0) to expand a region,
  e.g. fold(from_line=176, to_line=200, unfold=1).
- After writing or editing annotations, call `dryrun_annotation` to check their
  effect — it compiles the file (trimmed pipeline, no execution) and caches the
  result, returning a whole-file summary (optimized / killed / no-effect).
  Example: dryrun_annotation(annotation="annotation.json")
- Then call `query_feedback` to inspect the cached result, optionally narrowed
  to a line range or a previous run. Per annotation it reports: (1) load
  failures — fix those first; (2) optimizations produced (type narrowing →
  typed operation; shape → typed property read/write); (3) instructions that
  killed shape propagation; (4) "no effect". Out-of-range effects show as
  "somewhere else". Examples:
  query_feedback()                                  # latest run, whole file
  query_feedback(from_line=80, to_line=120)         # focus a region
  query_feedback(run=-2, from_line=80, to_line=120) # vs the previous run
  (run: -1/omit = latest, -2 = previous, k>0 = run id k)
  Iterate until no load failures and no surprising kills.
"""
