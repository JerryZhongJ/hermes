"""Shared helpers for the in-process MCP source tools (``locate``, ``fold``).

Only the bits both tools need live here: a uniform MCP error result, the
workdir-confined file resolver, and the byte-offset line table. Tool-specific
helpers stay in their own modules.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _err(msg: str) -> dict[str, Any]:
    """Standard MCP tool error result."""
    return {"content": [{"type": "text", "text": f"error: {msg}"}], "is_error": True}


def atomic_write_json(
    path: Path,
    value: Any,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> None:
    """Atomically publish JSON so readers never observe a partial document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=indent, ensure_ascii=ensure_ascii)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temp_path.unlink(missing_ok=True)


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


def resolve_line_window(
    n: int, from_line: int | None, to_line: int | None
) -> tuple[int, int]:
    """Validate and normalize the 1-based inclusive line window. Both None
    means the whole file (``[1, n]``); exactly one None is an error.

    Shared by ``fold`` and the annotation list tool so they share ONE window
    contract: 1-based, inclusive on both ends, ``1 <= from_line <= to_line <= n``.
    """
    if from_line is None and to_line is None:
        return 1, n
    if from_line is None or to_line is None:
        raise ValueError("specify both from_line and to_line, or neither for whole file")
    if from_line < 1 or to_line < from_line or to_line > n:
        raise ValueError(f"line range [{from_line},{to_line}] invalid; file has {n} line(s)")
    return from_line, to_line


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
