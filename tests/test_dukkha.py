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
    globals()["__test_root_bell"] = bell
    try:
        path = retention_path(bell, max_depth=4)
        assert path
        assert path[-1] is bell
    finally:
        del globals()["__test_root_bell"]


# --------------------------------------------------------------------------- #
# v0.2 features: allow=, transitive_depth, RetentionPath, pratitya_breakdown
# --------------------------------------------------------------------------- #


def test_let_go_allow_by_keyword_name():
    cache: list = []

    @let_go(allow={"config"})
    def constructor_like(config, *, debug=False):
        cache.append(config)
        return None

    constructor_like(_Bell("ok"))


def test_let_go_allow_by_positional_index():
    cache: list = []

    @let_go(allow={0})
    def store_first(x, y):
        cache.append(x)
        return None

    store_first(_Bell("ok"), _Bell("not-stored"))


def test_let_go_allow_does_not_whitelist_other_args():
    cache: list = []

    @let_go(allow={0})
    def leaky(x, y):
        cache.append(y)
        return None

    with pytest.raises(ClingingDetected):
        leaky(_Bell("ok"), _Bell("retained-but-not-allowed"))


def test_let_go_transitive_returned_structure_not_flagged():
    """``return [wrapper(x)]`` retains x via the returned list — but the
    list is returned to the caller, so this is not clinging."""

    @let_go(transitive_depth=3)
    def wrap_in_list(x):
        return [x]

    out = wrap_in_list(_Bell("inside"))
    assert isinstance(out, list)
    assert out[0].name == "inside"


def test_let_go_transitive_disabled_flags_returned_retention():
    @let_go(transitive_depth=0)
    def wrap_in_list(x):
        return [x]

    with pytest.raises(ClingingDetected):
        wrap_in_list(_Bell("inside"))


def test_retention_path_returns_dataclass_with_format():
    from buddhism.dukkha import RetentionPath

    bell = _Bell("rooted")
    globals()["__rp_root"] = bell
    try:
        path = retention_path(bell, max_depth=4)
        assert isinstance(path, RetentionPath)
        assert list(path) == path.path
        assert len(path) == len(path.path_types)
        formatted = path.format()
        assert "_Bell" in formatted
    finally:
        del globals()["__rp_root"]


def test_retention_path_iterable_like_v01():
    """v0.1 callers treated the return as a list. RetentionPath must be
    iterable, indexable, and len()-able to remain compatible."""
    bell = _Bell("rooted")
    globals()["__rp_compat_root"] = bell
    try:
        path = retention_path(bell, max_depth=4)
        seen = []
        for i, obj in enumerate(path):
            seen.append((i, type(obj).__name__))
        assert seen
        assert path[-1] is bell
    finally:
        del globals()["__rp_compat_root"]


def test_pratitya_breakdown_summarises_retained_reactive_graph():
    from buddhism import Cell, derive
    from buddhism.dukkha import observe

    held: list = []
    with observe() as r:
        c = Cell(1, name="c")
        d = derive(lambda: c() * 2, name="d")
        d()
        held.extend([c, d])

    breakdown = r.pratitya_breakdown()
    assert breakdown.cells >= 1
    assert breakdown.deriveds >= 1
    text = r.text_report()
    assert "Cell instances" in text


def test_pratitya_breakdown_empty_when_no_reactive_objects():
    held: list = []
    with observe() as r:
        held.append(_Bell("a"))
        held.append(_Bell("b"))
    breakdown = r.pratitya_breakdown()
    assert breakdown.is_empty()
