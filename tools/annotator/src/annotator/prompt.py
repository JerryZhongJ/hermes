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


def location_schema() -> str:
    return """{
  "start": {"line": 1, "column": 1},
  "end": {"line": 1, "column": 2}
}"""


def build_prompt(
    source_path: Path,
    annotation_path: Path,
) -> str:
    return f"""Read `./{source_path.name}`, analyze it, and write speculative optimization
guards to `./{annotation_path.name}` — each makes hot JavaScript code run faster by
inserting a runtime check the compiler can specialize around.

Basic concepts:
- target expression — a value the program computes or loads; a function
  parameter (loaded at entry) is one too. Every guard targets one.
- type — what kind of value a target expression holds: a concrete type, a
  union of several, or `any`. Supported concrete types: {", ".join(sorted(SUPPORTED_TYPES))}.
  Use any for any type not listed above (e.g. object, bigint, symbol).
- static shape — a description of an object's own properties (not inherited
  from its prototype), in order, each carrying a type. As opposed to the actual
  shape an object takes on at runtime which is built dynamically, the static shape
  is determined statically. Only static shapes whose properties are all data
  properties (non-accessor) are supported.

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
- SHAPE GUARD. Give a target expression and a static shape. The compiler
  inserts a shape check right after the expression that confirms the object
  already has that static shape through a SHAPE BINDING; on pass, property accesses on it take the
  shape fast path. The effect lasts only until the compiler suspects the
  object's shape may change — if an operation does not actually change it, emit another
  shape guard after that operation.

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
  property reads/writes, dense numeric/string work. For shape binding, two
  cost-vs-payoff don'ts:
  - Don't bind a typed shape to an object that is written often with values
    whose type the compiler can't determine statically — the write guard
    accumulates per write and can outweigh the read payoff. If you must bind
    it, declare such frequently-written properties as `any` in the static shape
    (any properties don't trigger the write guard).
  - Don't bind a typed shape to an object that flows outside shape-guard
    coverage and is written there (those writes are always checked).

JSON format:
- Top level: "static shapes" (name -> definition), "shape guards", "shape
  bindings", and optional "type guards".
- Field names must match exactly: "target range", "bind after" (optional),
  "shape", and "type". A type is a single string or an array for a union
  (e.g. ["number", "string"]).
- Location fields (each value is a source range, not a single point):
  - "target range" (all guards): the range of the target expression being
    checked.
  - For a parameter, use its declaration range as the "target range": the
    parameter itself in the signature. For `this`, use the range of the
    function body, for example `{{ ... }}`.
  - "bind after" (shape binding, optional): if omitted, the binding runs right
    after the target expression; if given, it runs after this point instead.
- Locations use 1-based line/column. The end column is EXCLUSIVE. "file" is
  optional (defaults to the source file being annotated):
```json
{location_schema()}
```
- Output must be pure JSON.

Example (type guard + shape guard + shape binding):
```json
{{
  "static shapes": {{
    "Point": {{
      "properties": [
        {{"name": "x", "type": "number"}},
        {{"name": "y", "type": "number"}}
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
- Create `./{annotation_path.name}` with the Write tool;
- Use the `locate` tool to get exact source ranges for annotations instead of
  grep/awk or counting columns by hand. Example:
  locate(file="{source_path.name}", from_line=2, to_line=5, text="abc")
  It returns each match as `line:startcol-endline:endcol` — 1-based, EXCLUSIVE
  end column, cross-line OK — which matches the annotation format. Omit from_line/to_line to search
  the whole file. Every match comes with a preview; pick the one you mean.
  Never guess a column.
- Use the `fold` tool first to get a structural view of large file:
  it folds multi-line blocks into ` … N lines folded …`, and prints
  1-based line numbers. Raise `unfold` (default 0) to expand a region,
  e.g. fold(file="{source_path.name}", from_line=176, to_line=200, unfold=1).
- Shell redirection like `>` `<` `<<`, `$()`, and interpreters `python3/node/sh -c` are blocked by
  the sandbox.
"""
