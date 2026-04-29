"""
karma — actions, traced.

  "Beings are owners of their karma, heirs of their karma, born of their
   karma, related through their karma, and have their karma as their refuge."
                                              — Aṅguttara Nikāya 5.57

Side-effect accounting. Every call to a :func:`karmic` function is observed
along four axes:

* globals **read** by the function body
* globals **written** by the function body
* I/O **events** (file open, network connect, subprocess) — runtime-traced
* arguments **mutated** by reference (compared via deep snapshots)

The result of the wrapped call is wrapped in a :class:`KarmicResult`,
which destructures: ``value, ledger = karmic_fn(...)``.

Three operating modes:

* **Default** — accumulate a :class:`KarmaLedger`; the user reads it.
* **Allow-list strict mode** — ``@karmic(allow={...})``: any side effect
  *outside* the allow-list raises :class:`KarmicViolation`.
* **Debt mode** — over many calls, unacknowledged side effects accumulate
  as :class:`KarmaDebt`. Tests can assert maximum debt thresholds.

Documented limitations
----------------------
* Globals tracking uses a tracking-``dict`` substituted for the function's
  ``__globals__``. CPython optimisations of ``LOAD_GLOBAL`` (especially
  3.11+ inline caches) may bypass the tracker, so read-tracking is
  best-effort. Write-tracking via ``STORE_GLOBAL`` is reliable across
  versions.
* I/O tracking is runtime-patching of ``builtins.open``, ``socket.socket``,
  and ``subprocess.Popen``. C-extensions that call into these from C
  bypass the patches. The package documents this.
* Argument mutation tracking uses ``copy.deepcopy`` snapshots; types
  that don't deepcopy (e.g. open file handles) are skipped, with a record
  in the ledger's ``unsupported`` list.
"""

from __future__ import annotations

import builtins
import copy
import functools
import threading
import types
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    Iterable,
    List,
    Optional,
    Set,
    Tuple,
    TypeVar,
    Union,
)

__all__ = [
    "karmic",
    "pure",
    "KarmaLedger",
    "KarmicResult",
    "KarmaDebt",
    "KarmicViolation",
    "IOEvent",
]


def pure(out_fn: Callable[..., T]) -> Callable[..., T]:
    """Marker decorator: declare that a function is intentionally side-effect-free.

    This is a *declarative* tag, not a runtime contract: it sets
    ``fn.__buddhism_pure__ = True`` and otherwise returns the function
    unchanged.  Combine with ``@karmic`` for runtime enforcement, or rely
    on :mod:`buddhism.path`'s Right Mindfulness check to verify that
    every public function carries a tag.

    The point: every public function in a disciplined codebase should have
    its effects *named* — even if the name is "none."

    The parameter is named ``out_fn`` because the decorator does mark its
    input (sets an attribute), so the "out" naming is doctrinally honest.
    """
    out_fn.__buddhism_pure__ = True  # type: ignore[attr-defined]
    return out_fn

T = TypeVar("T")


# --------------------------------------------------------------------------- #
# I/O event record
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class IOEvent:
    """One observed I/O action: ``kind`` is one of
    ``{"file_open", "socket_connect", "subprocess"}``; ``detail`` is a
    short string describing the operation."""

    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind}({self.detail})"


# --------------------------------------------------------------------------- #
# Per-thread active ledger stack (so nested @karmic calls accumulate properly)
# --------------------------------------------------------------------------- #


class _KarmaState(threading.local):
    def __init__(self) -> None:
        super().__init__()
        self.stack: List["KarmaLedger"] = []


_state = _KarmaState()


def _record_io(event: IOEvent) -> None:
    """Push ``event`` onto every ledger currently on this thread's stack."""
    if not _state.stack:
        return
    for ledger in _state.stack:
        ledger.io_events.append(event)


# --------------------------------------------------------------------------- #
# I/O patching (scoped via reference-counting)
# --------------------------------------------------------------------------- #


