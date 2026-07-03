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
    return f"""Read `./{source_path.name}`, analyze it, and write speculative optimization hints to
`./{annotation_path.name}` — this makes hot JavaScript code run faster.

Basic concepts:
- target expression — a value the program computes or loads; a function
  parameter (loaded at entry) is one too. Every hint targets one.
- type — what kind of value a target expression holds: a concrete type, a
  union of several, or `any`. Supported concrete types: {", ".join(sorted(SUPPORTED_TYPES))}.
  Use any for any type not listed above (e.g. object, bigint, symbol).
- static shape — a description of an object's own properties (not inherited
  from its prototype), in order, each carrying a type. As opposed to the actual
  shape an object takes on at runtime which is built dynamically, the static shape
  is determined statically. Only static shapes whose properties are all data
  properties (non-accessor) are supported.

What the hints are:
The hints are SPECULATIVE: each is checked at runtime, and a wrong hint never
 breaks correctness. Three kinds, each gated by a runtime check:
- TYPE HINT says a target expression's value is probably of a given type.
  Specify the target expression and its type; the check runs right after it is
  evaluated. On a pass the value is narrowed to that type, so arithmetic /
  string / compare ops on it take fast paths.
- SHAPE BINDING assumes an object's shape is fixed and equals a given static
  shape, and tries to bind the static shape to the object. Specify the target
  expression and the static shape; the binding runs right after the target
  expression, or give "bind after" to delay it to where the shape becomes fixed
  — e.g. when its properties are written one by one after construction.
- SHAPE HINT assumes an object has already been bound to a static shape by a
  shape binding, so property accesses on it take fast shape-based paths. Specify the target
  expression and the static shape; the check runs right after the target
  expression is evaluated and lasts only until something may change the
  object's shape; if it does not actually change the object's shape, emit the
  shape hint again after it.

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
- Locations use 1-based line/column. The end column is EXCLUSIVE. "file" is
  optional (defaults to the source file being annotated):
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
      "target range": {{"start": {{"line": 12, "column": 11}}, "end": {{"line": 12, "column": 16}}}},
      "type": "number"
    }}
  ],
  "shape hints": [
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
- Use the `fold` tool first to get a structural view of large or files: 
  it folds multi-line blocks into ` … N lines folded …`, and prints
  1-based line numbers. Raise `unfold` (default 0) to expand a region,
  e.g. fold(file="{source_path.name}", from_line=176, to_line=200, unfold=1).
- Shell redirection like `>` `<` `<<`, `$()`, and interpreters `python3/node/sh -c` are blocked by
  the sandbox.
"""
