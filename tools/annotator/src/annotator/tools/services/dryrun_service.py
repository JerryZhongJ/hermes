"""Host-side dryrun feedback service for the annotator.

Runs on the host and serially polls request-per-file jobs under
``attempt_dir/.feedback/requests``.  Every request has an independent annotation
snapshot and response, all keyed by the request UUID, so concurrent MCP calls do
not overwrite each other's files.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time
from pathlib import Path

from ..utils import atomic_write_json

LOGGER = logging.getLogger("dryrun_service")

FEEDBACK_SUBDIR = ".feedback"
REQUESTS_SUBDIR = "requests"
RESPONSES_SUBDIR = "responses"
SNAPSHOTS_SUBDIR = "snapshots"
POLL_INTERVAL_S = 0.1
RUN_TIMEOUT_S = 30
_REQ_ID_RE = re.compile(r"[0-9a-f]{32}")


def _error(req_id: str, message: str) -> dict:
    return {"req_id": req_id, "ok": False, "stdout": "", "stderr": message}


def _validated_request(
    path: Path, attempt_dir: Path
) -> tuple[dict | None, Path | None, dict | None]:
    """Read and validate one request against its request-per-file identity."""
    file_req_id = path.stem
    try:
        req = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, None, _error(file_req_id, f"invalid request JSON: {exc}")
    if not isinstance(req, dict):
        return None, None, _error(file_req_id, "request must be a JSON object")
    if not _REQ_ID_RE.fullmatch(file_req_id):
        return None, None, _error(
            file_req_id,
            "request filename must be a 32-character lowercase hex req_id",
        )
    if req.get("req_id") != file_req_id:
        return None, None, _error(
            file_req_id, "payload req_id does not match request filename"
        )
    expected_annotation = (
        f"{FEEDBACK_SUBDIR}/{SNAPSHOTS_SUBDIR}/{file_req_id}.json"
    )
    if req.get("annotation") != expected_annotation:
        return None, None, _error(
            file_req_id,
            f"annotation must be {expected_annotation}",
        )
    candidate = attempt_dir / expected_annotation
    try:
        annotation = candidate.resolve(strict=True)
    except OSError as exc:
        return None, None, _error(file_req_id, f"annotation snapshot unavailable: {exc}")
    if candidate.is_symlink() or annotation != candidate.absolute() or not annotation.is_file():
        return None, None, _error(file_req_id, "annotation snapshot is not a safe same-id file")
    return req, annotation, None


def _protocol_dir(root: Path, name: str) -> Path:
    path = root / FEEDBACK_SUBDIR / name
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.resolve() != path.absolute():
        raise OSError(f"unsafe dryrun protocol directory: {path}")
    return path


def _namespace_dirs(attempt_dir: Path, source_name: str) -> list[tuple[Path, Path]]:
    """The one feedback namespace: (workdir, source) for the run root.

    The parallel workflows' workers share the coordinator's workdir and
    drafts store — isolation is by draft name, not by directory.
    """
    return [(attempt_dir, attempt_dir / source_name)]


def serve(
    attempt_dir: Path,
    source_name: str,
    binary: Path,
    stop_event: threading.Event,
) -> None:
    """Serially process independent request files until ``stop_event`` is set.

    One service thread covers the attempt root's feedback namespace, so
    concurrent agents (coordinator + parallel workers) share one stateless
    compiler broker without sharing any mutable state.
    """
    attempt_dir = attempt_dir.resolve()
    try:
        _protocol_dir(attempt_dir, REQUESTS_SUBDIR)
        _protocol_dir(attempt_dir, RESPONSES_SUBDIR)
        _protocol_dir(attempt_dir, SNAPSHOTS_SUBDIR)
    except OSError as exc:
        LOGGER.error("could not initialize dryrun protocol directories: %s", exc)
        return

    while not stop_event.is_set():
        # One work snapshot: the root namespace.
        pending: list[tuple[Path, Path, Path]] = [
            (namespace_dir, req, namespace_source)
            for namespace_dir, namespace_source in _namespace_dirs(
                attempt_dir, source_name
            )
            for req in sorted(
                (namespace_dir / FEEDBACK_SUBDIR / REQUESTS_SUBDIR).glob("*.json")
            )
        ]
        if not pending:
            time.sleep(POLL_INTERVAL_S)
            continue

        for namespace_dir, req_path, namespace_source in pending:
            req, annotation, error = _validated_request(req_path, namespace_dir)
            if error is not None:
                res = error
            else:
                assert req is not None and annotation is not None
                res = _run(
                    req, binary, namespace_source, annotation, namespace_dir
                )
            namespace_responses = (
                namespace_dir / FEEDBACK_SUBDIR / RESPONSES_SUBDIR
            )
            try:
                atomic_write_json(namespace_responses / req_path.name, res)
            except OSError as exc:
                LOGGER.error(
                    "could not write dryrun response %s: %s", req_path.name, exc
                )
                time.sleep(POLL_INTERVAL_S)
                continue
            req_path.unlink(missing_ok=True)


def _run(
    req: dict,
    binary: Path,
    source: Path,
    annotation: Path,
    attempt_dir: Path,
) -> dict:
    req_id = req["req_id"]
    cmd = [str(binary), str(source), "-annotation-file", str(annotation)]
    if req.get("from_line"):
        cmd += ["-from-line", str(req["from_line"])]
    if req.get("to_line"):
        cmd += ["-to-line", str(req["to_line"])]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
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
        return _error(req_id, f"annotation-dryrun timed out after {RUN_TIMEOUT_S}s")
    except OSError as exc:
        return _error(req_id, f"failed to run annotation-dryrun: {exc}")
