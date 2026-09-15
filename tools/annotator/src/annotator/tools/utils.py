"""Shared helpers for the in-process MCP source tools (``locate``, ``fold``).

Only the bits both tools need live here: a uniform MCP error result, the
workdir-confined file resolver, the byte-offset line table, and the fold-only
scope-to-window resolution (the ownership-based scope contract the selecting
tools share lives in :func:`functions.resolve_scope`). Tool-specific helpers
stay in their own modules.
"""

from __future__ import annotations

import json
import os
import re
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


# The ONE shared scope vocabulary. Ownership semantics (a function loc_key
# means that function's direct statements only) are implemented in
# functions.resolve_scope; this text is the error every malformed scope
# surfaces verbatim.
SCOPE_HELP = (
    "scope must be one of: \"file\" (whole file; also the default when "
    "omitted) | a function loc_key like \"31:1\" (identifies ONE "
    "function; an ID copied from fold/list_checklist output, not an "
    "arbitrary coordinate range — it means that function's DIRECT "
    "statements only, nested functions are independent scopes, pass "
    "their own loc_keys) | a list of loc_keys like "
    "[\"31:1\", \"35:1\"] | \"<top-level>\" for module-level code | "
    "an inclusive line range like \"31-45\" (selects items whose own "
    "line falls inside)"
)


def parse_scope_window(
    scope: Any,
    source_data: bytes,
) -> tuple[int, int]:
    """Resolve a ``scope`` to a literal 1-based inclusive line window —
    FOLD-ONLY.

    ``fold`` is a visual text view: a function loc_key here means that
    function's whole line extents (nested functions' lines stay visible,
    which is the point of a fold view), NOT the ownership selection every
    other tool uses (:func:`functions.resolve_scope`). Do not wire new
    selecting tools to this.

    - ``"file"`` or None — the whole file (``[1, num_lines]``)
    - ``"12-40"`` — an inclusive line range
    - one loc_key (``"12:1"``) or a list of them — the union of the
      owning functions' line extents (contiguous window from the earliest
      start to the latest end)

    Raises ValueError with the shared ``SCOPE_HELP`` message.
    """
    if scope is None or scope == "file":
        return 1, len(build_line_starts(source_data))
    keys = [scope] if isinstance(scope, str) else scope
    if not isinstance(keys, list) or not keys:
        raise ValueError(SCOPE_HELP)
    if len(keys) == 1 and isinstance(keys[0], str) and re.fullmatch(r"^\d+-\d+$", keys[0]):
        a, b = keys[0].split("-")
        return resolve_line_window(len(build_line_starts(source_data)), int(a), int(b))
    # function loc_keys: union of line extents
    from .functions import extract_functions  # local import: tree-sitter pull

    known = {fn["loc_key"]: fn for fn in extract_functions(source_data)}
    if not all(isinstance(k, str) and k in known for k in keys):
        raise ValueError(SCOPE_HELP)
    spans = [(known[k]["start_line"], known[k]["end_line"]) for k in keys]
    return min(s for s, _ in spans), max(e for _, e in spans)


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
