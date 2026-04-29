"""Tests for the dependent-origination reactive graph."""

from __future__ import annotations

import gc
import threading
import weakref

import pytest

from buddhism.pratitya import (
    Cell,
    Conditioned,
    Derived,
    SamsaraError,
    batch,
    cell,
    derive,
    derived,
    on_change,
)


# --------------------------------------------------------------------------- #
# Standalone Cell + Derived
# --------------------------------------------------------------------------- #


def test_cell_basic_get_set():
    a = Cell(1)
    assert a.get() == 1
    assert a() == 1
    a.set(2)
    assert a() == 2


def test_derive_recomputes_on_dependency_change():
    a = Cell(1)
    b = Cell(2)
    c = derive(lambda: a() + b())
    assert c() == 3
    a.set(10)
    assert c() == 12
    b.set(20)
    assert c() == 30


def test_derived_decorator_form():
    a = Cell(2)

    @derive
    def squared():
        return a() * a()

    assert isinstance(squared, Derived)
    assert squared() == 4
    a.set(5)
    assert squared() == 25


def test_derived_named_decorator_form():
    a = Cell(3)

    @derive(name="cubed")
    def cubed():
        return a() ** 3

    assert cubed._name == "cubed"
    assert cubed() == 27


def test_chained_derived_propagates():
    a = Cell(2)
    b = derive(lambda: a() + 1, name="b")
    c = derive(lambda: b() * 10, name="c")
    assert c() == 30
    a.set(4)
    assert c() == 50


def test_dependency_set_is_dynamic_per_evaluation():
    a = Cell(True)
    b = Cell(100)
    c = Cell(200)

    @derive
    def chosen():
        return b() if a() else c()

    assert chosen() == 100
    # b is a dependency; c is not.
    c.set(999)
    assert chosen() == 100  # not invalidated by c

    a.set(False)
    assert chosen() == 999

    # Now c matters; b doesn't.
    b.set(0)
    assert chosen() == 999
    c.set(7)
    assert chosen() == 7


def test_setting_cell_to_same_value_does_not_invalidate():
    a = Cell(5)
    calls = {"n": 0}

    @derive
    def d():
        calls["n"] += 1
        return a() * 2

    assert d() == 10
    assert calls["n"] == 1
    a.set(5)  # same value
    assert d() == 10
    assert calls["n"] == 1  # not recomputed


def test_setting_cell_to_equal_value_does_not_invalidate():
    a = Cell([1, 2, 3])
    calls = {"n": 0}

    @derive
    def length():
        calls["n"] += 1
        return len(a())

    assert length() == 3
    assert calls["n"] == 1
    a.set([1, 2, 3])  # equal but not identical
    assert length() == 3
    assert calls["n"] == 1


# --------------------------------------------------------------------------- #
# Cycle detection
# --------------------------------------------------------------------------- #


def test_circular_dependency_raises_samsara():
    holder: dict = {}

    def f():
        return holder["g"]() + 1

    def g():
        return holder["f"]() + 1

    holder["f"] = derive(f, name="f")
    holder["g"] = derive(g, name="g")

    with pytest.raises(SamsaraError):
        holder["f"]()


# --------------------------------------------------------------------------- #
# on_change subscriptions
# --------------------------------------------------------------------------- #


def test_on_change_fires_for_cell():
    a = Cell(1)
    received: list = []
    sub = on_change(a, lambda old, new: received.append((old, new)))
    a.set(2)
    a.set(3)
    assert received == [(1, 2), (2, 3)]
    sub.cancel()
    a.set(4)
    assert received == [(1, 2), (2, 3)]


def test_on_change_fires_for_derived_with_dirty_recompute():
    a = Cell(1)
    b = Cell(2)
    s = derive(lambda: a() + b())
    s()  # prime
    received: list = []
    on_change(s, lambda old, new: received.append((old, new)))
    a.set(10)
    assert received == [(3, 12)]


def test_batch_collapses_subscriber_fires():
    a = Cell(1)
    b = Cell(2)
    s = derive(lambda: a() + b())
    s()
    fires: list = []
    on_change(s, lambda old, new: fires.append(new))

    with batch():
        a.set(10)
        b.set(20)
        assert fires == []  # nothing fired inside the batch
    assert fires == [30]


