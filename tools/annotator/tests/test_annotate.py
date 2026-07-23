#!/usr/bin/env python3
"""Tests for the annotation pipeline and runner selection.

The agent no longer writes annotation.json — it maintains an in-memory document
via the annotation MCP, and the worker flushes it to ``.annotations.json`` at
run end. The pipeline then validates and promotes that file to the output.
These tests cover that contract (plus codex being refused, since the
annotation MCP is claude-only) without spinning up a real agent: a fake runner
stands in for the agent/worker pair by writing ``.annotations.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from annotator.agents import AgentRun, create_runner
from annotator.pipeline import _load_and_validate, generate_annotations
from annotator.prompt import ABOUT_ANNOTATIONS_FILENAME, build_about_annotations_markdown


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
    """Stands in for the agent worker: writes the flushed document, returns a
    (possibly empty) error list."""

    def __init__(self, document: dict | None, errors: list[str] | None = None):
        self._document = document
        self._errors = errors or []

    def run(self, prompt: str, attempt_dir: Path, source_name: str) -> AgentRun:
        assert (attempt_dir / ABOUT_ANNOTATIONS_FILENAME).read_text(encoding="utf-8") == (
            build_about_annotations_markdown()
        )
        if self._document is not None:
            (attempt_dir / ".annotations.json").write_text(
                json.dumps(self._document, indent=2), encoding="utf-8"
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
    out = tmp_path / "annotations.json"
    return src, temp_root, out


# --- codex is refused (annotation MCP is claude-only) --------------------- #


def test_codex_runner_refused():
    cfg = SimpleNamespace(agent="codex")
    with pytest.raises(ValueError, match="claude backend"):
        create_runner(cfg, timeout_seconds=10)


def test_unknown_agent_refused():
    cfg = SimpleNamespace(agent="nope")
    with pytest.raises(ValueError, match="unsupported agent"):
        create_runner(cfg, timeout_seconds=10)


# --- pipeline: valid document is promoted to output ----------------------- #


def test_valid_document_promoted_to_output(tmp_path: Path):
    src, temp_root, out = _setup(tmp_path)
    runner = FakeRunner(_valid_doc())
    run = generate_annotations(runner, src, out, temp_root)
    assert not run.errors
    assert out.exists()
    promoted = json.loads(out.read_text(encoding="utf-8"))
    assert promoted == _valid_doc()


def test_agent_errors_short_circuit(tmp_path: Path):
    src, temp_root, out = _setup(tmp_path)
    runner = FakeRunner(document=None, errors=["agent exploded"])
    run = generate_annotations(runner, src, out, temp_root)
    assert run.errors == ["agent exploded"]
    assert not out.exists()  # nothing promoted on agent failure


def test_missing_flushed_file_is_an_error(tmp_path: Path):
    src, temp_root, out = _setup(tmp_path)
    # Agent reported success but flushed no document.
    runner = FakeRunner(document=None)
    run = generate_annotations(runner, src, out, temp_root)
    assert run.errors and "invalid" in run.errors[0]
    assert not out.exists()


def test_malformed_flushed_file_is_an_error(tmp_path: Path):
    src, temp_root, out = _setup(tmp_path)
    runner = FakeRunner(document={"static shapes": "not a map"})  # type: ignore[dict-item]
    run = generate_annotations(runner, src, out, temp_root)
    assert run.errors and "invalid" in run.errors[0]
    assert not out.exists()


# --- _load_and_validate (defense-in-depth gate) --------------------------- #


def test_load_and_validate_accepts_minimal(tmp_path: Path):
    p = tmp_path / "a.json"
    p.write_text(
        json.dumps(
            {"static shapes": {}, "shape guards": [], "shape bindings": [], "type guards": []}
        ),
        encoding="utf-8",
    )
    assert _load_and_validate(p)["static shapes"] == {}


def test_load_and_validate_rejects_non_object(tmp_path: Path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ValueError, match="top level"):
        _load_and_validate(p)


def test_load_and_validate_rejects_missing_arrays(tmp_path: Path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"static shapes": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="shape guards"):
        _load_and_validate(p)
