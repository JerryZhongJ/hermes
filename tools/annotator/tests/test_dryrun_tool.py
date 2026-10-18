"""Tests for the dryrun tool: filtering, rendering, and the shared cache."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest

from annotator.annotation_drafts import add_unique_draft, drafts
from annotator.tools import dryrun_tool
from annotator.tools.dryrun_tool import build_dryrun_tools
from annotator.tools.services import dryrun_service
from annotator.tools.utils import atomic_write_json


def _annotation(
    line: int,
    detail: str,
    *,
    optimizations: list[dict] | None = None,
    blockages: list[dict] | None = None,
    miss: list[dict] | None = None,
    missing_binding: str | None = None,
) -> dict:
    result = {
        "range": f"{line}:1-{line}:5",
        "kind": "shape guard",
        "detail": detail,
        "optimizations": optimizations or [],
        "blockages": blockages or [],
        "miss": miss or [],
    }
    if missing_binding is not None:
        result["missingBinding"] = missing_binding
    return result


def _effect(line: int, instruction: str, prop: str = "x") -> dict:
    return {
        "location": f"{line}:3",
        "instruction": instruction,
        "property": prop,
    }


def _report(
    *,
    annotations: list[dict] | None = None,
    warnings: str = "",
) -> dict:
    """A compile-result payload as the host service would produce.

    ``warnings`` rides on the (successful) run's stderr — the tool passes it
    through to the rendered output.
    """
    return {
        "ok": True,
        "stdout": json.dumps({"annotations": annotations or []}),
        "stderr": warnings,
    }


def _start_fake_host(tmp_path: Path, responses: list[dict], lock=None):
    """Serve queued responses over the real file-protocol directories.

    Each incoming request pops one queued response (ok / failure) and writes
    it back; the request count is asserted via the empty queue afterwards.
    """
    fb = tmp_path / ".feedback"
    (fb / "requests").mkdir(parents=True, exist_ok=True)
    (fb / "responses").mkdir(parents=True, exist_ok=True)
    queue = list(responses)
    state = {"count": 0}
    if lock is None:
        lock = threading.Lock()
    stop = threading.Event()

    def _serve() -> None:
        seen: set[str] = set()
        while not stop.is_set():
            for req_path in (fb / "requests").glob("*.json"):
                if req_path.stem in seen:
                    continue
                seen.add(req_path.stem)
                with lock:
                    state["count"] += 1
                    response = queue.pop(0) if queue else {
                        "ok": True,
                        "stdout": json.dumps({"annotations": []}),
                        "stderr": "",
                    }
                atomic_write_json(fb / "responses" / req_path.name, {
                    "req_id": req_path.stem,
                    **response,
                })
            stop.wait(0.005)

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    return state, stop, thread


def _dryrun_tool(tmp_path: Path, names: list[str]):
    (tool_obj,) = build_dryrun_tools(tmp_path, names)
    assert tool_obj.name == "dryrun"
    return tool_obj


def _call(tool, args: dict) -> dict:
    return asyncio.run(tool.handler(args))


def _text(tool, args: dict) -> str:
    result = _call(tool, args)
    assert not result.get("is_error"), result
    return result["content"][0]["text"]


def _write_source(tmp_path: Path, lines: int = 60) -> None:
    (tmp_path / "input.js").write_text("var a;\n" * lines, encoding="utf-8")


# --- argument validation ---------------------------------------------------- #


def test_schema_has_no_run_argument(tmp_path: Path):
    (tmp_path / "input.js").write_text("var a;\n", encoding="utf-8")
    tool_obj = _dryrun_tool(tmp_path, [add_unique_draft()])
    assert "run" not in tool_obj.input_schema["properties"]
    assert set(tool_obj.input_schema["properties"]) == {
        "draft",
        "scope",
        "feedback_types",
    }


def test_run_argument_is_rejected(tmp_path: Path):
    _write_source(tmp_path)
    draft = add_unique_draft()
    state, stop, thread = _start_fake_host(
        tmp_path, [_report(annotations=[_annotation(10, "a")])]
    )
    try:
        tool_obj = _dryrun_tool(tmp_path, [draft])
        result = _call(tool_obj, {"run": -1})
        assert result.get("is_error") is True
        assert "unexpected" in result["content"][0]["text"]
        assert state["count"] == 0  # rejected before any compile
    finally:
        stop.set()
        thread.join(timeout=2)


# --- summary + filtered detail in one call ----------------------------------- #


@pytest.fixture
def served_tool(tmp_path: Path):
    _write_source(tmp_path)
    draft = add_unique_draft()
    report = _report(
        annotations=[
            _annotation(
                10,
                "optimized",
                optimizations=[_effect(11, "PrLoadInst")],
                blockages=[_effect(12, "CallInst")],
                miss=[_effect(13, "LoadPropertyInst", "y")],
            ),
            _annotation(20, "idle"),
            _annotation(30, "killed-only", blockages=[_effect(31, "CallInst")]),
            _annotation(40, "unopt-only", miss=[_effect(41, "LoadPropertyInst")]),
            _annotation(50, "unbound", missing_binding="obj"),
        ],
        warnings="[31mloader warning[0m\n",
    )
    state, stop, thread = _start_fake_host(tmp_path, [report])
    tool_obj = _dryrun_tool(tmp_path, [draft])
    try:
        yield tool_obj
    finally:
        stop.set()
        thread.join(timeout=2)


def test_omitted_types_preserve_all_feedback_and_summary(served_tool):
    text = _text(served_tool, {})
    assert "[31mloader warning[0m" in text
    assert "optimized 11:3" in text
    assert "killed by 12:3" in text
    assert "13:3 property read .y not optimized" in text
    assert "✗ no effect" in text
    assert 'no shape binding for "obj"' in text
    assert "Summary: 1 optimized  2 kills  2 no-effect  2 unoptimized" in text
    # the whole-file summary line rides on top of the filtered view
    assert "Whole file: 1 optimized  2 kills  2 no-effect  2 unoptimized" in text


@pytest.mark.parametrize(
    ("feedback_type", "present", "absent", "summary"),
    [
        (
            "effect",
            ("optimized 11:3", "✗ no effect"),
            ("killed by", "not optimized"),
            "Summary: 1 optimized  2 no-effect",
        ),
        (
            "killed",
            ("killed by 12:3", "killed by 31:3"),
            ("✓ optimized", "not optimized"),
            "Summary: 2 kills",
        ),
        (
            "unoptimized",
            ("13:3 property read .y not optimized", "41:3 property read .x not optimized"),
            ("✓ optimized", "killed by"),
            "Summary: 2 unoptimized",
        ),
    ],
)
def test_single_type_filter(served_tool, feedback_type, present, absent, summary):
    text = _text(served_tool, {"feedback_types": [feedback_type]})
    assert f"types {feedback_type}" in text
    assert all(value in text for value in present)
    assert all(value not in text for value in absent)
    assert summary in text


def test_missing_binding_is_independent_from_missing_filter(served_tool):
    effect = _text(served_tool, {"feedback_types": ["effect"], "scope": "50-50"})
    missing = _text(served_tool, {"feedback_types": ["unoptimized"], "scope": "50-50"})
    assert 'no shape binding for "obj"' in effect
    assert 'no shape binding for "obj"' in missing
    assert "no-effect" not in effect.split("Effects:", 1)[1].split("Summary:", 1)[0]
    assert "Summary: 0 unoptimized" in missing


def test_multiline_annotation_range_uses_overlap(tmp_path: Path):
    _write_source(tmp_path)
    annotation = _annotation(
        20,
        "idle",
    )
    annotation["range"] = "20:1-22:5"
    draft = add_unique_draft()
    state, stop, thread = _start_fake_host(
        tmp_path, [_report(annotations=[annotation])]
    )
    try:
        tool_obj = _dryrun_tool(tmp_path, [draft])
        text = _text(tool_obj, {"feedback_types": ["effect"], "scope": "21-21"})
        assert 'shape guard "idle"' in text
        assert "✗ no effect" in text
    finally:
        stop.set()
        thread.join(timeout=2)


def test_type_filter_combines_with_line_range(served_tool):
    text = _text(
        served_tool,
        {"feedback_types": ["effect", "killed"], "scope": "10-10"},
    )
    assert "lines 10-10  types effect,killed" in text
    assert "1 optimized / 1 kill somewhere else" in text
    # the filtered Summary carries no missing dimension; the whole-file
    # header (which always shows every count) is the only place it appears
    body = text.split("\n", 1)[1]
    assert "unoptimized" not in body
    assert "Summary: 0 optimized  0 kills  0 no-effect" in body


def test_unselected_in_range_feedback_does_not_select_owner(served_tool):
    text = _text(served_tool, {"feedback_types": ["effect"], "scope": "31-31"})
    assert "killed-only" not in text
    assert "Effects:" not in text
    assert "Summary: 0 optimized  0 no-effect" in text


def test_selected_owner_keeps_its_no_effect_dimension(served_tool):
    text = _text(
        served_tool, {"feedback_types": ["effect", "killed"], "scope": "31-31"}
    )
    assert 'shape guard "killed-only"' in text
    assert "killed by 31:3" in text
    assert "✗ no effect" in text
    assert "Summary: 0 optimized  1 kill  1 no-effect" in text


def test_hidden_missing_does_not_become_no_effect(served_tool):
    text = _text(served_tool, {"feedback_types": ["effect"], "scope": "40-40"})
    assert "missing-only" not in text
    assert "✗ no effect" not in text


def test_warning_is_independent_from_types_and_empty_match(served_tool):
    text = _text(served_tool, {"feedback_types": ["killed"], "scope": "59-59"})
    assert "Warnings:\n  [31mloader warning[0m" in text
    assert "Effects:" not in text
    assert "Summary: 0 kills" in text


@pytest.mark.parametrize(
    ("feedback_types", "message"),
    [
        ([], "non-empty array"),
        ("effect", "non-empty array"),
        ([1], "entries must be strings"),
        (["effect", "effect"], "entries must be unique"),
        (["unknown"], "unknown feedback_types: unknown"),
    ],
)
def test_invalid_feedback_types(served_tool, feedback_types, message):
    result = _call(served_tool, {"feedback_types": feedback_types})
    assert result.get("is_error") is True
    assert message in result["content"][0]["text"]


def test_unknown_scope_rejected(tmp_path: Path):
    _write_source(tmp_path)
    draft = add_unique_draft()
    state, stop, thread = _start_fake_host(tmp_path, [_report()])
    try:
        tool_obj = _dryrun_tool(tmp_path, [draft])
        result = _call(tool_obj, {"scope": "999:1:999:9"})
        assert result.get("is_error") is True
        assert "unknown or malformed scope" in result["content"][0]["text"]
    finally:
        stop.set()
        thread.join(timeout=2)


# --- compile failures surface as errors -------------------------------------- #


def test_compile_failure_returned_as_error(tmp_path: Path):
    _write_source(tmp_path)
    draft = add_unique_draft()
    state, stop, thread = _start_fake_host(
        tmp_path, [{"ok": False, "stderr": "boom: bad annotation"}]
    )
    try:
        tool_obj = _dryrun_tool(tmp_path, [draft])
        result = _call(tool_obj, {})
        assert result.get("is_error") is True
        assert "annotation-dryrun failed" in result["content"][0]["text"]
        assert "boom" in result["content"][0]["text"]
    finally:
        stop.set()
        thread.join(timeout=2)


def test_unknown_draft_rejected_without_compiling(tmp_path: Path):
    _write_source(tmp_path)
    state, stop, thread = _start_fake_host(tmp_path, [])
    try:
        # names=[a, b] with no default: omitting draft= must be an error
        a, b = add_unique_draft(), add_unique_draft()
        tool_obj = _dryrun_tool(tmp_path, [a, b])
        result = _call(tool_obj, {})
        assert result.get("is_error") is True
        assert "pass draft=" in result["content"][0]["text"]
        assert state["count"] == 0
        result = _call(tool_obj, {"draft": "no-such-draft"})
        assert result.get("is_error") is True
        assert state["count"] == 0
    finally:
        stop.set()
        thread.join(timeout=2)


def test_draft_argument_selects_which_document_compiles(tmp_path: Path):
    _write_source(tmp_path)
    marker = add_unique_draft()
    other = add_unique_draft()
    report = _report(annotations=[_annotation(10, "from-marker")])
    state, stop, thread = _start_fake_host(tmp_path, [report])
    try:
        tool_obj = _dryrun_tool(tmp_path, [marker, other])  # no default
        text = _text(tool_obj, {"draft": marker})
        assert 'shape guard "from-marker"' in text
    finally:
        stop.set()
        thread.join(timeout=2)


# --- the shared cache: one compile per content change ------------------------ #


def test_same_content_compiles_once_across_calls(tmp_path: Path):
    _write_source(tmp_path)
    draft = add_unique_draft()
    state, stop, thread = _start_fake_host(
        tmp_path, [_report(annotations=[_annotation(10, "first")])]
    )
    try:
        tool_obj = _dryrun_tool(tmp_path, [draft])
        first = _text(tool_obj, {})
        second = _text(tool_obj, {"scope": "10-10", "feedback_types": ["effect"]})
        third = _text(tool_obj, {})
        assert state["count"] == 1  # unchanged draft: one compile total
        assert 'shape guard "first"' in first
        assert 'shape guard "first"' in second
        assert first == third
    finally:
        stop.set()
        thread.join(timeout=2)


def test_changed_content_recompiles(tmp_path: Path):
    _write_source(tmp_path)
    draft = add_unique_draft()
    state, stop, thread = _start_fake_host(
        tmp_path,
        [
            _report(annotations=[_annotation(10, "before")]),
            _report(annotations=[_annotation(10, "after")]),
        ],
    )
    try:
        tool_obj = _dryrun_tool(tmp_path, [draft])
        assert 'shape guard "before"' in _text(tool_obj, {})
        with drafts().lock(draft):
            doc = drafts().get(draft)
            doc.add_shape("Point", {"properties": [{"name": "x", "type": "number"}]})
            doc.add_array_item(
                "shape_guard",
                {
                    "target range": {
                        "start": {"line": 1, "column": 1},
                        "end": {"line": 1, "column": 5},
                    },
                    "shape": "Point",
                },
            )
        text = _text(tool_obj, {})
        assert state["count"] == 2
        assert 'shape guard "after"' in text
    finally:
        stop.set()
        thread.join(timeout=2)


def test_reason_revision_invalidates_cache(tmp_path: Path):
    """A check()/uncheck() mutation must invalidate the shared stamp too."""
    from annotator.tools.checklist_tool import reasons

    _write_source(tmp_path)
    draft = add_unique_draft()
    state, stop, thread = _start_fake_host(
        tmp_path,
        [_report(), _report()],
    )
    try:
        tool_obj = _dryrun_tool(tmp_path, [draft])
        _text(tool_obj, {})
        reasons().set(
            draft, [{"location": "1:1", "kind": "arithmetic"}], "other", "n"
        )
        _text(tool_obj, {})
        assert state["count"] == 2
    finally:
        stop.set()
        thread.join(timeout=2)


def test_fresh_result_persisted_under_feedback_cache(tmp_path: Path):
    _write_source(tmp_path)
    draft = add_unique_draft()
    state, stop, thread = _start_fake_host(
        tmp_path, [_report(annotations=[_annotation(10, "kept")])]
    )
    try:
        tool_obj = _dryrun_tool(tmp_path, [draft])
        _text(tool_obj, {})
        files = list((tmp_path / ".feedback" / "cache").glob("*.json"))
        assert len(files) == 1
        record = json.loads(files[0].read_text(encoding="utf-8"))
        assert record["data"]["annotations"][0]["detail"] == "kept"
        # a cached (unchanged) re-query persists nothing new
        _text(tool_obj, {})
        assert len(list((tmp_path / ".feedback" / "cache").glob("*.json"))) == 1
    finally:
        stop.set()
        thread.join(timeout=2)


def test_concurrent_calls_compile_once_per_content(tmp_path: Path):
    _write_source(tmp_path)
    draft = add_unique_draft()
    state, stop, thread = _start_fake_host(tmp_path, [_report()])
    tool_obj = _dryrun_tool(tmp_path, [draft])
    try:
        async def _three() -> list[dict]:
            return list(
                await asyncio.gather(*[tool_obj.handler({}) for _ in range(3)])
            )

        results = asyncio.run(_three())
        for result in results:
            assert not result.get("is_error"), result
        assert state["count"] == 1
    finally:
        stop.set()
        thread.join(timeout=2)


# --- unmatched annotations are auto-pruned ----------------------------------- #


def _warn(line: int, col: int, kind: str, name: str) -> str:
    """One AnnotationLoader unmatched warning, as stderr would carry it."""
    return (
        f"/workdir/input.js:{line}:{col}: warning: annotation "
        f'[{kind} "{name}"] unmatched: target range didn\'t emit annotation IR\n'
    )


def _add_annotation(doc, kind: str, start: tuple, end: tuple, **extra) -> None:
    item = {
        "target range": {
            "start": {"line": start[0], "column": start[1]},
            "end": {"line": end[0], "column": end[1]},
        },
        **extra,
    }
    doc.add_array_item(kind, item)


def _shapes(doc, *names: str) -> None:
    for name in names:
        doc.add_shape(name, {"properties": [{"name": "x", "type": "number"}]})


def test_unmatched_annotation_is_pruned_and_reported(tmp_path: Path):
    _write_source(tmp_path)
    draft = add_unique_draft()
    with drafts().lock(draft):
        doc = drafts().get(draft)
        _shapes(doc, "A", "B")
        _add_annotation(doc, "shape_guard", (10, 3), (10, 8), shape="A")
        _add_annotation(doc, "shape_binding", (12, 5), (12, 9), shape="B")
    state, stop, thread = _start_fake_host(
        tmp_path,
        [
            _report(
                annotations=[_annotation(10, "A")],
                warnings=_warn(12, 5, "shape binding", "B") + "other warning\n",
            )
        ],
    )
    try:
        tool_obj = _dryrun_tool(tmp_path, [draft])
        text = _text(tool_obj, {})
        assert "Auto-pruned 1 annotation that matched no IR" in text
        assert '- shape_binding "B" @12:5' in text
        # the unmatched line moved to the prune section, others stay visible
        assert "unmatched: target range" not in text
        assert "other warning" in text
        with drafts().lock(draft):
            doc = drafts().get(draft)
            assert doc.shape_bindings == []  # unmatched one is gone
            assert len(doc.shape_guards) == 1  # matched guard untouched
    finally:
        stop.set()
        thread.join(timeout=2)


def test_prototype_and_type_guard_warnings_prune_the_right_item(tmp_path: Path):
    _write_source(tmp_path)
    draft = add_unique_draft()
    with drafts().lock(draft):
        doc = drafts().get(draft)
        _shapes(doc, "A", "P")
        _add_annotation(
            doc, "shape_guard", (20, 1), (20, 6), shape="A", **{"prototype shape": "P"}
        )
        _add_annotation(doc, "type_guard", (30, 1), (30, 6), type=["number", "string"])
    state, stop, thread = _start_fake_host(
        tmp_path,
        [
            _report(
                warnings=_warn(20, 1, "prototype shape guard", "P")
                + _warn(30, 1, "type guard", "number|string")
            )
        ],
    )
    try:
        tool_obj = _dryrun_tool(tmp_path, [draft])
        text = _text(tool_obj, {})
        assert "Auto-pruned 2 annotations that matched no IR" in text
        assert '- shape_guard "P" @20:1' in text
        assert '- type_guard "number|string" @30:1' in text
        with drafts().lock(draft):
            doc = drafts().get(draft)
            assert doc.shape_guards == []
            assert doc.type_guards == []
    finally:
        stop.set()
        thread.join(timeout=2)


def test_same_range_guards_are_disambiguated_by_name(tmp_path: Path):
    _write_source(tmp_path)
    draft = add_unique_draft()
    with drafts().lock(draft):
        doc = drafts().get(draft)
        _shapes(doc, "A", "B")
        _add_annotation(doc, "shape_guard", (10, 3), (10, 8), shape="A")
        _add_annotation(doc, "shape_guard", (10, 3), (10, 8), shape="B")
    state, stop, thread = _start_fake_host(
        tmp_path, [_report(warnings=_warn(10, 3, "shape guard", "B"))]
    )
    try:
        tool_obj = _dryrun_tool(tmp_path, [draft])
        text = _text(tool_obj, {})
        assert '- shape_guard "B" @10:3' in text
        with drafts().lock(draft):
            doc = drafts().get(draft)
            assert [g["shape"] for g in doc.shape_guards] == ["A"]
    finally:
        stop.set()
        thread.join(timeout=2)


def test_ambiguous_same_range_same_name_is_left_for_manual_fix(tmp_path: Path):
    _write_source(tmp_path)
    draft = add_unique_draft()
    with drafts().lock(draft):
        doc = drafts().get(draft)
        _shapes(doc, "A")
        _add_annotation(doc, "shape_guard", (10, 3), (10, 8), shape="A")
        _add_annotation(doc, "shape_guard", (10, 3), (10, 9), shape="A")
    state, stop, thread = _start_fake_host(
        tmp_path, [_report(warnings=_warn(10, 3, "shape guard", "A"))]
    )
    try:
        tool_obj = _dryrun_tool(tmp_path, [draft])
        text = _text(tool_obj, {})
        assert "Auto-pruned" not in text
        assert "could not prune (ambiguous)" in text
        assert 'shape_guard "A" @10:3' in text
        with drafts().lock(draft):
            assert len(drafts().get(draft).shape_guards) == 2  # nothing deleted
    finally:
        stop.set()
        thread.join(timeout=2)


def test_warning_without_matching_item_is_skipped_silently(tmp_path: Path):
    _write_source(tmp_path)
    draft = add_unique_draft()
    state, stop, thread = _start_fake_host(
        tmp_path, [_report(warnings=_warn(99, 9, "shape binding", "ghost"))]
    )
    try:
        tool_obj = _dryrun_tool(tmp_path, [draft])
        text = _text(tool_obj, {})
        assert "Auto-pruned" not in text
        assert "could not prune" not in text
    finally:
        stop.set()
        thread.join(timeout=2)


def test_prune_invalidates_cache_so_next_call_recompiles_clean(tmp_path: Path):
    """The pruned draft's content changed: the next dryrun must recompile
    (and a clean recompile reports no pruning and keeps nothing hidden)."""
    _write_source(tmp_path)
    draft = add_unique_draft()
    with drafts().lock(draft):
        doc = drafts().get(draft)
        _shapes(doc, "B")
        _add_annotation(doc, "shape_binding", (12, 5), (12, 9), shape="B")
    state, stop, thread = _start_fake_host(
        tmp_path,
        [
            _report(warnings=_warn(12, 5, "shape binding", "B")),
            _report(),
        ],
    )
    try:
        tool_obj = _dryrun_tool(tmp_path, [draft])
        first = _text(tool_obj, {})
        assert "Auto-pruned 1 annotation" in first
        second = _text(tool_obj, {})
        assert state["count"] == 2  # prune changed the draft: recompiled
        assert "Auto-pruned" not in second
        assert "unmatched" not in second
    finally:
        stop.set()
        thread.join(timeout=2)


# --- host service tests (unchanged behavior) --------------------------------- #


def _wait_for_files(directory: Path, count: int) -> list[Path]:
    import time

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        files = list(directory.glob("*.json")) if directory.exists() else []
        if len(files) >= count:
            return files
        time.sleep(0.01)
    return []


def _start_service(tmp_path: Path, monkeypatch):
    import subprocess

    source = tmp_path / "input.js"
    source.write_text("print(1);\n", encoding="utf-8")
    binary = tmp_path / "annotation-dryrun"
    binary.write_text("", encoding="utf-8")
    stop = threading.Event()
    monkeypatch.setattr(dryrun_service, "POLL_INTERVAL_S", 0.01)
    thread = threading.Thread(
        target=dryrun_service.serve,
        args=(tmp_path, source.name, binary, stop),
    )
    thread.start()
    return binary, stop, thread


def test_host_processes_each_request_with_its_own_snapshot(tmp_path: Path, monkeypatch):
    import subprocess

    seen: list[tuple[str, str]] = []

    def fake_run(cmd, **_kwargs):
        annotation = Path(cmd[cmd.index("-annotation-file") + 1])
        seen.append((annotation.stem, annotation.read_text(encoding="utf-8")))
        return subprocess.CompletedProcess(cmd, 0, '{"annotations": []}', "")

    monkeypatch.setattr(dryrun_service.subprocess, "run", fake_run)
    _, stop, thread = _start_service(tmp_path, monkeypatch)
    requests = tmp_path / ".feedback/requests"
    for req_id, marker in (("a" * 32, "first"), ("b" * 32, "second")):
        snapshot = tmp_path / f".feedback/snapshots/{req_id}.json"
        atomic_write_json(snapshot, {"marker": marker})
        atomic_write_json(
            requests / f"{req_id}.json",
            {
                "req_id": req_id,
                "annotation": f".feedback/snapshots/{req_id}.json",
            },
        )

    responses = _wait_for_files(tmp_path / ".feedback/responses", 2)
    stop.set()
    thread.join(timeout=2)
    assert len(responses) == 2
    assert seen == [
        ("a" * 32, '{\n  "marker": "first"\n}\n'),
        ("b" * 32, '{\n  "marker": "second"\n}\n'),
    ]
    assert {json.loads(path.read_text())["req_id"] for path in responses} == {
        "a" * 32,
        "b" * 32,
    }


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("not json", "invalid request JSON"),
        ({"req_id": "b" * 32, "annotation": ".feedback/snapshots/" + "a" * 32 + ".json"},
         "payload req_id does not match"),
        ({"req_id": "a" * 32, "annotation": ".feedback/snapshots/" + "b" * 32 + ".json"},
         "annotation must be"),
    ],
)
def test_host_invalid_request_still_gets_independent_response(
    tmp_path: Path, monkeypatch, body, message
):
    monkeypatch.setattr(
        dryrun_service.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("invalid request must not run binary"),
    )
    _, stop, thread = _start_service(tmp_path, monkeypatch)
    req_id = "a" * 32
    request = tmp_path / f".feedback/requests/{req_id}.json"
    request.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(body, str):
        request.write_text(body, encoding="utf-8")
    else:
        atomic_write_json(request, body)

    responses = _wait_for_files(tmp_path / ".feedback/responses", 1)
    stop.set()
    thread.join(timeout=2)
    assert len(responses) == 1
    result = json.loads(responses[0].read_text(encoding="utf-8"))
    assert result["req_id"] == req_id
    assert result["ok"] is False
    assert message in result["stderr"]


def test_host_rejects_same_id_snapshot_symlink(tmp_path: Path, monkeypatch):
    outside_snapshot = tmp_path / "other.json"
    atomic_write_json(outside_snapshot, {})
    req_id = "a" * 32
    snapshot = tmp_path / f".feedback/snapshots/{req_id}.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.symlink_to(outside_snapshot)
    request = tmp_path / f".feedback/requests/{req_id}.json"
    atomic_write_json(
        request,
        {
            "req_id": req_id,
            "annotation": f".feedback/snapshots/{req_id}.json",
        },
    )
    monkeypatch.setattr(
        dryrun_service.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("unsafe snapshot must not run binary"),
    )
    _, stop, thread = _start_service(tmp_path, monkeypatch)
    responses = _wait_for_files(tmp_path / ".feedback/responses", 1)
    stop.set()
    thread.join(timeout=2)
    result = json.loads(responses[0].read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert "not a safe same-id file" in result["stderr"]


def test_no_effect_always_shown_regardless_of_feedback_types(served_tool):
    """no-effect is an always-on diagnostic: an in-scope annotation with no
    feedback of any kind must appear even when the query filters to a single
    feedback type — absence must only ever mean "out of scope"."""
    text = _text(served_tool, {"feedback_types": ["unoptimized"]})
    assert "✗ no effect" in text
    out = _text(
        served_tool, {"feedback_types": ["unoptimized"], "scope": "1-5"}
    )
    assert "✗ no effect" not in out  # out of scope: the only legitimate absence