_io_patch_lock = threading.Lock()
_io_patch_count = 0
_originals: Dict[str, Any] = {}


def _activate_io_tracking() -> None:
    """Patch I/O entry points so they record events to the active ledger."""
    global _io_patch_count
    with _io_patch_lock:
        _io_patch_count += 1
        if _io_patch_count > 1:
            return  # already patched

        _originals["open"] = builtins.open

        def tracking_open(*args: Any, **kwargs: Any):
            path = args[0] if args else kwargs.get("file", "?")
            mode = args[1] if len(args) >= 2 else kwargs.get("mode", "r")
            _record_io(IOEvent(kind="file_open", detail=f"{path!r} mode={mode!r}"))
            return _originals["open"](*args, **kwargs)

        builtins.open = tracking_open  # type: ignore[assignment]

        # socket
        try:
            import socket as _socket
            _originals["socket_connect"] = _socket.socket.connect

            def tracking_connect(self: Any, address: Any) -> Any:
                _record_io(IOEvent(kind="socket_connect", detail=str(address)))
                return _originals["socket_connect"](self, address)

            _socket.socket.connect = tracking_connect  # type: ignore[assignment]
        except Exception:
            pass

        # subprocess
        try:
            import subprocess as _subprocess
            _originals["popen_init"] = _subprocess.Popen.__init__

            def tracking_popen(self: Any, *args: Any, **kwargs: Any) -> None:
                cmd = args[0] if args else kwargs.get("args", "?")
                _record_io(IOEvent(kind="subprocess", detail=str(cmd)))
                _originals["popen_init"](self, *args, **kwargs)

            _subprocess.Popen.__init__ = tracking_popen  # type: ignore[assignment]
        except Exception:
            pass


def _deactivate_io_tracking() -> None:
    """Restore original I/O entry points (when no ledger remains active)."""
    global _io_patch_count
    with _io_patch_lock:
        _io_patch_count -= 1
        if _io_patch_count > 0:
            return
        if "open" in _originals:
            builtins.open = _originals.pop("open")
        if "socket_connect" in _originals:
            try:
                import socket as _socket
                _socket.socket.connect = _originals.pop("socket_connect")  # type: ignore[assignment]
            except Exception:
                _originals.pop("socket_connect", None)
        if "popen_init" in _originals:
            try:
                import subprocess as _subprocess
                _subprocess.Popen.__init__ = _originals.pop("popen_init")  # type: ignore[assignment]
            except Exception:
                _originals.pop("popen_init", None)


# --------------------------------------------------------------------------- #
# Tracking globals dict
# --------------------------------------------------------------------------- #


class _TrackingGlobals(dict):
    """A dict subclass that records reads against a parent ledger.

    Used to substitute a function's ``__globals__`` so that ``LOAD_GLOBAL``
    is observed via ``__getitem__``. Note that ``STORE_GLOBAL`` and
    ``DELETE_GLOBAL`` bypass dict subclasses in CPython (PyDict_SetItem
    goes straight to the C-level setter), so writes are detected by
    snapshot-and-diff in :func:`karmic` rather than via ``__setitem__``.

    Read-tracking is best-effort: CPython 3.11+ inline-caches LOAD_GLOBAL,
    which can bypass ``__getitem__`` for hot frames.
    """

    def __init__(self, source: Dict[str, Any], ledger: "KarmaLedger") -> None:
        super().__init__(source)
        object.__setattr__(self, "_ledger", ledger)

    def __getitem__(self, key: str) -> Any:  # type: ignore[override]
        ledger: KarmaLedger = self._ledger  # type: ignore[attr-defined]
        if not key.startswith("__"):
            ledger.globals_read.add(key)
        return super().__getitem__(key)


