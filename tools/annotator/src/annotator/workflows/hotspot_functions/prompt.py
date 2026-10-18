"""Coordinator prompt for exact hotspot-function annotation."""

from ...annotating_agent import WORKER_AGENT_NAME
from ...prompt import ABOUT_ANNOTATIONS_FILENAME, ABOUT_ANNOTATIONS_PATH
from .. import AnnotationRequest


def build_prompt(request: AnnotationRequest) -> str:
    if not request.targets:
        raise ValueError("hotspot-functions workflow requires at least one target")

    from ...tools import render_tool_sections

    tool_sections = render_tool_sections(list(request.enabled_tools), ())
    targets = "\n".join(f"- `{target}`" for target in request.targets)
    return f"""# Protocol (hotspot-functions workflow)

Before starting, Read `{ABOUT_ANNOTATIONS_PATH}`. The requested targets have
already been validated against the source function universe before Docker was
launched.

Targets (exact function loc_keys; EVERY one must end up covered):
{targets}

You are the coordinator. Each worker is a native `{WORKER_AGENT_NAME}`
subagent running in PARALLEL with the others; each owns one group of targets
and one annotation draft (name `hotspot:<n>`, assigned by you) — workers
cannot see each other's drafts.

1. Partition the targets into groups that belong together (same class, same
   call chain, or just a sensible batch — a single function is a group of
   one). Every target must appear in exactly one group.
2. Fan out ONE Task call per group, ALL IN ONE MESSAGE so they run in
   parallel (sequential messages run sequentially). Each Task call takes
   `subagent_type="{WORKER_AGENT_NAME}"` and its prompt passes:
   - the source file name: `{request.source_path.name}`
   - the group's exact function loc_keys
   - the draft name to work on: `hotspot:<n>` (n = 1, 2, 3... per group)
   Tell each worker its whole job is that group; it works until its
   checklist coverage is complete (uncovered == 0), so let it run — do not
   give it extra instructions.
3. Review each result's report. A worker's annotations live in its draft:
   `list_annotations(draft=...)` reads them live. A failed worker's targets
   simply have no annotation this round — report them; do not fabricate
   annotations.
4. When all workers are finished: call `save_annotations(draft=...)` for
   EVERY completed worker's draft (the `hotspot:<n>` names you assigned).
   Saving is YOUR job — the host ships whatever you saved; a draft you did
   not save is lost. Do not merge, do not write annotation JSON files by
   hand.

Read `./{request.source_path.name}` as needed to understand the targets; the
annotation work itself happens inside the workers.

Environment:
- Working directory: `/work`, containing `{request.source_path.name}` and
  `{ABOUT_ANNOTATIONS_FILENAME}`.

# Tool usage

- All enabled tools act on this one source file and have no `file` argument.
{"\n".join(tool_sections)}
"""


__all__ = ["build_prompt"]
