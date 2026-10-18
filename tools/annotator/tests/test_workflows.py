from __future__ import annotations

from pathlib import Path

import pytest

from annotator.workflows import (
    ANNOTATE_FILE,
    ANNOTATE_FILE_PARALLEL,
    ANNOTATE_HOTSPOT_FUNCTIONS,
    WORKFLOW_REGISTRY,
    AnnotationRequest,
    get_workflow_factory,
    resolve_workflow_factory,
)


def test_annotation_request_defaults_to_hotspot_workflow():
    request = AnnotationRequest(source_path=Path("input.js"))
    assert request.workflow == "annotate-hotspot-functions"
    assert request.targets == ()


def test_registry_contains_both_workflows():
    assert set(WORKFLOW_REGISTRY) == {
        "annotate-hotspot-functions",
        "annotate-file",
        "annotate-file-parallel",
    }


def test_resolver_is_a_pure_workflow_lookup():
    assert get_workflow_factory("annotate-file") is ANNOTATE_FILE
    assert resolve_workflow_factory("annotate-hotspot-functions") is ANNOTATE_HOTSPOT_FUNCTIONS
    # The old pipeline/alias selectors are gone: they resolve as unknown
    # workflows with the registry listing the real names.
    with pytest.raises(ValueError, match="unknown workflow 'target-function'"):
        get_workflow_factory("target-function")
    with pytest.raises(ValueError, match="unknown workflow 'hotspot-functions'"):
        resolve_workflow_factory("hotspot-functions")


def test_hotspot_workflow_prompt_and_agent_contract():
    factory = ANNOTATE_HOTSPOT_FUNCTIONS
    # Targets run as native annotator-worker subagents fanned out with the
    # Task tool — the coordinator delegates and saves, nothing else.
    assert factory.required_tools == ("dryrun",)
    assert factory.build is not None
    request = AnnotationRequest(
        source_path=Path("input.js"),
        workflow="annotate-hotspot-functions",
        targets=("1:1", "3:1"),
    )
    prompt = factory.build_prompt(request)
    # The fan-out instruction: Task tool, one message, worker subagent type.
    assert 'subagent_type="annotator-worker"' in prompt
    assert "ALL IN ONE MESSAGE" in prompt
    assert "PARALLEL" in prompt
    # Each Task prompt passes the draft contract name and the targets.
    assert "hotspot:<n>" in prompt
    assert "1:1" in prompt and "3:1" in prompt
    # The coordinator partitions targets into groups itself.
    assert "Partition the targets" in prompt
    # The coordinator's own job is saving the workers' drafts.
    assert "save_annotations" in prompt


def test_hotspot_stage_prompt_requires_targets():
    with pytest.raises(ValueError, match="at least one target"):
        ANNOTATE_HOTSPOT_FUNCTIONS.build_prompt(
            AnnotationRequest(
                source_path=Path("input.js"),
                workflow="annotate-hotspot-functions",
            )
        )


def test_unknown_workflow_lists_registered_names():
    with pytest.raises(ValueError, match="unknown workflow 'missing'") as exc:
        get_workflow_factory("missing")
    assert "annotate-hotspot-functions" in str(exc.value)
    assert "annotate-file" in str(exc.value)


# --- annotate-file (whole-file) workflow ----------------------------------- #


def test_annotate_file_workflow_contract():
    factory = ANNOTATE_FILE
    # One plain single-draft agent — no coordinator fan-out, no targets.
    assert factory.required_tools == ("dryrun", "checklist")
    assert factory.accepts_targets is False
    assert factory.build is not None
    prompt = factory.build_prompt(AnnotationRequest(source_path=Path("input.js")))
    assert 'scope="file"' in prompt
    assert "list_checklist" in prompt
    assert "uncovered" in prompt
    assert "do not split work into subagents" in prompt
    assert "hotspot" not in prompt


def test_annotate_file_rejects_target_functions(tmp_path: Path):
    from annotator.config import validate_workflow_targets

    source = tmp_path / "input.js"
    source.write_text("function f() {}", encoding="utf-8")
    with pytest.raises(ValueError, match="does not accept target"):
        validate_workflow_targets("annotate-file", ["1:1"], source)


# --- the annotate-file workflow's product gate ------------------------------- #


def test_saved_product_gate_blocks_until_main_json_exists(tmp_path: Path):
    from annotator.workflows.annotate_file.build import saved_product_gate

    gate = saved_product_gate(tmp_path, "main", max_followups=2)
    # Nothing saved: one more turn (the save reminder).
    prompt = gate(object())
    assert prompt is not None and "save_annotations" in prompt
    # Still nothing saved, budget left: one more turn.
    assert gate(object()) is not None
    # Budget exhausted: the session ends regardless.
    assert gate(object()) is None


def test_saved_product_gate_passes_once_saved(tmp_path: Path):
    from annotator.workflows.annotate_file.build import saved_product_gate

    gate = saved_product_gate(tmp_path, "main")
    (tmp_path / "main.json").write_text("{}", encoding="utf-8")
    assert gate(object()) is None


