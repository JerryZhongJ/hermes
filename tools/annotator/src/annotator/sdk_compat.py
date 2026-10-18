"""SDK compatibility shims applied at container startup.

``claude_agent_sdk`` hard-requires a ``signature`` on every thinking block.
Two sources produce signature-less blocks in our stack:

1. third-party gateways whose SSE streams omit ``signature`` (the host-side
   signature_proxy patches the wire, but cannot help once the CLI drops an
   EMPTY signature before emitting the message);
2. the CLI itself, when context management (microcompact) synthesizes replay
   history for a session -- those thinking blocks are CLI-made and never
   passed through the API at all (observed: subagent messages with
   ``context_management`` and a bare thinking block).

The signature is only ever consumed by the real Anthropic backend; nothing
downstream of the parser reads it. So: backfill a non-empty placeholder on
every thinking dict inside the raw payload, before the parser runs.
"""

from __future__ import annotations

import logging

LOGGER = logging.getLogger("annotator.sdk_compat")

_PLACEHOLDER = "annotator-sdk-compat-placeholder"
_installed = False


def _fix_thinking(obj) -> None:
    if isinstance(obj, dict):
        if obj.get("type") == "thinking" and not obj.get("signature"):
            obj["signature"] = _PLACEHOLDER
        for value in obj.values():
            _fix_thinking(value)
    elif isinstance(obj, list):
        for value in obj:
            _fix_thinking(value)


def install() -> None:
    """Wrap ``parse_message`` so missing signatures never abort a run."""
    global _installed
    if _installed:
        return
    try:
        from claude_agent_sdk._internal import client as internal_client
        from claude_agent_sdk._internal import message_parser
    except ImportError:  # SDK layout changed: fail loudly, not silently
        LOGGER.warning("sdk_compat: claude_agent_sdk internals not found")
        return

    original = message_parser.parse_message

    def parse_message_with_sigfix(data):  # noqa: ANN001, ANN202
        _fix_thinking(data)
        return original(data)

    message_parser.parse_message = parse_message_with_sigfix
    # _internal/client.py binds parse_message by name at import time; late
    # importers (client.py's function-level import) resolve via the module,
    # which is already patched.
    internal_client.parse_message = parse_message_with_sigfix
    _installed = True
    LOGGER.info("sdk_compat: thinking-signature backfill installed")
