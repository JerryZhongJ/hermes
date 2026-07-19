"""Tests for the dataflow tool: query_dataflow(source) drives a mock host.

query_dataflow writes ``.jelly/df_req.json`` (source) and waits for
``.jelly/df_res.json`` + ``.jelly/df.json``. A mock-host thread stands in for
the real host service: on df_req.json it writes a synthetic report + df_res.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from annotator.tools.dataflow_tool import build_dataflow_tools, make_dataflow_server


def _df_report() -> dict[str, Any]:
    """source x -> store .foo -> (property, hidden) -> load -> y -> return."""
    return {
        "schemaVersion": 1,
        "source": {"location": "a.js:2:5", "resolved": True, "var": "Identifier#x", "kind": "Identifier"},
        "completeness": {"aborted": False, "timeout": False, "waveLimitReached": 0, "indirectionsLimitReached": 0},
        "truncated": False,
        "truncationReason": None,
        "files": ["a.js"],
        "nodes": [
            {"id": 0, "kind": "variable", "var": "x", "location": "0:2:5:2:6", "depth": 0, "label": "x", "tokens": []},
            {"id": 1, "kind": "property", "var": ".foo", "depth": 1, "prop": "foo", "tokens": []},
            {"id": 2, "kind": "variable", "var": "y", "location": "0:4:1:4:2", "depth": 2, "label": "y", "tokens": []},
            {"id": 3, "kind": "return", "var": "ret", "location": "0:3:1:5:2", "depth": 3, "tokens": []},
        ],
        "edges": [
            {"from": 0, "to": 1, "kind": "store-property", "prop": "foo"},
            {"from": 1, "to": 2, "kind": "load-property", "prop": "foo"},
            {"from": 2, "to": 3, "kind": "return"},
        ],
    }


@pytest.fixture
def tools(tmp_path: Path) -> dict[str, Any]:
    return {t.name: t for t in build_dataflow_tools(tmp_path / "a.js", tmp_path)}


def _run(tool: Any, args: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(tool.handler(args))


def _text(result: dict[str, Any]) -> str:
    return result["content"][0]["text"]


def _mock_host(workdir: Path, df: dict[str, Any]) -> threading.Thread:
    """Thread that watches .jelly/df_req.json and replies with df + df_res."""
    req_path = workdir / ".jelly" / "df_req.json"

    def run() -> None:
        for _ in range(500):
            if req_path.exists():
                try:
                    req = json.loads(req_path.read_text(encoding="utf-8"))
                except ValueError:
                    return
                (workdir / ".jelly" / "df.json").write_text(json.dumps(df), encoding="utf-8")
                (workdir / ".jelly" / "df_res.json").write_text(
                    json.dumps({"req_id": req.get("req_id"), "ok": True}), encoding="utf-8"
                )
                return
            time.sleep(0.01)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def test_make_server_returns_sdk_config(tmp_path: Path):
    srv = make_dataflow_server(tmp_path / "a.js", tmp_path)
    assert srv["type"] == "sdk"
    assert srv["name"] == "jelly-dataflow"


def test_query_missing_source_errors(tools):
    res = _run(tools["query_dataflow"], {})
    assert res.get("is_error") is True


def test_query_reaches_expressions(tmp_path, tools):
    t = _mock_host(tmp_path, _df_report())
    res = _run(tools["query_dataflow"], {"source": "2:5:2:6"})
    t.join(timeout=5)
    txt = _text(res)
    assert "reached 2 source point(s)" in txt  # y (variable) + return
    assert "variable y" in txt
    assert "a.js:4" in txt  # y's location
    # property and internal nodes are hidden
    assert ".foo" not in txt
    assert "[internal]" not in txt


def test_query_exclude_kind_filters(tmp_path, tools):
    # excluding 'return' drops the return endpoint (its only inbound edge is return)
    t = _mock_host(tmp_path, _df_report())
    res = _run(tools["query_dataflow"], {"source": "a.js:2:5", "exclude_kinds": ["return"]})
    t.join(timeout=5)
    txt = _text(res)
    assert "reached 1 source point(s)" in txt  # only y, not return
    assert "variable y" in txt


def test_query_rejects_unknown_kind(tmp_path, tools):
    t = _mock_host(tmp_path, _df_report())
    res = _run(tools["query_dataflow"], {"source": "a.js:2:5", "include_kinds": ["nonsense"]})
    t.join(timeout=1)
    assert res.get("is_error") is True
