"""Assembly for the annotate-file workflow: one annotator agent.

The whole flow in one session: the workflow's main agent IS the shared
annotator agent (see :mod:`annotator.annotating_agent`) with scope "file".
The annotator's own job is full checklist coverage; the WORKFLOW's completion
gate composes two conditions — the annotator's coverage follow-up hook AND
the saved product (``main.json`` in the run workdir, written by the agent's
own ``save_annotations``). Nothing is ever flushed on the agent's behalf.
The workflow owns its prompt (the package's ``build_prompt``) — callers only
see ``run``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...workflows import Workflow

from ...annotating_agent import build_annotating_agent, coverage_followup_hook
from ..gates import compose_gates, saved_product_gate
from .prompt import build_prompt

LOGGER = logging.getLogger("annotate_file.build")

# The fixed draft name: save_annotations persists it as main.json, which the
# host pipeline promotes to --output. A fixed name (not a unique one) is the
# product contract between agent, gate, and host.
DRAFT_NAME = "main"


def build(cfg: dict[str, Any], work: Path) -> "Workflow":
    """Build the whole-file annotator workflow: agent + prompt + gate."""
    from ...workflows import Workflow
    from .. import AnnotationRequest

    source = work / cfg["source"]
    agent, draft_name = build_annotating_agent(
        "file",
        work,
        source,
        draft_name=DRAFT_NAME,
        enabled_tools=cfg.get("enabled_tools"),
        model=cfg.get("model"),
        settings=cfg.get("claude_settings"),
        stderr=LOGGER.error,
    )
    # The workflow's prompt (its own voice) replaces the generic annotator
    # one: the agent construction is shared, the prompt is per-flow.
    request = AnnotationRequest(
        source_path=source,
        workflow="annotate-file",
        enabled_tools=tuple(cfg.get("enabled_tools") or ()),
        targets=tuple(cfg.get("targets") or ()),
        metadata=cfg.get("metadata") or {},
    )
    prompt = build_prompt(request)
    # The workflow's gate: the annotator's coverage criterion plus the
    # workflow's own product check.
    return Workflow(
        agent=agent,
        prompt=prompt,
        append_prompt=cfg.get("append_prompt"),
        next_prompt=compose_gates(
            coverage_followup_hook(work, source, draft_name, "file"),
            saved_product_gate(work, draft_name),
        ),
    )


__all__ = ["DRAFT_NAME", "build"]
