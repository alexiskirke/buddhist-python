"""
anatta — Anātman (Non-Self).

  "Form is not self. If form were self, this form would not lend itself
   to dis-ease, and one could say of form, 'Let my form be thus, let
   my form not be thus.'"
                                  — Anattalakkhaṇa Sutta, SN 22.59

A small, pointed module on identity, equality, and the difference between
an object and its description.

Three primitives:

* :class:`StructuralEq` — mixin that derives ``__eq__`` and ``__hash__``
  from the configuration of attributes, not from object identity.
* :func:`without_self` — turn a bound method into a pure function whose
  ``self`` is replaced by an explicit state mapping.
* :func:`diff`         — distinguish "same object, mutated" from
  "different object, equal configuration".
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Tuple,
)

from .karma import pure
__all__ = [
    "StructuralEq",
    "without_self",
    "diff",
    "ConfigurationDiff",
]


# --------------------------------------------------------------------------- #
# StructuralEq mixin
# --------------------------------------------------------------------------- #


def _public_attrs(obj: Any) -> Dict[str, Any]:
    """Return ``{name: value}`` for non-underscore instance attributes.

    For ``__slots__``-only classes, walks the slot definitions across the
    MRO. For ``__dict__``-bearing classes, uses the dict directly.
    """
    out: Dict[str, Any] = {}
    cls = type(obj)
    # Slots first
    seen: set = set()
    for base in cls.__mro__:
        slots = getattr(base, "__slots__", ())
        if isinstance(slots, str):
            slots = (slots,)
        for s in slots:
            if s.startswith("_") or s in seen:
                continue
            seen.add(s)
            try:
                out[s] = getattr(obj, s)
            except AttributeError:
                continue
    # Then __dict__
    try:
        for k, v in obj.__dict__.items():
            if not k.startswith("_"):
                out[k] = v
    except AttributeError:
        pass
    return out


def _hashable_value(v: Any) -> Any:
    """Return a hashable surrogate for ``v``, falling back to id() when
    the value's type is unhashable."""
    try:
        hash(v)
        return v
    except TypeError:
        # Common case: lists, dicts. Recurse into a frozen form.
        if isinstance(v, list):
            return ("__list__",) + tuple(_hashable_value(x) for x in v)
        if isinstance(v, dict):
            return ("__dict__",) + tuple(
                sorted((k, _hashable_value(val)) for k, val in v.items())
            )
        if isinstance(v, set):
            return ("__set__",) + tuple(sorted(_hashable_value(x) for x in v))
        # Last resort: identity.  Documented caveat: two equal-looking
        # unhashable nested values will still hash differently if their
        # ids differ.
        return ("__id__", id(v))


class StructuralEq:
    """Mixin: ``__eq__`` and ``__hash__`` derived from a configuration of
    public attributes.

    Two instances are equal when they share both their *type* and the
    same values for every name in ``__structural_fields__``.

    Configuration:

    * ``__structural_fields__: tuple[str, ...]`` — explicit attribute names.
      If unset (default ``()``), all non-underscore instance attributes
      are used.
    * ``__structural_strict_type__: bool`` — if True (default), equality
      requires ``type(a) is type(b)``. If False, only the configuration
      must match, allowing cross-class structural equality.

    Implementation note: ``__hash__`` is safe for nested unhashable values
    (lists, dicts, sets become tuples; truly unhashable values fall back
    to ``id()``, with the documented caveat that two equal-looking
    unhashable nested values will hash differently).
    """

    __structural_fields__: Tuple[str, ...] = ()
    __structural_strict_type__: bool = True

    def _structural_items(self) -> Tuple[Tuple[str, Any], ...]:
        names = self.__structural_fields__
        if names:
            return tuple((n, getattr(self, n, None)) for n in names)
        return tuple(sorted(_public_attrs(self).items()))

    def __eq__(self, other: object) -> bool:
        if self is other:
            return True
        if self.__structural_strict_type__:
            if type(self) is not type(other):
                return NotImplemented if not isinstance(other, StructuralEq) else False
        else:
            if not isinstance(other, StructuralEq):
                return NotImplemented
        return self._structural_items() == other._structural_items()  # type: ignore[attr-defined]

    def __hash__(self) -> int:
        items = self._structural_items()
        try:
            return hash((type(self).__name__, items))
        except TypeError:
            hashed = tuple((k, _hashable_value(v)) for k, v in items)
            return hash((type(self).__name__, hashed))


# --------------------------------------------------------------------------- #
# without_self — turn a method into a pure function over an explicit state
# --------------------------------------------------------------------------- #


