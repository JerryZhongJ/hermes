#!/usr/bin/env python3
"""Tests for the annotation pipeline and runner selection.

The hotspot workflow's product is the coordinator's saved drafts: the
coordinator saves each finished target draft as ``hotspot:<id>.json`` in the
attempt workdir (``save_annotations``), and the host ships the whole workdir
to the output directory. These tests cover that contract without spinning up
a real agent: a fake runner stands in for the coordinator by writing the
saved-draft files.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from annotator.agents import AgentRun, TraceSource, create_runner
from annotator.pipeline import (
    generate_annotations,
    publish_trace,
    write_run_manifest,
)
from annotator.prompt import ABOUT_ANNOTATIONS_FILENAME, build_about_annotations_markdown
from annotator.workflows import AnnotationRequest


def _valid_doc() -> dict:
    return {
        "static shapes": {
            "Point": {"properties": [{"name": "x", "type": "number"}]}
        },
        "shape guards": [],
        "shape bindings": [
            {
                "target range": {
                    "start": {"line": 1, "column": 1},
                    "end": {"line": 1, "column": 10},
                },
                "shape": "Point",
            }
        ],
        "type guards": [],
    }


class FakeRunner:
    """Stands in for the coordinator: saves each produced target's draft as
    ``hotspot:<id>.json`` in the attempt workdir (what ``save_annotations``
    does) and returns a (possibly empty) error list.

    ``produced`` maps loc_key -> annotation document; targets absent from it
    are simply not saved (failed jobs persist nothing).
    """

    def __init__(self, produced: dict | None = None, errors: list[str] | None = None):
        self._produced = produced if produced is not None else {}
        self._errors = errors or []

    def run(
        self,
        attempt_dir: Path,
        source_name: str,
        request: AnnotationRequest,
        append_prompt: str | None = None,
    ) -> AgentRun:
        assert (attempt_dir / ABOUT_ANNOTATIONS_FILENAME).read_text(encoding="utf-8") == (
            build_about_annotations_markdown()
        )
        for loc_key, document in self._produced.items():
            name = f"hotspot:{loc_key.replace(':', '_')}"
            (attempt_dir / f"{name}.json").write_text(
                json.dumps(document, indent=2), encoding="utf-8"
            )
        return AgentRun(errors=list(self._errors))


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create separate input + temp_root dirs so generate_annotations' copy of
    the input into temp_root does not collide with the source (SameFileError)."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    src = src_dir / "input.js"
    src.write_text("var o = {x:1};\nprint(o.x);\n", encoding="utf-8")
    temp_root = tmp_path / "attempt"
    temp_root.mkdir()
    out = tmp_path / "annotations.d"
    return src, temp_root, out


def _hotspot_request(src: Path, targets: tuple[str, ...] = ()) -> AnnotationRequest:
    """The default workflow is the hotspot stage: every pipeline test needs a
    target. If the source has no function (the plain fixture), give it one."""
    from annotator.tools.functions import extract_functions

    funcs = extract_functions(src.read_bytes())
    if not funcs:
        src.write_text(
            src.read_text(encoding="utf-8") + "\nfunction tgt(o) { return o.x; }\n",
            encoding="utf-8",
        )
        funcs = extract_functions(src.read_bytes())
    target = funcs[0]["loc_key"]
    return AnnotationRequest(
        source_path=src,
        workflow="annotate-hotspot-functions",
        targets=targets or (target,),
    )


# --- non-claude agents are refused (annotation MCP is claude-only) -------- #


def test_codex_runner_refused():
    # The codex backend was removed; only the claude backend exists.
    cfg = SimpleNamespace(agent="codex")
    with pytest.raises(ValueError, match="unsupported agent"):
        create_runner(cfg, timeout_seconds=10)


def test_unknown_agent_refused():
    cfg = SimpleNamespace(agent="nope")
    with pytest.raises(ValueError, match="unsupported agent"):
        create_runner(cfg, timeout_seconds=10)


# --- pipeline: saved drafts ship with the whole workdir ---------------------- #


def test_saved_drafts_ship_with_workdir(tmp_path: Path):
    src, temp_root, out = _setup(tmp_path)
    from annotator.tools.functions import extract_functions

    src.write_text("function f(o) { return o.x; }\n", encoding="utf-8")
    target = extract_functions(src.read_bytes())[0]["loc_key"]
    runner = FakeRunner(produced={target: _valid_doc()})
    run = generate_annotations(
        runner, src, out, temp_root,
        request=_hotspot_request(src, (target,)),
    )
    assert not run.errors, run.errors
    fragment = out / f"hotspot:{target.replace(':', '_')}.json"
    assert fragment.is_file()
    promoted = json.loads(fragment.read_text(encoding="utf-8"))
    assert promoted == _valid_doc()


def test_failed_target_saves_nothing_but_others_ship(tmp_path: Path):
    src, temp_root, out = _setup(tmp_path)
    from annotator.tools.functions import extract_functions

    src.write_text("function f(o) { return o.x; }\nfunction g(o) { return o.y; }\n", encoding="utf-8")
    locs = [f["loc_key"] for f in extract_functions(src.read_bytes())]
    runner = FakeRunner(produced={locs[0]: _valid_doc()})
    run = generate_annotations(
        runner, src, out, temp_root,
        request=_hotspot_request(src, tuple(locs)),
    )
    assert not run.errors, run.errors
    assert (out / f"hotspot:{locs[0].replace(':', '_')}.json").is_file()
    assert not (out / f"hotspot:{locs[1].replace(':', '_')}.json").exists()


def test_zero_saved_drafts_fails(tmp_path: Path):
    src, temp_root, out = _setup(tmp_path)
    run = generate_annotations(
        FakeRunner(produced={}), src, out, temp_root, request=_hotspot_request(src)
    )
    assert run.errors and "no annotation product was saved" in run.errors[0]


def test_request_source_must_match_input(tmp_path: Path):
    src, temp_root, out = _setup(tmp_path)
    with pytest.raises(ValueError, match="source_path must match input_path"):
        generate_annotations(
            FakeRunner(),
            src,
            out,
            temp_root,
            request=AnnotationRequest(source_path=Path("other.js")),
        )


# --- the promotion path ships bytes, never parses (file mover, not curator) -- #


def test_promote_workdir_ships_saved_products_unchanged(tmp_path: Path):
    """main.json is copied verbatim: a fifth section (uncovered_reasons)
    or any other future extension must never fail promotion."""
    src, temp_root, out = _setup(tmp_path)
    payload = _valid_doc()
    payload["uncovered_reasons"] = [{"location": "1:2", "kind": "arithmetic"}]
    (temp_root / "main.json").write_text(json.dumps(payload), encoding="utf-8")
    run = generate_annotations(
        FakeRunner(), src, out, temp_root,
        request=AnnotationRequest(
            source_path=src, workflow="annotate-file"
        ),
    )
    assert not run.errors, run.errors
    promoted = json.loads((out / "main.json").read_text(encoding="utf-8"))
    assert promoted == payload  # byte-identical content, extra section intact


def test_promote_workdir_fails_without_any_product(tmp_path: Path):
    src, temp_root, out = _setup(tmp_path)
    run = generate_annotations(
        FakeRunner(), src, out, temp_root,
        request=AnnotationRequest(
            source_path=src, workflow="annotate-file"
        ),
    )
    assert run.errors and "no annotation product was saved" in run.errors[0]


def test_publish_trace_keeps_other_sessions(tmp_path: Path):
    source_dir = tmp_path / "claude" / "projects" / "-work"
    source_dir.mkdir(parents=True)
    main = source_dir / "session-1.jsonl"
    main.write_text('{"type":"user"}\n', encoding="utf-8")
    # Two hotspot target-agent sessions, one with its own subagents dir.
    other_a = source_dir / "target-a.jsonl"
    other_a.write_text('{"type":"assistant"}\n', encoding="utf-8")
    other_b = source_dir / "target-b.jsonl"
    other_b.write_text('{"type":"assistant"}\n', encoding="utf-8")
    (source_dir / "target-b" / "subagents").mkdir(parents=True)
    (source_dir / "target-b" / "subagents" / "inner.jsonl").write_text(
        '{"type":"user"}\n', encoding="utf-8"
    )
    run = AgentRun(
        errors=[],
        trace_source=TraceSource(
            main=main,
            session_id="session-1",
            others=(other_a, other_b),
        ),
        worker_completed=True,
    )
    run_path = tmp_path / "result.run.json"

    published = publish_trace(run_path, run)
    sessions = published.trace.directory / "sessions"
    assert (sessions / "target-a.jsonl").is_file()
    assert (sessions / "target-b.jsonl").is_file()
    assert (sessions / "target-b" / "subagents" / "inner.jsonl").is_file()


def test_publish_trace_copies_main_and_subagents(tmp_path: Path):
    source_dir = tmp_path / "claude" / "projects" / "-work"
    source_dir.mkdir(parents=True)
    main = source_dir / "session-1.jsonl"
    main.write_text('{"type":"user"}\n', encoding="utf-8")
    subagents = source_dir / "session-1" / "subagents"
    subagents.mkdir(parents=True)
    (subagents / "agent-a1.jsonl").write_text('{"type":"assistant"}\n', encoding="utf-8")
    run = AgentRun(
        errors=[],
        trace_source=TraceSource(main=main, session_id="session-1"),
        worker_completed=True,
    )
    run_path = tmp_path / "result.run.json"

    published = publish_trace(run_path, run)
    assert published.trace is not None
    assert (published.trace.directory / "session.jsonl").is_file()
    assert (published.trace.directory / "subagents" / "agent-a1.jsonl").is_file()
    assert published.trace.complete is True


def test_write_run_manifest_references_relative_trace(tmp_path: Path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    main = source_dir / "session-2.jsonl"
    main.write_text('{"type":"user"}\n', encoding="utf-8")
    run_path = tmp_path / "result.run.json"
    run = publish_trace(
        run_path,
        AgentRun(
            errors=[],
            trace_source=TraceSource(main=main, session_id="session-2"),
            worker_completed=True,
        ),
    )
    write_run_manifest(run_path, Path("input.js"), tmp_path / "out.json", 0.0, "claude", run)
    manifest = json.loads(run_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2
    assert not Path(manifest["trace"]["path"]).is_absolute()
    assert manifest["trace"]["main"] == "session.jsonl"
    assert manifest["output"]["published"] is False
