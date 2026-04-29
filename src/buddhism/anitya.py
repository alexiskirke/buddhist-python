"""
anitya — Anitya / Anicca (Impermanence).

  "All conditioned things are impermanent —
   when one sees this with wisdom, one turns away from suffering."
                                                — Dhammapada 277

Time as a first-class engineering primitive. Three tools:

* :class:`DecayDict` / :class:`DecaySet` — staleness as a continuous
  gradient: each entry returns a ``(value, confidence)`` tuple where
  confidence ∈ [0, 1] decays from 1 at insertion to ``eviction_threshold``.
  Not ``cachetools.TTLCache`` renamed: TTL is binary (alive/dead);
  this is graded.

* :func:`impermanent` — decorator marking a function whose return value
  has an expected validity window. Calls past the window return a
  :class:`Stale` wrapper that the caller must explicitly unwrap (refresh
  or accept). Bare attribute access on a :class:`Stale` raises
  :class:`StalenessError`. Like :class:`typing.Optional` for time.

* :class:`MemoryPressureRegistry` — register objects to be released under
  memory pressure, in priority order. Built on :class:`weakref.finalize`
  and :func:`resource.getrusage` (POSIX).
"""

from __future__ import annotations

import functools
import heapq
import math
import threading
import time
import weakref
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    TypeVar,
    Union,
)

from .karma import pure
__all__ = [
    "DecayDict",
    "DecaySet",
    "Stale",
    "StalenessError",
    "impermanent",
    "MemoryPressureRegistry",
    "exponential_decay",
    "linear_decay",
]

T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")


# --------------------------------------------------------------------------- #
# Decay functions
# --------------------------------------------------------------------------- #


@pure
def exponential_decay(elapsed_over_half_life: float) -> float:
    """``2 ** -(elapsed / half_life)``."""
    return float(2.0 ** -elapsed_over_half_life)


@pure
def linear_decay(elapsed_over_half_life: float) -> float:
    """``max(0, 1 - elapsed/(2*half_life))`` — reaches 0 at 2 half-lives."""
    return max(0.0, 1.0 - 0.5 * elapsed_over_half_life)


# --------------------------------------------------------------------------- #
# DecayDict / DecaySet — confidence-graded containers
# --------------------------------------------------------------------------- #


