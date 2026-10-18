"""Tests for the container worker: config validation, assembly dispatch, main."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import annotator.agent_worker as aw
from annotator.agent import Agent, RunOutcome


@pytest.fixture(autouse=True)
def _worker_paths(tmp_path, monkeypatch):
    """Redirect the worker's paths to a temp dir so tests stay hermetic."""
    monkeypatch.setattr(aw, "WORK", tmp_path)
    monkeypatch.setattr(aw, "WORKER_STATUS_FILE", tmp_path / ".worker_status.json")
    yield


def _source(tmp_path: Path, text: str = "function f(o) { return o.x + 1; }") -> Path:
    source = tmp_path / "input.js"
    source.write_text(text, encoding="utf-8")
    return source


# --- config validation ---------------------------------------------------------- #


def test_validate_config_resolves_factory_and_targets(tmp_path: Path):
    from annotator.workflows import ANNOTATE_HOTSPOT_FUNCTIONS

    source = _source(tmp_path)
    factory, targets = aw.validate_config(
        {
            "source": source.name,
            "model": None,
            "workflow": "annotate-hotspot-functions",
            "targets": ["1:1:1:28", "1:1:1:28"],
        },
        tmp_path,
    )
    assert factory is ANNOTATE_HOTSPOT_FUNCTIONS
    assert targets == ("1:1:1:28",)


def test_validate_config_requires_source_file(tmp_path: Path):
    with pytest.raises(RuntimeError, match="missing 'source'"):
        aw.validate_config({"model": None}, tmp_path)
    with pytest.raises(RuntimeError, match="not found in workspace"):
        aw.validate_config({"source": "gone.js"}, tmp_path)


def test_validate_config_rejects_unknown_workflow(tmp_path: Path):
    source = _source(tmp_path)
    with pytest.raises(RuntimeError, match="unknown workflow"):
        aw.validate_config({"source": source.name, "workflow": "missing"}, tmp_path)


def test_validate_config_target_rules(tmp_path: Path):
    source = _source(tmp_path)
    # hotspot without targets: rejected
    with pytest.raises(RuntimeError, match="requires target functions"):
        aw.validate_config(
            {"source": source.name, "workflow": "annotate-hotspot-functions"},
            tmp_path,
        )
    # annotate-file with targets: rejected
    with pytest.raises(RuntimeError, match="does not accept target"):
        aw.validate_config(
            {
                "source": source.name,
                "workflow": "annotate-file",
                "targets": ["1:1:1:28"],
            },
            tmp_path,
        )


# --- workflow build dispatch ---------------------------------------------------- #


def test_annotate_file_builds_annotator_agent_with_followup(tmp_path: Path):
    """Whole-file mode: the main agent IS the shared annotator agent (named
    'annotator'), with dryrun+checklist+annotations MCP servers — and the
    whole-file completion gate (coverage + saved main.json) as its private
    next_prompt. The workflow owns its prompt; only run() is public."""
    from annotator.annotation_drafts import drafts

    drafts().clear()
    source = _source(tmp_path)
    factory = aw.validate_config(
        {"source": source.name, "model": None, "workflow": "annotate-file"},
        tmp_path,
    )[0]
    workflow = factory.build({"source": source.name, "model": None}, tmp_path)
    # The workflow encapsulates everything; only run() is public.
    assert not hasattr(workflow, "agent")
    assert not hasattr(workflow, "next_prompt")
    assert hasattr(workflow, "run")
    drafts().clear()


def test_hotspot_workflow_builds_coordinator(tmp_path: Path):
    """Hotspot mode: the coordinator agent with its worker subagent
    definition and the saved-products gate (at least one hotspot:*.json);
    only run() is public."""
    from annotator.annotation_drafts import drafts

    drafts().clear()
    source = _source(tmp_path)
    target = "1:1:1:28"
    factory = aw.validate_config(
        {
            "source": source.name,
            "model": None,
            "workflow": "annotate-hotspot-functions",
            "targets": [target],
        },
        tmp_path,
    )[0]
    workflow = factory.build(
        {
            "source": source.name,
            "model": None,
            "targets": [target],
        },
        tmp_path,
    )
    assert hasattr(workflow, "run")
    assert not hasattr(workflow, "agent")
    assert not hasattr(workflow, "next_prompt")
    drafts().clear()


# --- main() plumbing ------------------------------------------------------------ #


def _point_at_workflow(tmp_path, monkeypatch, built, config):
    """Point the worker at a fake workflow whose build returns ``built``."""
    from annotator.workflows import WorkflowFactory

    monkeypatch.setattr(aw, "CONFIG_FILE", tmp_path / ".agent_config.json")
    (tmp_path / ".agent_config.json").write_text(
        json.dumps(config), encoding="utf-8"
    )
    fake = WorkflowFactory(
        name=config["workflow"],
        build_prompt=lambda request: "p",
        required_tools=(),
        build=lambda *a: built,
    )
    monkeypatch.setattr(aw, "resolve_workflow_factory", lambda name: fake)


def test_main_runs_session_and_completes(tmp_path, monkeypatch):
    """Successful run: the session runs with the workflow's private gate."""
    source = _source(tmp_path)
    ran = []
    agent = Agent("agent", cwd=".", mcp_servers={})

    def fake_run(prompt, **kwargs):
        ran.append((prompt, kwargs.get("next_prompt") is not None))
        return RunOutcome(session_id="session")

    agent.run = fake_run  # type: ignore[method-assign]

    from annotator.workflows import Workflow

    built = Workflow(agent=agent, prompt="p", next_prompt=lambda _r: None)
    _point_at_workflow(
        tmp_path, monkeypatch, built,
        {"source": source.name, "model": None, "workflow": "annotate-file"},
    )
    assert aw.main() == 0
    assert ran == [("p", True)]  # the workflow's own prompt reached the agent
    status = json.loads(
        (tmp_path / ".worker_status.json").read_text(encoding="utf-8")
    )
    assert status["completed"] is True


def test_main_failure_reports_error(tmp_path, monkeypatch):
    source = _source(tmp_path)
    agent = Agent("agent", cwd=".", mcp_servers={})

    def failing_run(prompt, **kwargs):
        return RunOutcome(session_id=None, ok=False, error="RuntimeError: boom")

    agent.run = failing_run  # type: ignore[method-assign]

    from annotator.workflows import Workflow

    built = Workflow(agent=agent, prompt="p", next_prompt=None)
    _point_at_workflow(
        tmp_path, monkeypatch, built,
        {"source": source.name, "model": None, "workflow": "annotate-file"},
    )
    assert aw.main() == 1
    status = json.loads(
        (tmp_path / ".worker_status.json").read_text(encoding="utf-8")
    )
    assert status["completed"] is False
    assert any("boom" in error for error in status["errors"])
