"""
pratitya — Pratītyasamutpāda (Dependent Origination)

  "When this is, that is.
   From the arising of this, that arises.
   When this isn't, that isn't.
   From the cessation of this, that ceases."
                            — Saṃyutta Nikāya 12.61

A reactive dependency graph: values arise from conditions and cease when
conditions cease. Built from Python's deepest leverage points — descriptors
(``__get__`` / ``__set__`` / ``__set_name__``), context variables for
implicit dependency tracking, and weak references so the graph itself does
not become a mechanism of clinging.

Three primitives:

* :class:`Cell`     — a mutable source-of-conditions.
* :class:`Derived`  — a value whose existence is contingent on other values.
* :func:`derive`    — a decorator/factory for creating Derived values.

Two ergonomic surfaces:

* Standalone, like signals::

      a = Cell(1)
      b = Cell(2)
      c = derive(lambda: a() + b())
      c()         # 3
      a.set(10)
      c()         # 12

* Class-attribute, descriptor-driven, like spreadsheets::

      class Sheet(Conditioned):
          a = cell(1)
          b = cell(2)

          @derived
          def c(self):
              return self.a + self.b

      s = Sheet()
      s.c          # 3
      s.a = 10
      s.c          # 12
"""

from __future__ import annotations

import threading
import warnings
import weakref
from contextlib import contextmanager
from contextvars import ContextVar
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    Iterator,
    List,
    Literal,
    Optional,
    Tuple,
    TypeVar,
    Union,
)

from .karma import pure
__all__ = [
    "Cell",
    "Derived",
    "Conditioned",
    "SamsaraError",
    "EqualityCheck",
    "cell",
    "derive",
    "derived",
    "batch",
    "on_change",
    "current_dependencies",
]

T = TypeVar("T")

# A sentinel that is distinct from None, since None is a valid value for cells.
_UNSET: Any = object()


class SamsaraError(RuntimeError):
    """Raised when a circular dependency is detected.

    Saṃsāra: the wheel of dependent arisings folding back upon itself.
    A → B → A has no still point at which to compute a value.
    """


# --------------------------------------------------------------------------- #
# Internal: dependency tracking
# --------------------------------------------------------------------------- #
#
# We use a ContextVar so that auto-tracking is correct under asyncio and
# threads.  The "current frame" is the Derived node currently re-evaluating
# its function; any Cell or Derived read while it is on the stack records
# itself as a dependency of that frame.

_eval_stack: ContextVar[Optional[Tuple["_Node", ...]]] = ContextVar(
    "buddhism_pratitya_eval_stack", default=None
)


def _push_frame(node: "_Node") -> Tuple["_Node", ...]:
    stack = _eval_stack.get() or ()
    if node in stack:
        chain = " → ".join(n._debug_name() for n in stack) + f" → {node._debug_name()}"
        raise SamsaraError(f"Circular dependency: {chain}")
    new = stack + (node,)
    _eval_stack.set(new)
    return new


def _pop_frame(token: Tuple["_Node", ...]) -> None:
    stack = _eval_stack.get() or ()
    # Pop only if the top matches; defensive against re-entrancy.
    if stack and stack[-1] is token[-1]:
        _eval_stack.set(stack[:-1] or None)


@pure
def current_dependencies() -> Tuple["_Node", ...]:
    """Return the currently-tracking eval-stack of Derived nodes.

    Useful for diagnostics: who is currently observing me?
    """
    return _eval_stack.get() or ()


# --------------------------------------------------------------------------- #
# Internal: batching
# --------------------------------------------------------------------------- #

_batch_depth: ContextVar[int] = ContextVar("buddhism_pratitya_batch_depth", default=0)
# Maps id(node) -> (node, old_value). We preserve the *first* old we see
# during a batch so that subscribers always receive the value the node had
# *before* the batch began, not after intermediate cascade steps.
_batch_pending: ContextVar[Optional[Dict[int, Tuple["_Node", Any]]]] = ContextVar(
    "buddhism_pratitya_batch_pending", default=None
)


@pure
@contextmanager
def batch() -> Iterator[None]:
    """Defer eager subscriber notifications until the block exits.

    Inside a ``with batch():`` block, Cell mutations still invalidate
    derived values, but on-change subscribers are queued and fired exactly
    once per affected node when the outermost batch closes.
    """
    depth = _batch_depth.get()
    _batch_depth.set(depth + 1)
    if depth == 0:
        _batch_pending.set({})
    try:
        yield
    finally:
        new_depth = _batch_depth.get() - 1
        _batch_depth.set(new_depth)
        if new_depth == 0:
            pending = _batch_pending.get() or {}
            _batch_pending.set(None)
            for node, old in pending.values():
                node._fire_subscribers(old=old)


