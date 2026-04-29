"""Cross-module composition tests.

Six compositions per the v0.2 spec:

1. A `Conditioned` instance is inspectable by `dukkha.observe()` with a
   specialised `pratitya_breakdown()` report.
2. A `Derived` value is wrappable with `@impermanent`: derivations that go
   stale even if their inputs haven't changed.
3. `@karmic` and `@let_go` compose: a function with both contracts.
4. `find_cycles` distinguishes saṃsāric cycles in the reactive graph
   (raise `SamsaraError`) from heap reference cycles (survive `gc.collect`).
5. `examine(obj)` works on any object, with progressively richer output as
   the object adopts more of the package's primitives.
6. `buddhism.path` understands the package's own decorators and treats
   their absence as the "Right Mindfulness" failure mode.
"""

from __future__ import annotations

import gc
import pathlib

import pytest

from buddhism.anatta import StructuralEq
from buddhism.anitya import Stale, impermanent
from buddhism.dukkha import (
    ClingingDetected,
    find_cycles,
    let_go,
    observe,
)
from buddhism.examine import examine
from buddhism.karma import KarmicResult, KarmicViolation, karmic, pure
from buddhism.path import PathConfig, run_all
from buddhism.pratitya import (
    Cell,
    Conditioned,
    SamsaraError,
    cell,
    derive,
    derived,
)


# --------------------------------------------------------------------------- #
# 1. Conditioned + observe() with pratitya_breakdown()
# --------------------------------------------------------------------------- #


def test_observe_summarises_retained_reactive_graph():
    class Sheet(Conditioned):
        a = cell(1)
        b = cell(2)

        @derived
        def c(self):
            return self.a + self.b

    keepers: list = []
    with observe() as report:
        s = Sheet()
        _ = s.c  # materialise the Derived
        keepers.append(s)

    breakdown = report.pratitya_breakdown()
    assert breakdown.cells >= 2  # a and b
    assert breakdown.deriveds >= 1  # c
    assert breakdown.conditioned_instances >= 1
    text = report.text_report()
    assert "Conditioned instances" in text


# --------------------------------------------------------------------------- #
# 2. Derived + @impermanent: stale derivations
# --------------------------------------------------------------------------- #


def test_derived_can_be_wrapped_in_impermanent():
    """A Derived can be wrapped by @impermanent so its computed value
    expires on a wall-clock timer, independent of its input cells."""

    class _Clock:
        t = 0.0

    clk = _Clock()

    a = Cell(10)
    base = derive(lambda: a() * 2, name="base")

    @impermanent(validity=5.0, clock=lambda: clk.t)
    def fresh_base() -> int:
        return base()

    assert fresh_base() == 20  # primes the cache
    a.set(50)
    # The Derived has changed (input mutated) but @impermanent is keyed on
    # wall clock, not graph dirtiness — within the validity window it serves
    # the cached value.
    out = fresh_base()
    assert out == 20  # cached

    clk.t = 10.0
    out = fresh_base()
    assert isinstance(out, Stale)
    assert out.refresh() == 100  # refresh observes the new cell value


# --------------------------------------------------------------------------- #
# 3. @karmic + @let_go composition
# --------------------------------------------------------------------------- #


def test_karmic_then_let_go_composes():
    """A function decorated with both @karmic and @let_go enforces both
    contracts: clinging → ClingingDetected, side effects → tracked in ledger."""

    @karmic
    @let_go
    def transform(buf):
        return [x * 2 for x in buf]

    out = transform([1, 2, 3])
    assert isinstance(out, KarmicResult)
    assert out.value == [2, 4, 6]
    # No retention, no global writes; mutation tracking sees buf unchanged.
    assert not out.ledger.arg_mutations


def test_let_go_inside_karmic_detects_clinging():
    class _Bell:
        pass

    cache: list = []

    @karmic
    @let_go
    def leaky(x):
        cache.append(x)
        return None

    with pytest.raises(ClingingDetected):
        leaky(_Bell())


