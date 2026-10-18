"""The annotator: one agent or subagent annotating one scope to full coverage.

Two constructions share this module:

- annotate-file's main agent IS an annotator (scope "file"), built by
  :func:`build_annotating_agent` with its own draft and the host-side
  :func:`coverage_followup_hook` keeping the same session going until every
  checklist item is optimized or carries a recorded reason.
- the parallel workflows' WORKERS are native ``annotator-worker`` subagents
  (:func:`worker_agent_definition`): the coordinator fans them out with the
  Task tool; each worker owns one chunk of the file and one named draft in
  the shared drafts store. Native subagents get no host-side follow-up hook,
  so their prompt carries the completion criterion itself: the worker keeps
  working until ``list_checklist`` reports ``summary.uncovered == 0`` for its
  scope; the coordinator's merged-draft coverage gate backstops it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from claude_agent_sdk import AgentDefinition

from .agent import Agent
from .annotation_drafts import add_unique_draft, drafts
from .prompt import (
    ABOUT_ANNOTATIONS_FILENAME,
    ABOUT_ANNOTATIONS_PATH,
)
from .tools import build_mcp_servers, render_tool_sections
from .tools.checklist_tool import _reason_index, coverage_snapshot
from .tools.dryrun_tool import run_dryrun_sync

# The completion criterion is checklist coverage, so these two are required.
ANNOTATING_TOOLS = ("dryrun", "checklist")

# Follow-up turns the host grants after the agent's own "done" turn before
# accepting the shortfall (the run report still carries the final numbers).
MAX_COVERAGE_FOLLOWUPS = 3


# --- scope ----------------------------------------------------------------- #


def normalize_scope(raw: Any) -> tuple[str, ...]:
    """Canonical scope: ``("file",)`` or a non-empty tuple of loc_keys."""
    if raw is None or raw == "file":
        return ("file",)
    keys = (raw,) if isinstance(raw, str) else tuple(raw)
    if not keys:
        raise ValueError("scope must not be empty")
    for key in keys:
        if not isinstance(key, str) or not key:
            raise ValueError("scope entries must be non-empty strings")
    if len(set(keys)) != len(keys):
        raise ValueError("scope must not repeat a function loc_key")
    return tuple(sorted(keys))  # order-insensitive: one grouping, one job


def scope_id(scope: Any) -> str:
    """A short stable id for a scope ("file" or the joined loc_keys)."""
    keys = normalize_scope(scope)
    return keys[0] if keys == ("file",) else "+".join(keys)


# --- prompt ---------------------------------------------------------------- #


def build_annotating_prompt(
    scope: Any,
    source_name: str,
    enabled_tools: list[str] | None = None,
) -> str:
    keys = normalize_scope(scope)
    whole_file = keys == ("file",)
    if whole_file:
        target_lines = (
            f"- Your targets: every function in `{source_name}` plus its\n"
            "  module-level code."
        )
        scope_arg = "file"
    else:
        targets = "\n".join(f"- `{key}`" for key in keys)
        target_lines = (
            "- Your targets, exactly these function loc_keys (use each as the\n"
            f"``scope`` in your checklist queries):\n{targets}"
        )
        scope_arg = json_scope(keys)
    tool_sections = render_tool_sections(
        list(enabled_tools or []), ANNOTATING_TOOLS
    )
    return f"""# Protocol (annotator)

Before starting, Read `{ABOUT_ANNOTATIONS_PATH}`. You own ONE annotation
document. Your goal is to finish the optimization checklist of your scope:
every checklist item is optimized (its speculative-path instruction got
strength-reduced or eliminated), OR you recorded a reason why it cannot be
optimized.

{target_lines}

1. Read `{source_name}` to understand the objects, prototypes, and call
   structure your targets touch.
2. Call `list_checklist` with scope {scope_arg} for the compiler-measured
   checklist — generic arithmetic operations, named property accesses, and
   dynamic calls, each marked optimized or not-optimized.
3. Work through the not-optimized sites. For each, FIRST try to make it
   optimized: add annotations through the mandatory annotations MCP (shape
   guards on the receiver, creation-site bindings, type guards). Verify
   with `dryrun` after each change, then re-query
   `list_checklist(scope={scope_arg}, only_uncovered=true)`.
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
   other (note mandatory). Several sites blocked by the same cause can be
   checked off together with `check(items=[...], reason=...)`. Reasons are
   auditable — never use one to dodge a site you could optimize with more
   effort.
