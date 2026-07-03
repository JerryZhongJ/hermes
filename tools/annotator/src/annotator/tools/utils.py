"""Shared helpers for the in-process MCP source tools (``locate``, ``fold``).

Only the bits both tools need live here: a uniform MCP error result, the
workdir-confined file resolver, and the byte-offset line table. Tool-specific
helpers stay in their own modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _err(msg: str) -> dict[str, Any]:
    """Standard MCP tool error result."""
    return {"content": [{"type": "text", "text": f"error: {msg}"}], "is_error": True}


def resolve_in_workdir(
    workdir_resolved: Path, file_arg: str
) -> tuple[Path | None, dict[str, Any] | None]:
    """Resolve ``file_arg`` (relative to the workdir) and confine it under
    ``workdir_resolved``. Returns ``(target, None)`` on success, or
    ``(None, error_result)`` if it escapes the workdir. Shared by the in-process
    MCP tools so a malicious prompt can't read outside the attempt directory.
    """
    target = (workdir_resolved / file_arg).resolve()
    try:
        target.relative_to(workdir_resolved)
    except ValueError:
        return None, _err(f"{file_arg!r} resolves outside the workdir")
    return target, None


def build_line_starts(data: bytes) -> list[int]:
    """Return byte offsets where each 1-based line starts.

    ``line_starts[i]`` is the first byte of line ``i + 1``; ``line_starts[0]``
    is always 0. A trailing newline does not create a spurious final entry
    unless there is content after it (matching how hermes counts lines), so
    ``len(line_starts)`` is the line count agents and the annotation JSON see.
    """
    starts = [0]
    start = 0
    while True:
        nl = data.find(b"\n", start)
        if nl < 0:
            break
        starts.append(nl + 1)
        start = nl + 1
    # Drop a phantom trailing line if the file ends with exactly one '\n'
    # (no content after it) — keeps len == the line numbers agents see.
    if len(starts) > 1 and starts[-1] == len(data):
        starts.pop()
    return starts