class _StateProxy(SimpleNamespace):
    """Argument-only proxy used as the synthesised ``self`` for a pure
    method invocation.

    Methods that read ``self.x`` see the corresponding key in the state
    mapping; assignments to ``self.x`` mutate the proxy (which the caller
    can read back via :meth:`as_dict`).
    """

    def as_dict(self) -> Dict[str, Any]:
        """Return the proxy's current state as a plain dict."""
        return dict(self.__dict__)


@pure
def without_self(method: Callable[..., Any]) -> Callable[..., Any]:
    """Transform a method into a pure function whose ``self`` is supplied
    as an explicit state mapping.

    Usage::

        class Counter:
            def __init__(self, n=0): self.n = n
            def step(self, k): return self.n + k

        pure = without_self(Counter.step)
        pure({"n": 10}, 5)   # 15

    The returned function takes ``state: Mapping[str, Any]`` as its first
    argument; anything else is forwarded to the original method.

    Useful for:
    * serialising work across process boundaries (state crosses, ``self``
      doesn't have to);
    * unit-testing methods without instantiating the class;
    * documenting that a method is, in fact, pure with respect to ``self``.

    Limitations: the proxy supports attribute reads and writes but not
    descriptor lookup, ``__class__``-aware behaviour, super(), or methods
    that introspect ``type(self)``. For those, instantiate normally.
    """
    if not callable(method):
        raise TypeError("without_self requires a callable")
    try:
        sig = inspect.signature(method)
    except (TypeError, ValueError):
        sig = None  # be tolerant; we still try

    def pure(state: Mapping[str, Any], /, *args: Any, **kwargs: Any) -> Any:
        if not isinstance(state, Mapping):
            raise TypeError(
                f"first argument to a without_self()-wrapped function "
                f"must be a mapping, got {type(state).__name__}"
            )
        proxy = _StateProxy(**dict(state))
        return method(proxy, *args, **kwargs)

    pure.__wrapped__ = method  # type: ignore[attr-defined]
    pure.__name__ = getattr(method, "__name__", "pure")
    pure.__doc__ = getattr(method, "__doc__", None)
    if sig is not None:
        pure.__signature__ = sig  # type: ignore[attr-defined]
    return pure


# --------------------------------------------------------------------------- #
# diff — three-way comparison of identity, configuration, and field changes
# --------------------------------------------------------------------------- #


@dataclass
class ConfigurationDiff:
    """Result of :func:`diff`.

    * ``same_identity``: ``a is b`` (the two references point at the same
      Python object).
    * ``same_configuration``: their public attributes are equal.
    * ``field_changes``: ``{name: (a_value, b_value)}`` for fields whose
      values differ. Empty when ``same_configuration`` is True.

    The four cases:

    +------------------+-------------------+---------------------------------+
    | same_identity    | same_configuration| meaning                         |
    +==================+===================+=================================+
    | True             | True              | The same object, no mutation    |
    +------------------+-------------------+---------------------------------+
    | True             | False             | The same object, mutated        |
    +------------------+-------------------+---------------------------------+
    | False            | True              | Two clones (or value-equal)     |
    +------------------+-------------------+---------------------------------+
    | False            | False             | Two distinct objects, distinct  |
    +------------------+-------------------+---------------------------------+
    """

    same_identity: bool
    same_configuration: bool
    field_changes: Dict[str, Tuple[Any, Any]] = field(default_factory=dict)

    def __bool__(self) -> bool:
        """An empty diff (everything matches) is falsy."""
        return not (self.same_identity and self.same_configuration)

    def summary(self) -> str:
        """Return a short human-readable description of this diff."""
        if self.same_identity and self.same_configuration:
            return "identical: same object, same configuration"
        if self.same_identity and not self.same_configuration:
            return f"mutated: same object, {len(self.field_changes)} field(s) changed"
        if not self.same_identity and self.same_configuration:
            return "cloned: distinct objects, identical configuration"
        return f"distinct: {len(self.field_changes)} field(s) differ"


@pure
def diff(a: Any, b: Any) -> ConfigurationDiff:
    """Compare two objects across identity and configuration."""
    same_id = a is b
    a_attrs = _public_attrs(a)
    b_attrs = _public_attrs(b)
    keys = set(a_attrs) | set(b_attrs)
    changes: Dict[str, Tuple[Any, Any]] = {}
    for k in sorted(keys):
        av = a_attrs.get(k, _MISSING)
        bv = b_attrs.get(k, _MISSING)
        if av is _MISSING and bv is _MISSING:
            continue
        try:
            equal = av == bv
        except Exception:
            equal = av is bv
        if not equal:
            changes[k] = (av, bv)
    return ConfigurationDiff(
        same_identity=same_id,
        same_configuration=not changes,
        field_changes=changes,
    )


_MISSING = object()
