from __future__ import annotations

import json
from pathlib import Path

import pytest

from annotator.config import (
    AgentConfig,
    effective_config,
    load_config,
    parse_args,
    validate_workflow_targets,
)


def _config(**updates: object) -> AgentConfig:
    values: dict[str, object] = {"agent": "claude"}
    values.update(updates)
    return AgentConfig.model_validate(values)


def _executable(tmp_path: Path) -> Path:
    path = tmp_path / "shermes"
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_config_defaults_to_hotspot_workflow():
    assert _config().workflow == "annotate-hotspot-functions"


def test_load_config_rejects_unknown_workflow(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"agent": "claude", "workflow": "missing"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown workflow 'missing'"):
        load_config(path)


def test_cli_workflow_selects_and_targets_repeat(tmp_path: Path):
    base = [
        str(tmp_path / "in.js"),
        "-o",
        str(tmp_path / "out.json"),
        "--config",
        str(tmp_path / "config.json"),
    ]
    # --workflow defaults to the hotspot flow and selects annotate-file.
    assert parse_args(base).workflow == "annotate-hotspot-functions"
    args = parse_args(
        [
            *base,
            "--workflow",
            "annotate-file",
            "--target-function",
            "1:1:2:2",
            "--target-function",
            "3:1:4:2",
        ]
    )
    assert args.workflow == "annotate-file"
    assert args.target_function == ["1:1:2:2", "3:1:4:2"]


def test_workflow_override_updates_effective_config():
    effective = effective_config(
        _config(workflow="annotate-hotspot-functions"),
        workflow_override="annotate-file",
    )
    assert effective.workflow == "annotate-file"


def test_validate_hotspot_targets_exact_deduplicated(tmp_path: Path):
    source = tmp_path / "input.js"
    source.write_text("function f() {}\nfunction g() {}\n", encoding="utf-8")
    from annotator.tools.functions import extract_functions

    functions = extract_functions(source.read_bytes())
    targets = [functions[1]["loc_key"], functions[0]["loc_key"], functions[1]["loc_key"]]
    assert validate_workflow_targets("annotate-hotspot-functions", targets, source) == (
        functions[1]["loc_key"],
        functions[0]["loc_key"],
    )
    with pytest.raises(ValueError, match="not found exactly"):
        validate_workflow_targets("annotate-hotspot-functions", ["1:1:1:2"], source)


def test_validate_workflow_target_rules(tmp_path: Path):
    source = tmp_path / "input.js"
    source.write_text("function f() {}", encoding="utf-8")
    with pytest.raises(ValueError, match="requires at least one"):
        validate_workflow_targets("annotate-hotspot-functions", [], source)
    with pytest.raises(ValueError, match="unknown workflow"):
        validate_workflow_targets("full", ["1:1:2:2"], source)