# --------------------------------------------------------------------------- #
# Subscriber records
# --------------------------------------------------------------------------- #


class _Subscription:
    """Holds a callback and offers .cancel().  Returned by on_change()."""

    __slots__ = ("_node_ref", "_callback")

    def __init__(self, node: "_Node", callback: Callable[[Any, Any], None]) -> None:
        # Weakref to the node, so a long-lived subscription doesn't keep
        # the graph alive.
        self._node_ref: weakref.ReferenceType = weakref.ref(node)
        self._callback = callback

    def cancel(self) -> None:
        """Detach this subscription from its node. Idempotent."""
        node = self._node_ref()
        if node is None:
            return
        try:
            node._subscribers.remove(self)
        except ValueError:
            pass


# --------------------------------------------------------------------------- #
# Node base
# --------------------------------------------------------------------------- #


class _Node:
    """Shared machinery for Cell and Derived.

    Edge ownership rule (the "non-clinging" invariant):

    * ``_dependents`` is a WeakSet — observers do NOT keep us alive, and
      we do NOT keep observers alive. The graph is structurally non-clinging.
    * ``_dependencies`` is a list of strong references owned by Derived
      so it can re-track on each recompute. Cells do not have dependencies.
    """

    __slots__ = (
        "_dependents",
        "_subscribers",
        "_lock",
        "__weakref__",
    )

    def __init__(self) -> None:
        self._dependents: "weakref.WeakSet[_Node]" = weakref.WeakSet()
        self._subscribers: List[_Subscription] = []
        self._lock = threading.RLock()

    # ----- internal API used by the graph -----
    def _track_access(self) -> None:
        stack = _eval_stack.get()
        if not stack:
            return
        observer = stack[-1]
        if observer is self:
            return
        observer._add_dependency(self)

    def _add_dependency(self, _other: "_Node") -> None:  # overridden in Derived
        pass

    def _invalidate(self) -> None:  # overridden in Derived
        pass

    def _value_for_subscribers(self) -> Any:  # overridden
        raise NotImplementedError

    def _fire_subscribers(self, old: Any = _UNSET, new: Any = _UNSET) -> None:
        if not self._subscribers:
            return
        if new is _UNSET:
            new = self._value_for_subscribers()
        for sub in list(self._subscribers):
            sub._callback(old, new)

    def _maybe_queue_subscribers(self, old: Any) -> None:
        # ───────────────────────────────────────────────────────────────────
        # BATCH INVARIANT (do not simplify without reading)
        # During a batch, a node's recorded `old` is the value it had at the
        # moment of the FIRST invalidation in the batch — never an
        # intermediate value introduced by the cascade. Replacing the
        # pending entry on later invalidations would break the diamond-
        # dependency test (test_diamond_dependency_fires_subscriber_exactly_once)
        # because subscribers would observe a transient "old" they never
        # actually saw. The "if key not in pending" check is the doctrine
        # holding the test.
        # ───────────────────────────────────────────────────────────────────
        if not self._subscribers:
            return
        if _batch_depth.get() > 0:
            pending = _batch_pending.get()
            if pending is not None:
                key = id(self)
                if key not in pending:
                    pending[key] = (self, old)
            return
        self._fire_subscribers(old=old)

    def _debug_name(self) -> str:
        return f"<{type(self).__name__} 0x{id(self):x}>"


# --------------------------------------------------------------------------- #
# Cell — a source of conditions
# --------------------------------------------------------------------------- #


EqualityCheck = Union[Literal["identity", "equal"], Callable[[Any, Any], bool]]


def _resolve_equality_check(check: EqualityCheck) -> Callable[[Any, Any], bool]:
    if check == "identity":
        return lambda a, b: a is b
    if check == "equal":
        # Try identity fast-path first to avoid invoking user __eq__ on
        # self-equal sentinels; fall back to ==.
        return lambda a, b: a is b or a == b
    if callable(check):
        return check
    raise ValueError(
        f"equality_check must be 'identity', 'equal', or a callable; got {check!r}"
    )