def test_diamond_dependency_fires_subscriber_exactly_once():
    """Regression: a node reachable via multiple invalidation paths must
    not fire its subscriber more than once per Cell write."""
    a = Cell(1)
    # Build a diamond: a → b, a → c, b → d, c → d
    b = derive(lambda: a() + 1, name="b")
    c = derive(lambda: a() + 2, name="c")
    d = derive(lambda: b() + c(), name="d")
    d()  # prime

    fires: list = []
    on_change(d, lambda old, new: fires.append((old, new)))

    a.set(10)
    assert fires == [(5, 23)]  # exactly one fire, with correct old/new

    a.set(20)
    assert fires == [(5, 23), (23, 43)]


def test_subscriber_old_value_preserved_across_cascade():
    """The 'old' value passed to subscribers must be the value the node
    had *before* the cascade began, not after intermediate steps."""
    a = Cell(1)
    b = derive(lambda: a() * 2)
    b()

    received: list = []
    on_change(b, lambda old, new: received.append((old, new)))

    a.set(5)
    a.set(7)
    assert received == [(2, 10), (10, 14)]


def test_nested_batches_only_fire_once_at_outermost_close():
    a = Cell(1)
    s = derive(lambda: a() * 2)
    s()
    fires: list = []
    on_change(s, lambda old, new: fires.append(new))
    with batch():
        with batch():
            a.set(2)
            a.set(3)
        assert fires == []
    assert fires == [6]


# --------------------------------------------------------------------------- #
# Class-attribute descriptors
# --------------------------------------------------------------------------- #


def test_descriptor_class_basic():
    class Sheet(Conditioned):
        a = cell(1)
        b = cell(2)

        @derived
        def c(self):
            return self.a + self.b

    s = Sheet()
    assert s.c == 3
    s.a = 10
    assert s.c == 12


def test_descriptors_are_per_instance():
    class Sheet(Conditioned):
        x = cell(0)

        @derived
        def y(self):
            return self.x * 2

    s1 = Sheet()
    s2 = Sheet()
    s1.x = 3
    s2.x = 5
    assert s1.y == 6
    assert s2.y == 10
    s1.x = 100
    assert s2.y == 10  # not affected


def test_derived_descriptor_cannot_be_set():
    class Sheet(Conditioned):
        a = cell(1)

        @derived
        def b(self):
            return self.a + 1

    s = Sheet()
    with pytest.raises(AttributeError):
        s.b = 99


def test_descriptor_class_works_without_conditioned_base():
    class Plain:
        a = cell(1)

        @derived
        def b(self):
            return self.a + 1

    p = Plain()
    assert p.b == 2
    p.a = 10
    assert p.b == 11


# --------------------------------------------------------------------------- #
# The non-clinging invariant: graph does not keep nodes alive
# --------------------------------------------------------------------------- #


def test_derived_does_not_keep_unreferenced_dependents_alive():
    a = Cell(1)
    d = derive(lambda: a() * 2)
    d()
    weak_d = weakref.ref(d)
    del d
    gc.collect()
    assert weak_d() is None
    # The Cell still works; its WeakSet has cleaned up.
    a.set(5)
    assert a() == 5


def test_conditioned_instance_can_be_garbage_collected():
    class Sheet(Conditioned):
        a = cell(1)

        @derived
        def b(self):
            return self.a * 10

    s = Sheet()
    assert s.b == 10
    weak_s = weakref.ref(s)
    del s
    gc.collect()
    assert weak_s() is None


# --------------------------------------------------------------------------- #
# Threading: a Cell mutated from another thread is observable
# --------------------------------------------------------------------------- #


def test_cell_thread_safe_visibility():
    a = Cell(0)

    def writer():
        for i in range(1, 1001):
            a.set(i)

    t = threading.Thread(target=writer)
    t.start()
    t.join()
    assert a() == 1000


