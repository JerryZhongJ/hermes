"""Named annotation drafts shared by every agent in the container.

One process-wide :class:`AnnotationDrafts` holds the annotation documents by
name. There is no isolation layer: every agent accesses the store directly by
draft name, and the names it may use are simply the ones the orchestrator
passed to its tool factories (at MCP-construction time, never by the agent
itself). Each draft guards its own document with a lock, so a snapshot taken
under the lock is never torn by a concurrent mutation.

Cross-agent transfer is in-memory: producer and consumer agents live in the
same process, so a draft created by one launcher is immediately readable by
any other agent that received its name. Saving to disk (``save_annotations``)
is product output, not transfer.

``AnnotationDocument`` keeps its role as the schema/validator for ONE draft's
content; drafts are disjoint so each guards its own document with a lock.
"""

from __future__ import annotations

import threading
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tools.annotation_tool import AnnotationDocument


class DraftsError(ValueError):
    """Unknown draft or ambiguous default."""


class AnnotationDrafts:
    """The container of named drafts; access is by name, locking per draft."""

    def __init__(self) -> None:
        self._docs: dict[str, tuple[AnnotationDocument, threading.RLock]] = {}
        self._lock = threading.Lock()

    def add(
        self, name: str, doc: AnnotationDocument | None = None
    ) -> AnnotationDocument:
        """Create one draft (empty unless a doc is given); name must be new."""
        from .tools.annotation_tool import AnnotationDocument
        from .tools.checklist_tool import reasons

        if not name:
            raise DraftsError("draft name must be non-empty")
        with self._lock:
            if name in self._docs:
                raise DraftsError(f"draft {name!r} already exists")
            document = doc if doc is not None else AnnotationDocument.empty()
            self._docs[name] = (document, threading.RLock())
            reasons().register(name)
            return document

    def get(self, name: str) -> AnnotationDocument:
        return self._entry_or_raise(name)[0]

    def lock(self, name: str) -> threading.RLock:
        """The draft's own lock — mutations and snapshots run under it."""
        return self._entry_or_raise(name)[1]

    def _entry_or_raise(self, name: str):
        with self._lock:
            entry = self._docs.get(name)
        if entry is None:
            raise DraftsError(f"unknown draft {name!r}")
        return entry

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._docs

    def names(self) -> list[str]:
        """Every draft name in the store (creation order)."""
        with self._lock:
            return list(self._docs)

    def drop(self, name: str) -> None:
        from .tools.checklist_tool import reasons

        with self._lock:
            self._docs.pop(name, None)
            reasons().drop(name)

    def clear(self) -> None:
        from .tools.checklist_tool import reasons

        with self._lock:
            self._docs.clear()
            for name in list(reasons().names()):
                reasons().drop(name)


# --- process singleton ------------------------------------------------------ #

_SINGLETON = AnnotationDrafts()


def drafts() -> AnnotationDrafts:
    """The process-wide drafts store shared by coordinator and target agents."""
    return _SINGLETON


def add_unique_draft(doc: AnnotationDocument | None = None) -> str:
    """Add one uniquely-named draft to the process store; return its name.

    Mostly for tests and tool factories: repeated calls never collide, so the
    process store needs no clearing between cases.
    """
    name = f"draft-{uuid.uuid4().hex[:8]}"
    drafts().add(name, doc)
    return name


__all__ = [
    "AnnotationDrafts",
    "DraftsError",
    "add_unique_draft",
    "drafts",
]
