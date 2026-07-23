"""Tests for atomic response publishing by the Jelly host services."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from annotator import priors_service


def _wait_for(calls: list[tuple[Path, dict[str, Any]]]) -> None:
    deadline = time.monotonic() + 2
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)
    assert calls


def test_callgraph_response_is_atomically_published(tmp_path: Path, monkeypatch):
    jelly = tmp_path / ".jelly"
    jelly.mkdir()
    (jelly / "req.json").write_text(json.dumps({"req_id": "callgraph", "rules": []}))
    published: list[tuple[Path, dict[str, Any]]] = []
    stop = threading.Event()

    def capture(path: Path, value: dict[str, Any]) -> None:
        published.append((path, value))
        stop.set()

    monkeypatch.setattr(priors_service, "atomic_write_json", capture)
    monkeypatch.setattr(priors_service, "_publish_output", lambda *_args: True)
    monkeypatch.setattr(
        priors_service,
        "_run",
        lambda *_args: {"req_id": "callgraph", "ok": True, "stderr": ""},
    )
    worker = threading.Thread(
        target=priors_service.serve,
        args=(tmp_path, "input.js", "jelly", stop),
        daemon=True,
    )
    worker.start()
    _wait_for(published)
    worker.join(timeout=1)

    assert published == [(jelly / "res.json", {"req_id": "callgraph", "ok": True, "stderr": ""})]


def test_dataflow_response_is_atomically_published(tmp_path: Path, monkeypatch):
    jelly = tmp_path / ".jelly"
    jelly.mkdir()
    (jelly / "df_req.json").write_text(
        json.dumps({"req_id": "dataflow", "source": "input.js:1:1:1:2", "direction": "both"})
    )
    published: list[tuple[Path, dict[str, Any]]] = []
    stop = threading.Event()

    def capture(path: Path, value: dict[str, Any]) -> None:
        published.append((path, value))
        stop.set()

    monkeypatch.setattr(priors_service, "atomic_write_json", capture)
    monkeypatch.setattr(
        priors_service,
        "_run_dataflow",
        lambda *_args: {"req_id": "dataflow", "ok": True, "stderr": ""},
    )
    worker = threading.Thread(
        target=priors_service.serve_dataflow,
        args=(tmp_path, "input.js", "jelly", stop),
        daemon=True,
    )
    worker.start()
    _wait_for(published)
    worker.join(timeout=1)

    assert published == [(jelly / "df_res.json", {"req_id": "dataflow", "ok": True, "stderr": ""})]
