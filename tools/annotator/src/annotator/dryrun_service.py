"""Host-side dryrun feedback service for the annotator.

Runs on the HOST (not inside the agent container). It polls
``attempt_dir/.feedback/req.json``, invokes the ``annotation-dryrun`` binary
(which lives only on the host — the agent in the container never touches
hermes), and writes ``res.json``. The in-container MCP tool ``dryrun_annotation``
writes the request / reads the response over the bind-mounted ``attempt_dir``
(↔ container ``/work``), so hermes never has to enter the container.

Single in-flight request: the agent calls tools serially, so a plain req/res
file pair keyed by ``req_id`` is enough (no queue, no locking beyond
unlink-after-read).
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from pathlib import Path

LOGGER = logging.getLogger("dryrun_service")

FEEDBACK_SUBDIR = ".feedback"
REQ_FILE = "req.json"
RES_FILE = "res.json"
POLL_INTERVAL_S = 0.1
RUN_TIMEOUT_S = 30


def serve(
    attempt_dir: Path,
    source_name: str,
    binary: Path,
    stop_event: threading.Event,
) -> None:
    """Poll ``attempt_dir/.feedback/req.json`` until ``stop_event`` is set.

    ``source_name`` is the single JS file being annotated (it lives in
    ``attempt_dir``); it is fixed for the whole run, so the request never
    carries it — only the (variable) annotation file does. On each request, run
    ``annotation-dryrun`` and write ``res.json``. Best-effort: a malformed
    request is dropped (the agent will time out and retry/re-report).
    """
    source = attempt_dir / source_name
    fb = attempt_dir / FEEDBACK_SUBDIR
    fb.mkdir(parents=True, exist_ok=True)
    req_path = fb / REQ_FILE
    res_path = fb / RES_FILE
    while not stop_event.is_set():
        if not req_path.exists():
            time.sleep(POLL_INTERVAL_S)
            continue
        try:
            req = json.loads(req_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            LOGGER.error("dropping bad req.json: %s", exc)
            req_path.unlink(missing_ok=True)
            continue
        res = _run(req, binary, source, attempt_dir)
        try:
            res_path.write_text(json.dumps(res), encoding="utf-8")
        except OSError as exc:
            LOGGER.error("could not write res.json: %s", exc)
        req_path.unlink(missing_ok=True)


def _run(req: dict, binary: Path, source: Path, attempt_dir: Path) -> dict:
    req_id = req.get("req_id")
    # The source file is fixed for the run (bound at serve() time as a host
    # path); the request carries only the variable annotation path, relative to
    # the workdir. Resolve it under attempt_dir so the binary always sees host
    # paths, never /work container paths.
    cmd = [str(binary), str(source)]
    ann = req.get("annotation")
    if ann:
        cmd += ["-annotation-file", str(attempt_dir / ann)]
    if req.get("from_line"):
        cmd += ["-from-line", str(req["from_line"])]
    if req.get("to_line"):
        cmd += ["-to-line", str(req["to_line"])]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_S,
            cwd=str(attempt_dir),
        )
        return {
            "req_id": req_id,
            "ok": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "req_id": req_id,
            "ok": False,
            "stdout": "",
            "stderr": f"annotation-dryrun timed out after {RUN_TIMEOUT_S}s",
        }
    except OSError as exc:
        return {
            "req_id": req_id,
            "ok": False,
            "stdout": "",
            "stderr": f"failed to run annotation-dryrun: {exc}",
        }
