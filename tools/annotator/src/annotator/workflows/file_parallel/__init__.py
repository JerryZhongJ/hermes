"""Parallel whole-file annotation workflow: chunked fan-out + merged gate."""


from .. import WorkflowFactory
from .build import build
from .prompt import build_prompt

# The coordinator fans chunks out to native ``annotator-worker`` subagents
# (Task tool) and merges their ``hotspot:<n>`` drafts into ``main``.
ANNOTATE_FILE_PARALLEL = WorkflowFactory(
    name="annotate-file-parallel",
    build_prompt=build_prompt,
    required_tools=("dryrun", "checklist"),
    accepts_targets=False,
    build=build,
)

__all__ = [
    "ANNOTATE_FILE_PARALLEL",
    "build_prompt",
]
