"""Prompt for the whole-file annotation workflow (simple-file flow)."""

from ...prompt import ABOUT_ANNOTATIONS_FILENAME, ABOUT_ANNOTATIONS_PATH


def build_prompt(request) -> str:
    from ...tools import render_tool_sections

    tool_sections = render_tool_sections(list(request.enabled_tools), ())
    return f"""# Protocol (annotate-file workflow)

Before starting, Read `{ABOUT_ANNOTATIONS_PATH}`. You own ONE annotation
document for the ENTIRE file: annotate every function to full checklist
coverage.

1. Read the whole source file `{request.source_path.name}` to understand its
   objects, prototypes, and call structure.
2. Call `list_checklist(scope="file")` for the whole-file optimization
   checklist — compiler-measured generic arithmetic operations, named
   property accesses, and dynamic calls, each marked optimized or
   not-optimized. The file view's detail list is capped at the top 50
   items; use a function scope (`list_checklist(scope=<function
   loc_key>)`) for the full details of a function.
3. Work through the not-optimized sites function by function. For each,
   FIRST try to make it optimized: add annotations through the mandatory
   annotations MCP (shapes at creation sites, bindings, shape guards, type
   guards). Verify with `dryrun` after each change, then
   re-query `list_checklist(scope=<function loc_key>, only_uncovered=true)`
   for the function you are working on (the file view is capped at the
   top-20 items; `summary` is always complete).
4. Only when a site genuinely cannot be optimized, check it off with
   `check(reason, location)` — a bare location ('line:col') suffices when it
   identifies exactly one site; pass kind/property only to disambiguate — and
   one of
   object-source-not-found | ambiguous-shape | maybe-not-number |
   no-closure-target | constructing-store (the store runs while the
   receiver's shape is still being constructed — namespace assembly,
   prototype setup, constructor body; the slot doesn't exist yet, so there
   is no fixed slot to write) |
   unsupported-property-type (note the attempted type) |
   other (note mandatory). Reasons are auditable — never use one to dodge a
   site you could optimize with more effort.
5. You are done ONLY when `list_checklist` reports file-scope
   `summary.uncovered` == 0. The host verifies whole-file coverage at every
   turn boundary and sends you the remaining uncovered sites as a follow-up
   turn until none remain (or follow-ups are exhausted) — so finish the
   list, do not stop early.

Prefer broad useful coverage over minimizing guard cost. Do not write
annotation JSON files directly; do not split work into subagents.

Environment:
- Working directory: `/work`, containing `{request.source_path.name}` and
  `{ABOUT_ANNOTATIONS_FILENAME}`.

# Tool usage

- All enabled tools act on this one source file and have no `file` argument.
{"\n".join(tool_sections)}
"""


__all__ = ["build_prompt"]
