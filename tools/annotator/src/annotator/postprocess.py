"""Post-hoc stats from run.json — no inline metric accumulation.

annotator now saves only a run record (meta + raw messages, thinking_tokens
filtered); this recomputes token/tool/event stats offline. Dispatches on
``meta.agent`` because claude (SDK Message stream) and codex (notification
stream) have different shapes. Reuses ``AgentMetrics`` from metrics.py.

Usage:
    uv run python -m annotator.postprocess <run.json | dir> [-o agg.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .metrics import AgentMetrics, json_get_int


def _walk(value: Any):
    """Yield every dict nested in value.

    Used to locate usage/tool_use regardless of the exact message envelope,
    which differs across SDK message types (and which to_jsonable reshapes).
    """
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _extract_claude(data: dict) -> AgentMetrics:
    m = AgentMetrics()
    for msg in data.get("messages", []):
        m.add_event((msg.get("type") if isinstance(msg, dict) else "") or "unknown")
        for d in _walk(msg):
            # usage snapshot: a dict carrying input_tokens + output_tokens
            if "input_tokens" in d and "output_tokens" in d:
                m.set_usage(
                    input_tokens=json_get_int(d, "input_tokens"),
                    output_tokens=json_get_int(d, "output_tokens"),
                    cached_input_tokens=(
                        json_get_int(d, "cache_creation_input_tokens")
                        + json_get_int(d, "cache_read_input_tokens")
                    ),
                    total_tokens=json_get_int(d, "total_tokens"),
                )
            # tool_use block: has a string name + an input payload
            # (to_jsonable drops its `type` field, so match on name+input)
            if isinstance(d.get("name"), str) and "input" in d:
                m.add_tool(d["name"])
            cost = d.get("total_cost_usd")
            if isinstance(cost, (int, float)):
                m.add_cost(cost)
    return m


def _extract_codex(data: dict) -> AgentMetrics:
    m = AgentMetrics()
    for msg in data.get("messages", []):
        m.add_event((msg.get("type") if isinstance(msg, dict) else "") or "unknown")
        for d in _walk(msg):
            if "input_tokens" in d and "output_tokens" in d:
                m.set_usage(
                    input_tokens=json_get_int(d, "input_tokens"),
                    output_tokens=json_get_int(d, "output_tokens"),
                    cached_input_tokens=json_get_int(d, "cached_input_tokens"),
                    total_tokens=json_get_int(d, "total_tokens"),
                )
            # codex tool calls carry the tool name under `tool`
            if isinstance(d.get("tool"), str):
                m.add_tool(d["tool"])
    return m


_EXTRACTORS = {"claude": _extract_claude, "codex": _extract_codex}


def recompute(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data.get("meta") or {}
    agent = meta.get("agent", "claude")
    metrics = _EXTRACTORS.get(agent, _extract_claude)(data)
    return {
        "file": str(path),
        "agent": agent,
        "input": meta.get("input"),
        "duration_seconds": meta.get("duration_seconds", 0.0),
        "errors": meta.get("errors", []),
        "metrics": metrics.to_json(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Recompute annotator stats from messages.json")
    ap.add_argument("input", help="messages.json file or directory (recursed for *.messages.json)")
    ap.add_argument("-o", "--output", help="write aggregate JSON to this path")
    args = ap.parse_args()

    src = Path(args.input)
    files = [src] if src.is_file() else sorted(src.rglob("*.run.json"))
    if not files:
        print(f"no messages.json under {src}", file=sys.stderr)
        return 1

    rows = [recompute(f) for f in files]

    tools: dict[str, int] = {}
    tot_input = tot_output = tot_cached = tot_tokens = tot_events = 0
    tot_duration = 0.0
    for r in rows:
        u = (r["metrics"].get("usage") or {})
        tot_input += u.get("input_tokens", 0)
        tot_output += u.get("output_tokens", 0)
        tot_cached += u.get("cached_input_tokens", 0)
        tot_tokens += u.get("total_tokens", 0)
        tot_events += r["metrics"].get("events", 0)
        tot_duration += r["duration_seconds"]
        for k, v in (r["metrics"].get("tool_counts") or {}).items():
            tools[k] = tools.get(k, 0) + int(v)

    agg = {
        "files": len(rows),
        "total_input_tokens": tot_input,
        "total_output_tokens": tot_output,
        "total_cached_input_tokens": tot_cached,
        "total_tokens": tot_tokens,
        "total_events": tot_events,
        "total_duration_seconds": round(tot_duration, 1),
        "tool_counts_total": tools,
        "per_file": rows,
    }

    print(f"[postprocess] files={agg['files']} tokens={agg['total_tokens']:,} "
          f"events={agg['total_events']:,} duration={agg['total_duration_seconds']}s")
    print(f"[postprocess] tools={tools}")
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(agg, indent=2), encoding="utf-8")
        print(f"[postprocess] -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
