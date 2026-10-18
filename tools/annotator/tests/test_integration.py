"""End-to-end integration test: real host services + real Jelly + annotator tools.

Spawns the callgraph_service and dataflow_service threads (they subprocess Jelly),
pre-generates the initial .jelly/cg.json (what pipeline.py will eventually do),
and drives the annotator tools through the full flow on ONE js file:
view_callgraph -> view_hot_value -> query_dataflow -> delete_call_edges ->
reanalyze (service reruns Jelly) -> view_callgraph (reloaded). Skipped when
Jelly is not available.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from annotator.tools.services.callgraph_service import serve, serve_dataflow
from annotator.tools.callgraph_tool import build_callgraph_tools
from annotator.tools.dataflow_tool import build_dataflow_tools

# one JS sample covering call graph, heat, a dataflow path, and an editable edge
SAMPLE_JS = """\
function hot(x) {
  return x;
}
function caller(a) {
  var r = hot(a);
  return r;
}
caller(1);
caller(2);
"""


def _jelly_bin() -> str | None:
    b = os.environ.get("JELLY_BIN")
    if b:
        return b
    w = shutil.which("jelly")
    if w:
        return w
    p = "/home/zjc/jelly/lib/main.js"
    if Path(p).exists():
        return f"node {p}"
    return None


@pytest.fixture
def jelly(tmp_path: Path):
    jbin = _jelly_bin()
    if not jbin:
        pytest.skip("jelly not available (npm link, or set JELLY_BIN, or /home/zjc/jelly/lib/main.js)")
    assert jbin is not None  # narrow for the type checker after the skip
    (tmp_path / "sample.js").write_text(SAMPLE_JS)
    (tmp_path / ".jelly").mkdir()
    # initial cg.json (host pre-gen — pipeline.py's job in production)
    r = subprocess.run(
        shlex_split(jbin) + ["-b", str(tmp_path), "--ignore-dependencies",
                             "-j", str(tmp_path / ".jelly" / "cg.json"), "sample.js"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        pytest.skip(f"jelly initial run failed: {r.stderr[-300:]}")
    stop = threading.Event()
    t1 = threading.Thread(target=serve, args=(tmp_path, "sample.js", jbin, stop), daemon=True)
    t2 = threading.Thread(target=serve_dataflow, args=(tmp_path, "sample.js", jbin, stop), daemon=True)
    t1.start()
    t2.start()
    yield tmp_path
    stop.set()
    t1.join(timeout=5)
    t2.join(timeout=5)


def shlex_split(s: str) -> list[str]:
    import shlex
    return shlex.split(s)


def _run(tool, args):
    return asyncio.run(tool.handler(args))


def _text(r):
    return r["content"][0]["text"]


def test_full_flow(jelly):
    wd = jelly
    cg = {t.name: t for t in build_callgraph_tools(wd / "sample.js", wd)}
    df = {t.name: t for t in build_dataflow_tools(wd / "sample.js", wd)}

    # 1. view auto-loads cg.json; grab a callsite + callee range from the output
    v = _text(_run(cg["view_callgraph"], {}))
    assert "call site(s)" in v
    callsite = re.search(r"callsite (\d+:\d+:\d+:\d+)", v)
    callee = re.search(r"-> (\d+:\d+:\d+:\d+)", v)
    assert callsite and callee, v
    cs, ce = callsite.group(1), callee.group(1)

    # 2. heat
    assert "Heat" in _text(_run(cg["view_hot_value"], {}))

    # 3. Dataflow queues work without blocking; retry until its keyed cache is ready.
    deadline = time.time() + 90
    dr = ""
    while time.time() < deadline:
        dr = _text(_run(df["query_dataflow"], {"source": cs}))
        if "not yet ready" not in dr:
            break
        time.sleep(0.5)
    assert "source:" in dr

    # 4. delete edge -> async reanalyze (service reruns Jelly with --call-edge-priors)
    _run(cg["delete_call_edges"], {"edges": [{"callsite": cs, "callee": ce}]})
    deadline = time.time() + 90
    last = ""
    while time.time() < deadline:
        last = _text(_run(cg["view_callgraph"], {}))
        if "stale: refresh pending" not in last:
            break
        time.sleep(0.5)
    assert "stale: refresh pending" not in last, "reanalyze did not complete in time"
    assert "revision 2" in last  # reloaded graph after reanalyze


# --- coordinator -> Task -> worker -> merge: the shared-draft chain ---------- #


def test_parallel_worker_chain_smoke(tmp_path):
    """The native-subagent migration's tool chain, driven end to end without
    a real Claude session: the worker bootstraps its draft (create_draft),
    annotates it (open-access annotation tools), and the coordinator merges
    the workers' drafts into ``main`` (copy_annotations) — through the same
    open-access tool constructions the coordinator session exposes and the
    workers inherit.
    """
    import asyncio

    from annotator.annotation_drafts import drafts
    from annotator.tools.annotation_tool import build_annotation_tools
    from annotator.tools.checklist_tool import build_checklist_tools
    from annotator.tools.dryrun_tool import run_dryrun_sync

    source = tmp_path / "input.js"
    source.write_text("function f(o) { var t = o.x + 1; o.y = t; return t; }\n")
    # The coordinator's open-access constructions (drafts_access=None), the
    # same ones build_mcp_servers wires into the shared MCP servers.
    annotation_tools = {
        t.name: t for t in build_annotation_tools(source, tmp_path)
    }
    checklist_tools = {
        t.name: t
        for t in build_checklist_tools(source, run_dryrun_sync(tmp_path, None))
    }

    def call(tools, name, args):
        return asyncio.run(tools[name].handler(args))

    def text(result):
        assert not result.get("is_error"), result
        return result["content"][0]["text"]

    try:
        drafts().clear()
        # --- two workers, each on its own assigned draft ----------------- #
        for n in (1, 2):
            text(call(annotation_tools, "create_draft", {"draft": f"hotspot:{n}"}))
            r = call(
                annotation_tools,
                "add_annotation",
                {
                    "kind": "static_shape",
                    "shape": f"P{n}",
                    "draft": f"hotspot:{n}",
                    # structurally different per worker: identical shapes
                    # would fold into one during the merge (by design)
                    "annotation": {
                        "properties": [
                            {"name": "x" if n == 1 else "y", "type": "number"}
                        ]
                    },
                },
            )
            assert not r.get("is_error"), r
            # A binding (not a bare shape) is what the merge copies over;
            # each worker binds a DIFFERENT range (one binding per range).
            r = call(
                annotation_tools,
                "add_annotation",
                {
                    "kind": "shape_binding",
                    "draft": f"hotspot:{n}",
                    "annotation": {
                        "target range": f"1:{10 + n}:1:14",
                        "shape": f"P{n}",
                    },
                },
            )
            assert not r.get("is_error"), r
            listing = text(
                call(
                    annotation_tools,
                    "list_annotations",
                    {"draft": f"hotspot:{n}"},
                )
            )
            assert "2 annotation(s)" in listing
        # A worker's annotations stay in its own draft.
        own = text(
            call(annotation_tools, "list_annotations", {"draft": "hotspot:2"})
        )
        assert "2 annotation(s)" in own
        drafts().add("main")

        # --- the coordinator merges into main ----------------------------- #
        for n in (1, 2):
            r = call(
                annotation_tools,
                "copy_annotations",
                {"source": f"hotspot:{n}", "dest": "main"},
            )
            assert not r.get("is_error"), r
        merged = text(
            call(annotation_tools, "list_annotations", {"draft": "main"})
        )
        # Both workers' bindings + their referenced shapes landed in main.
        assert "4 annotation(s)" in merged and "P1" in merged and "P2" in merged
    finally:
        drafts().clear()