class Cell(_Node, Generic[T]):
    """A mutable source value.

    Reading a Cell while a Derived is computing records a dependency.
    Setting a Cell invalidates every Derived that depends on it
    (transitively) and fires any subscribers (respecting batches).

    Parameters
    ----------
    value:
        The initial value.
    name:
        Optional debug name (used in :class:`SamsaraError` messages).
    equality_check:
        How to decide whether ``set(new)`` is a no-op:

        * ``"equal"`` (default) — uses ``a is b or a == b``. Backwards-
          compatible with v0.1, but ``__eq__`` may have side effects or
          raise for some user types.
        * ``"identity"`` — uses ``a is b`` only. Recommended for objects
          whose equality is expensive, side-effectful, or undefined.
        * A callable ``(old, new) -> bool``: returns True when the values
          should be treated as equal (and ``set`` skipped).
    """

    __slots__ = ("_value", "_name", "_eq")

    def __init__(
        self,
        value: T,
        *,
        name: Optional[str] = None,
        equality_check: EqualityCheck = "equal",
    ) -> None:
        super().__init__()
        self._value: T = value
        self._name = name
        self._eq: Callable[[Any, Any], bool] = _resolve_equality_check(equality_check)

    # ---- read / write ----
    def get(self) -> T:
        """Return the current value, recording a dependency edge if read inside
        a :class:`Derived`'s evaluation."""
        self._track_access()
        return self._value

    def set(self, value: T) -> None:
        """Replace the value and invalidate downstream Derived nodes.

        An implicit batch around every ``set()`` guarantees subscriber
        callbacks (which may call ``.get()`` and thereby re-clean a Derived)
        never run during the invalidation cascade. They fire exactly once,
        in topological order, after the cascade is complete.
        """
        with batch():
            with self._lock:
                old = self._value
                if self._eq(old, value):
                    return
                self._value = value
                for dep in list(self._dependents):
                    dep._invalidate()
            self._maybe_queue_subscribers(old=old)

    def __call__(self) -> T:
        return self.get()

    def _value_for_subscribers(self) -> Any:
        return self._value

    def _debug_name(self) -> str:
        return f"Cell({self._name!r})" if self._name else super()._debug_name()

    def __repr__(self) -> str:
        return f"Cell({self._value!r})"


# --------------------------------------------------------------------------- #
# Derived — a value contingent on other values
# --------------------------------------------------------------------------- #


class Derived(_Node, Generic[T]):
    """A value computed from other Cells or Deriveds.

    The function is re-run on demand: the first read after invalidation
    re-tracks dependencies. Dependencies are pull-based and self-cleaning:
    if a branch of code stops being executed, the corresponding edges
    cease to exist on the next recomputation.
    """

    __slots__ = ("_fn", "_value", "_dirty", "_dependencies", "_name")

    def __init__(self, fn: Callable[[], T], *, name: Optional[str] = None) -> None:
        super().__init__()
        self._fn: Callable[[], T] = fn
        self._value: Any = _UNSET
        self._dirty = True
        self._dependencies: List[_Node] = []
        self._name = name or getattr(fn, "__name__", None)

    # ---- graph edges ----
    def _add_dependency(self, other: _Node) -> None:
        self._dependencies.append(other)
        other._dependents.add(self)

    def _clear_dependencies(self) -> None:
        for dep in self._dependencies:
            try:
                dep._dependents.discard(self)
            except KeyError:
                pass
        self._dependencies.clear()

    # ---- invalidation ----
    def _invalidate(self) -> None:
        with self._lock:
            if self._dirty:
                return
            old = self._value
            self._dirty = True
            # Eagerly notify subscribers (or queue under a batch). They
            # will read .get() themselves to obtain the new value, which
            # forces a single recomputation.
            for d in list(self._dependents):
                d._invalidate()
        self._maybe_queue_subscribers(old=old)

    # ---- evaluation ----
    def get(self) -> T:
        """Return the current value, recomputing if dirty.

        Recomputation re-tracks dependencies (calling :func:`_clear_dependencies`
        first) so a function that branches on its inputs has a self-cleaning
        edge set.
        """
        self._track_access()
        if not self._dirty:
            return self._value  # type: ignore[return-value]
        with self._lock:
            if not self._dirty:  # double-checked under lock
                return self._value  # type: ignore[return-value]
            self._clear_dependencies()
            frame = _push_frame(self)
            try:
                self._value = self._fn()
            finally:
                _pop_frame(frame)
            self._dirty = False
            return self._value  # type: ignore[return-value]

    def __call__(self) -> T:
        return self.get()

    def _value_for_subscribers(self) -> Any:
        # Force compute so subscribers see the new value.
        return self.get()

    def _debug_name(self) -> str:
        return f"Derived({self._name!r})" if self._name else super()._debug_name()

    def __repr__(self) -> str:
        if self._dirty or self._value is _UNSET:
            return f"Derived(<{self._name}>, dirty)"
        return f"Derived(<{self._name}>={self._value!r})"


