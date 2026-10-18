"""Coordinator prompt for the parallel whole-file annotation workflow."""

from ...annotating_agent import WORKER_AGENT_NAME
from ...prompt import ABOUT_ANNOTATIONS_FILENAME, ABOUT_ANNOTATIONS_PATH
from .build import DRAFT_NAME
from .. import AnnotationRequest


def build_prompt(request: AnnotationRequest) -> str:
    from ...tools import render_tool_sections

    tool_sections = render_tool_sections(list(request.enabled_tools), ())
    return f"""# Protocol (annotate-file-parallel workflow)

Before starting, Read `{ABOUT_ANNOTATIONS_PATH}`. You own the ENTIRE file:
every function and the module-level code must end up optimized or carry a
recorded reason in ONE merged annotation document.

You are the coordinator. Each worker is a native `{WORKER_AGENT_NAME}`
subagent running in PARALLEL with the others; each owns one chunk of the
file and one annotation draft (name `hotspot:<n>`, assigned by you) —
workers cannot see each other's drafts.

1. Read `{request.source_path.name}` (use `fold` for structure) and PARTITION
   the whole file into chunks of function loc_keys: group functions that
   belong together (same class, same call chain, or just a contiguous batch)
   and keep each chunk around 500 source lines. This is guidance, not a hard
   limit — use your judgment; a class that splits awkwardly may be one chunk,
   tiny helpers may share one. EVERY part of the file must
   appear in exactly one chunk — remember each function loc_key stands for
   that function's DIRECT statements only: a nested function has its own
   loc_key and must appear as its own chunk entry (assigning an outer
   function does NOT cover its nested functions). Send the module-level code
   (top-level statements outside every function) as one chunk of its own,
   addressed as the scope `"<top-level>"`.
2. Fan out ONE Task call per chunk, ALL IN ONE MESSAGE so they run in
   parallel (sequential messages run sequentially). Each Task call takes
   `subagent_type="{WORKER_AGENT_NAME}"` and its prompt passes:
   - the source file name: `{request.source_path.name}`
   - the chunk's exact function loc_keys (for the module-level chunk: the
     scope `"<top-level>"`)
   - the draft name to work on: `hotspot:<n>` (n = 1, 2, 3... per chunk)
   Tell each worker its whole job is that chunk; it works until its
   checklist coverage is complete (uncovered == 0), so let it run — do not
   give it extra instructions.
3. Review each result's report. A failed worker's chunk simply has no
   annotations this round — rerun that chunk once (a fresh Task call, new
   draft name `hotspot:<m>`); if it fails again, report it and continue.
4. The 100% coverage criterion is enforced INSIDE each worker: it keeps
   working its own scope's checklist until every item is optimized or
   carries a recorded reason.
5. MERGE. For each completed worker's draft, in any order, call BOTH
   `copy_annotations(source=..., dest="{DRAFT_NAME}")` (annotations; the
   copy is ALL OR NOTHING — on any conflict NOTHING is applied and every
   conflict is reported: resolve it on YOUR draft with `update_annotation` /
   `delete_annotation`, then retry the copy) and
   `copy_reasons(source=..., dest="{DRAFT_NAME}")` (the worker's recorded
   not-optimized reasons). After all copies succeed, re-check with
   `list_checklist(scope="file", only_uncovered=true, draft="{DRAFT_NAME}")`
   (the file view's detail list is capped at the top 50 items; `summary` is
   always complete — use a function scope when you need full details).
6. You are done ONLY when `list_checklist` reports file-scope
   `summary.uncovered` == 0 on the merged document. The host verifies
   whole-file coverage at every turn boundary and sends you the remaining
   uncovered sites as a follow-up turn until none remain. Then call
   `save_annotations(draft="{DRAFT_NAME}")` — the host ships only what you saved.

Do not write annotation JSON files by hand.

Environment:
- Working directory: `/work`, containing `{request.source_path.name}` and
  `{ABOUT_ANNOTATIONS_FILENAME}`.

# Tool usage

- All enabled tools act on this one source file and have no `file` argument.
{"\n".join(tool_sections)}
"""


__all__ = ["build_prompt"]
