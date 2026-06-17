"""Agent metric accumulation."""

from __future__ import annotations

import dataclasses
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import TypeAlias

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


@dataclass
class TokenUsage:
    """Turn-cumulative token counts. Fields are aligned across Claude and Codex SDKs:
    Anthropic's cache_creation/cache_read are merged into cached_input_tokens
    (price details are tracked separately via cost_usd, not here).
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    total_tokens: int = 0

    def add(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_input_tokens: int = 0,
        total_tokens: int = 0,
    ) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cached_input_tokens += cached_input_tokens
        self.total_tokens += total_tokens

    @property
    def has_data(self) -> bool:
        return bool(self.input_tokens or self.output_tokens or self.cached_input_tokens)

    def to_json(self) -> dict[str, int]:
        total = self.total_tokens or (
            self.input_tokens + self.output_tokens + self.cached_input_tokens
        )
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "total_tokens": total,
        }


@dataclass
class AgentMetrics:
    events: int = 0
    event_types: Counter[str] = field(default_factory=Counter)
    unknown_event_samples: Counter[str] = field(default_factory=Counter)
    tool_counts: Counter[str] = field(default_factory=Counter)
    tool_categories: Counter[str] = field(default_factory=Counter)
    usage: TokenUsage | None = None
    cost_usd: float | None = None

    def add_event(self, event_type: str) -> None:
        self.events += 1
        self.event_types[event_type] += 1

    def add_unknown_event(self, key: str) -> None:
        self.unknown_event_samples[key[:80]] += 1

    def add_usage(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_input_tokens: int = 0,
        total_tokens: int = 0,
    ) -> None:
        if self.usage is None:
            self.usage = TokenUsage()
        self.usage.add(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            total_tokens=total_tokens,
        )

    def set_usage(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_input_tokens: int = 0,
        total_tokens: int = 0,
    ) -> None:
        """Replace the whole usage snapshot (vs add_usage which accumulates)."""
        self.usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            total_tokens=total_tokens,
        )

    def add_tool(self, name: str) -> None:
        self.tool_counts[name] += 1
        self.tool_categories[tool_category(name)] += 1

    def add_cost(self, value: float | None) -> None:
        if value is not None:
            self.cost_usd = (self.cost_usd or 0.0) + value

    def to_json(self) -> dict[str, object]:
        return {
            "events": self.events,
            "event_types": dict(self.event_types),
            "unknown_event_samples": dict(self.unknown_event_samples),
            "tool_counts": dict(self.tool_counts),
            "tool_categories": dict(self.tool_categories),
            "usage": self.usage.to_json() if self.usage and self.usage.has_data else None,
            "cost_usd": round(self.cost_usd, 6) if self.cost_usd is not None else None,
        }


def tool_category(name: str) -> str:
    lower = name.lower()
    if any(part in lower for part in ("read", "view", "open", "cat")):
        return "read"
    if any(part in lower for part in ("write", "edit", "patch", "create")):
        return "write"
    if any(part in lower for part in ("bash", "shell", "exec", "command")):
        return "shell"
    if any(part in lower for part in ("search", "grep", "rg", "find")):
        return "search"
    return "other"


def to_jsonable(value: object) -> JsonValue:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            key: to_jsonable(val)
            for key, val in dataclasses.asdict(value).items()
            if val is not None
        }
    if isinstance(value, Enum):
        return to_jsonable(value.value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return to_jsonable(model_dump(by_alias=True, mode="json"))
    if isinstance(value, dict):
        return {str(key): to_jsonable(val) for key, val in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def json_get_int(value: JsonValue, *keys: str) -> int:
    """Drill into a nested JSON dict by keys; return the int leaf, or 0 if absent."""
    node: JsonValue | None = value
    for key in keys:
        if not isinstance(node, dict):
            return 0
        node = node.get(key)
    return node if isinstance(node, int) and not isinstance(node, bool) else 0