def test_compose_gates_joins_prompts_and_ends_when_all_do():
    from annotator.workflows.annotate_file.build import compose_gates

    calls = {"a": 0, "b": 0}

    def gate_a(_r):
        calls["a"] += 1
        return "A: keep going" if calls["a"] < 2 else None

    def gate_b(_r):
        calls["b"] += 1
        return "B: save now"

    composed = compose_gates(gate_a, gate_b)
    # Both gates have prompts: joined, A's first.
    prompt = composed(object())
    assert prompt == "A: keep going\n\nB: save now"
    # A done, B still prompting: B's prompt alone goes out.
    assert composed(object()) == "B: save now"
    # All gates done: the session ends.
    def gate_c(_r):
        return None
    assert compose_gates(gate_c, gate_c)(object()) is None


# --- annotate-file-parallel (chunked whole-file) workflow ------------------- #


def test_annotate_file_parallel_workflow_contract():
    factory = ANNOTATE_FILE_PARALLEL
    assert factory.required_tools == ("dryrun", "checklist")
    assert factory.accepts_targets is False
    assert factory.build is not None
    prompt = factory.build_prompt(
        AnnotationRequest(source_path=Path("input.js"))
    )
    # Chunked Task-tool fan-out to worker subagents, ~200-line guidance.
    assert 'subagent_type="annotator-worker"' in prompt
    assert "ALL IN ONE MESSAGE" in prompt
    assert "200" in prompt
    assert "hotspot:<n>" in prompt
    # The merge step: annotations AND reasons copy into the fixed main draft,
    # conflicts resolved by the coordinator, whole-file coverage gate on the
    # merged document.
    assert "copy_annotations" in prompt
    assert "copy_reasons" in prompt
    assert 'draft="main"' in prompt
    assert "exactly one chunk" in prompt
    assert "uncovered" in prompt
    # Partitioning semantics: nested functions are independent chunk entries,
    # and module-level code is addressed by the explicit top-level scope.
    assert "DIRECT statements" in prompt
    assert "its own" in prompt and "loc_key" in prompt
    assert '"<top-level>"' in prompt


def test_parallel_workflows_register_the_worker_subagent(tmp_path, monkeypatch):
    """Both parallel workflows build a coordinator carrying the
    ``annotator-worker`` AgentDefinition (the native Task-tool fan-out)."""
    from annotator.agent import Agent
    from annotator.annotating_agent import WORKER_AGENT_NAME, worker_agent_definition

    source = tmp_path / "input.js"
    source.write_text("function f() {}\n", encoding="utf-8")

    definition = worker_agent_definition()
    # The worker protocol is self-contained: explicit draft passing and the
    # uncovered==0 completion criterion (no host-side follow-up hook).
    assert "summary.uncovered" in definition.prompt
    assert "create_draft" in definition.prompt
    # Scope ownership is innermost: nested functions outside the chunk list
    # are not the worker's to cover.
    assert "independent scopes" in definition.prompt

    captured: list[dict] = []

    def _capture(self, *args, **kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(Agent, "__init__", _capture)
    from annotator.annotation_drafts import drafts

    for name, extra in (
        ("annotate-file-parallel", {}),
        ("annotate-hotspot-functions", {"targets": ["1:1"]}),
    ):
        drafts().clear()
        factory = resolve_workflow_factory(name)
        factory.build({"model": None, "source": source.name, **extra}, tmp_path)
    drafts().clear()

    assert captured, "no coordinator was built"
    for kwargs in captured:
        agents = kwargs.get("agents") or {}
        assert WORKER_AGENT_NAME in agents
        assert agents[WORKER_AGENT_NAME].prompt == definition.prompt


def test_annotate_file_parallel_rejects_target_functions(tmp_path: Path):
    from annotator.config import validate_workflow_targets

    source = tmp_path / "input.js"
    source.write_text("function f() {}", encoding="utf-8")
    with pytest.raises(ValueError, match="does not accept target"):
        validate_workflow_targets("annotate-file-parallel", ["1:1"], source)


# --- the coordinator's saved-products gate ---------------------------------- #


def test_saved_products_gate_blocks_until_a_draft_is_saved(tmp_path: Path):
    from annotator.workflows.hotspot_functions.build import saved_products_gate

    gate = saved_products_gate(tmp_path, max_followups=2)
    # Nothing saved: one more turn (the save reminder).
    prompt = gate(object())
    assert prompt is not None and "save_annotations" in prompt
    # Still nothing saved, budget left: one more turn.
    assert gate(object()) is not None
    # Budget exhausted: the session ends regardless.
    assert gate(object()) is None


def test_saved_products_gate_passes_once_saved(tmp_path: Path):
    from annotator.workflows.hotspot_functions.build import saved_products_gate

    gate = saved_products_gate(tmp_path)
    (tmp_path / "hotspot:1_1_2_2-abc.json").write_text("{}", encoding="utf-8")
    assert gate(object()) is None


def test_worker_definition_crosses_the_sdk_serialization_boundary():
    """client.py turns each AgentDefinition into a plain dict via asdict();
    anything the worker definition carries must survive that (and JSON)."""
    import json
    from dataclasses import asdict

    from annotator.annotating_agent import worker_agent_definition

    payload = {
        k: v for k, v in asdict(worker_agent_definition()).items() if v is not None
    }
    # What initialize's agents field receives: JSON-safe scalars only.
    assert set(payload) == {"description", "prompt", "model"}
    json.dumps(payload)  # no in-process instances leaked into the payload
    assert payload["model"] == "inherit"
