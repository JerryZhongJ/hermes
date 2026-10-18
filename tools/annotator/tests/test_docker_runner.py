from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from annotator.workflows import AnnotationRequest
from annotator.docker_runner import (
    CLAUDE_CONFIG_DIR,
    CONTAINER_CLAUDE_CONFIG,
    DockerRunner,
)


def _runner() -> DockerRunner:
    config = SimpleNamespace(
        docker_image=None,
        enabled_tools=None,
        workflow="annotate-hotspot-functions",
        model=None,
        claude_settings=None,
    )
    return DockerRunner(config, timeout_seconds=10)  # type: ignore[arg-type]


def test_find_trace_discovers_native_session(tmp_path: Path):
    main = tmp_path / CLAUDE_CONFIG_DIR / "projects" / "-work" / "session.jsonl"
    main.parent.mkdir(parents=True)
    main.write_text("{}\n", encoding="utf-8")
    trace = _runner()._find_trace(tmp_path)
    assert trace is not None
    assert trace.main == main
    assert trace.session_id == "session"


def test_find_trace_prefers_recorded_session_id(tmp_path: Path):
    projects = tmp_path / CLAUDE_CONFIG_DIR / "projects" / "-work"
    projects.mkdir(parents=True)
    wanted = projects / "wanted.jsonl"
    wanted.write_text("{}\n", encoding="utf-8")
    (projects / "stale.jsonl").write_text("{}\n", encoding="utf-8")
    trace = _runner()._find_trace(tmp_path, session_id="wanted")
    assert trace is not None and trace.session_id == "wanted"


def test_read_worker_status_returns_session_id(tmp_path: Path):
    (tmp_path / ".worker_status.json").write_text(
        '{"completed": false, "errors": [], "session_id": "abc"}', encoding="utf-8"
    )
    errors, completed, session_id = _runner()._read_worker_status(tmp_path)
    assert (errors, completed, session_id) == ([], False, "abc")


def test_config_payload_includes_default_workflow(tmp_path: Path):
    runner = _runner()
    runner._write_config(
        tmp_path,
        "input.js",
        AnnotationRequest(source_path=Path("input.js")),
    )
    import json

    payload = json.loads((tmp_path / ".agent_config.json").read_text(encoding="utf-8"))
    assert payload["workflow"] == "annotate-hotspot-functions"
    assert payload["targets"] == []


def test_config_payload_includes_hotspot_targets(tmp_path: Path):
    runner = _runner()
    runner._write_config(
        tmp_path,
        "input.js",
        AnnotationRequest(
            source_path=Path("input.js"),
            workflow="annotate-hotspot-functions",
            targets=("1:1:2:2",),
        ),
    )
    import json

    payload = json.loads((tmp_path / ".agent_config.json").read_text(encoding="utf-8"))
    assert payload["workflow"] == "annotate-hotspot-functions"
    assert payload["targets"] == ["1:1:2:2"]


def test_container_mounts_isolated_claude_config(tmp_path: Path, monkeypatch):
    claude_config = tmp_path / CLAUDE_CONFIG_DIR
    claude_config.mkdir()
    config = SimpleNamespace(
        docker_image=None,
        enabled_tools=None,
        workflow="annotate-hotspot-functions",
        model=None,
        claude_settings=None,
    )
    runner = DockerRunner(config, timeout_seconds=10)  # type: ignore[arg-type]
    captured: list[str] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.extend(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("annotator.docker_runner.subprocess.run", fake_run)
    captured_setup: dict[str, object] = {}

    def fake_setups(*args: object) -> list[object]:
        captured_setup["required_tools"] = args[-1]
        return []

    monkeypatch.setattr("annotator.docker_runner.run_host_setups", fake_setups)
    runner._run_container(
        tmp_path,
        "/tmp/env",
        "input.js",
        AnnotationRequest(source_path=Path("input.js")),
    )

    assert f"{claude_config}:{CONTAINER_CLAUDE_CONFIG}" in captured
    assert f"CLAUDE_CONFIG_DIR={CONTAINER_CLAUDE_CONFIG}" in captured
    assert captured_setup["required_tools"] == ("dryrun",)