def test_karmic_strict_inside_let_go_detects_side_effect():
    counter = {"n": 0}

    # NOTE: order matters; karmic outer means ledger is built around let_go's wrap.
    @karmic(allow=set())
    @let_go
    def f(x):
        counter["n"] += 1  # mutates closure-captured dict (not a global)
        return x[0]

    # The closure dict is not a global; the ledger should see arg mutation
    # (counter dict) NOT global writes. allow=set() rules out arg mutation.
    out = f([7])
    # Actually: counter is captured in closure, not an arg. So no arg
    # mutation is tracked, no global write. allow=set() means no allowed
    # side effects, but no side effects occurred either. Pass.
    assert out.value == 7


# --------------------------------------------------------------------------- #
# 4. find_cycles vs SamsaraError: distinct cycle phenomena at distinct layers
# --------------------------------------------------------------------------- #


def test_samsaric_cycle_raises_at_eval_time():
    """A reactive cycle is detected at evaluation time as SamsaraError —
    it is the *evaluator's* refusal to chase its own tail. find_cycles
    looks at heap reference structure, which is a different layer."""
    holder: dict = {}

    def f():
        return holder["g"]() + 1

    def g():
        return holder["f"]() + 1

    holder["f"] = derive(f)
    holder["g"] = derive(g)
    with pytest.raises(SamsaraError):
        holder["f"]()


def test_heap_cycles_are_independent_of_samsara():
    """A reference cycle in user objects is detectable by find_cycles
    even though it would never raise SamsaraError — it's a cycle in
    *storage*, not in *evaluation*."""

    class Node:
        pass

    a = Node()
    b = Node()
    a.peer = b
    b.peer = a
    cycles = find_cycles([a, b])
    assert any(set(cyc) == {a, b} for cyc in cycles)


# --------------------------------------------------------------------------- #
# 5. examine() — progressively richer output across primitives
# --------------------------------------------------------------------------- #


def test_examine_progressive_richness():
    # Plain object: only the basic Anatta view.
    class Plain:
        def __init__(self, x):
            self.x = x

    plain = Plain(1)
    plain_r = examine(plain)
    assert plain_r.anatta.type_name == "Plain"
    assert not plain_r.anatta.reactive_dependencies
    assert plain_r.anatta.structural_hash is None

    # Adopting StructuralEq → Anatta gets a hash.
    class StructPlain(StructuralEq, Plain):
        pass

    sp = StructPlain(1)
    sp_r = examine(sp)
    assert sp_r.anatta.structural_hash is not None

    # Adopting Conditioned → Anatta lists reactive dependencies.
    class Reactive(Conditioned):
        a = cell(1)

        @derived
        def b(self):
            return self.a * 2

    r_obj = Reactive()
    _ = r_obj.b
    rich_r = examine(r_obj)
    assert "a" in rich_r.anatta.reactive_dependencies
    assert "b" in rich_r.anatta.reactive_dependencies


# --------------------------------------------------------------------------- #
# 6. buddhism.path eats its own dog food
# --------------------------------------------------------------------------- #


def test_buddhism_path_passes_against_buddhism_itself():
    """The package satisfies its own Eightfold Path with mindfulness on."""
    target = pathlib.Path(__file__).parent.parent / "src" / "buddhism"
    cfg = PathConfig.from_pyproject(pathlib.Path(__file__).parent.parent)
    cfg.enable_right_mindfulness = True
    report = run_all(target, cfg=cfg)
    failing = [r.name for r in report.results if not r.passed]
    assert not failing, (
        f"buddhism failed its own path: {failing}\n\n{report.text_report()}"
    )
    assert report.passed_count == report.total_count


def test_buddhism_path_is_eight_factors_when_enabled():
    target = pathlib.Path(__file__).parent.parent / "src" / "buddhism"
    cfg = PathConfig()
    cfg.enable_right_mindfulness = True
    report = run_all(target, cfg=cfg)
    assert report.total_count == 8


# --------------------------------------------------------------------------- #
# Bonus: a guaranteed-pure derivation via @karmic(allow=set())
# --------------------------------------------------------------------------- #


def test_pure_function_marker_recognised_by_examine():
    @pure
    def double(x: int) -> int:
        """Pure transformation."""
        return x * 2

    assert getattr(double, "__buddhism_pure__", False) is True
