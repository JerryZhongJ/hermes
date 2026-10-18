"""Assembly for the hotspot-functions workflow: the coordinator agent.

The container worker calls this with the host-staged config; it builds the
coordinator plus the ``annotator-worker`` subagent definition it fans out
with the Task tool. The workers share the coordinator's process-wide drafts
store (each owns one ``hotspot:<n>`` draft) and workdir; the coordinator
saves every completed draft (``hotspot:<n>.json`` — the host pipeline's
product pickup).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...workflows import Workflow

from ...agent import Agent
from ...annotating_agent import WORKER_AGENT_NAME, worker_agent_definition
from ...tools import build_mcp_servers

LOGGER = logging.getLogger("hotspot_functions.build")


def saved_products_gate(work: Path, max_followups: int = 3):
    """The coordinator's completion gate: a saved product ends the session.

    The coordinator's product is at least one saved hotspot draft
    (``hotspot:*.json`` at the workdir root, written by ``save_annotations``).
    An unsaved-turn gets one more prompt reminding it to save; after
    ``max_followups`` the session ends regardless (the run report then shows
    the missing product).
    """

    def _gate(_result) -> str | None:
        if any(work.glob("hotspot:*.json")):
            return None
        nonlocal max_followups
        if max_followups <= 0:
            return None
        max_followups -= 1
        return (
            "Product check after your turn: no hotspot draft is saved yet "
            "(no `hotspot:*.json` in the workdir) — an unsaved draft is not "
            "a product, and the host ships only what you saved. Call "
            "`save_annotations(draft=...)` for every completed worker's draft "
            "now, then finish."
        )

    return _gate


def build(cfg: dict[str, Any], work: Path) -> "Workflow":
    """Build the coordinator workflow: agent + prompt + product gate."""
    from ...workflows import Workflow
    from .. import AnnotationRequest
    from . import ANNOTATE_HOTSPOT_FUNCTIONS
    from .prompt import build_prompt

    source = work / cfg["source"]
    agent = Agent(
        "coordinator",
        cwd=str(work),
        # Open draft access: the coordinator reads and saves the workers'
        # drafts, whose names (one per target group it chose) are only known
        # after the fan-out.
        mcp_servers=build_mcp_servers(
            source,
            work,
            None,
            cfg.get("enabled_tools"),
            ANNOTATE_HOTSPOT_FUNCTIONS.required_tools,
        ),
        agents={WORKER_AGENT_NAME: worker_agent_definition()},
        model=cfg.get("model"),
        settings=cfg.get("claude_settings"),
        stderr=LOGGER.error,
    )
    # The workflow owns its prompt (the coordinator protocol).
    request = AnnotationRequest(
        source_path=source,
        workflow="annotate-hotspot-functions",
        enabled_tools=tuple(cfg.get("enabled_tools") or ()),
        targets=tuple(cfg.get("targets") or ()),
        metadata=cfg.get("metadata") or {},
    )
    # The coordinator's own completion gate: the session may not end until
    # at least one hotspot draft is saved (the run otherwise produced no
    # product). The workers are Task-tool subagents — none outlives the
    # coordinator session.
    return Workflow(
        agent=agent,
        prompt=build_prompt(request),
        append_prompt=cfg.get("append_prompt"),
        next_prompt=saved_products_gate(work),
    )


__all__ = ["build"]
