"""Tests for buddhism.anitya — impermanence primitives."""

from __future__ import annotations

import math

import pytest

from buddhism.anitya import (
    DecayDict,
    DecaySet,
    MemoryPressureRegistry,
    Stale,
    StalenessError,
    exponential_decay,
    impermanent,
    linear_decay,
)


class _Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


# --------------------------------------------------------------------------- #
# DecayDict / DecaySet
# --------------------------------------------------------------------------- #


def test_decay_dict_full_confidence_at_insertion():
    clk = _Clock()
    d: DecayDict[str, int] = DecayDict(half_life=10.0, clock=clk)
    d.set("k", 42)
    v, c = d.get("k")
    assert v == 42
    assert c == pytest.approx(1.0)


def test_decay_dict_half_at_half_life():
    clk = _Clock()
    d: DecayDict[str, int] = DecayDict(half_life=10.0, clock=clk)
    d.set("k", 1)
    clk.advance(10.0)
    _, c = d.get("k")
    assert c == pytest.approx(0.5)


def test_decay_dict_eviction_below_threshold():
    clk = _Clock()
    d: DecayDict[str, int] = DecayDict(
        half_life=1.0,
        eviction_threshold=0.1,
        clock=clk,
    )
    d.set("k", 1)
    clk.advance(10.0)  # confidence ~ 2^-10 ≈ 0.001 < 0.1
    v, c = d.get("k", default="MISS")
    assert v == "MISS"
    assert c == 0.0
    assert "k" not in d


def test_decay_dict_linear_decay_reaches_zero():
    clk = _Clock()
    d: DecayDict[str, int] = DecayDict(
        half_life=1.0,
        decay=linear_decay,
        clock=clk,
    )
    d.set("k", 1)
    clk.advance(0.5)
    _, c = d.get("k")
    assert c == pytest.approx(0.75)
    clk.advance(2.0)
    v, c = d.get("k", default="MISS")
    assert c == 0.0


def test_decay_dict_items_returns_live_with_confidence():
    clk = _Clock()
    d: DecayDict[str, int] = DecayDict(half_life=10.0, clock=clk)
    d.set("a", 1)
    d.set("b", 2)
    items = d.items()
    keys = {k for k, _, _ in items}
    assert keys == {"a", "b"}
    assert all(0 <= c <= 1 for _, _, c in items)


def test_decay_dict_invalid_args():
    with pytest.raises(ValueError):
        DecayDict(half_life=0)
    with pytest.raises(ValueError):
        DecayDict(half_life=1, eviction_threshold=1.5)


def test_decay_set_membership_decays():
    clk = _Clock()
    s = DecaySet(half_life=1.0, eviction_threshold=0.05, clock=clk)
    s.add("hello")
    assert "hello" in s
    clk.advance(10.0)
    assert "hello" not in s


# --------------------------------------------------------------------------- #
# @impermanent / Stale[T]
# --------------------------------------------------------------------------- #


def test_impermanent_returns_cached_within_window():
    clk = _Clock()
    calls = []

    @impermanent(validity=5.0, clock=clk)
    def now() -> str:
        calls.append("called")
        return "x"

    assert now() == "x"
    clk.advance(2.0)
    assert now() == "x"
    assert len(calls) == 1


def test_impermanent_returns_stale_outside_window():
    clk = _Clock()

    @impermanent(validity=5.0, clock=clk)
    def now() -> int:
        return 7

    now()  # prime
    clk.advance(10.0)
    out = now()
    assert isinstance(out, Stale)
    assert out.age >= 10.0
    assert out.validity == 5.0


def test_stale_bare_attribute_access_raises():
    clk = _Clock()

    @impermanent(validity=1.0, clock=clk)
    def fetch() -> dict:
        return {"value": 42}

    fetch()
    clk.advance(5.0)
    out = fetch()
    assert isinstance(out, Stale)
    with pytest.raises(StalenessError):
        _ = out.value  # type: ignore[attr-defined]


def test_stale_accept_returns_cached_value():
    clk = _Clock()

    @impermanent(validity=1.0, clock=clk)
    def fetch() -> int:
        return 99

    fetch()
    clk.advance(2.0)
    out = fetch()
    assert isinstance(out, Stale)
    assert out.accept_stale() == 99


def test_stale_refresh_recomputes():
    clk = _Clock()
    counter = {"n": 0}

    @impermanent(validity=1.0, clock=clk)
    def fetch() -> int:
        counter["n"] += 1
        return counter["n"]

    fetch()
    assert counter["n"] == 1
    clk.advance(2.0)
    out = fetch()
    assert isinstance(out, Stale)
    fresh = out.refresh()
    assert fresh == 2
    assert counter["n"] == 2


def test_stale_cached_value_does_not_raise():
    clk = _Clock()

    @impermanent(validity=1.0, clock=clk)
    def fetch() -> int:
        return 100

    fetch()
    clk.advance(5.0)
    out = fetch()
    assert isinstance(out, Stale)
    # cached_value is a property defined on the class, not "bare access"
    assert out.cached_value == 100


# --------------------------------------------------------------------------- #
# MemoryPressureRegistry
# --------------------------------------------------------------------------- #


class _Big:
    def __init__(self, label: str) -> None:
        self.label = label


def test_registry_releases_all():
    reg = MemoryPressureRegistry()
    released = []
    objs = [_Big(f"o{i}") for i in range(3)]
    for o in objs:
        reg.register(o, priority=0, on_release=lambda label=o.label: released.append(label))
    assert len(reg) == 3
    n = reg.release_all()
    assert n == 3
    assert sorted(released) == ["o0", "o1", "o2"]


def test_registry_priority_order():
    reg = MemoryPressureRegistry()
    released = []
    a, b, c = _Big("a"), _Big("b"), _Big("c")
    reg.register(a, priority=10, on_release=lambda: released.append("a"))
    reg.register(b, priority=1, on_release=lambda: released.append("b"))
    reg.register(c, priority=5, on_release=lambda: released.append("c"))
    reg.release_n(2)
    assert released == ["b", "c"]  # priority 1 then 5


def test_registry_release_under_pressure_with_fake_pressure():
    reg = MemoryPressureRegistry()
    released = []
    state = {"current": 1000}

    def fake_pressure() -> int:
        return state["current"]

    for i in range(5):
        reg.register(_Big(f"o{i}"), priority=i, on_release=lambda i=i: state.update(
            current=state["current"] - 100
        ))

    n = reg.release_under_pressure(500, current_pressure=fake_pressure)
    assert n >= 5  # released enough to bring pressure under 500
    assert state["current"] <= 500
