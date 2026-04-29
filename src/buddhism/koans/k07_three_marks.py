"""Koan 07 — The Three Marks of Existence (Tilakkhaṇa).

  "All conditioned things are anitya (impermanent).
   All conditioned things are dukkha (subject to clinging).
   All things are anatta (without independent self)."

Python feature: a single introspection function (:func:`buddhism.examine`)
that returns three orthogonal views of any object, each grounded in one
of the package's load-bearing primitives.

The principle: a Python object can be looked at along (at least) three
independent axes. Time, the social fact of who is holding it, and the
configuration of conditions that constitute it.
"""

from __future__ import annotations

from buddhism.anatta import StructuralEq
from buddhism.anitya import impermanent
from buddhism.examine import examine
from buddhism.karma import pure
from buddhism.pratitya import Conditioned, cell, derived

from . import __  # noqa: F401

TITLE = "Three Marks — every object, three views."

HINT = (
    "examine(obj) returns Anitya (time), Dukkha (clinging), and Anatta "
    "(configuration) views. Adopting StructuralEq populates the "
    "structural hash; Conditioned populates reactive dependencies; "
    "@impermanent populates staleness. The output gets richer as the "
    "object adopts more of the package's primitives."
)


@pure
def _step_plain_object_basic_view() -> None:
    class Plain:
        def __init__(self, x: int) -> None:
            self.x = x

    r = examine(Plain(5))
    assert r.anatta.type_name == "Plain"
    assert "x" in r.anatta.public_attrs
    assert not r.anitya.is_impermanent
    assert r.anatta.structural_hash is None


@pure
def _step_structural_eq_populates_hash() -> None:
    class P(StructuralEq):
        def __init__(self, x: int) -> None:
            self.x = x

    r = examine(P(7))
    assert r.anatta.structural_hash is not None


@pure
def _step_conditioned_populates_reactive_dependencies() -> None:
    class Sheet(Conditioned):
        a = cell(1)

        @derived
        def b(self) -> int:
            return self.a * 2

    s = Sheet()
    _ = s.b  # materialise
    r = examine(s)
    assert "a" in r.anatta.reactive_dependencies
    assert "b" in r.anatta.reactive_dependencies


@pure
def _step_impermanent_function_is_visible_to_examine() -> None:
    @impermanent(validity=10.0)
    def fetch() -> int:
        return 1

    r = examine(fetch)
    assert r.anitya.is_impermanent
    assert r.anitya.validity == 10.0


@pure
def _step_text_report_has_three_named_sections() -> None:
    class X:
        pass

    text = examine(X()).text_report()
    assert "Anitya" in text
    assert "Dukkha" in text
    assert "Anatta" in text


@pure
def KOAN() -> None:
    """Run all steps of this koan; raises AssertionError on first failure."""
    _step_plain_object_basic_view()
    _step_structural_eq_populates_hash()
    _step_conditioned_populates_reactive_dependencies()
    _step_impermanent_function_is_visible_to_examine()
    _step_text_report_has_three_named_sections()
