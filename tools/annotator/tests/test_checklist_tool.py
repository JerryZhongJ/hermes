"""Tests for the dryrun-projected checklist MCP tools."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from annotator.tools.checklist_tool import (
    TOP_LEVEL_KEY,
    _scope_checklist,
    build_checklist_tools,
    coverage_snapshot,
)

SOURCE = b"""function make() {
  var obj = {x: 1};
  return obj;
}
function f(o) {
  var t = o.x + 1;
  o.y = t;
  return t;
}
"""


def test_scope_groups_by_owning_function():
    report = {
        "opportunities": [
            {"kind": "arithmetic", "location": "6:11", "outcome": "optimized"},
            {"kind": "property_load", "location": "6:12", "property": "x", "outcome": "optimized"},
            {"kind": "property_store", "location": "7:7", "property": "y", "outcome": "not-optimized"},
            {"kind": "property_store", "location": "1:1", "property": "make", "outcome": "not-optimized"},
        ]
    }
    scoped = _scope_checklist(report, SOURCE)
    assert set(scoped) == {"1:1", "5:1"}
    f_items = {i["location"] for i in scoped["5:1"]}
    assert f_items == {"6:11", "6:12", "7:7"}
    assert {i["location"] for i in scoped["1:1"]} == {"1:1"}


def test_scope_joins_reasons_by_key():
    report = {
        "opportunities": [
            {"kind": "property_store", "location": "7:7", "property": "y", "outcome": "not-optimized"},
        ]
    }
    reasons = {
        ("7:7", "property_store", "y"): {"reason": "ambiguous-shape"},
        ("7:7", "property_store", ""): {"reason": "stale-key-must-not-match"},
    }
    scoped = _scope_checklist(report, SOURCE, reasons)
    (item,) = scoped["5:1"]
    assert item["reason"] == {"reason": "ambiguous-shape"}


def test_scope_assigns_nested_function_to_inner():
    nested = b"function outer() {\n  function inner() { return 1 + 1; }\n  return inner;\n}\n"
    report = {"opportunities": [{"kind": "arithmetic", "location": "2:24", "outcome": "not-optimized"}]}
    scoped = _scope_checklist(report, nested)
    assert set(scoped) == {"2:3"}


def test_scope_drops_unlocatable_entries():
    report = {"opportunities": [{"kind": "arithmetic", "location": "not-a-loc", "outcome": "optimized"}]}
    assert _scope_checklist(report, SOURCE) == {}


def test_top_level_sites_group_under_sentinel_and_count_in_file_view():
    """Sites outside every function (module top-level) must not vanish: they
    land in the sentinel group, excluded from function scopes but aggregated
    by the whole-file completion check."""
    source = b"var g = {n: 1};\nprint(g.n + 1);\n"
    report = {
        "opportunities": [
            {"kind": "property_load", "location": "2:8", "property": "n", "outcome": "not-optimized"},
            {"kind": "arithmetic", "location": "2:12", "outcome": "not-optimized"},
        ]
    }
    scoped = _scope_checklist(report, source)
    assert set(scoped) == {TOP_LEVEL_KEY}
    snapshot = coverage_snapshot(report, source, "file")
    assert snapshot["total"] == 2
    assert snapshot["uncovered"] == 2
    assert {i["location"] for i in snapshot["uncovered_items"]} == {"2:8", "2:12"}


def test_legacy_covered_outcome_still_counts():
    report = {
        "opportunities": [
            {"kind": "arithmetic", "location": "6:11", "outcome": "covered"},
        ]
    }
    scoped = _scope_checklist(report, SOURCE)
    (item,) = scoped["5:1"]
    assert item["outcome"] == "covered"


def _tools(tmp_path: Path, report: dict):
    from annotator.annotation_drafts import add_unique_draft

    async def fake_run(name=None):
        return report

    return build_checklist_tools(
        tmp_path / "input.js", fake_run, add_unique_draft()
    )


def _list_tool(tmp_path: Path, report: dict):
    (list_checklist, *_rest) = _tools(tmp_path, report)
    return list_checklist


def _text(tool, args: dict) -> str:
    result = asyncio.run(tool.handler(args))
    assert not result.get("is_error"), result
    return result["content"][0]["text"]


REPORT = {
    "opportunities": [
        {"kind": "arithmetic", "location": "6:11", "outcome": "optimized"},
        {"kind": "property_load", "location": "6:12", "property": "x", "outcome": "optimized"},
        {"kind": "property_store", "location": "7:7", "property": "y", "outcome": "not-optimized"},
        {"kind": "property_store", "location": "1:1", "property": "make", "outcome": "not-optimized"},
    ]
}


def test_list_single_function_scope(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    list_tool = _list_tool(tmp_path, REPORT)
    payload = json.loads(_text(list_tool, {"scope": "5:1"}))
    assert payload["scope"] == "5:1"
    assert payload["summary"] == {"total": 3, "optimized": 2, "reasoned": 0, "uncovered": 1}
    assert len(payload["checklist"]) == 3
    assert payload["checklist"][0]["id"].startswith("item_")
    assert all(i["function_loc_key"] == "5:1" for i in payload["checklist"])


def test_list_multi_function_scope(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    list_tool = _list_tool(tmp_path, REPORT)
    payload = json.loads(_text(list_tool, {"scope": ["5:1", "1:1"]}))
    assert payload["summary"] == {"total": 4, "optimized": 2, "reasoned": 0, "uncovered": 2}
    assert {i["function_loc_key"] for i in payload["checklist"]} == {"5:1", "1:1"}


def test_list_file_scope(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    list_tool = _list_tool(tmp_path, REPORT)
    payload = json.loads(_text(list_tool, {"scope": "file"}))
    # same universe as the multi-function list of every key
    assert payload["summary"] == {"total": 4, "optimized": 2, "reasoned": 0, "uncovered": 2}


def test_default_scope_is_file(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    list_tool = _list_tool(tmp_path, REPORT)
    payload = json.loads(_text(list_tool, {}))
    assert payload["scope"] == "file"
    assert payload["summary"] == {"total": 4, "optimized": 2, "reasoned": 0, "uncovered": 2}


def test_only_uncovered_filters(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    list_tool = _list_tool(tmp_path, REPORT)
    payload = json.loads(
        _text(list_tool, {"scope": ["5:1", "1:1"], "only_uncovered": True})
    )
    # summary still reports the full-scope counts
    assert payload["summary"] == {"total": 4, "optimized": 2, "reasoned": 0, "uncovered": 2}
    assert [i["location"] for i in payload["checklist"]] == ["7:7", "1:1"]


def test_duplicate_scope_keys_deduplicated(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    list_tool = _list_tool(tmp_path, REPORT)
    payload = json.loads(_text(list_tool, {"scope": ["5:1", "5:1"]}))
    assert payload["summary"]["total"] == 3


def test_without_view_no_reasons(tmp_path: Path):
    """No view → no reasons → every not-optimized item stays uncovered."""
    (tmp_path / "input.js").write_bytes(SOURCE)
    list_tool = _list_tool(tmp_path, REPORT)
    payload = json.loads(_text(list_tool, {"scope": "5:1"}))
    assert payload["summary"]["uncovered"] == 1


def test_zero_checklist_function_is_valid(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(b"function f() { return 1; }\n")
    list_tool = _list_tool(tmp_path, {"opportunities": []})
    payload = json.loads(_text(list_tool, {"scope": "1:1"}))
    assert payload["summary"] == {"total": 0, "optimized": 0, "reasoned": 0, "uncovered": 0}
    assert payload["checklist"] == []


def test_unknown_function_key_rejected(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    list_tool = _list_tool(tmp_path, {"opportunities": []})
    response = asyncio.run(list_tool.handler({"scope": "9:9"}))
    assert response.get("is_error")
    assert "unknown or malformed scope" in response["content"][0]["text"]


def test_malformed_scope_rejected(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    list_tool = _list_tool(tmp_path, {"opportunities": []})
    for bad in ([], 42, ["5:1", ""], {"a": 1}):
        response = asyncio.run(list_tool.handler({"scope": bad}))
        assert response.get("is_error"), bad


# --- the detail-list cap (CHECKLIST_ITEM_CAP) ------------------------------ #

from annotator.tools.checklist_tool import CHECKLIST_ITEM_CAP  # noqa: E402


def _big_report(n: int) -> dict:
    """n uncovered arithmetic items inside f ("5:1") plus one optimized."""
    return {
        "opportunities": [
            {"kind": "arithmetic", "location": f"6:{11 + i}", "outcome": "not-optimized"}
            for i in range(n)
        ]
        + [{"kind": "arithmetic", "location": "7:30", "outcome": "optimized"}]
    }


def test_file_scope_over_cap_truncates(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    report = _big_report(CHECKLIST_ITEM_CAP + 5)
    list_tool = _list_tool(tmp_path, report)
    payload = json.loads(_text(list_tool, {"scope": "file"}))
    assert len(payload["checklist"]) == CHECKLIST_ITEM_CAP
    # the first items in report order, deterministically
    assert payload["checklist"][0]["location"] == "6:11"
    assert payload["truncated"] is True
    assert payload["shown"] == CHECKLIST_ITEM_CAP
    # no only_uncovered: the capped list is the FULL item list (uncovered + optimized)
    assert payload["total"] == CHECKLIST_ITEM_CAP + 6
    assert "narrow scope" in payload["hint"]
    # summary stays complete — uncapped
    assert payload["summary"]["total"] == CHECKLIST_ITEM_CAP + 6
    assert payload["summary"]["uncovered"] == CHECKLIST_ITEM_CAP + 5


def test_at_or_below_cap_has_no_truncation_fields(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    # n uncovered + 1 optimized = n+1 detail items; at exactly the cap
    list_tool = _list_tool(tmp_path, _big_report(CHECKLIST_ITEM_CAP - 1))
    payload = json.loads(_text(list_tool, {"scope": "file"}))
    assert len(payload["checklist"]) == CHECKLIST_ITEM_CAP
    for field in ("truncated", "shown", "total", "hint"):
        assert field not in payload


def test_cap_applies_with_only_uncovered(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    report = _big_report(CHECKLIST_ITEM_CAP + 3)
    list_tool = _list_tool(tmp_path, report)
    payload = json.loads(
        _text(list_tool, {"scope": "file", "only_uncovered": True})
    )
    # the filter runs first, the cap applies to the filtered list
    assert payload["truncated"] is True
    assert payload["total"] == CHECKLIST_ITEM_CAP + 3
    assert payload["shown"] == CHECKLIST_ITEM_CAP
    assert len(payload["checklist"]) == CHECKLIST_ITEM_CAP


def test_host_completion_check_not_affected_by_cap(tmp_path: Path):
    """coverage_snapshot (the host follow-up hook) reads the summary path,
    never the capped MCP detail list: uncovered>0 must still block completion
    with the full uncovered item list."""
    (tmp_path / "input.js").write_bytes(SOURCE)
    report = _big_report(CHECKLIST_ITEM_CAP + 5)
    snapshot = coverage_snapshot(report, (tmp_path / "input.js").read_bytes(), "file")
    assert snapshot["uncovered"] == CHECKLIST_ITEM_CAP + 5
    assert snapshot["uncovered"] > 0  # not judged complete
    assert len(snapshot["uncovered_items"]) == CHECKLIST_ITEM_CAP + 5


# --- the write side: check / uncheck / list_reasons over the reason store -- #

from annotator.annotation_drafts import add_unique_draft  # noqa: E402
from annotator.tools.checklist_tool import reasons  # noqa: E402


class monkeypatched_run_dryrun:
    """Patch the host compile out, keeping the shared cache path real.

    ``fake_compile`` is a sync ``() -> (report, stderr)``; every path that
    would run the host binary (``make_compile_fn``) calls it instead, so
    call counts reflect true compiles through the shared ReportCache.
    """

    def __init__(self, workdir: Path, draft: str, fake_compile):
        self._workdir = workdir
        self._draft = draft
        self._fake = fake_compile
        self._original = dryrun_tool.make_compile_fn

    def _patched(self, workdir, name):
        fake = self._fake

        async def _run_async():
            return fake()

        return _run_async

    def __enter__(self):
        dryrun_tool.make_compile_fn = self._patched
        return self

    def __exit__(self, *exc):
        dryrun_tool.make_compile_fn = self._original
        return False


def _write_tools(tmp_path: Path, report: dict, draft: str):
    async def fake_run(name=None):
        return report

    (_list, check, list_reasons, uncheck, _copy_reasons) = build_checklist_tools(
        tmp_path / "input.js", fake_run, draft
    )
    return check, list_reasons, uncheck


def test_check_single_records_one_reason(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    draft = add_unique_draft()
    check, list_reasons, uncheck = _write_tools(tmp_path, REPORT, draft)
    # bare location identifies the site; kind/property auto-filled
    payload = json.loads(_text(check, {"location": "7:7", "reason": "ambiguous-shape"}))
    assert payload["checked"] == 1
    record = reasons().get(draft)[0]
    assert (record["location"], record["kind"], record["property"]) == (
        "7:7", "property_store", "y",
    )
    listing = json.loads(_text(list_reasons, {}))
    assert listing["count"] == 1
    assert listing["reasons"][0]["location"] == "7:7"


def test_check_batch_shares_one_reason(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    draft = add_unique_draft()
    check, *_ = _write_tools(tmp_path, REPORT, draft)
    payload = json.loads(
        _text(
            check,
            {
                "items": [
                    {"location": "7:7", "kind": "property_store", "property": "y"},
                    {"location": "6:11", "kind": "arithmetic"},
                ],
                "reason": "maybe-not-number",
            },
        )
    )
    assert payload["checked"] == 2
    records = reasons().get(draft)
    assert {r["reason"] for r in records} == {"maybe-not-number"}
    # re-checking overlapping items replaces, not duplicates
    _text(check, {"items": [{"location": "7:7", "kind": "property_store", "property": "y"}], "reason": "other", "note": "n"})
    records = reasons().get(draft)
    assert len(records) == 2
    (replaced,) = [r for r in records if r["location"] == "7:7"]
    assert replaced["reason"] == "other"


def test_check_rejects_bad_input(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    draft = add_unique_draft()
    check, *_ = _write_tools(tmp_path, REPORT, draft)
    for bad in (
        {"reason": "other", "note": "n"},  # no site at all
        {"location": "9:9", "reason": "other", "note": "n"},  # site not in checklist
        {"location": "7:7", "kind": "property_store", "items": [], "reason": "other", "note": "n"},  # both forms
        {"items": [], "reason": "other", "note": "n"},  # empty batch
        {"items": [{"location": "1:1", "kind": "call"}, {"location": "1:1", "kind": "call"}], "reason": "other", "note": "n"},  # dup
        {"location": "7:7", "kind": "property_store", "reason": "other"},  # note missing
    ):
        response = asyncio.run(check.handler(bad))
        assert response.get("is_error"), bad


def test_check_ambiguous_location_lists_candidates(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    draft = add_unique_draft()
    # two checklist items share location 1:1
    report = {
        "opportunities": [
            {"kind": "arithmetic", "location": "1:1", "outcome": "not-optimized"},
            {"kind": "call", "location": "1:1", "property": "f", "outcome": "not-optimized"},
        ]
    }
    check, *_ = _write_tools(tmp_path, report, draft)
    response = asyncio.run(
        check.handler({"location": "1:1", "reason": "other", "note": "n"})
    )
    assert response["is_error"]
    text = response["content"][0]["text"]
    assert "matches 2 checklist items" in text
    assert "arithmetic" in text and "call f" in text
    # kind disambiguates
    payload = json.loads(
        _text(check, {"location": "1:1", "kind": "call", "reason": "other", "note": "n"})
    )
    assert payload["checked"] == 1
    assert payload["items"][0]["property"] == "f"


def test_uncheck_removes_one_record(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    draft = add_unique_draft()
    check, _list_reasons, uncheck = _write_tools(tmp_path, REPORT, draft)
    _text(check, {"items": [{"location": "7:7", "kind": "property_store", "property": "y"}, {"location": "6:11", "kind": "arithmetic"}], "reason": "ambiguous-shape"})
    _text(uncheck, {"location": "6:11"})
    records = reasons().get(draft)
    assert [r["location"] for r in records] == ["7:7"]


def test_checklist_joins_store_reasons(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    draft = add_unique_draft()
    tools = build_checklist_tools(tmp_path / "input.js", _fake_report, draft)
    list_tool, check, *_ = tools
    _text(check, {"location": "7:7", "kind": "property_store", "property": "y", "reason": "ambiguous-shape"})
    payload = json.loads(_text(list_tool, {"scope": "5:1"}))
    assert payload["summary"]["reasoned"] == 1
    assert payload["summary"]["uncovered"] == 0


async def _fake_report(name=None):
    return REPORT


def test_reason_revision_invalidates_cached_report(tmp_path: Path):
    """A check() between two list_checklist calls must re-run the dryrun."""
    (tmp_path / "input.js").write_bytes(SOURCE)
    draft = add_unique_draft()
    runs = []

    def counting_compile():
        runs.append(1)
        return REPORT, ""

    with monkeypatched_run_dryrun(tmp_path, draft, counting_compile):
        list_tool, check, *_ = build_checklist_tools(
            tmp_path / "input.js",
            dryrun_tool.run_dryrun_sync(tmp_path, draft),
            draft,
        )
        _text(list_tool, {"scope": "5:1"})
        assert len(runs) == 1
        _text(list_tool, {"scope": "5:1"})  # unchanged → cached
        assert len(runs) == 1
        _text(check, {"location": "7:7", "kind": "property_store", "property": "y", "reason": "ambiguous-shape"})
        _text(list_tool, {"scope": "5:1"})  # reason revision changed → rerun
        assert len(runs) == 2


# --- the shared report cache (dryrun tool ↔ list_checklist) ------------------ #

import pytest  # noqa: E402

from annotator.tools import dryrun_tool  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_shared_caches(monkeypatch):
    """Isolate the process-wide per-workdir cache registry per test."""
    monkeypatch.setattr(dryrun_tool, "_CACHES", {})


def test_dryrun_then_list_checklist_share_one_compile(tmp_path: Path):
    """Same content: a dryrun call then a list_checklist call compile once."""
    (tmp_path / "input.js").write_bytes(SOURCE)
    draft = add_unique_draft()
    runs = []

    def counting_compile():
        runs.append(1)
        return REPORT, ""

    with monkeypatched_run_dryrun(tmp_path, draft, counting_compile):
        dryrun = next(
            tool
            for tool in dryrun_tool.build_dryrun_tools(tmp_path, [draft])
            if tool.name == "dryrun"
        )
        result = asyncio.run(dryrun.handler({}))
        assert not result.get("is_error"), result
        assert len(runs) == 1

        # list_checklist over the same (unchanged) draft reuses the report
        list_tool, *_ = build_checklist_tools(
            tmp_path / "input.js",
            dryrun_tool.run_dryrun_sync(tmp_path, draft),
            draft,
        )
        payload = json.loads(_text(list_tool, {"scope": "5:1"}))
        assert payload["summary"]["uncovered"] == 1
        assert len(runs) == 1  # no second compile


def test_annotation_change_recompiles_once_for_both_callers(tmp_path: Path):
    """A draft mutation invalidates the shared stamp: exactly one recompile
    serves whichever caller asks first; the other reuses it."""
    (tmp_path / "input.js").write_bytes(SOURCE)
    draft = add_unique_draft()
    runs = []

    def counting_compile():
        runs.append(1)
        return REPORT, ""

    with monkeypatched_run_dryrun(tmp_path, draft, counting_compile):
        dryrun = next(
            tool
            for tool in dryrun_tool.build_dryrun_tools(tmp_path, [draft])
            if tool.name == "dryrun"
        )
        asyncio.run(dryrun.handler({}))
        assert len(runs) == 1

        # mutate the draft → the stamp moves → one recompile, both reuse it
        from annotator.annotation_drafts import drafts

        with drafts().lock(draft):
            drafts().get(draft).add_shape(
                "Point", {"properties": [{"name": "x", "type": "number"}]}
            )
        asyncio.run(dryrun.handler({}))
        assert len(runs) == 2

        list_tool, *_ = build_checklist_tools(
            tmp_path / "input.js",
            dryrun_tool.run_dryrun_sync(tmp_path, draft),
            draft,
        )
        _text(list_tool, {"scope": "5:1"})
        assert len(runs) == 2  # still the same compile


def test_reasons_survive_save_and_drop(tmp_path: Path):
    """reasons ride along in the saved product json; dropping frees the store."""
    import json as _json

    import pytest

    from annotator.annotation_drafts import drafts
    from annotator.tools.checklist_tool import REASONS_KEY

    (tmp_path / "input.js").write_bytes(SOURCE)
    draft = add_unique_draft()
    check, *_ = _write_tools(tmp_path, REPORT, draft)
    _text(check, {"location": "7:7", "kind": "property_store", "property": "y", "reason": "ambiguous-shape"})

    # the save bridge: product json carries the reasons section inline
    payload = _json.loads(drafts().get(draft).to_json())
    payload[REASONS_KEY] = reasons().get(draft)
    seed = tmp_path / "seed.json"
    seed.write_text(_json.dumps(payload))

    drafts().drop(draft)
    with pytest.raises(Exception):
        reasons().get(draft)


# --- copy_reasons (the reason store's own cross-draft transfer) ------------- #


def _reasons_tools(tmp_path: Path, report: dict):
    """Checklist tools with a default draft; returns (tools, draft)."""
    async def fake_run(name=None):
        return report

    draft = add_unique_draft()
    tools = build_checklist_tools(tmp_path / "input.js", fake_run, draft)
    return tools, draft


def test_copy_reasons_unions_and_keeps_dest_records(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    tools, dest = _reasons_tools(tmp_path, REPORT)
    src = add_unique_draft()
    reasons().set(dest, [{"location": "5:1", "kind": "call", "property": "f"}], "no-closure-target")
    reasons().set(src, [{"location": "7:7", "kind": "property_store", "property": "y"}], "ambiguous-shape")
    # Same key in both: dest's record wins.
    reasons().set(src, [{"location": "5:1", "kind": "call", "property": "f"}], "other", "src note")
    (_list, _check, _lr, _unc, copy_reasons) = tools
    result = asyncio.run(copy_reasons.handler({"source": src}))
    assert not result.get("is_error")
    merged = {(r["location"], r["kind"]): r["reason"] for r in reasons().get(dest)}
    assert merged == {
        ("5:1", "call"): "no-closure-target",
        ("7:7", "property_store"): "ambiguous-shape",
    }


def test_copy_reasons_rejects_self_and_unknown_source(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    tools, dest = _reasons_tools(tmp_path, REPORT)
    (_list, _check, _lr, _unc, copy_reasons) = tools
    for bad_source, needle in ((dest, "itself"), ("no-such-draft", "unknown draft")):
        result = asyncio.run(copy_reasons.handler({"source": bad_source}))
        assert result.get("is_error")
        assert needle in result["content"][0]["text"]


# --- explicit-draft queries (the parallel workers' open-access mode) -------- #


def _open_tools(tmp_path: Path, report: dict):
    """Open-access checklist: no server default — every call passes draft=."""
    async def fake_run(name=None):
        assert name is not None, "open access must resolve an explicit draft"
        return report

    return build_checklist_tools(tmp_path / "input.js", fake_run, None)


def test_open_access_list_requires_explicit_draft(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    (list_tool, *_rest) = _open_tools(tmp_path, REPORT)
    result = asyncio.run(list_tool.handler({"scope": "5:1"}))
    assert result.get("is_error")
    assert "pass draft=" in result["content"][0]["text"]


def test_open_access_list_with_explicit_draft_reports_that_draft(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(SOURCE)
    from annotator.annotation_drafts import add_unique_draft

    (list_tool, *_rest) = _open_tools(tmp_path, REPORT)
    name = add_unique_draft()
    # The reason index is per-draft: a reason recorded on this draft removes
    # the item from uncovered, an unknown draft has no reasons.
    reasons().set(
        name,
        [{"location": "7:7", "kind": "property_store", "property": "y"}],
        "ambiguous-shape",
    )
    result = asyncio.run(
        list_tool.handler({"scope": "5:1", "draft": name})
    )
    assert not result.get("is_error")
    payload = json.loads(result["content"][0]["text"])
    assert payload["summary"]["reasoned"] == 1
    assert payload["summary"]["uncovered"] == 0


# --- explicit top-level addressing and window top-level merge ---------------- #

# Module-level stores on lines 1-2; line 3+ is a function with its own site.
TOP_SOURCE = b"""var g = {n: 1};
g.m = g.n + 1;
function f() {
  g.k = 2;
}
"""

_TOP_REPORT = {
    "opportunities": [
        {"kind": "property_store", "location": "2:1", "property": "m", "outcome": "not-optimized"},
        {"kind": "property_load", "location": "2:8", "property": "n", "outcome": "not-optimized"},
        {"kind": "arithmetic", "location": "2:13", "outcome": "not-optimized"},
        {"kind": "property_store", "location": "4:3", "property": "k", "outcome": "not-optimized"},
    ]
}


def _top_tools(tmp_path: Path):
    (tmp_path / "input.js").write_bytes(TOP_SOURCE)
    from annotator.annotation_drafts import add_unique_draft

    async def fake_run(name=None):
        return _TOP_REPORT

    return build_checklist_tools(
        tmp_path / "input.js", fake_run, add_unique_draft()
    )


def test_top_level_key_selectable_as_scope(tmp_path: Path):
    (list_tool, *_rest) = _top_tools(tmp_path)
    result = asyncio.run(list_tool.handler({"scope": TOP_LEVEL_KEY}))
    assert not result.get("is_error"), result
    payload = json.loads(result["content"][0]["text"])
    assert payload["summary"]["total"] == 3
    assert {i["location"] for i in payload["checklist"]} == {"2:1", "2:8", "2:13"}


def test_top_level_key_mixed_into_loc_key_list(tmp_path: Path):
    (list_tool, *_rest) = _top_tools(tmp_path)
    result = asyncio.run(list_tool.handler({"scope": ["3:1", TOP_LEVEL_KEY]}))
    assert not result.get("is_error"), result
    payload = json.loads(result["content"][0]["text"])
    assert payload["summary"]["total"] == 4
    assert {i["location"] for i in payload["checklist"]} == {
        "2:1", "2:8", "2:13", "4:3",
    }


def test_line_range_covering_top_level_sites_finds_them(tmp_path: Path):
    """The raytrace pitfall: a purely top-level window like "2-2" used to
    return zero items because line ranges only resolved to functions."""
    (list_tool, *_rest) = _top_tools(tmp_path)
    result = asyncio.run(list_tool.handler({"scope": "2-2"}))
    assert not result.get("is_error"), result
    payload = json.loads(result["content"][0]["text"])
    assert payload["summary"]["total"] == 3
    assert {i["function_loc_key"] for i in payload["checklist"]} == {TOP_LEVEL_KEY}
    # A window with no top-level sites inside stays function-only.
    result = asyncio.run(list_tool.handler({"scope": "4-4"}))
    payload = json.loads(result["content"][0]["text"])
    assert payload["summary"]["total"] == 1
    assert {i["function_loc_key"] for i in payload["checklist"]} == {"3:1"}


def test_line_window_filters_sites_not_whole_functions(tmp_path: Path):
    """A line window is SITE-level: only items whose own location line falls
    inside it are listed — "6-6" inside f (lines 5-8) must not drag in the
    line-7 site the way the old function-selector resolution did."""
    (tmp_path / "input.js").write_bytes(SOURCE)
    list_tool = _list_tool(tmp_path, REPORT)
    payload = json.loads(_text(list_tool, {"scope": "6-6"}))
    assert payload["summary"] == {"total": 2, "optimized": 2, "reasoned": 0, "uncovered": 0}
    assert {i["location"] for i in payload["checklist"]} == {"6:11", "6:12"}
    # summary and detail agree on the single-line window holding one item.
    payload = json.loads(_text(list_tool, {"scope": "7-7"}))
    assert payload["summary"] == {"total": 1, "optimized": 0, "reasoned": 0, "uncovered": 1}
    assert [i["location"] for i in payload["checklist"]] == ["7:7"]


def test_line_window_spanning_functions_and_top_level_merges_both(tmp_path: Path):
    """A window crossing the function/top-level boundary selects the sites of
    both sides that fall inside it (and nothing else)."""
    (list_tool, *_rest) = _top_tools(tmp_path)
    payload = json.loads(_text(list_tool, {"scope": "2-4"}))
    assert payload["summary"]["total"] == 4
    assert {i["location"] for i in payload["checklist"]} == {"2:1", "2:8", "2:13", "4:3"}


def test_line_window_out_of_file_rejected_like_dryrun(tmp_path: Path):
    """Same window contract as dryrun/resolve_scope: b beyond the file's
    line count is a malformed scope, not a silently-clamped one."""
    (tmp_path / "input.js").write_bytes(SOURCE)  # 8 lines
    list_tool = _list_tool(tmp_path, REPORT)
    for bad in ("5-99", "0-3", "5-4"):
        response = asyncio.run(list_tool.handler({"scope": bad}))
        assert response.get("is_error"), bad
        assert "unknown or malformed scope" in response["content"][0]["text"]


def test_function_scope_excludes_nested_function_sites(tmp_path: Path):
    """Innermost-ownership regression: sites in a nested function belong to
    the nested function's loc_key, never to the outer function's scope."""
    nested = b"""function outer() {
  var o = {a: 1};
  o.a = o.a + 1;
  function inner() {
    var p = {b: 2};
    p.b = p.b + 2;
  }
  return inner;
}
"""
    (tmp_path / "input.js").write_bytes(nested)
    from annotator.annotation_drafts import add_unique_draft

    report = {
        "opportunities": [
            {"kind": "property_store", "location": "3:3", "property": "a", "outcome": "not-optimized"},
            {"kind": "arithmetic", "location": "3:9", "outcome": "not-optimized"},
            {"kind": "property_store", "location": "6:5", "property": "b", "outcome": "not-optimized"},
            {"kind": "arithmetic", "location": "6:11", "outcome": "not-optimized"},
        ]
    }

    async def fake_run(name=None):
        return report

    (list_tool, *_rest) = build_checklist_tools(
        tmp_path / "input.js", fake_run, add_unique_draft()
    )
    result = asyncio.run(list_tool.handler({"scope": "1:1"}))
    assert not result.get("is_error"), result
    payload = json.loads(result["content"][0]["text"])
    assert {i["location"] for i in payload["checklist"]} == {"3:3", "3:9"}
    assert {i["function_loc_key"] for i in payload["checklist"]} == {"1:1"}
    # The nested function's own loc_key ("4:3" — its declaration start) covers
    # exactly the nested sites.
    result = asyncio.run(list_tool.handler({"scope": "4:3"}))
    payload = json.loads(result["content"][0]["text"])
    assert {i["location"] for i in payload["checklist"]} == {"6:5", "6:11"}
