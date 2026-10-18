"""Tests for the annotator agent's coverage follow-up hook.

``coverage_followup_hook`` drives same-session follow-up turns from a fresh
dryrun measurement; the session ends when the scope's checklist is covered
(UNCOVERED == 0). Product checking is NOT its business — that lives in the
invoking workflow's own gate (see test_agent_worker / test_workflows).
These tests exercise the hook with injected fakes (no dryrun service, no
real report).
"""

from __future__ import annotations

from pathlib import Path

import annotator.annotating_agent as aa
from annotator.annotating_agent import coverage_followup_hook
from annotator.annotation_drafts import add_unique_draft

SOURCE = b"function f(o) { return o.x + 1; }\n"


async def _report():
    return {"opportunities": []}


def _hook(monkeypatch, tmp_path: Path, snapshot_fn, max_followups=1):
    monkeypatch.setattr(
        aa, "run_dryrun_sync",
        lambda workdir, draft: _report,
    )
    monkeypatch.setattr(aa, "coverage_snapshot", snapshot_fn)
    source = tmp_path / "input.js"
    source.write_bytes(SOURCE)
    draft = add_unique_draft()
    hook = coverage_followup_hook(
        tmp_path, source, draft, "file", max_followups=max_followups
    )
    return hook


def test_followup_prompt_lists_uncovered_sites(monkeypatch, tmp_path):
    snapshot = {
        "uncovered": 2,
        "total": 5,
        "optimized": 2,
        "reasoned": 1,
        "uncovered_items": [
            {"location": "1:20", "kind": "property_load", "property": "x"},
            {"location": "1:26", "kind": "arithmetic"},
        ],
    }
    hook = _hook(monkeypatch, tmp_path, lambda *a: snapshot)
    prompt = hook(object())
    assert prompt is not None
    assert "2 uncovered of 5" in prompt
    assert "- 1:20 property_load .x" in prompt
    assert "- 1:26 arithmetic" in prompt
    assert "Continue in your scope" in prompt


def test_full_coverage_ends_session_without_any_saved_file(monkeypatch, tmp_path):
    """Coverage alone ends the session — the hook never checks products."""
    snapshot = {
        "uncovered": 0, "total": 5, "optimized": 4, "reasoned": 1,
        "uncovered_items": [],
    }
    hook = _hook(monkeypatch, tmp_path, lambda *a: snapshot)
    assert hook(object()) is None  # no <draft>.json written anywhere


def test_followups_exhaust_then_none(monkeypatch, tmp_path):
    snapshot = {
        "uncovered": 1, "total": 1, "optimized": 0, "reasoned": 0,
        "uncovered_items": [{"location": "1:20", "kind": "property_load"}],
    }
    hook = _hook(monkeypatch, tmp_path, lambda *a: snapshot, max_followups=2)
    assert hook(object()) is not None
    assert hook(object()) is not None
    assert hook(object()) is None  # budget exhausted: shortfall accepted


def test_dryrun_failure_ends_session(monkeypatch, tmp_path):
    async def _boom():
        raise RuntimeError("dryrun down")

    monkeypatch.setattr(aa, "run_dryrun_sync", lambda workdir, draft: _boom)
    source = tmp_path / "input.js"
    source.write_bytes(SOURCE)
    draft = add_unique_draft()
    hook = coverage_followup_hook(tmp_path, source, draft, "file")
    assert hook(object()) is None