5. You are done ONLY when `list_checklist` reports `summary.uncovered` == 0
   for your scope. If progress truly stalls on remaining sites, exhaust
   your ideas (different guard placements, source bindings at object
   creation points, batch guards) before recording reasons. The host
   verifies coverage at every turn boundary and sends you the remaining
   uncovered sites as a follow-up turn until none remain — so finish the
   list, do not stop early.
6. When (and only when) your checklist is finished, SAVE your work: call
   `save_annotations()` for your draft. Do not save an unfinished draft just
   to end the session.

Prefer broad useful coverage over minimizing guard cost. Do not write
annotation JSON files by hand; do not split work into subagents.

Environment:
- Working directory: your cwd, containing `{source_name}` and
  `{ABOUT_ANNOTATIONS_FILENAME}`.

# Tool usage

- All enabled tools act on this one source file and have no `file` argument.
{"\n".join(tool_sections)}
"""


def json_scope(keys: tuple[str, ...]) -> str:
    """The scope rendered for prompt examples (list of loc_keys or "file")."""
    return "file" if keys == ("file",) else str(list(keys)).replace("'", '"')


# --- the annotator main agent (annotate-file) -------------------------------- #


def build_annotating_agent(
    scope: Any,
    workdir: Path,
    source: Path,
    *,
    draft_name: str | None = None,
    enabled_tools: list[str] | None = None,
    model: str | None = None,
    settings: Any = None,
    timeout_s: float | None = None,
    stderr=None,
) -> tuple[Agent, str]:
    """Instantiate one annotator agent over its own named draft.

    Returns ``(agent, draft_name)`` — the draft is created here (a unique
    name unless the caller names it) and is the agent's sole product: the
    agent SAVES it itself via ``save_annotations``; nothing is flushed on its
    behalf.
    """
    if draft_name is None:
        draft_name = add_unique_draft()
    elif not drafts().has(draft_name):
        drafts().add(draft_name)
    agent = Agent(
        "annotator",
        cwd=str(workdir),
        mcp_servers=build_mcp_servers(
            source,
            workdir,
            ([draft_name], draft_name),
            enabled_tools,
            ANNOTATING_TOOLS,
        ),
        model=model,
        settings=settings,
        timeout_s=timeout_s,
        stderr=stderr,
    )
    return agent, draft_name


# --- the annotator worker subagent (parallel workflows) ---------------------- #

WORKER_AGENT_NAME = "annotator-worker"

# The worker's system prompt is static; the per-chunk specifics (target
# loc_keys, draft name, source file name) travel in the Task tool's prompt.
WORKER_PROMPT = """You are an annotator worker: one parallel worker among \
several, each owning one chunk of the same source file. You share the
annotations MCP with the other workers, so EVERY draft-scoped tool call
(add_annotation, batch_add_guards, update_annotation, delete_annotation,
list_annotations, dryrun, list_checklist, check, uncheck, list_reasons) MUST
pass your assigned draft name explicitly — work ONLY on that draft, never on
any other.

Your assignment message gives you: the source file name, your exact target
function loc_keys, and your draft name. Then:

1. Call `create_draft(draft=<your draft name>)` FIRST — the other tools need
   the draft to exist.
2. Read the source file to understand the objects, prototypes, and call
   structure your targets touch.