# --------------------------------------------------------------------------- #
# Subscription
# --------------------------------------------------------------------------- #


@pure
def on_change(node: _Node, callback: Callable[[Any, Any], None]) -> _Subscription:
    """Subscribe ``callback(old, new)`` to changes of a Cell or Derived.

    The subscription is returned and can be cancelled via ``.cancel()``.
    Subscriptions hold a strong reference to their node only via the
    callback's closure; the inverse direction is via ``_subscribers`` which
    is part of the node itself, so cancellation is the user's responsibility.
    """
    if not isinstance(node, _Node):
        raise TypeError("on_change requires a Cell or Derived")
    sub = _Subscription(node, callback)
    node._subscribers.append(sub)
    return sub


# --------------------------------------------------------------------------- #
# Standalone factory
# --------------------------------------------------------------------------- #


@pure
def derive(fn: Optional[Callable[[], T]] = None, *, name: Optional[str] = None):
    """Create a Derived value from a zero-arg callable.

    Usable as a function or decorator::

        c = derive(lambda: a() + b())

        @derive
        def c():
            return a() + b()
    """
    if fn is None:
        def _factory(f: Callable[[], T]) -> Derived[T]:
            return Derived(f, name=name)
        return _factory
    return Derived(fn, name=name)


# --------------------------------------------------------------------------- #
# Descriptor surface for class-bodies
# --------------------------------------------------------------------------- #
#
# The descriptor design keeps the *per-instance* graph living on the instance
# (in a single ``__buddhism_nodes__`` dict).  No graph-state lives on the
# class.  This is the doctrinal point: each instance is its own arising of
# conditions; the class is only a pattern.

_NODES_ATTR = "__buddhism_nodes__"


def _class_has_nodes_slot(cls: type) -> bool:
    """Return True if ``_NODES_ATTR`` is defined as a slot anywhere in MRO.

    We test for a member-descriptor on the class hierarchy rather than calling
    ``getattr`` on the instance, so we don't accidentally pick up an instance
    attribute that happens to be named the same.
    """
    for base in cls.__mro__:
        slot = base.__dict__.get(_NODES_ATTR)
        if slot is not None and not callable(slot):
            return True
    return False


def _instance_nodes(instance: object) -> dict:
    """Return the per-instance ``{name: Node}`` dict, materialising it lazily.

    Storage strategy, in order of preference:

    1. If the class declares ``__buddhism_nodes__`` in ``__slots__``, use that
       slot. (The cleanest path for ``__slots__``-only classes.)
    2. Otherwise, store on ``instance.__dict__``.
    3. If the instance has neither, raise :class:`TypeError` with a clear
       remediation hint.
    """
    cls = type(instance)
    if _class_has_nodes_slot(cls):
        try:
            nodes = getattr(instance, _NODES_ATTR)
        except AttributeError:
            nodes = None
        if nodes is None:
            nodes = {}
            object.__setattr__(instance, _NODES_ATTR, nodes)
        return nodes  # type: ignore[no-any-return]

    try:
        instance_dict = instance.__dict__
    except AttributeError as e:
        cls_name = cls.__name__
        raise TypeError(
            f"{cls_name!r} declares __slots__ without __dict__ and without "
            f"a {_NODES_ATTR!r} slot, so reactive descriptors have nowhere "
            f"to store per-instance graph state. Either add {_NODES_ATTR!r} "
            f"to __slots__, allow __dict__, or do not use cell()/@derived "
            f"on this class."
        ) from e

    nodes = instance_dict.get(_NODES_ATTR)
    if nodes is None:
        nodes = {}
        instance_dict[_NODES_ATTR] = nodes
    return nodes


class _DescriptorBase:
    """Common machinery for cell/derived descriptors."""

    __slots__ = ("_attr_name",)

    def __init__(self) -> None:
        self._attr_name: Optional[str] = None

    def __set_name__(self, owner: type, name: str) -> None:
        self._attr_name = name


