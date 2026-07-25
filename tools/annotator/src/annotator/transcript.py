"""Tolerant reader for Claude Code's internal JSONL transcripts.

The transcript format is intentionally treated as an internal, versioned-by-
Claude-Code input: unknown records are ignored, malformed lines are counted,
and only the small message/content/usage subset needed for metrics is read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .metrics import AgentMetrics


@dataclass
class TranscriptRead:
    metrics: AgentMetrics = field(default_factory=AgentMetrics)
    warnings: list[str] = field(default_factory=list)
    raw_records: int = 0
    thinking_blocks: int = 0
    threads: int = 0

    def provenance(self) -> dict[str, object]:
        return {
            "format": "claude-code-jsonl",
            "threads": self.threads,
            "raw_records": self.raw_records,
            "thinking_blocks": self.thinking_blocks,
            "warnings": self.warnings,
        }


def read_trace(directory: Path, main_name: str = "session.jsonl") -> TranscriptRead:
    """Read one published trace directory, including every subagent sidecar."""
    result = TranscriptRead()
    paths = [directory / main_name]
    subagents = directory / "subagents"
    if subagents.is_dir():
        paths.extend(sorted(subagents.rglob("agent-*.jsonl")))

    usage_by_response: dict[tuple[str, str], dict[str, int]] = {}
    tool_ids: set[tuple[str, str]] = set()
    for path in paths:
        if not path.is_file():
            if path == paths[0]:
                result.warnings.append(f"transcript not found: {path}")
            continue
        result.threads += 1
        _read_jsonl(path, result, usage_by_response, tool_ids)

    for usage in usage_by_response.values():
        cached = usage["cache_creation_input_tokens"] + usage["cache_read_input_tokens"]
        result.metrics.add_usage(
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            cached_input_tokens=cached,
            total_tokens=usage["input_tokens"] + usage["output_tokens"] + cached,
        )
    return result


def _read_jsonl(
    path: Path,
    result: TranscriptRead,
    usage_by_response: dict[tuple[str, str], dict[str, int]],
    tool_ids: set[tuple[str, str]],
) -> None:
    thread = str(path)
    try:
        handle = path.open(encoding="utf-8")
    except OSError as exc:
        result.warnings.append(f"could not read {path}: {exc}")
        return

    malformed = 0
    with handle:
        lines = handle
        for line in lines:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(entry, dict):
                malformed += 1
                continue
            result.raw_records += 1
            event_type = entry.get("type")
            result.metrics.add_event(event_type if isinstance(event_type, str) else "unknown")
            if event_type != "assistant":
                continue
            message = entry.get("message")
            if not isinstance(message, dict):
                continue
            response_id = message.get("id")
            if not isinstance(response_id, str):
                response_id = entry.get("uuid")
            if isinstance(response_id, str):
                usage = _usage(message.get("usage"))
                if usage is not None:
                    key = (thread, response_id)
                    previous = usage_by_response.get(key)
                    if previous is None or _usage_total(usage) > _usage_total(previous):
                        usage_by_response[key] = usage
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type == "thinking":
                    result.thinking_blocks += 1
                if block_type not in ("tool_use", "server_tool_use"):
                    continue
                tool_id = block.get("id")
                name = block.get("name")
                if not isinstance(tool_id, str) or not isinstance(name, str):
                    continue
                key = (thread, tool_id)
                if key not in tool_ids:
                    tool_ids.add(key)
                    result.metrics.add_tool(name)
    if malformed:
        result.warnings.append(f"{path}: ignored {malformed} malformed JSONL line(s)")


def _usage(value: object) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    keys = (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    )
    usage = {key: _int(value.get(key)) for key in keys}
    return usage if any(usage.values()) else None


def _usage_total(usage: dict[str, int]) -> int:
    return sum(usage.values())


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