class DecayDict(Generic[K, V]):
    """A mapping whose entries' confidence decays continuously.

    Each :meth:`set` records the wall-clock time of insertion. Each
    :meth:`get` returns ``(value, confidence)`` where ``confidence`` is
    ``decay(elapsed / half_life) ∈ [0, 1]``. When confidence falls below
    ``eviction_threshold``, the entry is removed on the next access.

    Parameters
    ----------
    half_life:
        Seconds at which the default decay function returns 0.5.
    decay:
        ``Callable[[float], float]`` mapping ``elapsed/half_life`` to
        confidence. Default: :func:`exponential_decay`.
    eviction_threshold:
        Entries whose confidence drops below this on access are evicted.
    clock:
        Callable returning the current time, defaults to ``time.monotonic``.
        Inject a fake clock to make tests deterministic.
    """

    def __init__(
        self,
        half_life: float,
        *,
        decay: Callable[[float], float] = exponential_decay,
        eviction_threshold: float = 0.01,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if half_life <= 0:
            raise ValueError("half_life must be positive")
        if not (0.0 <= eviction_threshold < 1.0):
            raise ValueError("eviction_threshold must be in [0, 1)")
        self.half_life = float(half_life)
        self._decay = decay
        self.eviction_threshold = float(eviction_threshold)
        self._clock = clock
        # name -> (timestamp, value)
        self._store: Dict[K, Tuple[float, V]] = {}
        self._lock = threading.RLock()

    # ----- core API -----
    def set(self, key: K, value: V) -> None:
        """Store ``value`` under ``key``, recording the current time."""
        with self._lock:
            self._store[key] = (self._clock(), value)

    def get(self, key: K, default: Any = None) -> Tuple[Optional[V], float]:
        """Return ``(value, confidence)``.

        On miss, returns ``(default, 0.0)``.
        On hit-but-too-stale, evicts and returns ``(default, 0.0)``.
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return default, 0.0
            timestamp, value = entry
            elapsed = self._clock() - timestamp
            confidence = self._decay(elapsed / self.half_life)
            if confidence < self.eviction_threshold:
                del self._store[key]
                return default, 0.0
            return value, confidence

    def confidence(self, key: K) -> float:
        """Return current confidence for ``key`` without evicting."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return 0.0
            timestamp, _ = entry
            elapsed = self._clock() - timestamp
            return float(self._decay(elapsed / self.half_life))

    def delete(self, key: K) -> None:
        """Remove ``key`` from the dict if present."""
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        """Remove every entry."""
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return key in self._store

    def __iter__(self) -> Iterator[K]:
        with self._lock:
            return iter(list(self._store.keys()))

    def items(self) -> List[Tuple[K, V, float]]:
        """Return ``[(key, value, confidence), ...]`` for all live entries."""
        with self._lock:
            now = self._clock()
            out: List[Tuple[K, V, float]] = []
            for k, (ts, v) in list(self._store.items()):
                elapsed = now - ts
                conf = float(self._decay(elapsed / self.half_life))
                if conf < self.eviction_threshold:
                    del self._store[k]
                    continue
                out.append((k, v, conf))
            return out

    def __repr__(self) -> str:
        return f"DecayDict(half_life={self.half_life}, n={len(self._store)})"


class DecaySet(Generic[T]):
    """A set whose membership decays continuously.

    Implemented atop :class:`DecayDict` with value ``True``.
    """

    def __init__(
        self,
        half_life: float,
        *,
        decay: Callable[[float], float] = exponential_decay,
        eviction_threshold: float = 0.01,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._d: DecayDict = DecayDict(
            half_life,
            decay=decay,
            eviction_threshold=eviction_threshold,
            clock=clock,
        )

    def add(self, item: T) -> None:
        """Add ``item`` (or refresh its insertion time)."""
        self._d.set(item, True)

    def confidence(self, item: T) -> float:
        """Return current membership confidence for ``item`` ∈ [0, 1]."""
        return self._d.confidence(item)

    def __contains__(self, item: object) -> bool:
        v, c = self._d.get(item)  # type: ignore[arg-type]
        return v is True

    def __len__(self) -> int:
        return len(self._d)

    def __iter__(self) -> Iterator[T]:
        return iter(self._d)


# --------------------------------------------------------------------------- #
# Stale[T] — explicit-staleness wrapper
# --------------------------------------------------------------------------- #


class StalenessError(RuntimeError):
    """Raised when a stale value is accessed without explicit acknowledgement."""


class Stale(Generic[T]):
    """A value that has gone stale and demands an explicit decision.

    Bare attribute access raises :class:`StalenessError`. To use the value:

    * ``s.refresh()`` — re-call the underlying function, returning a fresh
      value.
    * ``s.accept_stale()`` — return the cached stale value, acknowledging
      its staleness.
    * ``s.cached_value`` — read the cached value without acknowledgement
      (does not raise, but also does not refresh).
    """

    __slots__ = (
        "_value",
        "_age",
        "_validity",
        "_refresh_fn",
        "__weakref__",
    )

    def __init__(
        self,
        value: T,
        *,
        age: float,
        validity: float,
        refresh_fn: Callable[[], T],
    ) -> None:
        object.__setattr__(self, "_value", value)
        object.__setattr__(self, "_age", age)
        object.__setattr__(self, "_validity", validity)
        object.__setattr__(self, "_refresh_fn", refresh_fn)

    @property
    def age(self) -> float:
        """Seconds since the cached value was computed."""
        return self._age

    @property
    def validity(self) -> float:
        """The validity window the wrapped function declared, in seconds."""
        return self._validity

    @property
    def cached_value(self) -> T:
        """Raw access without acknowledgement. Does not raise."""
        return self._value

    def refresh(self) -> T:
        """Re-call the underlying function and return the fresh value."""
        return self._refresh_fn()

    def accept_stale(self) -> T:
        """Return the cached stale value, explicitly acknowledging staleness."""
        return self._value

    def __getattr__(self, name: str) -> Any:
        # Bare access: refuse, force the user to choose.
        raise StalenessError(
            f"Value is stale (age={self._age:.2f}s > validity={self._validity:.2f}s); "
            f"call .refresh(), .accept_stale(), or read .cached_value to continue."
        )

    def __repr__(self) -> str:
        return f"Stale(age={self._age:.2f}s, validity={self._validity:.2f}s)"


# --------------------------------------------------------------------------- #
# @impermanent — validity-window decorator
# --------------------------------------------------------------------------- #


def impermanent(
    validity: float,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> Callable[[Callable[..., T]], Callable[..., Union[T, "Stale[T]"]]]:
    """Decorator: mark a function whose return value has a validity window.

    Inside the window, calls return the cached value directly. Outside,
    calls return a :class:`Stale[T]` the caller must explicitly unwrap.

    Parameters
    ----------
    validity:
        Seconds the cached value is considered fresh.
    clock:
        Time source, defaults to :func:`time.monotonic`. Inject for tests.

    Caching is keyed on the *call signature* (positional + keyword args
    rendered to a hashable tuple). Functions whose arguments are not
    hashable will simply not reuse caches; they re-compute every call.
    """
    if validity <= 0:
        raise ValueError("validity must be positive")

    def _wrap(fn: Callable[..., T]) -> Callable[..., Union[T, "Stale[T]"]]:
        cache: Dict[Tuple[Any, ...], Tuple[float, T]] = {}
        lock = threading.RLock()

        def _key(args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> Optional[Tuple[Any, ...]]:
            try:
                return (args, tuple(sorted(kwargs.items())))
            except TypeError:
                return None

        def _recompute(args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> T:
            value = fn(*args, **kwargs)
            key = _key(args, kwargs)
            if key is not None:
                with lock:
                    cache[key] = (clock(), value)
            return value

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Union[T, "Stale[T]"]:
            key = _key(args, kwargs)
            now = clock()
            if key is not None:
                with lock:
                    entry = cache.get(key)
                if entry is not None:
                    ts, value = entry
                    age = now - ts
                    if age <= validity:
                        return value
                    # Bind a refresh closure that bypasses the cache check
                    # and forces a recomputation, updating the cache.
                    return Stale(
                        value,
                        age=age,
                        validity=validity,
                        refresh_fn=lambda: _recompute(args, kwargs),  # noqa: B023
                    )
            return _recompute(args, kwargs)

        wrapper.__validity__ = validity  # type: ignore[attr-defined]
        wrapper.__buddhism_anitya__ = True  # type: ignore[attr-defined]
        return wrapper

    return _wrap


# --------------------------------------------------------------------------- #
# MemoryPressureRegistry — drop-on-load registry
# --------------------------------------------------------------------------- #


@dataclass(order=True)
class _RegistryEntry:
    priority: int
    insertion_order: int
    obj_id: int = field(compare=False)
    on_release: Optional[Callable[[], None]] = field(compare=False, default=None)
    weakref: Any = field(compare=False, default=None)


def _default_pressure_bytes() -> int:
    """Best-effort current resident memory in bytes (POSIX) or 0."""
    try:
        import resource as _resource
        usage = _resource.getrusage(_resource.RUSAGE_SELF)
        # ru_maxrss is bytes on macOS, kilobytes on Linux. Normalise.
        import sys as _sys
        if _sys.platform == "darwin":
            return int(usage.ru_maxrss)
        return int(usage.ru_maxrss) * 1024
    except Exception:
        return 0


class MemoryPressureRegistry:
    """Register objects that opt into being released under memory pressure.

    Lower ``priority`` values are released first ("less attached").
    Releasing means: the registry's internal reference is dropped, and any
    ``on_release`` callback is invoked. The user's external strong refs
    are *not* touched — the registry only releases what *it* holds.

    The primary use case is a registry of caches/buffers that ``get_X``
    can rebuild on demand: when memory is tight, the registry forgets,
    and the next ``get_X()`` recomputes.
    """

    def __init__(self) -> None:
        self._entries: List[_RegistryEntry] = []
        self._counter = 0
        self._lock = threading.RLock()

    def register(
        self,
        obj: Any,
        *,
        priority: int = 0,
        on_release: Optional[Callable[[], None]] = None,
    ) -> None:
        """Add ``obj`` to the registry. Lower priorities are released first."""
        with self._lock:
            self._counter += 1
            try:
                wref = weakref.ref(obj)
            except TypeError:
                wref = lambda obj=obj: obj  # type: ignore[assignment,misc]
            entry = _RegistryEntry(
                priority=priority,
                insertion_order=self._counter,
                obj_id=id(obj),
                on_release=on_release,
                weakref=wref,
            )
            heapq.heappush(self._entries, entry)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def release_under_pressure(
        self,
        target_bytes: int,
        *,
        current_pressure: Optional[Callable[[], int]] = None,
    ) -> int:
        """Release entries until the current pressure is at or below
        ``target_bytes``.

        If ``current_pressure`` is None, uses :func:`_default_pressure_bytes`.
        Returns the number of entries released.
        """
        pressure_fn = current_pressure or _default_pressure_bytes
        released = 0
        with self._lock:
            while self._entries and pressure_fn() > target_bytes:
                entry = heapq.heappop(self._entries)
                obj = entry.weakref() if callable(entry.weakref) else None
                if entry.on_release is not None:
                    try:
                        entry.on_release()
                    except Exception:
                        pass
                # Drop the registry's reference. (We never held a strong one
                # by design; this just removes the heap entry.)
                released += 1
                # Encourage release of ``obj`` if it's only held by the
                # caller's local scope and our weakref.
                del obj
        return released

    def release_all(self) -> int:
        """Release every registered entry, in priority order. Returns count."""
        with self._lock:
            count = len(self._entries)
            while self._entries:
                entry = heapq.heappop(self._entries)
                if entry.on_release is not None:
                    try:
                        entry.on_release()
                    except Exception:
                        pass
            return count

    def release_n(self, n: int) -> int:
        """Release the lowest-priority ``n`` entries. Returns count released."""
        with self._lock:
            count = 0
            while self._entries and count < n:
                entry = heapq.heappop(self._entries)
                if entry.on_release is not None:
                    try:
                        entry.on_release()
                    except Exception:
                        pass
                count += 1
            return count
