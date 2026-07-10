# Annotator agent image — runs the claude backend's agent in-container.
#
# Build:  docker build -t annotator-agent:latest .
#
# The host annotator launches this image per attempt:
#   docker run --rm --env-file <key/proxy> -v <attempt_dir>:/work \
#     annotator-agent:latest python -m annotator.agent_worker
#
# Inside, agent_worker runs claude with permission_mode=bypassPermissions and
# no in-process sandbox — the container IS the isolation boundary.

FROM python:3.13-slim

# nodejs gives the agent an extra interpreter to execute / sanity-check JS
# ("the more tools the better"). The claude CLI itself does NOT need node:
# claude_agent_sdk ships a bundled native ELF binary it finds automatically.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency metadata first so source edits don't bust the install layer.
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY README.md ./README.md

# Pulls in: claude-agent-sdk (with the ~249MB bundled native claude binary),
# tree-sitter, tree-sitter-javascript, pydantic. No npm, no node toolchain
# beyond the apt nodejs above; tree-sitter wheels are manylinux (no build deps).
RUN pip install --no-cache-dir .

# HOME=/tmp: the bundled claude may write state under ~/.claude; point HOME at
# writable, ephemeral /tmp (container is discarded after the run).
# CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK=1: skip the 2s `claude -v` probe in
# connect() — the image pins the version.
# PYTHONUNBUFFERED=1: container logs reach the host capture promptly.
ENV HOME=/tmp \
    PYTHONUNBUFFERED=1 \
    CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK=1

# No ENTRYPOINT/CMD: the host runner passes `python -m annotator.agent_worker`
# explicitly, and ad-hoc verification uses `docker run ... <image> python -c ...`.