def _diff_globals_writes(
    before_keys: FrozenSet[str],
    before_ids: Dict[str, int],
    current: Dict[str, Any],
    ledger: "KarmaLedger",
) -> None:
    """Detect global writes by diffing the function's globals dict.

    A write is recorded when:
      * a key is new (added during the call), or
      * an existing key now binds a different object (by id).
    """
    current_keys = set(current.keys())
    for k in current_keys - before_keys:
        if k.startswith("__"):
            continue
        ledger.globals_written.add(k)
    for k in before_keys & current_keys:
        if k.startswith("__"):
            continue
        if id(current[k]) != before_ids.get(k):
            ledger.globals_written.add(k)
    for k in before_keys - current_keys:
        if k.startswith("__"):
            continue
        ledger.globals_written.add(k)  # del-from-globals counts as write


# --------------------------------------------------------------------------- #
# KarmaLedger
# --------------------------------------------------------------------------- #


@dataclass
class KarmaLedger:
    """Structured side-effect record from one ``@karmic`` call."""

    globals_read: Set[str] = field(default_factory=set)
    globals_written: Set[str] = field(default_factory=set)
    io_events: List[IOEvent] = field(default_factory=list)
    arg_mutations: Dict[int, Tuple[Any, Any]] = field(default_factory=dict)
    unsupported: List[str] = field(default_factory=list)
    acknowledged: Set[str] = field(default_factory=set)

    def is_pure(self) -> bool:
        """True iff this call produced *no* side effects."""
        return (
            not self.globals_written
            and not self.io_events
            and not self.arg_mutations
        )

    def acknowledge(
        self,
        *,
        globals: Iterable[str] = (),
        io: bool = False,
        args: Iterable[int] = (),
    ) -> None:
        """Mark named side effects as accepted, reducing :meth:`debt`."""
        for g in globals:
            self.acknowledged.add(f"global:{g}")
        if io:
            self.acknowledged.add("io")
        for i in args:
            self.acknowledged.add(f"arg:{i}")

    def debt(self) -> "KarmaDebt":
        """Compute a :class:`KarmaDebt` over unacknowledged side effects."""
        unacked_globals = {
            g for g in self.globals_written
            if f"global:{g}" not in self.acknowledged
        }
        io_unacked = bool(self.io_events) and "io" not in self.acknowledged
        unacked_args = {
            i for i in self.arg_mutations
            if f"arg:{i}" not in self.acknowledged
        }
        return KarmaDebt(
            globals_unacknowledged=unacked_globals,
            io_unacknowledged=io_unacked,
            args_unacknowledged=unacked_args,
        )

    def text_report(self) -> str:
        """Render this ledger as a multi-line human-readable text block."""
        if self.is_pure():
            return "Karma ledger: pure call (no observed side effects)."
        lines = ["Karma ledger:"]
        if self.globals_read:
            lines.append(f"  globals read:    {sorted(self.globals_read)}")
        if self.globals_written:
            lines.append(f"  globals written: {sorted(self.globals_written)}")
        if self.io_events:
            lines.append(f"  io events:       {len(self.io_events)}")
            for e in self.io_events[:5]:
                lines.append(f"    - {e}")
            if len(self.io_events) > 5:
                lines.append(f"    ... ({len(self.io_events) - 5} more)")
        if self.arg_mutations:
            lines.append(f"  arg mutations:   indices {sorted(self.arg_mutations)}")
        if self.unsupported:
            lines.append(f"  unsupported:     {self.unsupported}")
        return "\n".join(lines)


@dataclass
class KarmaDebt:
    """Unacknowledged side effects, summarised."""

    globals_unacknowledged: Set[str] = field(default_factory=set)
    io_unacknowledged: bool = False
    args_unacknowledged: Set[int] = field(default_factory=set)

    @property
    def total(self) -> int:
        """Total count of unacknowledged side-effect items."""
        return (
            len(self.globals_unacknowledged)
            + (1 if self.io_unacknowledged else 0)
            + len(self.args_unacknowledged)
        )

    def __bool__(self) -> bool:
        return self.total > 0

    def __str__(self) -> str:
        return f"KarmaDebt(total={self.total})"


