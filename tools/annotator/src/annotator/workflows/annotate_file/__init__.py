"""Whole-file annotation workflow: one agent, the entire file's checklist."""


from .. import WorkflowFactory
from ..gates import compose_gates, saved_product_gate  # noqa: F401 — re-export
from .build import build
from .prompt import build_prompt

# One plain single-draft agent assembled by the worker — no native subagents.
ANNOTATE_FILE = WorkflowFactory(
    name="annotate-file",
    build_prompt=build_prompt,
    required_tools=("dryrun", "checklist"),
    accepts_targets=False,
    build=build,
)

__all__ = [
    "ANNOTATE_FILE",
    "build_prompt",
    "compose_gates",
    "saved_product_gate",
]
