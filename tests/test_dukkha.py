"""Tests for the dukkha clinging/leak profiler."""

from __future__ import annotations

import gc
import weakref

import pytest

from buddhism.dukkha import (
    Attachment,
    ClingingDetected,
    find_cycles,
    let_go,
    observe,
    retention_path,
)


class _Bell:
    def __init__(self, name: str = "?") -> None:
        self.name = name


# --------------------------------------------------------------------------- #
# Attachment
# --------------------------------------------------------------------------- #


def test_attachment_alive_then_released():
    bell = _Bell("a")
    a = Attachment(bell)
    assert a.alive
    bell = None  # noqa: F841
    gc.collect()
    assert not a.alive


def test_attachment_finds_referrers():
    bell = _Bell("a")
    keepers = [bell]
    att = Attachment(bell)
    bell = None  # noqa: F841
    gc.collect()
    refs = att.referrers()
    # The list `keepers` must show up as a referrer.
    assert any(r is keepers for r in refs)


def test_attachment_to_unweakable_object_falls_back():
    # Tuples cannot be weak-referenced, but Attachment must still construct.
    t = (1, 2, 3)
    a = Attachment(t)
    # alive is best-effort True via gc scan; we don't assert on falsy
    # liveness for non-weakable objects, only that no exception was raised.
    assert a.typename == "tuple"


# --------------------------------------------------------------------------- #
# observe()
# --------------------------------------------------------------------------- #


def test_observe_detects_retained_objects():
    keepers: list = []
    with observe() as r:
        for i in range(3):
            keepers.append(_Bell(f"b{i}"))
    assert r.type_counts.get("_Bell", 0) == 3
    assert "_Bell" in r.text_report()


def test_observe_ignores_objects_freed_inside_block():
    with observe() as r:
        for _ in range(5):
            _Bell("ephemeral")  # not retained
        gc.collect()
    assert r.type_counts.get("_Bell", 0) == 0


def test_observe_attachments_returned():
    keepers: list = []
    with observe() as r:
        keepers.append(_Bell("retained"))
    atts = r.attachments()
    bells = [a for a in atts if a.typename == "_Bell"]
    assert len(bells) >= 1
    assert any(a.alive for a in bells)


# --------------------------------------------------------------------------- #
# find_cycles
# --------------------------------------------------------------------------- #


def test_find_cycles_detects_two_node_cycle():
    class Node:
        pass

    a = Node()
    b = Node()
    a.peer = b
    b.peer = a
    cycles = find_cycles([a, b])
    flat = {id(o) for c in cycles for o in c}
    assert id(a) in flat and id(b) in flat


def test_find_cycles_detects_self_loop():
    class Node:
        pass

    a = Node()
    a.me = a
    cycles = find_cycles([a])
    assert any(any(o is a for o in c) for c in cycles)


def test_find_cycles_no_false_positive_on_chain():
    class Node:
        pass

    a = Node()
    b = Node()
    c = Node()
    a.next = b
    b.next = c  # no cycle
    cycles = find_cycles([a, b, c])
    assert cycles == []


# --------------------------------------------------------------------------- #
# let_go decorator
# --------------------------------------------------------------------------- #


def test_let_go_passes_when_no_retention():
    @let_go
    def pure(x):
        return x.name + "!"

    bell = _Bell("hi")
    assert pure(bell) == "hi!"


def test_let_go_raises_on_retained_argument():
    cache: list = []

    @let_go
    def leaky(x):
        cache.append(x)
        return None

    with pytest.raises(ClingingDetected):
        leaky(_Bell("x"))


def test_let_go_warn_mode():
    cache: list = []

    @let_go(raise_on_clinging=False)
    def leaky(x):
        cache.append(x)
        return None

    with pytest.warns(RuntimeWarning):
        leaky(_Bell("x"))


# --------------------------------------------------------------------------- #
# retention_path
# --------------------------------------------------------------------------- #


def test_retention_path_finds_some_path():
    bell = _Bell("rooted")
    # We deliberately put the bell in a module-level global so that it
    # has a clean root.
    globals()["__test_root_bell"] = bell
    try:
        path = retention_path(bell, max_depth=4)
        assert path  # not empty
        # Last element should be the bell itself.
        assert path[-1] is bell
    finally:
        del globals()["__test_root_bell"]
