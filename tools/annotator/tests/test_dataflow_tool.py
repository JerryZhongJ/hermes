"""Tests for non-blocking, keyed Jelly dataflow queries."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from annotator.tools import dataflow_tool
from annotator.tools.dataflow_tool import build_dataflow_tools, make_dataflow_server


def _df_report() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "source": {"location": "a.js:2:5", "resolved": True, "var": "Identifier#x", "kind": "Identifier"},
        "completeness": {"aborted": False, "timeout": False},
        "truncated": False,
        "files": ["a.js"],
        "nodes": [
            {"id": 0, "kind": "variable", "var": "x", "location": "0:2:5:2:6", "label": "x"},
            {"id": 1, "kind": "property", "var": ".foo"},
            {"id": 2, "kind": "variable", "var": "y", "location": "0:4:1:4:2", "label": "y"},
            {"id": 3, "kind": "return", "var": "ret", "location": "0:3:1:5:2"},
        ],
        "edges": [
            {"from": 0, "to": 1, "kind": "store-property"},
            {"from": 1, "to": 2, "kind": "load-property"},
            {"from": 2, "to": 3, "kind": "return"},
        ],
    }


def _tools(workdir: Path) -> dict[str, Any]:
    return {tool.name: tool for tool in build_dataflow_tools(workdir / "a.js", workdir)}


def _run(tool: Any, args: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(tool.handler(args))


def _text(result: dict[str, Any]) -> str:
    return result["content"][0]["text"]


def _complete_pending(workdir: Path, report: dict[str, Any]) -> None:
    req = json.loads((workdir / ".jelly" / "df_req.json").read_text(encoding="utf-8"))
    req_id = req["req_id"]
    (workdir / ".jelly" / f"df.{req_id}.json").write_text(json.dumps(report), encoding="utf-8")
    (workdir / ".jelly" / "df_res.json").write_text(
        json.dumps({"req_id": req_id, "ok": True}), encoding="utf-8"
    )


def test_make_server_returns_sdk_config(tmp_path: Path):
    srv = make_dataflow_server(tmp_path / "a.js", tmp_path)
    assert srv["type"] == "sdk"
    assert srv["name"] == "jelly-dataflow"


def test_query_missing_source_errors(tmp_path: Path):
    res = _run(_tools(tmp_path)["query_dataflow"], {})
    assert res.get("is_error") is True


def test_dataflow_request_is_atomically_published(tmp_path: Path, monkeypatch):
    published: list[tuple[Path, dict[str, Any]]] = []

    def capture(path: Path, value: dict[str, Any]) -> None:
        published.append((path, value))

    monkeypatch.setattr(dataflow_tool, "atomic_write_json", capture)
    _run(_tools(tmp_path)["query_dataflow"], {"source": "2:5:2:6", "direction": "reverse"})

    assert len(published) == 1
    path, request = published[0]
    assert path == tmp_path / ".jelly" / "df_req.json"
    assert request["source"] == "a.js:2:5:2:6"
    assert request["direction"] == "reverse"
    assert isinstance(request["req_id"], str)


def test_first_query_is_immediately_not_ready_then_caches_result(tmp_path: Path):
    tools = _tools(tmp_path)
    first = _run(tools["query_dataflow"], {"source": "2:5:2:6"})
    assert "not yet ready" in _text(first)
    _complete_pending(tmp_path, _df_report())

    cached = _run(tools["query_dataflow"], {"source": "2:5:2:6"})
    text = _text(cached)
    assert "→ flows out: 2 point(s)" in text
    assert "variable y" in text
    assert "a.js:4" in text
    assert ".foo" not in text


def test_different_key_queues_without_blocking_cached_result(tmp_path: Path):
    tools = _tools(tmp_path)
    _run(tools["query_dataflow"], {"source": "2:5:2:6"})
    _complete_pending(tmp_path, _df_report())
    _run(tools["query_dataflow"], {"source": "2:5:2:6"})

    first_other = _run(tools["query_dataflow"], {"source": "4:1:4:2", "direction": "reverse"})
    assert "not yet ready" in _text(first_other)
    cached = _run(tools["query_dataflow"], {"source": "2:5:2:6"})
    assert "→ flows out: 2 point(s)" in _text(cached)
    assert "not yet ready" not in _text(cached)


def test_query_rejects_unknown_kind(tmp_path: Path):
    res = _run(
        _tools(tmp_path)["query_dataflow"],
        {"source": "2:5:2:6", "include_kinds": ["nonsense"]},
    )
    assert res.get("is_error") is True
