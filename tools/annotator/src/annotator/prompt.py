"""Prompt construction for agent-generated annotations."""

from __future__ import annotations

from pathlib import Path


SUPPORTED_TYPES = {
    "number",
    "string",
    "boolean",
    "object",
    "null",
    "undefined",
    "bigint",
    "symbol",
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
    return f"""Read `./{source_path.name}`, analyze it, and write speculative optimization hints to
`./{annotation_path.name}` — this makes hot JavaScript code run faster.

Basic concepts:
- expression — a value the program computes or loads; a function parameter
  (loaded at entry) is one too. Every hint targets an expression.
- type — what kind of value an expression holds: a single concrete type
  (e.g. `number`), a union of several, or `any` (all types — no narrowing).
  Concrete types: {", ".join(sorted(SUPPORTED_TYPES))}.
- shape — an object's own properties only (not inherited from its prototype),
  in order, each carrying a type.

What the hints are:
The hints are SPECULATIVE: each is checked at runtime, and a wrong hint only
falls back to the slow path — it never breaks correctness. Three kinds, each
gated by a runtime check:
- TYPE HINT says an expression's value is probably of a given type. Specify
  the expression and its type; the check runs right after the expression is
  evaluated. On a pass the value is narrowed to that type, so arithmetic /
  string / compare ops on it take fast paths.
- SHAPE HINT says an object's value probably has a given shape. Specify the
  expression, the shape, and the expression(s) or statement(s) after which it takes
  effect. A shape hint may need to be inserted at several points: some
  instructions (property writes, unknown calls, heap side effects) invalidate
  it, so it must be re-confirmed after each.
  On a pass, property accesses on it use fast shape-based loads.
- SHAPE ASSIGNMENT says an object probably has a given shape right after it is
  constructed. Specify the object, the shape, and the point right after
  construction where it takes effect. The runtime tries to set the typed shape
  on the object, taking effect only if the object's actual shape matches. Every 
  shape also needs at least one assignment to take effect.

Where to place them:
Emit a hint only when all three hold:
- Correctness — a hint must be likely true at runtime. For a shape
  hint/assignment, "true" means the object's shape equals the declared one —
  same properties, same order, same property types. Shape equality is
  all-or-nothing: one extra, missing, or wrongly-typed property and the check
  fails outright (harmless but useless). 
- Necessity — only where the compiler can't already derive the type/shape. A
  hint that confirms what's already known (literals, constants, values implied
  by a shape or a prior hint) does nothing. 
- Usefulness — where it actually pays off: the hottest code — loops, nested
  loops, frequently called functions, core data-structure accesses, repeated
  property reads/writes, dense numeric/string work.

JSON format:
- Top level: "shapes" (name -> definition), "shape hints", "shape
  assignments", and optional "type hints".
- Each referenced shape is defined once in "shapes" (names are internal ids)
  and must have at least one shape assignment — otherwise that shape's hints
  will never work.
- Field names must match exactly: "expression range", "hint after ranges",
  "assign after", "shape", and "type". A type is a single string or an array
  for a union (e.g. ["number", "string"]).
- Location fields (each value is a source range, not a single point):
  - "expression range" (all hints): the range of the expression or object being
    checked.
  - For a parameter, use its declaration range as the "expression range": the
    parameter itself in the signature, or the whole function for `this`.
  - "hint after ranges" (shape hint) / "assign after" (shape assignment): ranges
    of expressions or statements after which the check (or shape-set) is
    inserted.
- Locations use 1-based line/column. The end column is EXCLUSIVE:
```json
{location_schema()}
```
- Output must be pure JSON.

Example (type hint + shape hint + shape assignment):
```json
{{
  "shapes": {{
    "Point": {{
      "properties": [
        {{"name": "x", "type": "number"}},
        {{"name": "y", "type": "number"}}
      ]
    }}
  }},
  "type hints": [
    {{
      "expression range": {{"file": "{source_path.name}", "start": {{"line": 12, "column": 11}}, "end": {{"line": 12, "column": 16}}}},
      "type": "number"
    }}
  ],
  "shape hints": [
    {{
      "expression range": {{"file": "{source_path.name}", "start": {{"line": 10, "column": 8}}, "end": {{"line": 10, "column": 9}}}},
      "hint after ranges": [
        {{"file": "{source_path.name}", "start": {{"line": 10, "column": 8}}, "end": {{"line": 10, "column": 9}}}}
      ],
      "shape": "Point"
    }}
  ],
  "shape assignments": [
    {{
      "expression range": {{"file": "{source_path.name}", "start": {{"line": 4, "column": 9}}, "end": {{"line": 4, "column": 19}}}},
      "assign after": {{"file": "{source_path.name}", "start": {{"line": 4, "column": 9}}, "end": {{"line": 4, "column": 19}}}},
      "shape": "Point"
    }}
  ]
}}
```

Tool usage:
- Create `./{annotation_path.name}` with the Write tool; do not use Bash (shell
  redirection > < <<, $(), and interpreters python3/node/sh -c are blocked by
  the sandbox).
"""
