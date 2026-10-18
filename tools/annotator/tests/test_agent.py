"""Tests for the Agent class: instantiate, fill config, run."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from claude_agent_sdk.types import ResultMessage, SystemMessage

from annotator.agent import Agent
from annotator.annotation_drafts import add_unique_draft
from annotator.agent import base_options, run_persistent_session


def _system(subtype: str, **data) -> SystemMessage:
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
        FakeClient.trace.append("enter")
        return self

    async def __aexit__(self, *_args: object) -> None:
        FakeClient.trace.append("exit")

    async def query(self, prompt: str) -> None:
        FakeClient.trace.append(f"query:{prompt}")

    async def receive_messages(self) -> AsyncIterator[object]:
        for event in FakeClient.events:
            FakeClient.trace.append("yield")
            yield event


def _mcp(tmp_path: Path, drafts_access=None) -> dict:
    from annotator.tools import build_mcp_servers

    source = tmp_path / "input.js"
    source.write_text("function f(o) { return o.x; }", encoding="utf-8")
    return build_mcp_servers(source, tmp_path, drafts_access, None, ("source-fold",))


def _agent(tmp_path: Path, mcp=None, **overrides) -> Agent:
    kwargs: dict = {
        "name": "test agent",
        "cwd": str(tmp_path),
        "mcp_servers": mcp if mcp is not None else _mcp(tmp_path),
    }
    kwargs.update(overrides)
    return Agent(**kwargs)


# --- purity: agent-level config only ---------------------------------------- #


def test_agent_class_is_domain_blind(tmp_path: Path):
    """The class sees prompt/cwd/servers/knobs only — no drafts, no tools."""
    import annotator.agent as agent_module

    agent = _agent(tmp_path, timeout_s=5.0)
    assert agent.timeout_s == 5.0
    assert agent.mcp_servers
    for forbidden in ("view", "required_tools", "cfg", "workspace", "publish"):
        assert not hasattr(agent, forbidden)
    module_source = Path(agent_module.__file__ or "").read_text(encoding="utf-8")
    assert "annotation_drafts" not in module_source
    assert "from .tools" not in module_source


# --- run lifecycle ----------------------------------------------------------- #


def test_run_async_open_access_has_freeform_draft_arg(tmp_path: Path):
    """Open access (None): the annotations server is present and its draft
    argument is a free-form name (no enum) — the coordinator's mode."""
    agent = _agent(tmp_path, mcp=_mcp(tmp_path, drafts_access=None))
    seen: dict[str, object] = {}

    class OptionsClient(FakeClient):
        def __init__(self, *, options):
            super().__init__(options=options)
            seen["mcp"] = options.mcp_servers

    FakeClient.events = [_result()]
    asyncio.run(agent.run_async("do it", client_factory=OptionsClient))  # type: ignore[arg-type]
    assert "annotations" in seen["mcp"]
    assert "source-fold" in seen["mcp"]


def test_run_async_with_drafts_has_annotations_server(tmp_path: Path):
    name = add_unique_draft()
    agent = _agent(tmp_path, mcp=_mcp(tmp_path, drafts_access=([name], name)))
    seen: dict[str, object] = {}

    class OptionsClient(FakeClient):
        def __init__(self, *, options):
            super().__init__(options=options)
            seen["mcp"] = options.mcp_servers

    FakeClient.events = [_result()]
    asyncio.run(agent.run_async("do it", client_factory=OptionsClient))  # type: ignore[arg-type]
    assert "annotations" in seen["mcp"]


# --- outcome contract: data out, never raises ---------------------------------- #


def test_success_returns_ok_outcome_with_session_id(tmp_path: Path):
    agent = _agent(tmp_path)
    FakeClient.events = [
        _system("task_started", task_id="task-1"),
        _result(),
        _system("task_updated", task_id="task-1", patch={"status": "completed"}),
        _result(),
    ]
    FakeClient.trace = []
    outcome = asyncio.run(
        agent.run_async("do it", client_factory=FakeClient)  # type: ignore[arg-type]
    )
    assert outcome.ok is True
    assert outcome.session_id == "session"
    assert outcome.error is None


