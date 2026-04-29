"""Koan 05 — Emptiness (Śūnyatā).

  "Form is emptiness; emptiness is form."
                                — Heart Sūtra

Python feature: ``None``, sentinels, falsy values, and ``__bool__``.

Empty is not the same as nothing. ``None`` is *something*: a single,
specific object, the canonical sentinel for absence. ``[]`` is something
too: a list of length zero. They are both "empty" in different ways.

The Pythonic mistake is to confuse "absent" with "false" — to write
``if x:`` when you mean ``if x is None:`` and to mistake an empty
container for a missing one.
"""

from __future__ import annotations

from . import __  # noqa: F401
from buddhism.karma import pure

TITLE = "Emptiness — None is not zero is not False is not []."

HINT = (
    "`is None` checks for the sentinel. `not x` checks for falsiness "
    "(0, '', [], {}, set(), None all qualify). They overlap but are "
    "not the same. When a function might legitimately return any "
    "falsy value, use a private sentinel instead of None."
)


def _step_none_is_a_singleton() -> None:
    a = None
    b = None
    # There is exactly one None object in the entire process.
    assert a is b
    assert id(a) == id(b)


def _step_falsy_is_not_the_same_as_none() -> None:
    falsy_values = [None, 0, 0.0, "", [], {}, set(), False]
    # All eight are falsy:
    for v in falsy_values:
        assert not v
    # But only one of them is None:
    nones = [v for v in falsy_values if v is None]
    assert len(nones) == 1


def _step_default_arguments_with_none() -> None:
    # The standard idiom for "a default the caller might want to override
    # with any value, including a falsy one":
    def append_to(item, bucket=None):
        if bucket is None:
            bucket = []  # fresh empty list per call
        bucket.append(item)
        return bucket

    first = append_to(1)
    second = append_to(2)
    # No shared default. (Compare with k01_impermanence's mutable-default trap.)
    assert first is not second
    assert first == [1]
    assert second == [2]


def _step_private_sentinels_distinguish_truly_unset() -> None:
    # When None is itself a valid value, the API needs a *different*
    # sentinel. The Pythonic recipe is a module-private object.
    _MISSING = object()

    def get_value(d: dict, key: str, default=_MISSING):
        if key in d:
            return d[key]
        if default is _MISSING:
            raise KeyError(key)
        return default

    d = {"a": None}
    # None is a real, present value:
    assert get_value(d, "a") is None
    # Missing keys raise:
    try:
        get_value(d, "b")
        raised = False
    except KeyError:
        raised = True
    assert raised
    # …unless we provide an explicit default, which may itself be None:
    assert get_value(d, "b", default=None) is None


def _step_empty_containers_are_still_objects() -> None:
    # An empty list is not nothing. It has a type, a length, an id, and
    # the capacity to be mutated into something. Form is emptiness;
    # emptiness is form.
    empty = []
    assert empty == []
    assert isinstance(empty, list)
    assert len(empty) == 0
    assert id(empty)  # has an identity

    empty.append(1)
    assert empty == [1]
    # The same object — its identity persists across changes in form.


@pure
def KOAN() -> None:
    """Run all steps of this koan; raises AssertionError on first failure."""
    _step_none_is_a_singleton()
    _step_falsy_is_not_the_same_as_none()
    _step_default_arguments_with_none()
    _step_private_sentinels_distinguish_truly_unset()
    _step_empty_containers_are_still_objects()
