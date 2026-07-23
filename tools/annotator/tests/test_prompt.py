"""Tests for the five-stage prompt and shared annotation-guide contract."""

from __future__ import annotations

from pathlib import Path

from annotator.prompt import (
    ABOUT_ANNOTATIONS_FILENAME,
    ABOUT_ANNOTATIONS_PATH,
    build_about_annotations_markdown,
    build_prompt,
)
from annotator.subagents_def import (
    ANNOTATE_CHUNK_AGENT,
    SHAPE_FACTS_CHUNK_AGENT,
    SHAPE_REVIEW_AGENT,
    UNDERSTAND_CHUNK_AGENT,
)


def test_about_annotations_explains_mechanism_schema_and_example():
    text = build_about_annotations_markdown()
    assert "Shape and type mechanisms" in text
    assert "write guard" in text
    assert "Annotation schema" in text
    assert "Worked example" in text
    assert '"type": "closure"' in text
    assert '"target function"' in text
    assert '"closure":' not in text


def test_all_agent_roles_read_the_shared_about_annotations_file():
    main = build_prompt(Path("input.js"))
    assert ABOUT_ANNOTATIONS_PATH in main
    assert ABOUT_ANNOTATIONS_PATH in UNDERSTAND_CHUNK_AGENT.prompt
    assert ABOUT_ANNOTATIONS_PATH in SHAPE_FACTS_CHUNK_AGENT.prompt
    assert ABOUT_ANNOTATIONS_PATH in ANNOTATE_CHUNK_AGENT.prompt
    assert ABOUT_ANNOTATIONS_PATH in SHAPE_REVIEW_AGENT.prompt
    assert ABOUT_ANNOTATIONS_FILENAME in main


def test_five_stages_and_roles_are_explicit():
    main = build_prompt(Path("input.js"))
    for marker in (
        "PHASE 1 — GENERAL UNDERSTANDING",
        "PHASE 2 — SHAPE FACTS",
        "PHASE 3 — CANONICAL STATIC SHAPES",
        "PHASE 4 — SOURCE ANNOTATIONS",
        "PHASE 5 — REVIEW AND CONVERGENCE",
    ):
        assert marker in main
    assert "understand-chunk" in main
    assert "shape-facts-chunk" in main
    assert "annotate-chunk" in main
    assert "shape-review" in main
    assert "spawn ONE" in main
    assert "EVERY final retained annotation" in main


def test_global_review_agent_owns_phase3_and_phase5():
    prompt = SHAPE_REVIEW_AGENT.prompt
    assert "PHASE 3 — CANONICAL STATIC SHAPES" in prompt
    assert "PHASE 5 — REVIEW AND CONVERGENCE" in prompt
    assert "static_shape" in prompt
    assert "EVERY final retained annotation" in prompt


def test_subagents_use_soft_responsibility_rules():
    assert "soft responsibility rule" in ANNOTATE_CHUNK_AGENT.prompt
    assert "do NOT add/delete" in UNDERSTAND_CHUNK_AGENT.prompt
    assert "Do NOT add/delete" in SHAPE_FACTS_CHUNK_AGENT.prompt
    assert "Do NOT create static shapes" in ANNOTATE_CHUNK_AGENT.prompt
    assert "list_annotations(kinds=[\"static_shape\"])" in ANNOTATE_CHUNK_AGENT.prompt
