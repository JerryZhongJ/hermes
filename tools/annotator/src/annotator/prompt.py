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
- target expression — a value the program computes or loads; a function
  parameter (loaded at entry) is one too. Every hint targets one.
- type — what kind of value a target expression holds: a single concrete type
  (e.g. `number`), a union of several, or `any` (all types — no narrowing).
  Concrete types: {", ".join(sorted(SUPPORTED_TYPES))}.
- static shape — a description of an object's own properties (not inherited
  from its prototype), in order, each carrying a type. As opposed to the actual
  shape an object takes on at runtime which is built dynamically, the static shape
  is determined statically. Only static shapes whose properties are all data
  properties (non-accessor) are supported.

What the hints are:
The hints are SPECULATIVE: each is checked at runtime, and a wrong hint only
falls back to the slow path — it never breaks correctness. Three kinds, each
gated by a runtime check:
- TYPE HINT says a target expression's value is probably of a given type.
  Specify the target expression and its type; the check runs right after it is
  evaluated. On a pass the value is narrowed to that type, so arithmetic /
  string / compare ops on it take fast paths.
- SHAPE HINT assumes a real object matches a static shape, so property accesses
  on it take fast shape-based paths. The check runs right after the target
  expression is evaluated, same as a type hint. Specify the target expression
  and the static shape.
- SHAPE BINDING binds a static shape onto an object — a shape hint's
  assumption only holds at points after such a binding. Specify the target
  expression and the static shape; the binding runs right after the target
  expression, or give "bind after" to delay it to a later point where the
  object's actual shape already equals the static shape.

Where to place them:
Emit a hint only when all three hold:
- Correctness — a hint must be likely true at runtime. For a shape
  hint/binding, "true" means the object's actual shape equals the static
  shape — same properties, same order, same property types. Shape equality is
  all-or-nothing: one extra, missing, or wrongly-typed property and the check
  fails outright (harmless but useless).
- Necessity — only where the compiler can't already derive the type/shape. A
  hint that confirms what's already known (literals, constants, values implied
  by a shape or a prior hint) does nothing.
- Usefulness — where it actually pays off: the hottest code — loops, nested
  loops, frequently called functions, core data-structure accesses, repeated
  property reads/writes, dense numeric/string work.

JSON format:
- Top level: "static shapes" (name -> definition), "shape hints", "shape
  bindings", and optional "type hints".
- Field names must match exactly: "target range", "bind after" (optional),
  "shape", and "type". A type is a single string or an array for a union
  (e.g. ["number", "string"]).
- Location fields (each value is a source range, not a single point):
  - "target range" (all hints): the range of the target expression being
    checked.
  - For a parameter, use its declaration range as the "target range": the
    parameter itself in the signature. For `this`, use the range of the
    function it belongs to — the function expression/declaration itself, for 
    example `function() {{ ... }}`.
  - "bind after" (shape binding, optional): if omitted, the binding runs right
    after the target expression; if given, it runs after this point instead.
- Locations use 1-based line/column. The end column is EXCLUSIVE:
```json
{location_schema()}
```
- Output must be pure JSON.

Example (type hint + shape hint + shape binding):
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
  "type hints": [
    {{
      "target range": {{"file": "{source_path.name}", "start": {{"line": 12, "column": 11}}, "end": {{"line": 12, "column": 16}}}},
      "type": "number"
    }}
  ],
  "shape hints": [
    {{
      "target range": {{"file": "{source_path.name}", "start": {{"line": 10, "column": 8}}, "end": {{"line": 10, "column": 9}}}},
      "shape": "Point"
    }}
  ],
  "shape bindings": [
    {{
      "target range": {{"file": "{source_path.name}", "start": {{"line": 4, "column": 9}}, "end": {{"line": 4, "column": 19}}}},
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
