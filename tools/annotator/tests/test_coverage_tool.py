"""Tests for function-identity coverage accounting."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from annotator.tools.annotation_tool import AnnotationDocument, KIND_TYPE_GUARD
from annotator.tools.chunk_tool import build_index
from annotator.tools.coverage_tool import build_coverage_tools

_SOURCE = """function outer() {
  const outside = 1;
  function inner() {
    const inside = 2;
    return inside;
  }
  return outside;
}
const top = 0;
"""


def _prepare(tmp_path: Path) -> tuple[Path, AnnotationDocument, dict[str, Any]]:
    source = tmp_path / "input.js"
    source.write_text(_SOURCE, encoding="utf-8")
    build_index(source, tmp_path)
    doc = AnnotationDocument.empty()
    tools = {tool.name: tool for tool in build_coverage_tools(source, tmp_path, doc)}
    return source, doc, tools


def _run(tool: Any) -> str:
    result = asyncio.run(tool.handler({}))
    return result["content"][0]["text"]


def _add_type(doc: AnnotationDocument, start: tuple[int, int], end: tuple[int, int]) -> None:
    doc.add_array_item(
        KIND_TYPE_GUARD,
        {
            "target range": {
                "start": {"line": start[0], "column": start[1]},
                "end": {"line": end[0], "column": end[1]},
            },
            "type": "number",
        },
    )


def test_inner_annotation_only_covers_inner(tmp_path: Path):
    _, doc, tools = _prepare(tmp_path)
    _add_type(doc, (4, 11), (4, 17))  # `inside` in inner

    output = _run(tools["coverage"])

    assert "annotated=1" in output
    assert "uncovered=1" in output
    assert "outer" in output
    assert "inner" not in output


def test_outer_annotation_only_covers_outer(tmp_path: Path):
    _, doc, tools = _prepare(tmp_path)
    _add_type(doc, (2, 9), (2, 16))  # `outside` outside inner

    output = _run(tools["coverage"])

    assert "annotated=1" in output
    assert "uncovered=1" in output
    assert "inner" in output
    assert "outer" not in output


def test_top_level_annotation_is_unattributed(tmp_path: Path):
    _, doc, tools = _prepare(tmp_path)
    _add_type(doc, (9, 1), (9, 6))  # top-level `const` has no function owner

    output = _run(tools["coverage"])

    assert "annotated=0" in output
    assert "unattributed annotations: 1" in output
    assert "uncovered=2" in output