# --------------------------------------------------------------------------- #
# KarmicResult — value + ledger
# --------------------------------------------------------------------------- #


class KarmicResult(tuple):
    """A 2-tuple ``(value, ledger)`` with named attribute access.

    Destructures naturally::

        result, ledger = karmic_fn(...)

    and exposes named access::

        out = karmic_fn(...)
        out.value
        out.ledger
    """

    __slots__ = ()

    def __new__(cls, value: Any, ledger: "KarmaLedger") -> "KarmicResult":
        return tuple.__new__(cls, (value, ledger))

    @property
    def value(self) -> Any:
        """The wrapped function's return value."""
        return self[0]

    @property
    def ledger(self) -> "KarmaLedger":
        """The :class:`KarmaLedger` accumulated during the call."""
        return self[1]

    def __repr__(self) -> str:
        return f"KarmicResult(value={self.value!r}, ledger=<{self.ledger.text_report().splitlines()[0]}>)"


# --------------------------------------------------------------------------- #
# KarmicViolation
# --------------------------------------------------------------------------- #


class KarmicViolation(RuntimeError):
    """Raised when ``@karmic(allow=...)`` strict mode detects an unauthorised
    side effect."""


# --------------------------------------------------------------------------- #
# Argument-snapshot helpers
# --------------------------------------------------------------------------- #


_ATOMIC = (type(None), bool, int, float, complex, str, bytes, frozenset)


def _is_atomic(obj: Any) -> bool:
    if isinstance(obj, _ATOMIC):
        return True
    if isinstance(obj, tuple) and all(_is_atomic(x) for x in obj):
        return True
    return False


def _snapshot(obj: Any) -> Tuple[Any, Optional[str]]:
    """Return ``(snapshot_or_None, error)`` for argument mutation tracking.

    Atomic types skip the snapshot (they are their own snapshot); everything
    else is deepcopied. If deepcopy fails, the error string is returned and
    the caller should record it in ``ledger.unsupported``.
    """
    if _is_atomic(obj):
        return obj, None
    try:
        return copy.deepcopy(obj), None
    except Exception as e:
        return None, f"{type(obj).__name__}: {e!s}"


def _equal_after(before: Any, after: Any) -> bool:
    if before is after:
        return True
    try:
        return before == after
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# karmic decorator
# --------------------------------------------------------------------------- #