def test_failure_returns_not_ok_outcome_with_reason(tmp_path: Path):
    agent = _agent(tmp_path)
    FakeClient.events = [
        _system("task_started", task_id="task-1"),
        _result(error=True),
        _system("task_updated", task_id="task-1", patch={"status": "completed"}),
        _result(error=True),
    ]
    outcome = asyncio.run(
        agent.run_async("do it", client_factory=FakeClient)  # type: ignore[arg-type]
    )  # no raise — the Agent boundary turns failures into data
    assert outcome.ok is False
    assert "test agent:" in (outcome.error or "")


def test_error_result_is_labeled_with_agent_name(tmp_path: Path):
    agent = _agent(tmp_path, name="target agent")
    FakeClient.events = [_result(error=True)]
    outcome = asyncio.run(
        agent.run_async("do it", client_factory=FakeClient)  # type: ignore[arg-type]
    )
    assert outcome.ok is False
    assert "target agent: Claude Code" in (outcome.error or "")


def test_timeout_bounds_session_not_publish(tmp_path: Path):
    class StalledClient(FakeClient):
        async def receive_messages(self) -> AsyncIterator[object]:
            await asyncio.sleep(10)
            yield _result()

    agent = _agent(tmp_path, timeout_s=0.05)
    outcome = asyncio.run(
        agent.run_async("do it", client_factory=StalledClient)  # type: ignore[arg-type]
    )
    assert outcome.ok is False
    assert "TimeoutError" in (outcome.error or "")


# --- session engine (merged from test_sessions) ---------------------------------- #


def _run(coro) -> None:
    import asyncio

    asyncio.run(coro)


# --- base_options ------------------------------------------------------------ #


def test_base_options_common_knobs():
    options = base_options(
        cwd="/work", cfg={"model": "m", "claude_settings": {"a": 1}}, mcp_servers={}
    )
    assert options.cwd == "/work"
    assert options.model == "m"
    assert options.max_buffer_size == 64 * 1024 * 1024
    assert options.permission_mode == "bypassPermissions"
    assert options.env == {}
    assert options.settings == '{"a": 1}'
    # Omitted knobs fall back to the SDK defaults.
    assert options.agents is None
    assert options.stderr is None


def test_base_options_settings_passthrough():
    plain = base_options(cwd="/w", cfg={"claude_settings": "raw"}, mcp_servers={})
    assert plain.settings == "raw"
    missing = base_options(cwd="/w", cfg={}, mcp_servers={})
    assert missing.settings is None


# --- run_persistent_session --------------------------------------------------- #


def test_persistent_drains_active_task_before_final_result():
    # Turn 1 ends while the task is still running -> must NOT stop. The task
    # then completes and the follow-up result (nothing active) ends the run.
    FakeClient.events = [
        _system("task_started", task_id="task-1"),
        _result(),
        _system("task_updated", task_id="task-1", patch={"status": "completed"}),
        _result(),
    ]
    FakeClient.trace = []
    messages: list[object] = []
    results: list[ResultMessage] = []
    outcome = asyncio.run(
        run_persistent_session(
            "p",
            object(),  # type: ignore[arg-type]
            on_message=lambda m, s: messages.append(m),
            on_result=results.append,
            client_factory=FakeClient,
        )
    )
    assert outcome.session_id == "session"
    assert FakeClient.trace[-2] == "yield"  # broke on the 4th event (last two: final yield+exit)
    assert len(messages) == 4
    assert len(results) == 2


def test_persistent_hooks_run_per_message_and_result():
    FakeClient.events = [_result()]
    FakeClient.trace = []
    seen_ids: list[str | None] = []
    results: list[ResultMessage] = []
    asyncio.run(
        run_persistent_session(
            "p",
            object(),  # type: ignore[arg-type]
            on_message=lambda m, s: seen_ids.append(s),
            on_result=results.append,
            client_factory=FakeClient,
        )
    )
    assert seen_ids == ["session"]
    assert len(results) == 1


