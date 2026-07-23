"""Tests for the Jelly call-graph tools (async auto-loading + auto-reanalyze).

Handler tests drive tools directly via ``await tool.handler(args)``. The workdir
fixture pre-writes ``.jelly/cg.json`` so queries auto-load it (no explicit load
step). Pure-function tests (build_model / overrides / heat) need no workdir.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from annotator.tools.callgraph import (
    CallEdgeOverrides,
    HeatAssumptions,
    HeatParams,
    build_model,
    compute_heat,
)
from annotator.tools import callgraph_tool
from annotator.tools.callgraph_tool import build_callgraph_tools, make_callgraph_server


def _cg() -> dict[str, Any]:
    return {
        "files": ["a.js"],
        "functions": {
            "0": "0:1:1:6:1",
            "1": "0:2:2:4:3",
            "2": "0:5:2:5:10",
        },
        "calls": {
            "0": "0:3:5:3:10",
            "1": "0:1:5:1:10",
        },
        "fun2fun": [[0, 1], [1, 2]],
        "call2fun": [[0, 2], [1, 1]],
        "entries": ["a.js"],
    }


def _eff(model) -> Any:
    return CallEdgeOverrides().effective_edges(model)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    jd = tmp_path / ".jelly"
    jd.mkdir()
    (jd / "cg.json").write_text(json.dumps(_cg()), encoding="utf-8")
    return tmp_path


@pytest.fixture
def tools(workdir: Path) -> dict[str, Any]:
    return {t.name: t for t in build_callgraph_tools(workdir / "a.js", workdir)}


async def _call(tool: Any, args: dict[str, Any]) -> dict[str, Any]:
    return await tool.handler(args)


def _run(tool: Any, args: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(_call(tool, args))


def _text(result: dict[str, Any]) -> str:
    return result["content"][0]["text"]


# --- pure: model / overrides / heat (no workdir) ------------------------- #


def test_build_model_identifies_entries_callers():
    model = build_model(_cg())
    assert model.entries == {0}
    assert model.module_funs == {0}
    assert model.call2caller == {0: 1, 1: 0}


def test_override_exclude_drops_edge():
    model = build_model(_cg())
    ov = CallEdgeOverrides()
    ov.set(model.calls[1].loc_key, model.functions[1].loc_key, "exclude")
    eff = ov.effective_edges(model)
    assert eff.call2fun_by_call[1] == set()


def test_heat_simple_chain_converges_to_one():
    model = build_model(_cg())
    heat = compute_heat(model, _eff(model), HeatAssumptions(), HeatParams(), {})
    by_key = {r["loc_key"]: r for r in heat["per_function"]}
    assert heat["status"] == "converged"
    assert by_key[model.functions[2].loc_key]["hot"] == pytest.approx(1.0)


def test_heat_hard_override_propagates():
    model = build_model(_cg())
    f = model.functions[1].loc_key
    a = HeatAssumptions(function_hot={f: 5.0})
    heat = compute_heat(model, _eff(model), a, HeatParams(), {})
    by_key = {r["loc_key"]: r for r in heat["per_function"]}
    assert by_key[f]["hot"] == pytest.approx(5.0)
    assert by_key[model.functions[2].loc_key]["hot"] == pytest.approx(5.0)


def test_heat_exec_expt_changes_hot():
    model = build_model(_cg())
    call0 = model.calls[0].loc_key
    a = HeatAssumptions(exec_expt={call0: 3.0})
    heat = compute_heat(model, _eff(model), a, HeatParams(), {})
    by_key = {r["loc_key"]: r for r in heat["per_function"]}
    assert by_key[model.functions[2].loc_key]["hot"] == pytest.approx(3.0)


def test_heat_target_prob_sum_over_one_raises():
    cg = _cg()
    cg["functions"]["3"] = "0:7:1:7:5"
    cg["call2fun"].append([1, 3])
    model = build_model(cg)
    call1 = model.calls[1].loc_key
    a = HeatAssumptions(target_prob={call1: {model.functions[1].loc_key: 0.7, model.functions[3].loc_key: 0.7}})
    with pytest.raises(ValueError):
        compute_heat(model, _eff(model), a, HeatParams(), {})


# --- handler: auto-load / no-graph / views ------------------------------- #


def test_make_server_returns_sdk_config(workdir: Path):
    srv = make_callgraph_server(workdir / "a.js", workdir)
    assert srv["type"] == "sdk"
    assert srv["name"] == "jelly"


def test_view_auto_loads(workdir, tools):
    # no load_callgraph call — view_callgraph auto-loads .jelly/cg.json
    res = _run(tools["view_callgraph"], {})
    assert "2 call site(s)" in _text(res)


def test_view_no_callgraph_is_not_ready(tmp_path):
    tools = {t.name: t for t in build_callgraph_tools(tmp_path / "a.js", tmp_path)}
    res = _run(tools["view_callgraph"], {})
    assert "not yet ready" in _text(res)
    assert not res.get("is_error")  # informational, not an error


def test_get_callers_auto(workdir, tools):
    model = build_model(_cg())
    res = _run(tools["get_callers"], {"callee": model.functions[2].loc_key})
    assert "1 caller(s)" in _text(res)


def test_get_callees_by_caller(workdir, tools):
    model = build_model(_cg())
    res = _run(tools["get_callees"], {"caller": model.functions[1].loc_key})
    assert "1 callee(s)" in _text(res)


def test_view_callgraph_filters(workdir, tools):
    assert "0 call site(s)" in _text(_run(tools["view_callgraph"], {"min_callees": 2}))
    assert "2 call site(s)" in _text(_run(tools["view_callgraph"], {"file": "a.js"}))


def test_view_hot_auto_and_filter(workdir, tools):
    model = build_model(_cg())
    _run(tools["set_hot_value"], {"func": model.functions[2].loc_key, "value": 5})
    keeps = _run(tools["view_hot_value"], {"min_hot": 3})
    assert "5.00" in _text(keeps)
    drops = _run(tools["view_hot_value"], {"min_hot": 10})
    assert "5.00" not in _text(drops)


def test_set_exec_expt_auto(workdir, tools):
    model = build_model(_cg())
    _run(tools["set_exec_expt"], {"callsite": model.calls[0].loc_key, "value": 3})
    assert "3.00" in _text(_run(tools["view_hot_value"], {}))


def test_set_target_prob_nonzero(workdir, tools):
    model = build_model(_cg())
    _run(tools["set_target_prob"], {
        "callsite": model.calls[0].loc_key,
        "callee": model.functions[2].loc_key,
        "prob": 0.5,
    })
    assert "0.50" in _text(_run(tools["view_hot_value"], {}))


def test_set_hot_value_rejects_negative(workdir, tools):
    model = build_model(_cg())
    res = _run(tools["set_hot_value"], {"func": model.functions[1].loc_key, "value": -5})
    assert res.get("is_error") is True


def test_set_target_prob_rejects_out_of_range(workdir, tools):
    model = build_model(_cg())
    for bad in (1.5, -0.1):
        res = _run(tools["set_target_prob"], {
            "callsite": model.calls[0].loc_key,
            "callee": model.functions[2].loc_key,
            "prob": bad,
        })
        assert res.get("is_error") is True


# --- handler: async reanalyze (delete triggers host roundtrip) ----------- #


def test_delete_triggers_async_reanalyze(workdir, tools):
    model = build_model(_cg())
    res = _run(tools["delete_call_edges"], {
        "edges": [{"callsite": model.calls[0].loc_key, "callee": model.functions[2].loc_key}]
    })
    assert "已请求 host 重分析" in _text(res)
    # While the host has not answered, queries still serve the stable graph with
    # the local override overlay and identify the result as stale.
    pending = _run(tools["view_callgraph"], {})
    assert "2 call site(s)" in _text(pending)
    assert "stale: refresh pending" in _text(pending)
    assert not pending.get("is_error")


def test_reanalyze_request_is_atomically_published(workdir, tools, monkeypatch):
    published: list[tuple[Path, dict[str, Any]]] = []

    def capture(path: Path, value: dict[str, Any]) -> None:
        published.append((path, value))

    monkeypatch.setattr(callgraph_tool, "atomic_write_json", capture)
    model = build_model(_cg())
    _run(tools["delete_call_edges"], {
        "edges": [{"callsite": model.calls[0].loc_key, "callee": model.functions[2].loc_key}]
    })

    assert len(published) == 1
    path, request = published[0]
    assert path == workdir / ".jelly" / "req.json"
    assert isinstance(request["req_id"], str)
    assert len(request["rules"]) == 1


def test_second_mutation_is_coalesced_into_followup_refresh(workdir, tools):
    model = build_model(_cg())
    _run(tools["delete_call_edges"], {
        "edges": [{"callsite": model.calls[0].loc_key, "callee": model.functions[2].loc_key}]
    })
    first_req = json.loads((workdir / ".jelly" / "req.json").read_text(encoding="utf-8"))
    _run(tools["add_call_edges"], {
        "edges": [{"callsite": model.calls[0].loc_key, "callee": model.functions[1].loc_key}]
    })
    # A pending request is never overwritten; the second mutation remains local
    # until the first host response is consumed.
    assert json.loads((workdir / ".jelly" / "req.json").read_text(encoding="utf-8")) == first_req
    (workdir / ".jelly" / "res.json").write_text(
        json.dumps({"req_id": first_req["req_id"], "ok": True}), encoding="utf-8"
    )
    _run(tools["view_callgraph"], {})
    second_req = json.loads((workdir / ".jelly" / "req.json").read_text(encoding="utf-8"))
    assert second_req["req_id"] != first_req["req_id"]
    assert len(second_req["rules"]) == 2


def test_reanalyze_completion_reloads_and_clears_overrides(workdir, tools):
    model = build_model(_cg())
    _run(tools["delete_call_edges"], {
        "edges": [{"callsite": model.calls[0].loc_key, "callee": model.functions[2].loc_key}]
    })
    # stand in for the host: read req_id, rewrite cg.json, post res.json
    req = json.loads((workdir / ".jelly" / "req.json").read_text(encoding="utf-8"))
    cg = _cg()
    cg["functions"]["999"] = "0:9:1:9:2"  # marker proving reload
    (workdir / ".jelly" / "cg.json").write_text(json.dumps(cg), encoding="utf-8")
    (workdir / ".jelly" / "res.json").write_text(
        json.dumps({"req_id": req["req_id"], "ok": True}), encoding="utf-8"
    )
    # next query absorbs the result: reload (revision bump) + session overrides cleared
    res = _run(tools["view_callgraph"], {})
    txt = _text(res)
    assert "revision 2" in txt  # reload bumped revision
    # overrides cleared: list shows none
    listed = _run(tools["list_call_edge_overrides"], {})
    assert "0 override(s)" in _text(listed)


def test_add_call_edges_batch_reject(workdir, tools):
    model = build_model(_cg())
    res = _run(tools["add_call_edges"], {"edges": [
        {"callsite": model.calls[0].loc_key, "callee": model.functions[1].loc_key},
        {"callsite": "a.js:99:1:99:2", "callee": model.functions[1].loc_key},
    ]})
    txt = _text(res)
    assert "1 edge(s) included" in txt
    assert "rejected" in txt
