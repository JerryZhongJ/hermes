"""Hotspot-function annotation workflow: coordinator + native worker subagents."""


from .. import WorkflowFactory
from .build import build
from .prompt import build_prompt

# The coordinator fans work out to native ``annotator-worker`` subagents
# (Task tool): each owns one target group and one ``hotspot:<n>`` draft in
# the shared drafts store — no per-job workdir, no launch MCP.
ANNOTATE_HOTSPOT_FUNCTIONS = WorkflowFactory(
    name="annotate-hotspot-functions",
    build_prompt=build_prompt,
    required_tools=("dryrun",),
    accepts_targets=True,
    build=build,
)

__all__ = [
    "ANNOTATE_HOTSPOT_FUNCTIONS",
    "build_prompt",
]