def test_persistent_stream_end_without_result_errors():
    FakeClient.events = [_system("task_started", task_id="task-1")]
    with pytest.raises(RuntimeError, match="before ResultMessage"):
        _run(
            run_persistent_session(
                "p", object(), client_factory=FakeClient  # type: ignore[arg-type]
            )
        )


def test_persistent_unfinished_task_errors():
    FakeClient.events = [_system("task_started", task_id="task-1"), _result()]
    with pytest.raises(
        RuntimeError, match="unfinished background tasks: task-1"
    ):
        _run(
            run_persistent_session(
                "p", object(), client_factory=FakeClient  # type: ignore[arg-type]
            )
        )


def test_persistent_error_result_raised_after_draining():
    FakeClient.events = [_result(error=True)]
    FakeClient.trace = []
    with pytest.raises(RuntimeError, match="error result"):
        _run(
            run_persistent_session(
                "p", object(), client_factory=FakeClient  # type: ignore[arg-type]
            )
        )
    assert FakeClient.trace[-1] == "exit"


def test_persistent_error_result_carries_label():
    FakeClient.events = [_result(error=True)]
    FakeClient.trace = []
    with pytest.raises(
        RuntimeError, match="target agent: Claude Code returned an error result"
    ):
        _run(
            run_persistent_session(
                "p", object(), client_factory=FakeClient,  # type: ignore[arg-type]
                error_label="target agent",
            )
        )


# --- next_prompt follow-up turns --------------------------------------------- #


class TurnClient(FakeClient):
    """Yields one ResultMessage per query, then stops the turn."""

    def __init__(self, *, options: object) -> None:
        super().__init__(options=options)
        self.turns = 0

    async def query(self, prompt: str) -> None:
        await super().query(prompt)
        self.turns += 1

    async def receive_messages(self) -> AsyncIterator[object]:
        # Each query starts exactly one turn; skip events consumed by an
        # earlier turn.
        for event in FakeClient.events[self.turns - 1]:
            FakeClient.trace.append("yield")
            yield event


def test_persistent_followup_turns_until_callback_satisfied():
    # Turn 1: callback says continue -> follow-up query. Turn 2: callback
    # says done -> session ends normally.
    FakeClient.events = [[_result()], [_result()]]
    FakeClient.trace = []
    prompts: list[str] = []

    def next_prompt(_result):
        prompts.append("called")
        return "continue" if len(prompts) == 1 else None

    outcome = asyncio.run(
        run_persistent_session(
            "p",
            object(),  # type: ignore[arg-type]
            next_prompt=next_prompt,
            client_factory=TurnClient,
        )
    )
    assert outcome.session_id == "session"
    assert prompts == ["called", "called"]
    assert "query:continue" in FakeClient.trace
    assert FakeClient.trace[0] == "enter" and FakeClient.trace[-1] == "exit"


def test_persistent_followup_not_consulted_after_error():
    FakeClient.events = [[_result(error=True)]]
    FakeClient.trace = []
    calls: list[bool] = []

    def next_prompt(_result):
        calls.append(True)
        return "continue"

    with pytest.raises(RuntimeError, match="error result"):
        _run(
            run_persistent_session(
                "p",
                object(),  # type: ignore[arg-type]
                next_prompt=next_prompt,
                client_factory=TurnClient,
            )
        )
    assert calls == []  # error result short-circuits the callback


def test_persistent_no_callback_single_turn():
    FakeClient.events = [[_result()]]
    FakeClient.trace = []
    asyncio.run(
        run_persistent_session(
            "p", object(), client_factory=TurnClient  # type: ignore[arg-type]
        )
    )
    assert FakeClient.trace.count("query:p") == 1  # initial query only
    assert "query:continue" not in FakeClient.trace
