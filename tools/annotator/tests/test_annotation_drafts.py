"""Tests for the named-draft store (shared, accessed by name)."""

from __future__ import annotations

import json
import threading

import pytest

from annotator.annotation_drafts import (
    AnnotationDrafts,
    DraftsError,
    drafts,
)


def _shape_doc(name: str = "S") -> dict:
    return {
        "static shapes": {name: {"properties": [{"name": "x", "type": "number"}]}},
        "shape guards": [],
        "shape bindings": [],
        "type guards": [],
    }


@pytest.fixture(autouse=True)
def _clear_singleton():
    drafts().clear()
    yield
    drafts().clear()


def test_add_rejects_duplicate_names():
    store = AnnotationDrafts()
    store.add("a")
    with pytest.raises(DraftsError, match="already exists"):
        store.add("a")


def test_get_unknown_draft_raises():
    store = AnnotationDrafts()
    with pytest.raises(DraftsError, match="unknown draft"):
        store.get("missing")


def test_lock_unknown_draft_raises():
    store = AnnotationDrafts()
    with pytest.raises(DraftsError, match="unknown draft"):
        store.lock("missing")


def test_concurrent_mutations_under_per_draft_lock():
    store = AnnotationDrafts()
    doc = store.add("shared")
    lock = store.lock("shared")
    errors: list[Exception] = []

    def mutate(index: int):
        try:
            with lock:
                doc.add_shape(
                    f"T{index}", {"properties": [{"name": "x", "type": "number"}]}
                )
        except Exception as exc:  # noqa: BLE001 — recorded for the assert
            errors.append(exc)

    threads = [
        threading.Thread(target=mutate, args=(index,)) for index in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # dict writes under the lock never lose an update
    assert len(doc.static_shapes) == 8


def test_disjoint_drafts_snapshot_concurrently():
    store = AnnotationDrafts()
    a = store.add("a")
    b = store.add("b")
    a.load_from_dict(_shape_doc("A"))
    b.load_from_dict(_shape_doc("B"))

    snapshots: list[str] = []

    def snap_a():
        with store.lock("a"):
            snapshots.append(json.dumps(a.to_dict()))

    def mutate_b():
        with store.lock("b"):
            b.load_from_dict(_shape_doc("B2"))

    t1 = threading.Thread(target=snap_a)
    t2 = threading.Thread(target=mutate_b)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert "A" in snapshots[0]
    assert "B2" in b.static_shapes
