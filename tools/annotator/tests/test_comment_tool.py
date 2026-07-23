"""Tests for locked, atomically published five-stage comments."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
from pathlib import Path
from typing import Any

from annotator.tools.chunk_tool import build_index
from annotator.tools.comment_tool import build_comment_tools


_SOURCE = """function example() {
  const a = {};
  // keep this function large enough for concurrent line notes
  a.x = 1;
  a.y = 2;
  a.z = 3;
  a.w = 4;
  a.v = 5;
  return a;
}
// padding
// padding
"""


def _prepare(workdir: Path) -> Path:
    source = workdir / "input.js"
    source.write_text(_SOURCE, encoding="utf-8")
    build_index(source, workdir, lines_per_chunk=100)
    return source


def _tools(workdir: Path, source: Path | None = None) -> dict[str, Any]:
    return {tool.name: tool for tool in build_comment_tools(workdir, source)}


def _run(tool: Any, args: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(tool.handler(args))


def _text(result: dict[str, Any]) -> str:
    return result["content"][0]["text"]


def _write_in_process(workdir: str, source: str, line: int) -> None:
    tools = _tools(Path(workdir), Path(source))
    result = _run(
        tools["write_comment"],
        {
            "phase": "phase1",
            "chunk_id": "chunk_001",
            "from_line": line,
            "to_line": line,
            "comment": f"note {line}",
        },
    )
    if result.get("is_error"):
        raise RuntimeError(_text(result))


def test_write_list_filter_and_delete_round_trip(tmp_path: Path):
    source = _prepare(tmp_path)
    tools = _tools(tmp_path, source)
    first = _run(
        tools["write_comment"],
        {
            "phase": "phase1",
            "chunk_id": "chunk_001",
            "from_line": 2,
            "to_line": 4,
            "comment": "general understanding",
        },
    )
    second = _run(
        tools["write_comment"],
        {
            "phase": "phase2",
            "chunk_id": "chunk_001",
            "from_line": 3,
            "to_line": 5,
            "comment": "shape facts",
        },
    )
    review = _run(
        tools["write_comment"],
        {
            "phase": "phase5",
            "from_line": 3,
            "to_line": 3,
            "comment": "review keeps this annotation",
        },
    )
    assert "#1 phase1" in _text(first)
    assert "#2 phase2" in _text(second)
    assert "#3 phase5" in _text(review)

    listed = _run(tools["list_comments"], {"phase": "phase2", "from_line": 3, "to_line": 5})
    assert "shape facts" in _text(listed)
    assert "general understanding" not in _text(listed)

    by_chunk = _run(tools["list_comments"], {"chunk_id": "chunk_001"})
    assert "general understanding" in _text(by_chunk)
    assert "shape facts" in _text(by_chunk)
    assert "review keeps" not in _text(by_chunk)

    deleted = _run(tools["delete_comment"], {"id": 1})
    assert not deleted.get("is_error")
    remaining = _run(tools["list_comments"], {})
    assert "shape facts" in _text(remaining)
    assert "general understanding" not in _text(remaining)


def test_chunk_comment_requires_owner_and_stays_in_chunk(tmp_path: Path):
    source = _prepare(tmp_path)
    tools = _tools(tmp_path, source)

    missing_owner = _run(
        tools["write_comment"],
        {"phase": "phase1", "from_line": 2, "to_line": 2, "comment": "missing owner"},
    )
    assert missing_owner.get("is_error")
    assert "require chunk_id" in _text(missing_owner)

    outside_owner = _run(
        tools["write_comment"],
        {
            "phase": "phase2",
            "chunk_id": "chunk_001",
            "from_line": 11,
            "to_line": 11,
            "comment": "outside",
        },
    )
    assert outside_owner.get("is_error")
    assert "fall outside" in _text(outside_owner)


def test_parallel_process_writers_preserve_all_comments(tmp_path: Path):
    source = _prepare(tmp_path)
    ctx = multiprocessing.get_context("fork")
    processes = [
        ctx.Process(target=_write_in_process, args=(str(tmp_path), str(source), line))
        for line in range(1, 9)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    sidecar = tmp_path / ".chunks" / "comments.json"
    items = json.loads(sidecar.read_text(encoding="utf-8"))
    assert len(items) == 8
    assert sorted(item["id"] for item in items) == list(range(1, 9))
    assert {item["comment"] for item in items} == {f"note {line}" for line in range(1, 9)}
    assert {item["phase"] for item in items} == {"phase1"}
    assert {item["chunk_id"] for item in items} == {"chunk_001"}


def test_malformed_sidecar_is_reported_not_silently_empty(tmp_path: Path):
    sidecar = tmp_path / ".chunks" / "comments.json"
    sidecar.parent.mkdir()
    sidecar.write_text("{not json", encoding="utf-8")

    result = _run(_tools(tmp_path)["list_comments"], {})
    assert result.get("is_error")
    assert "could not read comments" in _text(result)
