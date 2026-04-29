"""Koan 01 — Impermanence (Anitya / Anicca).

  "All conditioned things are impermanent —
   when one sees this with wisdom, one turns away from suffering."
                                    — Dhammapada 277

Python feature: object identity, mutation, and aliasing.

The list you have now is not the list you had a moment ago.  The name
`x` is impermanent in two ways: the binding can change (the name now
refers to a different object), and the object itself can change in place
(mutation).  Confusing these two is the source of most aliasing bugs.

To self-test, replace any literal answer below with ``__`` (imported from
``buddhism.koans``) and re-run::

    python -m buddhism.koans
"""

from __future__ import annotations

from . import __  # noqa: F401  (used when the student blanks out an answer)

TITLE = "Impermanence — what changes, and what changes about what changes."

HINT = (
    "Two distinct kinds of change exist in Python: rebinding a name "
    "(the name now refers to a different object), and mutating an "
    "object (the object itself changes). Aliases share the second but "
    "not the first."
)


def _step_rebind_does_not_mutate() -> None:
    a = [1, 2, 3]
    b = a
    a = a + [4]  # rebinding `a` to a NEW list
    # `b` still refers to the original list. Rebinding `a` did not touch it.
    assert b == [1, 2, 3]
    assert a == [1, 2, 3, 4]
    assert a is not b


def _step_mutation_propagates_through_aliases() -> None:
    a = [1, 2, 3]
    b = a
    a.append(4)  # mutating the object both names point to
    assert b == [1, 2, 3, 4]
    assert a is b


def _step_immutables_cannot_be_mutated() -> None:
    s = "hello"
    t = s
    s = s + " world"  # creates a new string; t still points to the old
    assert t == "hello"
    assert s == "hello world"
    # Strings (and tuples, and frozensets) admit no mutation. They are,
    # in this technical sense, free of clinging — you cannot make an
    # alias suffer your changes.


def _step_default_argument_keeps_arising() -> None:
    # Default arguments are evaluated ONCE at def-time. If the default is
    # a mutable object, every call sees the same one — a famous source
    # of suffering. The default has impermanent contents but a permanent
    # identity.
    def append_to(item, bucket=[]):
        bucket.append(item)
        return bucket

    first = append_to(1)
    second = append_to(2)
    # Both calls share the same bucket — the default is conditioned by
    # the def-statement, not the call.
    assert first is second
    assert first == [1, 2]


def KOAN() -> None:
    _step_rebind_does_not_mutate()
    _step_mutation_propagates_through_aliases()
    _step_immutables_cannot_be_mutated()
    _step_default_argument_keeps_arising()
