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
  "file": "<basename of input file>",
  "start": {"line": 1, "column": 1},
  "end": {"line": 1, "column": 2}
}"""


def build_prompt(
    source_path: Path,
    source_text: str,
    annotation_path: Path,
) -> str:
    return f"""You are generating a Hermes annotation JSON file for performance optimization.

Write the final annotation JSON to this exact path:
{annotation_path}

Tool usage:
- Create the annotation file with the Write tool directly.
- Do NOT use the Bash tool to write the file: shell output redirection (>), input redirection (<), heredocs (<<), command substitution $(), and interpreters such as python3 / node / sh -c are blocked by the sandbox and will be denied, wasting turns.
- To verify the file after writing, use the Read tool rather than Bash.

Target:
- Use typed shape and type annotations to help the Hermes compiler optimize hot code.
- Prioritize loops, nested loops, frequently called functions, core data structure accesses, and repeated property reads/writes.
- Keep cold-code annotations restrained and spend annotation effort where optimization payoff is most likely.

Shape accuracy:
- A typed shape must exactly match the actual constructed object: complete property set, no extra properties, accurate property types.
- Property order must match the object construction / initialization write order. Typed shapes are order-sensitive.
- For objects with uncertain construction or mutation history, prefer a local shape hint or skip that shape.

JSON format:
- The top-level object must contain "shapes", "shape hints", and "shape assignments". It may also contain "type hints".
- Locations use 1-based line and column numbers.
- Location objects have this form:
```json
{location_schema()}
```
- "shapes" is an object mapping shape names to shape definitions. Shape names are only stable identifiers used by hints and assignments.
- Field names must match Hermes AnnotationLoader exactly: "expression range", "hint after ranges", "assign after", "shape".
- Property types are one of: {", ".join(sorted(SUPPORTED_TYPES))}. A union type is represented as an array of those strings.
- The annotation file content must be pure JSON.

Annotation strategy:
- Every typed shape needs at least one assignment.
- Prefer assignment at the object literal or after initialization completes.
- Property read/write, unknown calls, and generic unary/binary operations may block shape propagation through heap side effects.
- When useful, annotate operands with type/shape information or place a shape hint after a blocking operation.
- For unary/binary numeric operations, prefer type hints proving operands are "number".
- For unknown-shape property reads/writes, prefer a shape hint on the object or assignment after construction completes.

Example shape annotation:
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
  "type hints": [],
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

Input file: {source_path.name}
```javascript
{source_text}
```
"""
