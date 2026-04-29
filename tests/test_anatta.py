"""Tests for buddhism.anatta — non-self / structural identity tools."""

from __future__ import annotations

import pytest

from buddhism.anatta import (
    ConfigurationDiff,
    StructuralEq,
    diff,
    without_self,
)


# --------------------------------------------------------------------------- #
# StructuralEq
# --------------------------------------------------------------------------- #


def test_structural_eq_default_uses_all_public_attrs():
    class Point(StructuralEq):
        def __init__(self, x, y):
            self.x = x
            self.y = y

    a = Point(1, 2)
    b = Point(1, 2)
    c = Point(1, 3)
    assert a == b
    assert a is not b
    assert a != c
    assert hash(a) == hash(b)
    assert hash(a) != hash(c) or a == c  # at minimum, equal -> equal hash


def test_structural_eq_explicit_fields():
    class Person(StructuralEq):
        __structural_fields__ = ("name",)

        def __init__(self, name, age):
            self.name = name
            self.age = age

    a = Person("Alice", 30)
    b = Person("Alice", 99)
    c = Person("Bob", 30)
    assert a == b  # age is not part of structural identity
    assert a != c


def test_structural_eq_strict_type_default():
    class A(StructuralEq):
        def __init__(self, n):
            self.n = n

    class B(StructuralEq):
        def __init__(self, n):
            self.n = n

    a = A(1)
    b = B(1)
    assert a != b  # different classes despite same configuration


def test_structural_eq_loose_type_allows_cross_class():
    class A(StructuralEq):
        __structural_strict_type__ = False

        def __init__(self, n):
            self.n = n

    class B(StructuralEq):
        __structural_strict_type__ = False

        def __init__(self, n):
            self.n = n

    a = A(1)
    b = B(1)
    assert a == b


def test_structural_eq_unhashable_field_falls_back_safely():
    class Bag(StructuralEq):
        def __init__(self, items):
            self.items = items

    a = Bag([1, 2, 3])
    b = Bag([1, 2, 3])
    assert a == b
    h_a = hash(a)
    h_b = hash(b)
    assert h_a == h_b  # equal-list contents → equal hashes via the surrogate


def test_structural_eq_in_a_set():
    class P(StructuralEq):
        def __init__(self, x):
            self.x = x

    s = {P(1), P(1), P(2)}
    assert len(s) == 2


# --------------------------------------------------------------------------- #
# without_self
# --------------------------------------------------------------------------- #


def test_without_self_basic_pure_call():
    class Counter:
        def __init__(self, n=0):
            self.n = n

        def step(self, k):
            return self.n + k

    pure = without_self(Counter.step)
    assert pure({"n": 10}, 5) == 15
    assert pure({"n": 0}, 7) == 7


def test_without_self_mutating_proxy_is_visible():
    class Box:
        def fill(self, x):
            self.value = x
            return self.value

    pure = without_self(Box.fill)
    state = {"value": None}
    out = pure(state, 99)
    assert out == 99
    # The original state dict is not mutated; the proxy is internal.
    assert state == {"value": None}


def test_without_self_requires_mapping_first_arg():
    class C:
        def f(self):
            return 1

    pure = without_self(C.f)
    with pytest.raises(TypeError):
        pure(123)  # not a mapping


def test_without_self_preserves_signature_and_name():
    class C:
        def m(self, x: int, y: int = 7) -> int:
            return x + y

    pure = without_self(C.m)
    assert pure.__name__ == "m"


# --------------------------------------------------------------------------- #
# diff / ConfigurationDiff
# --------------------------------------------------------------------------- #


class _Box:
    def __init__(self, x, y):
        self.x = x
        self.y = y


def test_diff_identical():
    a = _Box(1, 2)
    d = diff(a, a)
    assert d.same_identity
    assert d.same_configuration
    assert not d.field_changes
    assert not d  # bool: identical ⇒ falsy
    assert "identical" in d.summary()


def test_diff_mutated():
    a = _Box(1, 2)
    a_was_x = a.x
    a.x = 99
    # Compare to a "snapshot view" by making a clone with the prior value;
    # diff should report mutation against itself only via separate instances.
    b = _Box(a_was_x, 2)
    d = diff(a, b)
    assert not d.same_identity
    assert "x" in d.field_changes
    assert d.field_changes["x"] == (99, 1)


def test_diff_clones_same_configuration():
    a = _Box(1, 2)
    b = _Box(1, 2)
    d = diff(a, b)
    assert not d.same_identity
    assert d.same_configuration
    assert "cloned" in d.summary()


def test_diff_distinct():
    a = _Box(1, 2)
    b = _Box(3, 4)
    d = diff(a, b)
    assert not d.same_identity
    assert not d.same_configuration
    assert set(d.field_changes) == {"x", "y"}


def test_diff_returns_dataclass():
    d = diff(_Box(1, 2), _Box(1, 2))
    assert isinstance(d, ConfigurationDiff)
