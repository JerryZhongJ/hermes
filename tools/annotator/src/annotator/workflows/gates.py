"""Shared workflow completion gates (``next_prompt`` hooks).

A gate runs at every result boundary of a session; returning a prompt string
sends it as a follow-up turn, returning None ends the session. Gates keep
their own follow-up budget. Two gates are shared by the whole-file workflows:

- the **product gate**: the agent's saved draft file exists (the agent saves
  via ``save_annotations``; the host never flushes on its behalf);
- ``compose_gates``: several gates end the session only when EVERY one does.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

# Follow-up turns a product gate grants before accepting the missing product.
MAX_SAVE_FOLLOWUPS = 3


def saved_product_gate(
    work: Path, draft: str, max_followups: int = MAX_SAVE_FOLLOWUPS
):
    """One saved draft ends the session; an unsaved turn gets one reminder.

    The product is ``<workdir>/<draft>.json`` (written by the agent's own
    ``save_annotations``). After ``max_followups`` reminders the session ends
    regardless (the run report then shows the missing product).
    """
    followups_left = max_followups
    saved_file = work / f"{draft}.json"

    def _gate(_result) -> str | None:
        nonlocal followups_left
        if saved_file.is_file():
            return None
        if followups_left <= 0:
            return None
        followups_left -= 1
        return (
            "Product check after your turn: your annotation draft is not "
            "saved yet — an unsaved draft is not a product, and the host "
            "ships only what you saved. Call "
            f"`save_annotations(draft=\"{draft}\")` now, then finish."
        )

    return _gate


def compose_gates(*gates: Callable[[Any], str | None]):
    """Combine gates: follow-up prompts are joined, session ends when all do.

    Order matters: earlier gates' prompts (e.g. coverage before product)
    come first in the joined prompt.
    """

    def _composed(result) -> str | None:
        prompts = [p for gate in gates if (p := gate(result)) is not None]
        if not prompts:
            return None
        return "\n\n".join(prompts)

    return _composed


__all__ = ["MAX_SAVE_FOLLOWUPS", "compose_gates", "saved_product_gate"]
