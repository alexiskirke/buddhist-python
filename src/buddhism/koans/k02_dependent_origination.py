"""Koan 02 — Dependent Origination (Pratītyasamutpāda).

  "When this is, that is.
   From the arising of this, that arises."
                       — Saṃyutta Nikāya 12.61

Python feature: descriptors (``__get__`` / ``__set__`` / ``__set_name__``)
and the reactive dependency graph in :mod:`buddhism.pratitya`.

The principle: a value is what it is *because* of its conditions. If those
conditions change, the value's existence requires re-arising. We can model
this with descriptors that, on read, record the current evaluation context
and, on write, invalidate everything downstream.
"""

from __future__ import annotations

from buddhism.pratitya import Cell, Conditioned, batch, cell, derive, derived, on_change

from . import __  # noqa: F401

TITLE = "Dependent Origination — values arising from conditions."

HINT = (
    "Reading a Cell or Derived inside another Derived's body records a "
    "dependency edge. Writing to a Cell invalidates all transitive "
    "dependents. Until the next read, the Derived is dirty — its old "
    "value is no longer trusted."
)


def _step_standalone_signals() -> None:
    a = Cell(1)
    b = Cell(2)
    c = derive(lambda: a() + b())
    assert c() == 3
    a.set(10)
    assert c() == 12  # c re-arises automatically because its conditions changed


def _step_descriptors_on_a_class() -> None:
    class Triangle(Conditioned):
        base = cell(3.0)
        height = cell(4.0)

        @derived
        def area(self) -> float:
            return 0.5 * self.base * self.height

    t = Triangle()
    assert t.area == 6.0

    t.base = 6.0
    assert t.area == 12.0  # re-arose from the new conditions

    t.height = 10.0
    assert t.area == 30.0


def _step_only_actual_dependencies_are_tracked() -> None:
    # The graph only tracks dependencies that the function actually reads
    # on the path it takes. A condition that is not read does not count.
    a = Cell(True)
    b = Cell(100)
    c = Cell(200)

    @derive
    def chosen():
        if a():
            return b()
        else:
            return c()

    assert chosen() == 100

    # Changing c does NOT invalidate `chosen`, because `chosen` did not
    # read c on its last evaluation.
    c.set(999)
    assert chosen() == 100  # unchanged

    # But once we flip `a` and re-read, the graph reorganises itself:
    a.set(False)
    assert chosen() == 999

    # Now changing b no longer matters; changing c does.
    b.set(0)
    assert chosen() == 999
    c.set(7)
    assert chosen() == 7


def _step_subscriptions_fire_on_change() -> None:
    received: list = []

    a = Cell(1)
    b = Cell(2)
    s = derive(lambda: a() + b(), name="sum")

    # Force first evaluation so `s` has a current value.
    assert s() == 3

    sub = on_change(s, lambda old, new: received.append((old, new)))

    a.set(10)
    # The subscriber is fired eagerly. `s` re-arises on first read by the callback.
    assert received == [(3, 12)]

    b.set(0)
    assert received == [(3, 12), (12, 10)]

    sub.cancel()
    a.set(0)
    # Subscription cancelled; nothing new appended.
    assert received == [(3, 12), (12, 10)]


def _step_batched_updates_collapse() -> None:
    # Multiple updates in a batch fire each subscriber at most once.
    a = Cell(1)
    b = Cell(2)
    s = derive(lambda: a() + b())
    s()  # prime

    fires: list = []
    on_change(s, lambda old, new: fires.append(new))

    with batch():
        a.set(10)
        b.set(20)
    # One coalesced fire after the batch closes.
    assert fires == [30]


def KOAN() -> None:
    _step_standalone_signals()
    _step_descriptors_on_a_class()
    _step_only_actual_dependencies_are_tracked()
    _step_subscriptions_fire_on_change()
    _step_batched_updates_collapse()