class _CellDescriptor(_DescriptorBase, Generic[T]):
    """Descriptor that materialises a per-instance ``Cell`` on first access."""

    __slots__ = ("_default", "_equality_check")

    def __init__(self, default: T, *, equality_check: EqualityCheck = "equal") -> None:
        super().__init__()
        self._default: T = default
        self._equality_check: EqualityCheck = equality_check

    def _get_cell(self, instance: object) -> Cell:
        nodes = _instance_nodes(instance)
        cell_obj = nodes.get(self._attr_name)
        if cell_obj is None:
            cell_obj = Cell(
                self._default,
                name=self._attr_name,
                equality_check=self._equality_check,
            )
            nodes[self._attr_name] = cell_obj
        return cell_obj

    def __get__(self, instance: Optional[object], owner: type) -> Any:
        if instance is None:
            return self
        return self._get_cell(instance).get()

    def __set__(self, instance: object, value: Any) -> None:
        self._get_cell(instance).set(value)


class _DerivedDescriptor(_DescriptorBase, Generic[T]):
    """Descriptor that materialises a per-instance ``Derived`` on first access.

    The wrapped function takes ``self`` as its only argument; we adapt it
    into a zero-arg closure for the underlying Derived.

    Non-clinging invariant
    ----------------------
    The bound closure captures ``self`` via :func:`weakref.ref` so the
    descriptor does not keep the instance alive. If the instance is not
    weak-referenceable, the descriptor *refuses* by default and raises
    :class:`TypeError`. To opt into strong-ref behaviour explicitly, set
    ``__buddhism_strong_refs__ = True`` on the class.
    """

    __slots__ = ("_fn",)

    def __init__(self, fn: Callable[[Any], T]) -> None:
        super().__init__()
        self._fn: Callable[[Any], T] = fn

    def _get_derived(self, instance: object) -> Derived:
        nodes = _instance_nodes(instance)
        node = nodes.get(self._attr_name)
        if node is None:
            try:
                weak_self = weakref.ref(instance)

                def _bound() -> Any:
                    self_ = weak_self()
                    if self_ is None:
                        raise ReferenceError(
                            "Conditioned instance has been collected; "
                            "the conditions for this derivation have ceased."
                        )
                    return self._fn(self_)
            except TypeError:
                if not getattr(type(instance), "__buddhism_strong_refs__", False):
                    raise TypeError(
                        f"{type(instance).__name__!r} is not weak-referenceable, "
                        f"so the reactive graph would have to keep its instances "
                        f"alive (clinging). Either add '__weakref__' to __slots__, "
                        f"or opt into strong-ref mode by setting "
                        f"'__buddhism_strong_refs__ = True' on the class."
                    )
                warnings.warn(
                    f"{type(instance).__name__!r}: strong-ref Derived (instance "
                    f"is not weak-referenceable). The reactive graph will keep "
                    f"this instance alive.",
                    RuntimeWarning,
                    stacklevel=3,
                )

                def _bound() -> Any:
                    return self._fn(instance)

            node = Derived(_bound, name=self._attr_name)
            nodes[self._attr_name] = node
        return node

    def __get__(self, instance: Optional[object], owner: type) -> Any:
        if instance is None:
            return self
        return self._get_derived(instance).get()

    def __set__(self, instance: object, value: Any) -> None:
        raise AttributeError(
            f"{self._attr_name!r} is a derived value; it arises from its "
            f"conditions and cannot be assigned directly."
        )


@pure
def cell(default: T, *, equality_check: EqualityCheck = "equal") -> Any:
    """Class-attribute factory for a reactive Cell.

    Type-erased to ``Any`` so that ``self.attr`` reads as the underlying
    value type to the type-checker.

    See :class:`Cell` for the meaning of ``equality_check``.
    """
    return _CellDescriptor(default, equality_check=equality_check)


@pure
def derived(fn: Callable[[Any], T]) -> Any:
    """Class-attribute decorator for a Derived value (takes ``self``)."""
    return _DerivedDescriptor(fn)


class Conditioned:
    """Optional base class for objects whose attributes are reactive.

    Inheriting from ``Conditioned`` is the most ergonomic path: it gives the
    instance ``__dict__`` and ``__weakref__`` slots, plus introspection via
    :meth:`__pratitya_nodes__`. The descriptors *can* work on classes that
    do not inherit from ``Conditioned``, provided those classes have either
    a ``__dict__`` or a ``__buddhism_nodes__`` slot, and are
    weak-referenceable (or opt into strong-ref mode).
    """

    __slots__ = ("__dict__", "__weakref__")

    def __pratitya_nodes__(self) -> dict:
        """Return a snapshot of the live graph of nodes for this instance."""
        return dict(_instance_nodes(self))
