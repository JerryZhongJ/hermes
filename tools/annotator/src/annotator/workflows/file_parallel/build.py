"""Assembly for the annotate-file-parallel workflow: coordinator + merge gate.

The container-entry session is a coordinator that fans the file's chunks out
to native ``annotator-worker`` subagents (Task tool) — each owns one
``hotspot:<n>`` draft in the shared drafts store — then merges the workers'
drafts into one fixed draft (``main``) whose file-scope coverage gate — the
same one annotate-file uses — enforces the 100% whole-file criterion on the
MERGED document, not per worker. The product is the same ``main.json`` the
annotate-file pipeline promotes to ``--output``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...workflows import Workflow

from ...agent import Agent
from ...annotating_agent import WORKER_AGENT_NAME, coverage_followup_hook, worker_agent_definition
from ...tools import build_mcp_servers
from ..gates import compose_gates, saved_product_gate

LOGGER = logging.getLogger("file_parallel.build")

# The merged draft: the coordinator copies each worker's draft into it and
# the product gate expects it saved as main.json (the annotate-file contract).
DRAFT_NAME = "main"


def build(cfg: dict[str, Any], work: Path) -> "Workflow":
    """Build the parallel whole-file workflow: coordinator + coverage gate."""
    from ...workflows import Workflow
    from .. import AnnotationRequest
    from . import ANNOTATE_FILE_PARALLEL
    from .prompt import build_prompt

    source = work / cfg["source"]
    # The merged draft exists before the coordinator's first turn so its
    # tools (checklist/dryrun/copy_annotations) can address it immediately.
    from ...annotation_drafts import drafts

    if not drafts().has(DRAFT_NAME):
        drafts().add(DRAFT_NAME)
    agent = Agent(
        "coordinator",
        cwd=str(work),
        # Open draft access: the coordinator reads and merges the drafts of
        # workers it launched, whose names it assigns at fan-out time.
        mcp_servers=build_mcp_servers(
            source,
            work,
            None,
            cfg.get("enabled_tools"),
            ANNOTATE_FILE_PARALLEL.required_tools,
        ),
        agents={WORKER_AGENT_NAME: worker_agent_definition()},
        model=cfg.get("model"),
        settings=cfg.get("claude_settings"),
        stderr=LOGGER.error,
    )
    request = AnnotationRequest(
        source_path=source,
        workflow="annotate-file-parallel",
        enabled_tools=tuple(cfg.get("enabled_tools") or ()),
        targets=tuple(cfg.get("targets") or ()),
        metadata=cfg.get("metadata") or {},
    )
    # The gate chain: whole-file coverage of the MERGED draft (host-measured
    # follow-ups while uncovered sites remain) + the saved-product check —
    # the same composition annotate-file runs, on the same fixed draft.
    return Workflow(
        agent=agent,
        prompt=build_prompt(request),
        append_prompt=cfg.get("append_prompt"),
        next_prompt=compose_gates(
            coverage_followup_hook(work, source, DRAFT_NAME, "file"),
            saved_product_gate(work, DRAFT_NAME),
        ),
    )


__all__ = ["DRAFT_NAME", "build"]
