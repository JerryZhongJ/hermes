"""Claude backend: orchestrates the agent inside a Docker container.

The host runner no longer imports ``claude_agent_sdk``. Instead it prepares the
attempt directory (bind-mounted at :data:`CONTAINER_WORK` in the container),
drops the prompt + non-secret config there, writes the API-key/proxy env to an
OUT-OF-VOLUME temp file, and launches the annotator Docker image. The
in-container worker (:mod:`annotator.agent_worker`) runs claude with
``bypassPermissions`` and no in-process sandbox, then writes the collected
messages + errors back into the volume for us to read.

The container is the sole isolation boundary — that is why every old
in-process restriction (SDK sandbox, ``can_use_tool`` path fence,
``setting_sources=[]`` isolation, ``tools=[...]`` allowlist, auto-memory
disable) has been removed and now lives only as comments in the worker.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from ..config import AgentConfig
from ..tools import run_host_setups
from . import AgentRun

LOGGER = logging.getLogger("claude_code")

# Default image tag; overridable via AgentConfig.docker_image.
DEFAULT_IMAGE = "annotator-agent:latest"

# Bind-mount target inside the container; must match agent_worker.WORK.
CONTAINER_WORK = "/work"

# Seconds the outer `timeout` waits after SIGTERM before SIGKILL.
KILL_GRACE = 10

# Extra slack the Python subprocess timeout adds on top of the agent timeout +
# kill grace, so the outer `timeout` always gets to clean up first.
SUBPROCESS_SLACK = 30

# Exit code coreutils `timeout` returns when it killed the monitored process
# (i.e. the agent run hit the wall-clock limit).
TIMEOUT_EXIT = 124


class ClaudeSdkRunner:
    """Claude backend that runs the agent inside a Docker container.

    Keeps the original ``run(prompt, attempt_dir) -> AgentRun`` contract so
    pipeline.py / annotate.py are untouched.
    """

    def __init__(self, config: AgentConfig, timeout_seconds: int) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds

    def run(self, prompt: str, attempt_dir: Path, source_name: str) -> AgentRun:
        if shutil.which("docker") is None:
            return AgentRun(
                errors=[
                    "docker not found on PATH; the claude backend runs the "
                    "agent in a container — install Docker or choose another agent"
                ]
            )

        self._write_prompt(attempt_dir, prompt)
        self._write_config(attempt_dir, source_name)
        env_file = self._write_env_file()
        try:
            completed = self._run_container(attempt_dir, env_file, source_name)
        except subprocess.TimeoutExpired:
            return AgentRun(errors=["agent timed out"])
        finally:
            self._unlink_quiet(env_file)

        self._log_container_output(completed)

        messages, errors = self._read_results(attempt_dir)
        # returncode 124 = coreutils `timeout` killed the run; <0 = the process
        # was terminated by a signal (happens when docker is slow to tear down a
        # SIGKILL'd container and the Python subprocess guard then kills it).
        # Either way the worker had no chance to flush results, so surface the
        # canonical timeout message instead of a cryptic exit code.
        if completed.returncode == TIMEOUT_EXIT or completed.returncode < 0:
            if not errors:
                errors = ["agent timed out"]
            return AgentRun(errors=errors, messages=messages)
        if completed.returncode != 0 and not errors:
            errors = [f"agent worker exited with code {completed.returncode}"]
        return AgentRun(errors=errors, messages=messages)

    # --- run preparation ---

    def _image(self) -> str:
        return self.config.docker_image or DEFAULT_IMAGE

    def _write_prompt(self, attempt_dir: Path, prompt: str) -> None:
        (attempt_dir / ".prompt.txt").write_text(prompt, encoding="utf-8")

    def _write_config(self, attempt_dir: Path, source_name: str) -> None:
        # Non-secret fields only: model + claude_settings + the source filename.
        # The API key travels via the env-file and never enters this (possibly
        # --keep-workdir'd) volume. ``source`` is the single JS file the
        # in-container tools bind to (locate/fold/dryrun); the host
        # knows it, the container worker reads it here rather than guessing.
        payload = {
            "model": self.config.model,
            "claude_settings": self.config.claude_settings,
            "source": source_name,
            "enabled_tools": self.config.enabled_tools,
        }
        (attempt_dir / ".agent_config.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )

    def _write_env_file(self) -> str:
        # Lives OUTSIDE the volume: docker reads it, it is not echoed into
        # `ps` / `docker inspect` argv, and it is unlinked right after the run.
        fd, path = tempfile.mkstemp(prefix="annotator-env-", suffix=".env")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for key, value in self.config.environment().items():
                handle.write(f"{key}={value}\n")
        return path

    # --- container launch ---

    def _run_container(
        self, attempt_dir: Path, env_file: str, source_name: str
    ) -> subprocess.CompletedProcess[str]:
        cmd = [
            "timeout",
            "-k",
            str(KILL_GRACE),
            str(self.timeout_seconds),
            "docker",
            "run",
            "--rm",
            # Run as the host uid:gid: the agent process must be non-root
            # (claude refuses bypassPermissions under root/sudo) AND it must be
            # able to write the bind-mounted attempt_dir (owned by the host user).
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--env-file",
            env_file,
            "-v",
            f"{attempt_dir}:{CONTAINER_WORK}",
            self._image(),
            "python",
            "-m",
            "annotator.agent_worker",
        ]
        # Host-side tool setup: each enabled tool runs its own host_setup (start its
        # own service thread / pre-generate its own data / find its own binary). The
        # orchestrator only starts and joins the returned threads around the docker
        # run — it knows no specific tool (no dryrun/jelly/feedback here).
        stop_event = threading.Event()
        host_threads = run_host_setups(
            attempt_dir, source_name, self.config, stop_event, self.config.enabled_tools,
        )
        for t in host_threads:
            t.start()
        LOGGER.info(
            "docker run image=%s timeout=%ss work=%s (host threads: %d)",
            self._image(), self.timeout_seconds, attempt_dir, len(host_threads),
        )
        try:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds + KILL_GRACE + SUBPROCESS_SLACK,
            )
        finally:
            stop_event.set()
            for t in host_threads:
                t.join(timeout=5)

    # --- result collection ---

    def _read_results(self, attempt_dir: Path) -> tuple[list[object], list[str]]:
        messages: list[object] = []
        errors: list[str] = []
        messages_path = attempt_dir / ".messages.json"
        errors_path = attempt_dir / ".errors.json"
        try:
            loaded = json.loads(messages_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                messages = loaded
        except (OSError, json.JSONDecodeError):
            LOGGER.warning("missing or invalid %s", messages_path)
        try:
            loaded = json.loads(errors_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                errors = [str(item) for item in loaded]
        except (OSError, json.JSONDecodeError):
            LOGGER.warning("missing or invalid %s", errors_path)
        return messages, errors

    def _log_container_output(self, completed: subprocess.CompletedProcess[str]) -> None:
        for line in completed.stdout.splitlines():
            if line.strip():
                LOGGER.info("[container] %s", line)
        for line in completed.stderr.splitlines():
            if line.strip():
                LOGGER.error("[container] %s", line)

    @staticmethod
    def _unlink_quiet(path: str) -> None:
        try:
            os.unlink(path)
        except OSError:
            pass
