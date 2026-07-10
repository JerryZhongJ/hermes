"""In-process MCP source tools for the annotator agent.

Shared helpers live in :mod:`annotator.tools.utils`; each tool keeps its own
module. :func:`build_source_mcp_servers` assembles all three, bound to the
single source file of an annotator run, so runners stay free of tool detail
(SRP: a runner drives an agent; it does not know which tools exist).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .dryrun_tool import make_dryrun_server
from .fold_tool import make_fold_server
from .locate_tool import make_locate_server


def build_source_mcp_servers(source: Path, workdir: Path) -> dict[str, Any]:
    """Build the three in-process MCP servers for one annotator run.

    ``source`` is the single JS file being annotated — ``locate``/``fold`` read
    it directly. ``workdir`` is the bind-mounted attempt directory, needed by
    the dryrun tools (for the annotation file, the ``.feedback`` request/
    response dropbox, and the run cache); the dryrun tools do NOT take the
    source — it is fixed at the host dryrun_service. Returns the
    ``mcp_servers`` mapping consumed by ``ClaudeAgentOptions``.
    """
    return {
        "source-fold": make_fold_server(source),
        "source-locate": make_locate_server(source),
        "dryrun": make_dryrun_server(workdir),
    }
