"""Koan 03 — Non-Self (Anatta / Anātman).

  "Form is not self. If form were self, this form would not lend itself
   to dis-ease, and one could say of form, 'Let my form be thus, let
   my form not be thus.'"
                                  — Anattalakkhaṇa Sutta, Saṃyutta Nikāya 22.59

Python feature: identity vs. equality, ``__dict__``, attribute lookup,
and the difference between an object and its description.

A Python object has no inherent "self". What we call its identity is
``id(o)``, which is a contingent fact (CPython returns its memory
address) — it may differ between processes, between runs, between
implementations.  What we call its "qualities" are its ``__dict__`` and
the attributes its class makes available; they too can be replaced.
"""

from __future__ import annotations

from . import __  # noqa: F401
from buddhism.karma import pure

TITLE = "Non-Self — identity is not equality, and equality is not sameness."

HINT = (
    "Three different relations: `is` (same object), `==` (equal value), "
    "and `hash` (placement in a hash table). They agree by convention, "
    "not by necessity. Names, dicts, and class definitions are the "
    "vehicles of identity — never inherent in the object."
)


def _step_identity_is_contingent() -> None:
    a = [1, 2, 3]
    b = [1, 2, 3]
    # Same value, different object.
    assert a == b
    assert a is not b
    # Identity is not a property of the value; it is a property of
    # *this allocation*.


def _step_small_int_caching_is_an_implementation_detail() -> None:
    x = 256
    y = 256
    # CPython interns small ints; `is` happens to be True. This is not a
    # guarantee of the language, only of the implementation.
    assert x == y
    assert x is y  # CPython-specific; do not rely on this in real code.

    big_x = 10_000
    big_y = 10_000
    # Outside the small-int cache, the implementation makes no promise.
    assert big_x == big_y
    # We do NOT assert big_x is big_y; whether it holds is contingent.


def _step_attributes_are_a_dict_not_a_self() -> None:
    class Person:
        pass

    p = Person()
    p.name = "Mary"
    # The `name` is not "in" the Person — it is in p's __dict__.
    assert p.__dict__ == {"name": "Mary"}

    # We can replace the entire bag of qualities at once.
    p.__dict__ = {"name": "Anne", "occupation": "engineer"}
    assert p.name == "Anne"
    assert p.occupation == "engineer"

    # We can even delete it.
    del p.name
    assert "name" not in p.__dict__


def _step_class_attributes_are_inherited_not_owned() -> None:
    class Vehicle:
        wheels = 4

    car = Vehicle()
    assert car.wheels == 4
    assert "wheels" not in car.__dict__  # the value lives on the class

    # Assigning to the instance shadows the class attribute. The class
    # attribute is unchanged; the instance now owns its own copy.
    car.wheels = 6
    assert car.wheels == 6
    assert Vehicle.wheels == 4

    other = Vehicle()
    assert other.wheels == 4

    # Removing the instance attribute reveals the class attribute again.
    del car.wheels
    assert car.wheels == 4


def _step_descriptors_intercept_self() -> None:
    # Descriptors (objects with __get__) intercept attribute access. They
    # are how `property`, `classmethod`, `staticmethod`, and indeed our
    # own `cell()` and `derived` work.
    class Squared:
        def __set_name__(self, owner, name):
            self._name = name

        def __get__(self, instance, owner):
            if instance is None:
                return self
            x = instance.__dict__.get("_x", 0)
            return x * x

        def __set__(self, instance, value):
            instance.__dict__["_x"] = value

    class Box:
        v = Squared()

    b = Box()
    b.v = 5
    assert b.v == 25
    assert b.__dict__ == {"_x": 5}
    # `v` is not on `b`. The class arranged for `v` access to *appear*
    # to belong to `b`.


@pure
def KOAN() -> None:
    """Run all steps of this koan; raises AssertionError on first failure."""
    _step_identity_is_contingent()
    _step_small_int_caching_is_an_implementation_detail()
    _step_attributes_are_a_dict_not_a_self()
    _step_class_attributes_are_inherited_not_owned()
    _step_descriptors_intercept_self()
