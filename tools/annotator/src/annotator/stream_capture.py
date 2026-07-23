"""Capture the NDJSON line that trips the SDK's stream buffer guard.

The bundled Claude CLI writes one JSON message per line to stdout. The Agent
SDK's subprocess transport bounds each line at 1 MiB and raises
``SDKJSONDecodeError`` when a line crosses that limit — but the offending bytes
are discarded before parsing, so the run record never shows which message blew
up. That guard is a closure inside
``SubprocessCLITransport._read_messages_impl``, so the only way to see the frame
is to replace that one method.

The SDK is pinned (``claude-agent-sdk==0.2.123``); this module copies the
method verbatim and adds a single capture step that runs *before* the raise:
the offending line's length, head/tail preview, and best-effort parsed
``type``/``subtype`` are written to ``<workdir>/.buffer-overflow.json``. The cap
is unchanged — the run still fails (the framing error is unrecoverable for the
session) — but the diagnostic now identifies the culprit.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import anyio

LOGGER = logging.getLogger("stream_capture")

OVERFLOW_FILE = ".buffer-overflow.json"


def install(overflow_path: Path) -> None:
    """Monkeypatch the SDK transport to dump the oversized line before raising.

    No-op (with a warning) if the installed SDK does not match the pinned
    method shape this copy was written against — drifting silently would
    reintroduce the original blind failure.
    """
    try:
        from claude_agent_sdk._errors import (
            CLIConnectionError,
            CLIJSONDecodeError as SDKJSONDecodeError,
            ProcessError,
        )
        from claude_agent_sdk._internal.transport import subprocess_cli as sc
    except Exception as exc:  # pragma: no cover - SDK layout changed
        LOGGER.warning("stream_capture: could not import SDK transport: %s", exc)
        return

    expected = (
        hasattr(sc.SubprocessCLITransport, "_read_messages_impl"),
        hasattr(sc, "_LineFramer"),
        hasattr(sc, "_parse_stdout_line"),
        hasattr(sc, "_DEFAULT_MAX_BUFFER_SIZE"),
    )
    if not all(expected):
        LOGGER.warning(
            "stream_capture: SDK transport layout changed; skipping capture"
        )
        return

    _LineFramer = sc._LineFramer  # type: ignore[attr-defined]
    _parse_stdout_line = sc._parse_stdout_line  # type: ignore[attr-defined]
    logger = sc.logger

    def _capture(raw: str, length: int, limit: int, complete: bool) -> None:
        parsed: dict[str, Any] | None = None
        if complete:
            try:
                parsed = _parse_stdout_line(raw)
            except Exception:
                parsed = None
        record = {
            "length_bytes": length,
            "limit_bytes": limit,
            "complete_line": complete,
            "head": raw[:1024],
            "tail": raw[-1024:] if length > 1024 else "",
            "parsed_type": parsed.get("type") if isinstance(parsed, dict) else None,
            "parsed_subtype": (
                parsed.get("subtype") if isinstance(parsed, dict) else None
            ),
            "parsed_keys": sorted(parsed.keys()) if isinstance(parsed, dict) else None,
        }
        try:
            overflow_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            logger.error("stream_capture: could not write %s: %s", overflow_path, exc)

    async def _read_messages_impl(self):  # type: ignore[no-untyped-def]
        if not self._process or not self._stdout_stream:
            raise CLIConnectionError("Not connected")

        framer = _LineFramer()

        def guard(length: int, raw: str = "", complete: bool = False) -> None:
            if length > self._max_buffer_size:
                _capture(raw, length, self._max_buffer_size, complete)
                raise SDKJSONDecodeError(
                    f"JSON message exceeded maximum buffer size of "
                    f"{self._max_buffer_size} bytes (line length {length}); "
                    f"diagnostic written to {overflow_path}",
                    ValueError(
                        f"Buffer size {length} exceeds limit "
                        f"{self._max_buffer_size}"
                    ),
                )

        try:
            async for chunk in self._stdout_stream:
                for line in framer.push(chunk):
                    guard(len(line), raw=line, complete=True)
                    data = _parse_stdout_line(line)
                    if data is not None:
                        yield data
                guard(framer.pending_len, raw="".join(framer._pending), complete=False)

        except anyio.ClosedResourceError:
            pass
        except GeneratorExit:
            return

        tail = framer.flush()
        try:
            data = _parse_stdout_line(tail)
        except SDKJSONDecodeError:
            logger.debug(
                "Dropping truncated JSON at end of CLI stdout: %s", tail[:200]
            )
            data = None
        if data is not None:
            yield data

        try:
            returncode = await self._process.wait()
        except Exception:
            returncode = -1

        if returncode is not None and returncode != 0:
            self._exit_error = ProcessError(
                f"Command failed with exit code {returncode}",
                exit_code=returncode,
                stderr="Check stderr output for details",
            )
            raise self._exit_error

    sc.SubprocessCLITransport._read_messages_impl = _read_messages_impl  # type: ignore[assignment]
    LOGGER.info("stream_capture: installed overflow diagnostic at %s", overflow_path)
