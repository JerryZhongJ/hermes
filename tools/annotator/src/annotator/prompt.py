"""Prompt construction for agent-generated annotations."""

from __future__ import annotations

from pathlib import Path

ABOUT_ANNOTATIONS_FILENAME = ".about_annotations.md"
ABOUT_ANNOTATIONS_PATH = f"/work/{ABOUT_ANNOTATIONS_FILENAME}"
_ABOUT_FILE = Path(__file__).with_name("about_annotations.md")


def build_about_annotations_markdown() -> str:
    """Return the shared explanation of annotation meaning and mechanics.

    The content lives in ``about_annotations.md`` next to this module and is
    copied verbatim — edit that file, not this function.
    """
    return _ABOUT_FILE.read_text(encoding="utf-8")