def karmic(
    fn: Optional[Callable[..., T]] = None,
    *,
    allow: Optional[Iterable[str]] = None,
    track_globals: bool = True,
    track_io: bool = True,
    track_arg_mutations: bool = True,
) -> Any:
    """Decorator: wrap ``fn`` to return a :class:`KarmicResult`.

    Parameters
    ----------
    allow:
        Iterable of side-effect names. If provided, switches to strict
        mode: any side effect *not* in the allow-list raises
        :class:`KarmicViolation`. Naming convention:

        * ``"global:NAME"`` — permits writing to global ``NAME``
        * ``"io"`` — permits any I/O event
        * ``"arg:0"``, ``"arg:1"`` — permits mutating positional arg N
        * the literal name ``"global:*"`` permits any global write
    track_globals, track_io, track_arg_mutations:
        Per-axis disable flags (default all True). Strict-mode violations
        only fire on tracked axes.

    The decorated function returns a :class:`KarmicResult` for unwrapping.
    """

    allow_set: FrozenSet[str] = frozenset(allow) if allow else frozenset()
    strict = allow is not None

    def _wrap(f: Callable[..., T]) -> Callable[..., KarmicResult]:
        if not isinstance(f, types.FunctionType):
            raise TypeError(
                f"@karmic only supports plain Python functions, not {type(f).__name__}"
            )

        @functools.wraps(f)
        def inner(*args: Any, **kwargs: Any) -> KarmicResult:
            ledger = KarmaLedger()

            # Snapshot positional args (mutation tracking).
            snapshots: Dict[int, Any] = {}
            if track_arg_mutations:
                for i, a in enumerate(args):
                    snap, err = _snapshot(a)
                    if err is not None:
                        ledger.unsupported.append(f"arg[{i}] ({err})")
                    elif not _is_atomic(a):
                        snapshots[i] = snap

            if track_io:
                _activate_io_tracking()
            _state.stack.append(ledger)

            # Optionally substitute __globals__ for read tracking, and
            # snapshot the original dict for write diff.
            target_fn: Callable[..., T] = f
            before_keys: FrozenSet[str] = frozenset()
            before_ids: Dict[str, int] = {}
            tracking_globals: Optional[_TrackingGlobals] = None
            if track_globals:
                # Snapshot real globals BEFORE we substitute, so we can diff
                # the real dict (which the function will mutate via STORE_GLOBAL).
                real_globals = f.__globals__
                before_keys = frozenset(real_globals.keys())
                before_ids = {k: id(v) for k, v in real_globals.items()}
                # The tracking dict is a copy used only for read observation;
                # writes inside the function still hit f.__globals__ because
                # we substitute with a dict that *shares the same underlying
                # state* via dict-update semantics. Concretely: we install
                # the tracking dict, run, then propagate any new/changed
                # keys back into the real __globals__ AFTER the call.
                tracking_globals = _TrackingGlobals(real_globals, ledger)
                target_fn = types.FunctionType(
                    f.__code__,
                    tracking_globals,
                    f.__name__,
                    f.__defaults__,
                    f.__closure__,
                )
                target_fn.__kwdefaults__ = f.__kwdefaults__  # type: ignore[attr-defined]

            try:
                value = target_fn(*args, **kwargs)
            finally:
                _state.stack.pop()
                if track_io:
                    _deactivate_io_tracking()
                if track_globals and tracking_globals is not None:
                    # Diff the tracking dict against the snapshot; record
                    # writes; then propagate new/changed bindings back to
                    # the real module globals so the function's effect on
                    # module state is preserved.
                    real_globals = f.__globals__
                    _diff_globals_writes(
                        before_keys, before_ids, dict(tracking_globals), ledger
                    )
                    # Propagate to real globals
                    for k, v in tracking_globals.items():
                        if k.startswith("__"):
                            continue
                        if k not in before_keys or id(v) != before_ids.get(k):
                            real_globals[k] = v
                    for k in before_keys - set(tracking_globals.keys()):
                        if k.startswith("__"):
                            continue
                        real_globals.pop(k, None)

            # Compare arg snapshots to detect mutation.
            if track_arg_mutations:
                for i, before in snapshots.items():
                    if i >= len(args):
                        continue
                    after = args[i]
                    if not _equal_after(before, after):
                        ledger.arg_mutations[i] = (before, after)

            # Strict mode: check allow-list
            if strict:
                _enforce_allow(ledger, allow_set, f)

            return KarmicResult(value, ledger)

        inner.__buddhism_karmic__ = True  # type: ignore[attr-defined]
        return inner

    if fn is None:
        return _wrap
    return _wrap(fn)


def _enforce_allow(
    ledger: KarmaLedger,
    allow_set: FrozenSet[str],
    f: Callable[..., Any],
) -> None:
    violations: List[str] = []

    if "global:*" not in allow_set:
        for g in ledger.globals_written:
            if f"global:{g}" not in allow_set:
                violations.append(f"global write: {g}")
    if ledger.io_events and "io" not in allow_set:
        for e in ledger.io_events:
            if f"io:{e.kind}" not in allow_set:
                violations.append(f"io: {e}")
    for i in ledger.arg_mutations:
        if f"arg:{i}" not in allow_set:
            violations.append(f"argument {i} mutated")

    if violations:
        raise KarmicViolation(
            f"{f.__qualname__}: side effects outside allow-list: {violations}"
        )
