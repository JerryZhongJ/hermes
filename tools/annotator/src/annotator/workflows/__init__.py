"""Workflow registry: one self-contained package per annotation flow.

A ``WorkflowFactory`` is the blueprint for one flow: it carries the
declaration (prompt builder, required tools, target acceptance) and ``build``,
which constructs one runnable :class:`Workflow` — the container-entry agent,
the workflow's prompt, and its completion gates, all behind one ``run``
method. Each flow lives in its own package under ``workflows/`` owning
prompt + build side by side; adding a flow = adding a package + one
registry entry.

When a real multi-workflow pipeline need appears, add it then — with its
state handoff shaped by that need, not speculated now.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, Mapping  # noqa: F401 — Mapping re-exported

if TYPE_CHECKING:
    from ..agent import Agent

PromptBuilder = Callable[["AnnotationRequest"], str]


@dataclass(frozen=True)
class AnnotationRequest:
    """Inputs that select and parameterize one annotation run."""

    source_path: Path
    workflow: str = "annotate-hotspot-functions"
    targets: tuple[str, ...] = ()
    enabled_tools: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )


class Workflow:
    """One runnable workflow instance: run it, nothing else is public.

    The workflow OWNS its prompt (built at construction, from the workflow's
    own voice) and its completion gates (``next_prompt`` hooks — the natural
    home of e.g. whole-file coverage + saved product). Callers see only
    :meth:`run`, which forwards the status callbacks they own. The agent
    persists its own product (``save_annotations``); nothing is flushed or
    published by the host on its behalf.
    """

    def __init__(
        self,
        agent: "Agent",
        prompt: str,
        next_prompt: Callable[[Any], str | None] | None = None,
        append_prompt: str | None = None,
    ) -> None:
        self._agent = agent
        if append_prompt:
            prompt = prompt + "\n\n" + append_prompt
        self._prompt = prompt
        self._next_prompt = next_prompt

    def run(
        self,
        *,
        on_message: Callable[[object, str | None], None] | None = None,
        on_result: Callable[[Any], None] | None = None,
    ) -> Any:
        """Run the workflow's session to completion (blocking)."""
        return self._agent.run(
            self._prompt,
            on_message=on_message,
            on_result=on_result,
            next_prompt=self._next_prompt,
        )


# The build signature every workflow factory implements: given the run
# config dict and the bind-mount work root, produce the runnable Workflow
# (its prompt is the workflow's own business). The registry import stays
# tool-free.
Builder = Callable[[dict, Path], "Workflow"]


@dataclass(frozen=True)
class WorkflowFactory:
    """Factory for one annotation flow: declaration + ``build``."""

    name: str
    build_prompt: PromptBuilder
    required_tools: tuple[str, ...]
    # Whether the run takes --target-function loc_keys (hotspot workflows
    # do; whole-file workflows don't). Read by the CLI's validation, never
    # hardcoded against workflow names there.
    accepts_targets: bool = False
    build: Builder | None = None


from .annotate_file import ANNOTATE_FILE  # noqa: E402
from .file_parallel import ANNOTATE_FILE_PARALLEL  # noqa: E402
from .hotspot_functions import ANNOTATE_HOTSPOT_FUNCTIONS  # noqa: E402

WORKFLOW_REGISTRY: Mapping[str, WorkflowFactory] = MappingProxyType(
    {
        ANNOTATE_HOTSPOT_FUNCTIONS.name: ANNOTATE_HOTSPOT_FUNCTIONS,
        ANNOTATE_FILE.name: ANNOTATE_FILE,
        ANNOTATE_FILE_PARALLEL.name: ANNOTATE_FILE_PARALLEL,
    }
)


def get_workflow_factory(name: str) -> WorkflowFactory:
    """Resolve one registered workflow factory by workflow name."""
    try:
        return WORKFLOW_REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(WORKFLOW_REGISTRY))
        raise ValueError(
            f"unknown workflow {name!r}; available workflows: {available}"
        ) from None


def resolve_workflow_factory(name: str = "annotate-hotspot-functions") -> WorkflowFactory:
    """Worker-facing alias of :func:`get_workflow_factory`."""
    return get_workflow_factory(name)


__all__ = [
    "ANNOTATE_FILE",
    "ANNOTATE_FILE_PARALLEL",
    "ANNOTATE_HOTSPOT_FUNCTIONS",
    "AnnotationRequest",
    "Workflow",
    "WORKFLOW_REGISTRY",
    "WorkflowFactory",
    "get_workflow_factory",
    "resolve_workflow_factory",
]
