"""Verify the concurrency assumptions behind synchronous-blocking MCP tools.

``launch_hotspot_agent`` is being changed from thread-spawning to
synchronous-blocking: the coordinator issues N parallel tool calls in one
turn and each blocks until its target agent finishes. This only preserves
parallelism if (a) the SDK serves in-process MCP control requests as
concurrent asyncio tasks (not serialized in the receive loop) and (b) sync
blocking work wrapped in ``asyncio.to_thread`` actually overlaps.
"""

from __future__ import annotations

import asyncio
import time


def test_sdk_spawns_control_request_handlers() -> None:
    """The SDK receive loop spawns a task per control request (no await).

    Source-verified contract: ``Query._read_messages`` routes every
    ``control_request`` to ``_spawn_control_request_handler``, which calls
    ``self.spawn_task(...)`` and returns immediately — the loop never awaits
    a handler, so N parallel MCP tool calls execute as N concurrent tasks.
    This test pins the method's existence and non-blocking shape so an SDK
    upgrade that serializes them fails loudly here.
    """
    import inspect

    from claude_agent_sdk._internal.query import Query

    src = inspect.getsource(Query._spawn_control_request_handler)
    assert "spawn_task" in src and "await" not in src.split("docstring")[-1].split('"""')[-1]
    loop_src = inspect.getsource(Query._read_messages)
    assert "_spawn_control_request_handler" in loop_src


def test_to_thread_blocking_work_overlaps() -> None:
    """The real launch shape: sync blocking work (one job launcher) wrapped
    in to_thread runs on distinct worker threads concurrently."""
    import threading

    def blocking_work() -> str:
        time.sleep(0.5)
        return threading.current_thread().name

    async def run() -> list[str]:
        return await asyncio.gather(
            *(asyncio.to_thread(blocking_work) for _ in range(4))
        )

    start = time.monotonic()
    threads = asyncio.run(run())
    total = time.monotonic() - start
    # Concurrent: total ~= 0.5s. Serialized would be >= 2.0s.
    assert total < 1.0, f"to_thread work serialized: {total:.3f}s"
    assert len(set(threads)) > 1, "all work ran on one thread"