3. Call `list_checklist(scope=<your loc_keys>, draft=<your draft>)` for the
   compiler-measured checklist — generic arithmetic operations, named
   property accesses, and dynamic calls, each marked optimized or
   not-optimized. Note a function loc_key's scope covers only that
   function's DIRECT statements: nested functions are independent scopes
   (their sites belong to the nested function's own loc_key), so when a
   nested function is not in your chunk list its sites are not yours to
   cover.
4. Work through the not-optimized sites. For each, FIRST try to make it
   optimized: add annotations (shape guards on the receiver, creation-site
   bindings, type guards). Verify with `dryrun(draft=...)` after each
   change, then re-query
   `list_checklist(scope=..., only_uncovered=true, draft=...)`.
5. Only when a site genuinely cannot be optimized, check it off with
   `check(draft=..., reason=..., location=...)` — a bare location
   ('line:col') suffices when it identifies exactly one site; pass
   kind/property only to disambiguate — and one of
   object-source-not-found | ambiguous-shape | maybe-not-number |
   no-closure-target | constructing-store (the store runs while the
   receiver's shape is still being constructed — namespace assembly,
   prototype setup, constructor body; the slot doesn't exist yet, so there
   is no fixed slot to write) |
   unsupported-property-type (note the attempted type) |
   other (note mandatory). Several sites blocked by the same cause can be
   checked off together with `check(draft=..., items=[...], reason=...)`.
   Reasons are auditable — never use one to dodge a site you could optimize
   with more effort.
6. You are done ONLY when `list_checklist(scope=<your loc_keys>,
   only_uncovered=true, draft=<your draft>)` reports `summary.uncovered`
   == 0. If progress truly stalls, exhaust your ideas (different guard
   placements, source bindings at object creation points, batch guards)
   before recording reasons. Nothing re-prompts you — keep working your
   scope until the criterion holds, then STOP.

Prefer broad useful coverage over minimizing guard cost. Do not write
annotation JSON files by hand, do not save the draft (the coordinator owns
saving/merging), do not spawn subagents.
"""


def worker_agent_definition() -> AgentDefinition:
    """The ``annotator-worker`` subagent the parallel coordinators fan out.

    No ``tools``/``maxTurns``: the worker inherits the session's toolset
    (the in-process MCP servers cannot be re-specified per subagent) and
    runs until its coverage criterion holds; session-level timeout is the
    outer runner's concern.
    """
    return AgentDefinition(
        description=(
            "Annotate one chunk of the source file (a list of function "
            "loc_keys) on an assigned draft to full checklist coverage. Use "
            "for every parallel annotation chunk the coordinator fans out."
        ),
        prompt=WORKER_PROMPT,
        model="inherit",
    )


# --- coverage follow-up (the annotator main agent's completion criterion) ---- #


def coverage_followup_hook(
    workdir: Path,
    source: Path,
    draft: str,
    scope: Any,
    max_followups: int = MAX_COVERAGE_FOLLOWUPS,
):
    """The annotator's completion gate: full checklist coverage ends the session.

    Runs at every result boundary of the same session. The session ends
    (returns None) only when the scope's checklist is fully covered
    (uncovered == 0, or the dryrun itself fails — the failure is reported,
    not retried away). While uncovered sites remain (and turns are left) the
    follow-up prompt lists them.

    Measurements go through the shared dryrun report cache: an unchanged
    draft reuses the report the agent's own ``dryrun``/``list_checklist``
    calls already compiled (no extra host compile per turn boundary).

    Product checking is NOT this hook's business: saving the draft is the
    caller's workflow's concern (it composes its own product gate).
    """
    run_dryrun = run_dryrun_sync(workdir, draft)  # shared-report-cache composition
    followups_left = max_followups

    def _hook(_result) -> str | None:
        nonlocal followups_left
        try:
            report = asyncio.run(run_dryrun())
            snapshot = coverage_snapshot(
                report, source.read_bytes(), scope, _reason_index(draft)
            )
        except Exception:  # noqa: BLE001 — measurement failure ends, not hangs
            return None
        uncovered = 0 if snapshot is None else snapshot["uncovered"]
        if uncovered == 0:
            return None  # coverage met: the annotator's job is done
        if followups_left <= 0:
            return None  # budget exhausted: shortfall accepted, not hung on
        followups_left -= 1
        sites = "\n".join(
            f"- {i['location']} {i['kind']}"
            + (f" .{i['property']}" if i.get("property") else "")
            for i in snapshot["uncovered_items"]
        )
        return (
            f"Checklist check after your turn: {snapshot['uncovered']} "
            f"uncovered of {snapshot['total']} "
            f"({snapshot['optimized']} optimized, {snapshot['reasoned']} "
            f"reasoned). Continue in your scope: optimize these sites or "
            f"record a reason for each —\n{sites}"
        )

    return _hook


__all__ = [
    "ANNOTATING_TOOLS",
    "MAX_COVERAGE_FOLLOWUPS",
    "WORKER_AGENT_NAME",
    "build_annotating_agent",
    "build_annotating_prompt",
    "coverage_followup_hook",
    "normalize_scope",
    "scope_id",
    "worker_agent_definition",
]
