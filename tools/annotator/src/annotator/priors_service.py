"""Host-side Jelly re-analysis service for call-edge priors.

Runs on the HOST (not inside the agent container — the container sandbox blocks
``node``). Polls ``attempt_dir/.jelly/req.json``; on each request writes the
contained override rules to a priors JSON, re-runs Jelly with
``--call-edge-priors`` to regenerate the call graph (``cg.json``), and writes
``res.json``. The in-container MCP tool ``reanalyze_call_graph`` drives it over
the bind-mounted attempt_dir (↔ container ``/work``).

Mirrors dryrun_service.py: single in-flight request (the agent calls tools
serially), req/res file pair keyed by ``req_id``, unlink-after-read.

Request shape (written by the agent tool):
    {"req_id": "<hex>", "rules": [{"callsite": locKey, "callee": locKey, "mode": "include"|"exclude"}]}
locKeys use annotator's callgraph.loc_key format (relative file path + 1-based
range), identical to Jelly's locKeyFromNode — so the same rules flow from the
annotator session into Jelly's --call-edge-priors unchanged.
"""

from __future__ import annotations

import json
import logging
import shlex
import subprocess
import threading
import time
from pathlib import Path

LOGGER = logging.getLogger("priors_service")

JELLY_SUBDIR = ".jelly"
REQ_FILE = "req.json"
RES_FILE = "res.json"
PRIOR_FILE = "prior.json"
CG_FILE = "cg.json"
POLL_INTERVAL_S = 0.1
RUN_TIMEOUT_S = 120


def serve(
    attempt_dir: Path,
    source_name: str,
    jelly_bin: str,
    stop_event: threading.Event,
    root: Path | None = None,
    callgraph: str = CG_FILE,
) -> None:
    """Poll ``attempt_dir/.jelly/req.json`` until ``stop_event`` is set.

    On each request, write the rules to ``.jelly/prior.json`` and re-run Jelly
    with ``--call-edge-priors`` to regenerate ``attempt_dir/<callgraph>``.
    ``source_name`` is the single JS file being annotated (entry for Jelly);
    ``root`` is Jelly's basedir (defaults to attempt_dir). Best-effort: a bad
    request is dropped (the agent times out and re-reports).
    """
    root = root or attempt_dir
    pd = attempt_dir / JELLY_SUBDIR
    pd.mkdir(parents=True, exist_ok=True)
    req_path = pd / REQ_FILE
    res_path = pd / RES_FILE
    prior_path = pd / PRIOR_FILE
    cg_path = pd / callgraph
    while not stop_event.is_set():
        if not req_path.exists():
            time.sleep(POLL_INTERVAL_S)
            continue
        try:
            req = json.loads(req_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            LOGGER.error("dropping bad priors req.json: %s", exc)
            req_path.unlink(missing_ok=True)
            continue
        res = _run(req, jelly_bin, root, source_name, prior_path, cg_path, attempt_dir)
        try:
            res_path.write_text(json.dumps(res), encoding="utf-8")
        except OSError as exc:
            LOGGER.error("could not write priors res.json: %s", exc)
        req_path.unlink(missing_ok=True)


def _run(
    req: dict,
    jelly_bin: str,
    root: Path,
    source_name: str,
    prior_path: Path,
    cg_path: Path,
    attempt_dir: Path,
) -> dict:
    req_id = req.get("req_id")
    rules = req.get("rules") or []
    try:
        prior_path.write_text(json.dumps({"version": 1, "rules": rules}), encoding="utf-8")
    except OSError as exc:
        return {"req_id": req_id, "ok": False, "stderr": f"could not write prior.json: {exc}"}
    cmd = shlex.split(str(jelly_bin)) + [
        "-b", str(root), "--ignore-dependencies",
        "-j", str(cg_path), "--call-edge-priors", str(prior_path), source_name,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=RUN_TIMEOUT_S, cwd=str(attempt_dir)
        )
        return {"req_id": req_id, "ok": proc.returncode == 0, "stderr": proc.stderr[-2000:]}
    except subprocess.TimeoutExpired:
        return {"req_id": req_id, "ok": False, "stderr": f"jelly timed out after {RUN_TIMEOUT_S}s"}
    except OSError as exc:
        return {"req_id": req_id, "ok": False, "stderr": f"failed to run jelly: {exc}"}


def serve_dataflow(
    attempt_dir: Path,
    source_name: str,
    jelly_bin: str,
    stop_event: threading.Event,
    root: Path | None = None,
) -> None:
    """Poll ``attempt_dir/.jelly/df_req.json`` until ``stop_event`` is set.

    Sibling of :func:`serve` for the dataflow tool: each request carries a
    ``source`` (``file:line:col``); the service re-runs Jelly with
    ``--dataflow-json .jelly/df.json --dataflow-source <source>`` and writes
    ``df_res.json``. Used by the agent's ``query_dataflow`` tool to trace
    may-flow from an arbitrary expression chosen at query time.
    """
    root = root or attempt_dir
    jd = attempt_dir / JELLY_SUBDIR
    jd.mkdir(parents=True, exist_ok=True)
    req_path = jd / "df_req.json"
    res_path = jd / "df_res.json"
    df_path = jd / "df.json"
    while not stop_event.is_set():
        if not req_path.exists():
            time.sleep(POLL_INTERVAL_S)
            continue
        try:
            req = json.loads(req_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            LOGGER.error("dropping bad df_req.json: %s", exc)
            req_path.unlink(missing_ok=True)
            continue
        res = _run_dataflow(req, jelly_bin, root, source_name, df_path, attempt_dir)
        try:
            res_path.write_text(json.dumps(res), encoding="utf-8")
        except OSError as exc:
            LOGGER.error("could not write df_res.json: %s", exc)
        req_path.unlink(missing_ok=True)


def _run_dataflow(
    req: dict,
    jelly_bin: str,
    root: Path,
    source_name: str,
    df_path: Path,
    attempt_dir: Path,
) -> dict:
    req_id = req.get("req_id")
    source = req.get("source")
    if not isinstance(source, str) or not source:
        return {"req_id": req_id, "ok": False, "stderr": "missing 'source' in df_req.json"}
    cmd = shlex.split(str(jelly_bin)) + [
        "-b", str(root), "--ignore-dependencies",
        "--dataflow-json", str(df_path), "--dataflow-source", source, source_name,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=RUN_TIMEOUT_S * 4, cwd=str(attempt_dir)
        )
        return {"req_id": req_id, "ok": proc.returncode == 0, "stderr": proc.stderr[-2000:]}
    except subprocess.TimeoutExpired:
        return {"req_id": req_id, "ok": False, "stderr": f"jelly dataflow timed out after {RUN_TIMEOUT_S * 4}s"}
    except OSError as exc:
        return {"req_id": req_id, "ok": False, "stderr": f"failed to run jelly: {exc}"}
