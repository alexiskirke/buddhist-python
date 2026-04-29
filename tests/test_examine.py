"""Tests for buddhism.examine — Three Marks introspection."""

from __future__ import annotations

import pytest

from buddhism.anatta import StructuralEq
from buddhism.anitya import impermanent
from buddhism.examine import (
    AnattaReading,
    AnityaReading,
    DukkhaReading,
    ThreeMarksReading,
    examine,
)
from buddhism.pratitya import Cell, Conditioned, cell, derived


def test_examine_returns_dataclass():
    r = examine(42)
    assert isinstance(r, ThreeMarksReading)
    assert isinstance(r.anitya, AnityaReading)
    assert isinstance(r.dukkha, DukkhaReading)
    assert isinstance(r.anatta, AnattaReading)


def test_examine_plain_object_basic_fields():
    class Plain:
        def __init__(self, x):
            self.x = x

    obj = Plain(5)
    r = examine(obj)
    assert r.anatta.type_name == "Plain"
    assert "x" in r.anatta.public_attrs
    assert not r.anitya.is_impermanent


def test_examine_stale_value():
    class _Clock:
        t = 0.0

    clk = _Clock()

    @impermanent(validity=1.0, clock=lambda: clk.t)
    def fetch():
        return [1, 2, 3]

    fetch()
    clk.t = 5.0
    out = fetch()  # returns Stale
    r = examine(out)
    assert r.anitya.is_impermanent
    assert r.anitya.staleness is not None
    assert r.anitya.staleness["age"] >= 5.0


def test_examine_impermanent_function():
    @impermanent(validity=10.0)
    def f():
        return 1

    r = examine(f)
    assert r.anitya.is_impermanent
    assert r.anitya.validity == 10.0


def test_examine_conditioned_instance_reports_dependencies():
    class Sheet(Conditioned):
        a = cell(1)
        b = cell(2)

        @derived
        def c(self):
            return self.a + self.b

    s = Sheet()
    _ = s.c  # materialise
    r = examine(s)
    assert "a" in r.anatta.reactive_dependencies
    assert "b" in r.anatta.reactive_dependencies
    assert "c" in r.anatta.reactive_dependencies


def test_examine_structural_eq_reports_hash():
    class P(StructuralEq):
        def __init__(self, x):
            self.x = x

    r = examine(P(7))
    assert r.anatta.structural_hash is not None


def test_examine_text_report_has_three_sections():
    class X:
        def __init__(self):
            self.k = 1

    text = examine(X()).text_report()
    assert "Anitya" in text
    assert "Dukkha" in text
    assert "Anatta" in text


def test_examine_cell_reports_subscribers_count():
    from buddhism.pratitya import on_change

    c = Cell(0)
    on_change(c, lambda old, new: None)
    r = examine(c)
    assert r.dukkha.reactive_subscribers == 1
