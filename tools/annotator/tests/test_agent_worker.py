"""Tests for persistent ClaudeSDKClient task draining in agent_worker."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from claude_agent_sdk.types import ResultMessage, SystemMessage

from annotator.agent_worker import _collect


def _system(subtype: str, **data: Any) -> SystemMessage:
    return SystemMessage(subtype=subtype, data={"subtype": subtype, **data})


def _result(*, error: bool = False) -> ResultMessage:
    return ResultMessage(
        subtype="error_during_execution" if error else "success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=error,
        num_turns=1,
        session_id="session",
        stop_reason="end_turn",
        result="failed" if error else "done",
    )


class FakeClient:
    events: list[object] = []
    trace: list[str] = []

    def __init__(self, *, options: object) -> None:
        self.options = options

    async def __aenter__(self) -> "FakeClient":
        self.trace.append("enter")
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.trace.append("exit")

    async def query(self, prompt: str) -> None:
        self.trace.append(f"query:{prompt}")

    async def receive_messages(self) -> AsyncIterator[object]:
        for index, event in enumerate(self.events):
            self.trace.append(f"yield:{index}")
            yield event


def _run(events: list[object]) -> tuple[list[object], list[str]]:
    FakeClient.events = events
    FakeClient.trace = []
    messages: list[object] = []
    asyncio.run(
        _collect(
            "prompt",
            object(),  # type: ignore[arg-type]
            messages,
            client_factory=FakeClient,  # type: ignore[arg-type]
        )
    )
    return messages, FakeClient.trace


def test_result_without_background_task_completes():
    messages, trace = _run([_result()])
    assert [entry["type"] for entry in messages if isinstance(entry, dict)] == ["result"]
    assert trace == ["enter", "query:prompt", "yield:0", "exit"]


def test_result_with_active_task_does_not_break_before_followup_turn():
    # Turn 1 ends while the task is still running -> must NOT break. The task
    # then completes, which (in the real CLI) triggers turn 2; only that second
    # result, with nothing active, ends the session.
    events = [
        _system("task_started", task_id="task-1", description="probe"),
        _result(),
        _system("task_progress", task_id="task-1", description="probe"),
        _system("task_updated", task_id="task-1", patch={"status": "completed"}),
        _result(),
    ]
    messages, trace = _run(events)
    assert len(messages) == 5
    # Broke on the final (5th) event, the second result — not on the first.
    assert trace[-2] == "yield:4"


@pytest.mark.parametrize("status", ["completed", "failed", "stopped"])
def test_task_notification_terminal_then_followup_result_ends(status: str):
    _run(
        [
            _system("task_started", task_id="task-1"),
            _result(),
            _system("task_notification", task_id="task-1", status=status),
            _result(),
        ]
    )


@pytest.mark.parametrize("status", ["completed", "failed", "killed"])
def test_task_updated_terminal_then_followup_result_ends(status: str):
    _run(
        [
            _system("task_started", task_id="task-1"),
            _result(),
            _system("task_updated", task_id="task-1", patch={"status": status}),
            _result(),
        ]
    )


def test_task_terminal_before_result_ends_at_that_result():
    # Task already finished when the result arrives -> break on the result.
    _run(
        [
            _system("task_started", task_id="task-1"),
            _system("task_notification", task_id="task-1", status="completed"),
            _result(),
        ]
    )


def test_late_progress_cannot_reactivate_terminal_task():
    # Once terminal, a later task_progress must not make the task look active
    # again at the final result.
    _run(
        [
            _system("task_started", task_id="task-1"),
            _system("task_notification", task_id="task-1", status="completed"),
            _system("task_progress", task_id="task-1"),
            _result(),
        ]
    )


def test_final_error_result_is_raised_after_draining():
    FakeClient.events = [
        _system("task_started", task_id="task-1"),
        _result(error=True),  # turn 1 errors, but task still active -> drain
        _system("task_notification", task_id="task-1", status="completed"),
        _result(error=True),  # final turn still errors -> raise
    ]
    FakeClient.trace = []
    with pytest.raises(RuntimeError, match="Claude Code returned an error result"):
        asyncio.run(
            _collect(
                "prompt",
                object(),  # type: ignore[arg-type]
                [],
                client_factory=FakeClient,  # type: ignore[arg-type]
            )
        )
    assert FakeClient.trace[-1] == "exit"


def test_stream_ending_without_result_errors():
    with pytest.raises(RuntimeError, match="before ResultMessage"):
        _run([_system("task_started", task_id="task-1")])


def test_stream_ending_with_active_task_errors():
    FakeClient.events = [_system("task_started", task_id="task-1"), _result()]
    FakeClient.trace = []
    with pytest.raises(RuntimeError, match="unfinished background tasks: task-1"):
        asyncio.run(
            _collect(
                "prompt",
                object(),  # type: ignore[arg-type]
                [],
                client_factory=FakeClient,  # type: ignore[arg-type]
            )
        )


def test_thinking_tokens_are_filtered_without_affecting_completion():
    messages, _ = _run([_system("thinking_tokens", value=1), _result()])
    assert len(messages) == 1
    assert isinstance(messages[0], dict) and messages[0]["type"] == "result"
