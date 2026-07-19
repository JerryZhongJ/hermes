"""Tests for build_source_mcp_servers tool selection (annotator/tools decoupling)."""

from __future__ import annotations

from pathlib import Path

from annotator.tools import build_source_mcp_servers, run_host_setups


def test_default_is_empty_no_tools(tmp_path: Path):
    src = tmp_path / "a.js"
    src.write_text("", encoding="utf-8")
    # Nothing is enabled by default — every tool must be listed in config.enabled_tools.
    servers = build_source_mcp_servers(src, tmp_path)
    assert servers == {}


def test_explicit_enable_jelly(tmp_path: Path):
    src = tmp_path / "a.js"
    src.write_text("", encoding="utf-8")
    servers = build_source_mcp_servers(src, tmp_path, ["source-fold", "jelly", "jelly-dataflow"])
    assert set(servers) == {"source-fold", "jelly", "jelly-dataflow"}
    assert servers["jelly"]["name"] == "jelly"
    assert servers["jelly-dataflow"]["name"] == "jelly-dataflow"


def test_unknown_names_ignored(tmp_path: Path):
    src = tmp_path / "a.js"
    src.write_text("", encoding="utf-8")
    servers = build_source_mcp_servers(src, tmp_path, ["source-fold", "nonsense", ""])
    assert set(servers) == {"source-fold"}


def test_empty_enabled_means_no_tools(tmp_path: Path):
    src = tmp_path / "a.js"
    src.write_text("", encoding="utf-8")
    servers = build_source_mcp_servers(src, tmp_path, [])
    assert servers == {}


# --- host_setup (host-side: each tool returns un-started Threads) --- #

def _cfg(feedback=None, jelly=None):
    from types import SimpleNamespace
    return SimpleNamespace(feedback_bin_dir=feedback, jelly_bin=jelly)


def test_run_host_setups_default_empty(tmp_path: Path):
    import threading
    threads = run_host_setups(tmp_path, "a.js", _cfg(), threading.Event())
    assert threads == []  # nothing enabled by default


def test_run_host_setups_fold_locate_noop(tmp_path: Path):
    import threading
    threads = run_host_setups(tmp_path, "a.js", _cfg(), threading.Event(), ["source-fold", "source-locate"])
    assert threads == []  # fold/locate have no host needs


def test_run_host_setups_dryrun_without_binary(tmp_path: Path):
    import threading
    threads = run_host_setups(tmp_path, "a.js", _cfg(), threading.Event(), ["dryrun"])
    assert threads == []  # feedback_bin_dir unset -> dryrun host_setup returns []


def test_run_host_setups_jelly_without_binary(tmp_path: Path):
    import threading
    threads = run_host_setups(tmp_path, "a.js", _cfg(), threading.Event(), ["jelly", "jelly-dataflow"])
    assert threads == []  # jelly_bin unset -> both return []