@pytest.mark.xfail(
    reason=(
        "v0.2 documented limitation: pratitya is single-writer / multi-reader "
        "in the trivial sense (per-node RLock prevents value tearing inside "
        "a single get/set) but the invalidation cascade and ContextVar-based "
        "batches do not cross OS threads, so concurrent readers can observe "
        "intermediate cascade states. A graph-level RLock is the v0.3 fix."
    ),
    strict=False,
)
def test_concurrent_read_write_no_torn_states():
    """Concurrent writer + readers should never observe torn cascade states."""
    a = Cell(0)
    b = Cell(0)

    @derive
    def s() -> int:
        # The invariant: when the writer keeps a == b, the sum is always 2*a.
        return a() + b()

    s()  # prime

    stop = threading.Event()
    seen_inconsistent = []

    def writer() -> None:
        for i in range(2000):
            with batch():
                a.set(i)
                b.set(i)
        stop.set()

    def reader() -> None:
        while not stop.is_set():
            v = s()
            # If the cascade tore, we'd see odd values (a even, b odd).
            # With single-writer batched writes, sum is always even.
            if v % 2 != 0:
                seen_inconsistent.append(v)

    w = threading.Thread(target=writer)
    rs = [threading.Thread(target=reader) for _ in range(2)]
    w.start()
    for r in rs:
        r.start()
    w.join()
    for r in rs:
        r.join()
    assert not seen_inconsistent, (
        f"saw torn reads (single-writer expectation violated): "
        f"{seen_inconsistent[:5]}"
    )


# --------------------------------------------------------------------------- #
# v0.2 fixes — equality_check, slots-only classes, strong-ref opt-in
# --------------------------------------------------------------------------- #


def test_equality_check_identity_avoids_user_eq():
    class TouchyEq:
        def __init__(self, x):
            self.x = x

        def __eq__(self, other):  # noqa: D401
            raise RuntimeError("__eq__ should not be called")

        def __hash__(self):
            return id(self)

    obj = TouchyEq(1)
    a = Cell(obj, equality_check="identity")
    a.set(obj)  # same object — short-circuits via `is`, not `==`
    assert a() is obj
    a.set(TouchyEq(2))  # different object — set proceeds
    # We never asked for ==, so RuntimeError must not have been raised.


def test_equality_check_callable_short_circuits():
    a = Cell(1.0, equality_check=lambda old, new: abs(old - new) < 0.5)
    fired: list = []
    on_change(a, lambda old, new: fired.append((old, new)))
    a.set(1.2)  # within 0.5 → no fire
    assert fired == []
    a.set(2.0)  # outside 0.5 → fires
    assert fired == [(1.0, 2.0)]


def test_slots_only_class_with_buddhism_nodes_slot_works():
    class Lean:
        __slots__ = ("__buddhism_nodes__", "__weakref__")

        a = cell(1)

        @derived
        def b(self):
            return self.a * 10

    obj = Lean()
    assert obj.b == 10
    obj.a = 7
    assert obj.b == 70


def test_slots_only_class_without_dict_or_nodes_slot_raises():
    class Doomed:
        __slots__ = ("__weakref__",)

        a = cell(1)

    obj = Doomed()
    with pytest.raises(TypeError, match="reactive descriptors"):
        _ = obj.a


def test_unweakreferenceable_class_refuses_by_default():
    class CantWeak:
        __slots__ = ("__buddhism_nodes__",)  # no __weakref__

        a = cell(1)

        @derived
        def b(self):
            return self.a * 2

    obj = CantWeak()
    # Reading the cell is fine; reading the Derived needs to capture self.
    assert obj.a == 1
    with pytest.raises(TypeError, match="not weak-referenceable"):
        _ = obj.b


def test_unweakreferenceable_class_strong_ref_opt_in():
    import warnings as _warnings

    class CantWeakOptIn:
        __slots__ = ("__buddhism_nodes__",)
        __buddhism_strong_refs__ = True

        a = cell(1)

        @derived
        def b(self):
            return self.a * 3

    obj = CantWeakOptIn()
    with _warnings.catch_warnings(record=True) as w:
        _warnings.simplefilter("always")
        assert obj.b == 3
    assert any(issubclass(x.category, RuntimeWarning) for x in w)
