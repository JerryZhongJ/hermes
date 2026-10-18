"""Tests for build_source_mcp_servers tool selection (annotator/tools decoupling)."""

from __future__ import annotations

from pathlib import Path

import pytest

from annotator.annotation_drafts import add_unique_draft, drafts
from annotator.tools import (
    build_mcp_servers,
    resolve_enabled,
    run_host_setups,
)
from annotator.tools.annotation_tool import AnnotationDocument, build_annotation_tools


def _access(doc: AnnotationDocument | None = None):
    """A drafts access pair (names, default) over one fresh process-store draft."""
    name = add_unique_draft(doc)
    return ([name], name)


@pytest.fixture(autouse=True)
def _clear_singleton():
    drafts().clear()
    yield
    drafts().clear()


def test_annotation_server_always_present(tmp_path: Path):
    src = tmp_path / "a.js"
    src.write_text("", encoding="utf-8")
    # The annotation tools are MANDATORY: present even with no optional tools.
    servers = build_mcp_servers(src, tmp_path, _access(AnnotationDocument.empty()))
    assert set(servers) == {"annotations"}


def test_explicit_enable_jelly(tmp_path: Path):
    src = tmp_path / "a.js"
    src.write_text("", encoding="utf-8")
    servers = build_mcp_servers(
        src, tmp_path, _access(AnnotationDocument.empty()),
        ["source-fold", "jelly", "jelly-dataflow"]
    )
    # The mandatory annotation server accompanies requested optional tools.
    assert set(servers) == {
        "annotations", "source-fold", "jelly", "jelly-dataflow"
    }
    assert servers["jelly"]["name"] == "jelly"
    assert servers["jelly-dataflow"]["name"] == "jelly-dataflow"


def test_unknown_names_ignored(tmp_path: Path):
    src = tmp_path / "a.js"
    src.write_text("", encoding="utf-8")
    servers = build_mcp_servers(
        src, tmp_path, _access(AnnotationDocument.empty()),
        ["source-fold", "nonsense", ""]
    )
    assert set(servers) == {"annotations", "source-fold"}


def test_empty_enabled_means_only_annotations(tmp_path: Path):
    src = tmp_path / "a.js"
    src.write_text("", encoding="utf-8")
    servers = build_mcp_servers(src, tmp_path, _access(AnnotationDocument.empty()), [])
    assert set(servers) == {"annotations"}


def test_unknown_required_tool_fails_but_optional_remains_ignored(tmp_path: Path):
    src = tmp_path / "a.js"
    src.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown required tool"):
        build_mcp_servers(
            src,
            tmp_path,
            _access(AnnotationDocument.empty()),
            required_tools=("not-registered",),
        )
    servers = build_mcp_servers(
        src,
        tmp_path,
        _access(AnnotationDocument.empty()),
        ["not-registered"],
        required_tools=(),
    )
    assert set(servers) == {"annotations"}


def test_checklist_registry_builds_dryrun_projection(tmp_path: Path):
    src = tmp_path / "a.js"
    src.write_text("function f(o) { return o.x; }", encoding="utf-8")
    servers = build_mcp_servers(
        src,
        tmp_path,
        _access(AnnotationDocument.empty()),
        required_tools=("checklist",),
    )
    assert set(servers) == {"annotations", "checklist"}
    assert resolve_enabled(None, ("checklist",)) == ["checklist"]


def test_explicit_required_tools_override_default(tmp_path: Path):
    src = tmp_path / "a.js"
    src.write_text("", encoding="utf-8")
    servers = build_mcp_servers(
        src,
        tmp_path,
        _access(AnnotationDocument.empty()),
        ["source-locate"],
        required_tools=("dryrun",),
    )
    assert set(servers) == {"annotations", "dryrun", "source-locate"}
    assert resolve_enabled(["source-locate"], ()) == ["source-locate"]


def test_batch_shape_guard_tool_is_mandatory(tmp_path: Path):
    src = tmp_path / "a.js"
    src.write_text("function f(obj) { obj.x; }\n", encoding="utf-8")
    names = {
        tool.name
        for tool in build_annotation_tools(src, tmp_path, *_access())
    }
    assert "batch_add_guards" in names


def test_annotation_tools_share_one_document(tmp_path: Path):
    src = tmp_path / "a.js"
    src.write_text("", encoding="utf-8")
    doc = AnnotationDocument.empty()
    access = _access(doc)
    servers = build_mcp_servers(src, tmp_path, access, ["dryrun"])
    # Both the annotation server and the dryrun server operate on the same
    # draft (same name in the shared store).
    assert "annotations" in servers and "dryrun" in servers
    assert drafts().get(access[1]) is doc
    assert doc.to_dict()["static shapes"] == {}


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
    threads = run_host_setups(
        tmp_path, "a.js", _cfg(), threading.Event(), ["source-fold", "source-locate"]
    )
    assert threads == []  # fold/locate have no host needs

def test_run_host_setups_dryrun_without_binary(tmp_path: Path):
    import threading
    threads = run_host_setups(tmp_path, "a.js", _cfg(), threading.Event(), ["dryrun"])
    assert threads == []  # feedback_bin_dir unset -> dryrun host_setup returns []

def test_run_host_setups_jelly_without_binary(tmp_path: Path):
    import threading
    threads = run_host_setups(
        tmp_path, "a.js", _cfg(), threading.Event(), ["jelly", "jelly-dataflow"]
    )
    assert threads == []  # jelly_bin unset -> both return []

def test_run_host_setups_dryrun_checklist_single_service(tmp_path: Path):
    """dryrun + checklist share one host service — started exactly once."""
    import threading

    from annotator.tools import resolve_host_setup_tools

    assert resolve_host_setup_tools(None, ("dryrun", "checklist")) == [
        "dryrun",
    ]
    assert resolve_host_setup_tools(["dryrun"], ("checklist",)) == ["dryrun"]
    assert resolve_host_setup_tools(["checklist"], ("dryrun",)) == ["dryrun"]
    # Without a configured binary both specs still produce zero threads.
    threads = run_host_setups(
        tmp_path, "a.js", _cfg(), threading.Event(), None, ("dryrun", "checklist")
    )
    assert threads == []
