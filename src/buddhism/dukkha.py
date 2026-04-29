"""
dukkha — the profiler of clinging.

  "What, monks, is the noble truth of the origin of dukkha?
   It is craving — clinging — taṇhā — which leads to renewed becoming."
                                        — Dhammacakkappavattana Sutta

In Python, *clinging* is the technical name for: reference cycles you didn't
mean to create, caches that keep growing, closures that capture more than
they should, and listeners that outlive their listened-to.  The garbage
collector is willing to let go; we are the ones holding on.

This module provides:

* :class:`Attachment`     — a weak handle to one specific object.
* :func:`observe`         — context manager diffing live objects across a block.
* :class:`RetentionReport`— structured result with cross-module breakdowns.
* :func:`find_cycles`     — strongly-connected components in a referent graph.
* :func:`let_go`          — decorator asserting a function does not retain inputs.
* :func:`retention_path`  — one short path of clinging from a GC root to an object.
* :class:`RetentionPath`  — structured wrapper around the result.

Documented limitations
----------------------
* :func:`observe` walks ``gc.get_objects()`` which only returns
  GC-tracked objects: small ints, interned strings, and tuples of
  immutables are invisible. This is usually a feature for the use case
  ("show me my retained user objects, not CPython internals") but it
  must be stated.

* :func:`let_go` cannot detect retention through C-extension internals
  that bypass weakref or gc. Pure-Python retention is detected reliably.

* The cycle detector treats certain container types (``dict``, ``list``,
  ``tuple``, ``set``, ``frozenset``) as transparent: edges are followed
  through them so user-level cycles are visible even when the cycle
  passes through ``__dict__``.
"""

from __future__ import annotations

import functools
import gc
import inspect
import sys
import types
import warnings
import weakref
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Collection,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from .karma import pure
__all__ = [
    "Attachment",
    "RetentionReport",
    "RetentionPath",
    "observe",
    "find_cycles",
    "let_go",
    "retention_path",
    "ClingingDetected",
]


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #

_INFRASTRUCTURE_TYPES: Tuple[type, ...] = (
    types.FrameType,
    types.ModuleType,
    types.MethodType,
    types.BuiltinFunctionType,
    types.BuiltinMethodType,
    types.MappingProxyType,
)


def _is_infrastructure(obj: Any) -> bool:
    if isinstance(obj, _INFRASTRUCTURE_TYPES):
        return True
    cls = type(obj)
    name = cls.__name__
    if name in {"cell", "weakproxy", "_FakeFrame", "weakcallableproxy"}:
        return True
    return False


def _safe_type_name(obj: Any) -> str:
    try:
        return type(obj).__name__
    except Exception:
        return "<unknown>"


def _safe_repr(obj: Any, limit: int = 80) -> str:
    try:
        r = repr(obj)
    except Exception:
        return f"<{_safe_type_name(obj)} (repr failed)>"
    if len(r) > limit:
        return r[: limit - 1] + "…"
    return r


def _dukkha_internal_ids() -> Set[int]:
    ids: Set[int] = set()
    mod = sys.modules.get(__name__)
    if mod is not None:
        ids.add(id(mod))
        ids.add(id(mod.__dict__))
        for v in mod.__dict__.values():
            ids.add(id(v))
    return ids


# --------------------------------------------------------------------------- #
# Attachment — a weak handle
# --------------------------------------------------------------------------- #


class Attachment:
    """A weak handle to a single object you want to watch let go of.

    Usage::

        a = Attachment(obj)
        del obj
        gc.collect()
        if a.alive:
            print("Still clinging.")
            for r in a.referrers():
                print("  held by:", r)
    """

    __slots__ = ("_ref", "_typename", "_repr", "_id")

    def __init__(self, obj: Any) -> None:
        self._typename = _safe_type_name(obj)
        self._repr = _safe_repr(obj)
        self._id = id(obj)
        try:
            self._ref: Optional[weakref.ReferenceType] = weakref.ref(obj)
        except TypeError:
            self._ref = None

    @property
    def alive(self) -> bool:
        """Whether the watched object is still reachable."""
        if self._ref is not None:
            return self._ref() is not None
        for obj in gc.get_objects():
            if id(obj) == self._id:
                return True
        return False

    @property
    def typename(self) -> str:
        """Type name of the watched object at the time of attachment."""
        return self._typename

    def get(self) -> Any:
        """Strong-deref the weak reference (returns ``None`` if released)."""
        if self._ref is None:
            return None
        return self._ref()

    def referrers(
        self,
        *,
        max_items: int = 25,
        include_infrastructure: bool = False,
    ) -> List[Any]:
        """Return strong referrers of the object (filtered for relevance)."""
        obj = self.get()
        if obj is None:
            return []
        skip = _dukkha_internal_ids()
        skip.add(id(obj))
        skip.add(id(self))
        out: List[Any] = []
        for r in gc.get_referrers(obj):
            if id(r) in skip:
                continue
            if not include_infrastructure and _is_infrastructure(r):
                continue
            out.append(r)
            if len(out) >= max_items:
                break
        return out

    def __repr__(self) -> str:
        state = "alive" if self.alive else "released"
        return f"Attachment({self._typename}, {state}, repr={self._repr})"


# --------------------------------------------------------------------------- #
# RetentionReport — result of observe()
# --------------------------------------------------------------------------- #


@dataclass
class _PratityaBreakdown:
    """Cross-module summary of a retained reactive graph (set by
    :meth:`RetentionReport.pratitya_breakdown`)."""

    cells: int = 0
    deriveds: int = 0
    conditioned_instances: int = 0
    edges: int = 0
    subscribers: int = 0
    examples: List[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        """True if no reactive-graph nodes were retained."""
        return (
            self.cells == 0
            and self.deriveds == 0
            and self.conditioned_instances == 0
        )

    def text_report(self) -> str:
        """Render this breakdown as human-readable text."""
        if self.is_empty():
            return "No reactive-graph nodes retained."
        lines = [
            f"Reactive graph retention:",
            f"  Cell instances:        {self.cells}",
            f"  Derived instances:     {self.deriveds}",
            f"  Conditioned instances: {self.conditioned_instances}",
            f"  Total edges:           {self.edges}",
            f"  Total subscribers:     {self.subscribers}",
        ]
        if self.examples:
            lines.append("  Examples:")
            for e in self.examples[:5]:
                lines.append(f"    - {e}")
        return "\n".join(lines)


@dataclass
class RetentionReport:
    """Result of an :func:`observe` block."""

    new_objects: List[Any] = field(default_factory=list)
    type_counts: Dict[str, int] = field(default_factory=dict)
    cycles_found: int = 0

    def attachments(self) -> List[Attachment]:
        """Wrap each new object in an :class:`Attachment` (best-effort)."""
        out: List[Attachment] = []
        for obj in self.new_objects:
            try:
                out.append(Attachment(obj))
            except Exception:
                continue
        return out

    def pratitya_breakdown(self) -> _PratityaBreakdown:
        """Cross-module hook: summarise any retained reactive-graph nodes.

        If the leak you caught is a `pratitya.Cell` / `Derived` /
        `Conditioned` (or an instance whose ``__dict__`` contains such a
        graph), this returns a structured summary of *what kind* of
        leaking reactive graph it is.
        """
        breakdown = _PratityaBreakdown()
        try:
            from buddhism import pratitya as _p
        except Exception:  # pratitya not importable for some reason
            return breakdown

        Cell = _p.Cell
        Derived = _p.Derived
        Conditioned = _p.Conditioned

        for obj in self.new_objects:
            if isinstance(obj, Cell):
                breakdown.cells += 1
                breakdown.edges += len(obj._dependents)
                breakdown.subscribers += len(obj._subscribers)
                breakdown.examples.append(obj._debug_name())
            elif isinstance(obj, Derived):
                breakdown.deriveds += 1
                breakdown.edges += len(obj._dependents) + len(obj._dependencies)
                breakdown.subscribers += len(obj._subscribers)
                breakdown.examples.append(obj._debug_name())
            elif isinstance(obj, Conditioned):
                breakdown.conditioned_instances += 1
                try:
                    nodes = obj.__pratitya_nodes__()
                    breakdown.examples.append(
                        f"{type(obj).__name__}({len(nodes)} nodes)"
                    )
                except Exception:
                    breakdown.examples.append(type(obj).__name__)
        return breakdown

    def text_report(self, *, top_n: int = 12) -> str:
        """Render this retention report as human-readable text."""
        lines = []
        if not self.new_objects:
            lines.append(
                "No clinging detected. The block let go of everything it took up."
            )
            return "\n".join(lines)
        lines.append(
            f"{len(self.new_objects)} object(s) retained after the block. "
            f"({self.cycles_found} reference cycle(s) detected.)"
        )
        lines.append("")
        lines.append("Top retained types:")
        ranked = sorted(self.type_counts.items(), key=lambda kv: kv[1], reverse=True)
        for name, count in ranked[:top_n]:
            lines.append(f"  {count:>5}  {name}")
        if len(ranked) > top_n:
            extra = sum(c for _, c in ranked[top_n:])
            lines.append(f"  {extra:>5}  (other types)")

        breakdown = self.pratitya_breakdown()
        if not breakdown.is_empty():
            lines.append("")
            lines.append(breakdown.text_report())

        return "\n".join(lines)

    def __str__(self) -> str:
        return self.text_report()


# --------------------------------------------------------------------------- #
# observe() — diff live objects across a block
# --------------------------------------------------------------------------- #


def _live_object_ids() -> Set[int]:
    """Return ids of currently GC-tracked objects.

    LIMITATION: This walks ``gc.get_objects()``, which only returns objects
    tracked by the cyclic GC. Small ints, interned strings, and atomic
    tuples are invisible — they are reference-counted but not GC-tracked.
    For the use case (detecting *user* retention) this is appropriate.
    """
    gc.collect()
    return {id(o) for o in gc.get_objects()}


def _ids_to_objects(ids: Iterable[int]) -> List[Any]:
    target = set(ids)
    out: List[Any] = []
    for o in gc.get_objects():
        if id(o) in target:
            out.append(o)
    return out


@pure
@contextmanager
def observe(*, ignore_types: Sequence[type] = ()) -> Iterator[RetentionReport]:
    """Diff live objects across a block, yielding a :class:`RetentionReport`.

    Usage::

        with observe() as r:
            do_some_work()
        print(r.text_report())

    Limitations:
      * Only GC-tracked objects are visible (see :func:`_live_object_ids`).
      * Forces ``gc.collect()`` at entry and exit to avoid spurious reports
        on about-to-die objects.
    """
    report = RetentionReport()
    before = _live_object_ids()
    internal = _dukkha_internal_ids()

    try:
        yield report
    finally:
        gc.collect()
        after = _live_object_ids()
        new_ids = after - before - internal
        new_objs: List[Any] = []
        type_counts: Dict[str, int] = {}
        ignore_set: Tuple[type, ...] = tuple(ignore_types)
        for obj in _ids_to_objects(new_ids):
            if _is_infrastructure(obj):
                continue
            if ignore_set and isinstance(obj, ignore_set):
                continue
            new_objs.append(obj)
            tn = _safe_type_name(obj)
            type_counts[tn] = type_counts.get(tn, 0) + 1

        cycles = 0
        if 0 < len(new_objs) <= 5000:
            cycles = _tarjan_sccs(new_objs, return_components=False)  # type: ignore[assignment]

        report.new_objects = new_objs
        report.type_counts = type_counts
        report.cycles_found = cycles


# --------------------------------------------------------------------------- #
# Cycle detection (Tarjan SCC, used by both observe() and find_cycles())
# --------------------------------------------------------------------------- #

_TRANSPARENT_CONTAINER_TYPES: Tuple[type, ...] = (
    dict,
    list,
    tuple,
    set,
    frozenset,
)


def _expand_referents(x: Any, in_set: Set[int]) -> List[int]:
    """Return ids of objects in ``in_set`` reachable from ``x`` via referents,
    treating transparent containers (dict, list, tuple, set, frozenset) as
    pass-through.

    This is what makes "user-level cycles" visible: ``a.peer = b`` is
    reachable through ``a.__dict__`` even though ``a.__dict__`` itself
    is not in our candidate set.
    """
    out: List[int] = []
    # Note: we deliberately do NOT pre-mark id(x); we must be able to
    # detect self-loops (an object referencing itself through its __dict__).
    seen: Set[int] = set()
    try:
        stack = list(gc.get_referents(x))
    except Exception:
        return out
    while stack:
        r = stack.pop()
        rid = id(r)
        if rid in seen:
            continue
        seen.add(rid)
        if rid in in_set:
            out.append(rid)
            continue  # don't recurse past a "real" graph node
        if isinstance(r, _TRANSPARENT_CONTAINER_TYPES):
            try:
                stack.extend(gc.get_referents(r))
            except Exception:
                continue
    return out


def _tarjan_sccs(
    objs: Sequence[Any],
    *,
    return_components: bool,
) -> Union[int, List[List[Any]]]:
    """Iterative Tarjan SCC over the referent graph induced by ``objs``,
    with transparent-container expansion.

    If ``return_components`` is True, returns a list of SCCs (each a
    list of objects) where every SCC has size > 1 OR is a self-loop.
    Otherwise returns the count of such SCCs.
    """
    obj_by_id: Dict[int, Any] = {id(o): o for o in objs}
    in_set: Set[int] = set(obj_by_id)
    indices: Dict[int, int] = {}
    lowlinks: Dict[int, int] = {}
    on_stack: Set[int] = set()
    stack: List[int] = []
    counter = [0]
    components: List[List[Any]] = []
    count = 0

    def referents(x_id: int) -> List[int]:
        return _expand_referents(obj_by_id[x_id], in_set)

    def strongconnect(v: int) -> None:
        nonlocal count
        work: List[Tuple[int, Iterator[int]]] = [(v, iter(referents(v)))]
        indices[v] = counter[0]
        lowlinks[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        while work:
            node, it = work[-1]
            try:
                w = next(it)
            except StopIteration:
                work.pop()
                if work:
                    parent = work[-1][0]
                    if lowlinks[node] < lowlinks[parent]:
                        lowlinks[parent] = lowlinks[node]
                if lowlinks[node] == indices[node]:
                    members: List[int] = []
                    while True:
                        x = stack.pop()
                        on_stack.discard(x)
                        members.append(x)
                        if x == node:
                            break
                    if len(members) > 1 or (
                        len(members) == 1 and node in referents(node)
                    ):
                        if return_components:
                            components.append([obj_by_id[m] for m in members])
                        else:
                            count += 1
                continue
            if w not in indices:
                indices[w] = counter[0]
                lowlinks[w] = counter[0]
                counter[0] += 1
                stack.append(w)
                on_stack.add(w)
                work.append((w, iter(referents(w))))
            elif w in on_stack:
                if indices[w] < lowlinks[node]:
                    lowlinks[node] = indices[w]

    for o in objs:
        if id(o) not in indices:
            strongconnect(id(o))

    return components if return_components else count


@pure
def find_cycles(objects: Optional[Iterable[Any]] = None) -> List[List[Any]]:
    """Return strongly-connected components of size >1 (or self-loops).

    Each returned inner list is one cycle. If ``objects`` is None, we
    operate over all gc-tracked, non-infrastructure objects (slow on large
    processes — prefer passing an explicit candidate set).
    """
    if objects is None:
        gc.collect()
        objects = [
            o for o in gc.get_objects()
            if not _is_infrastructure(o) and id(o) not in _dukkha_internal_ids()
        ]
    objs = list(objects)
    return _tarjan_sccs(objs, return_components=True)  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# let_go decorator
# --------------------------------------------------------------------------- #


class ClingingDetected(AssertionError):
    """Raised by :func:`let_go` when a function retains arguments past return."""


# Sentinel for "use default"
_DEFAULT_ALLOW: frozenset = frozenset()


def _walk_referents(root: Any, max_depth: int) -> Set[int]:
    """Collect ids of all objects reachable from ``root`` via referents,
    up to ``max_depth`` hops. Used to whitelist argument retention through
    a returned structure.
    """
    if root is None:
        return set()
    found: Set[int] = {id(root)}
    frontier: List[Any] = [root]
    for _ in range(max_depth):
        next_frontier: List[Any] = []
        for obj in frontier:
            try:
                for r in gc.get_referents(obj):
                    rid = id(r)
                    if rid in found:
                        continue
                    found.add(rid)
                    next_frontier.append(r)
            except Exception:
                continue
        if not next_frontier:
            break
        frontier = next_frontier
    return found


def let_go(
    fn: Optional[Callable] = None,
    *,
    raise_on_clinging: bool = True,
    allow: Optional[Collection[Union[int, str]]] = None,
    transitive_depth: int = 3,
):
    """Decorator: assert that ``fn`` does not retain its arguments after returning.

    Parameters
    ----------
    raise_on_clinging:
        If True (default), raise :class:`ClingingDetected` on retention;
        otherwise emit a :class:`RuntimeWarning`.
    allow:
        Iterable of argument positions (ints) or keyword names (strs)
        whose retention is permitted. Useful for constructors that
        legitimately store an argument as ``self.<attr>``::

            class Service:
                @let_go(allow={"config", 0})
                def __init__(self, config, *, debug=False):
                    self.config = config
    transitive_depth:
        How many hops outward from the returned value count as "carried
        out by the result." Defaults to 3 so that ``return [wrapper(x)]``
        does not flag transitive retention through the returned structure.
        Set to 0 to disable transitive whitelisting.

    Limitations
    -----------
    * Works for objects that support :func:`weakref.ref`. Immutable atoms
      (small ints, interned strings, plain tuples) cannot be tracked.
    * Cannot detect retention via C-extension internals.
    """

    allow_set: frozenset = frozenset(allow) if allow else _DEFAULT_ALLOW

    def _wrap(f: Callable) -> Callable:
        # Pre-compute the signature once for parameter-name binding.
        try:
            sig = inspect.signature(f)
        except (TypeError, ValueError):
            sig = None

        @functools.wraps(f)
        def inner(*args, **kwargs):
            # Bind positional args to parameter names so that allow={"config"}
            # matches the first positional argument when its parameter is named
            # config. Falls back to numeric indices if signature isn't available.
            param_name_for_pos: Dict[int, str] = {}
            if sig is not None:
                pos_params = [
                    p.name for p in sig.parameters.values()
                    if p.kind in (
                        inspect.Parameter.POSITIONAL_ONLY,
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    )
                ]
                for i in range(min(len(args), len(pos_params))):
                    param_name_for_pos[i] = pos_params[i]

            attachments: List[Tuple[str, int, Optional[str], Attachment]] = []
            for i, a in enumerate(args):
                try:
                    attachments.append(
                        (
                            f"arg[{i}]:{_safe_type_name(a)}",
                            i,
                            param_name_for_pos.get(i),
                            Attachment(a),
                        )
                    )
                except TypeError:
                    pass
            for k, v in kwargs.items():
                try:
                    attachments.append(
                        (f"kw:{k}:{_safe_type_name(v)}", -1, k, Attachment(v))
                    )
                except TypeError:
                    pass

            result = f(*args, **kwargs)

            args = ()  # noqa: F841 — defensive
            kwargs = {}  # noqa: F841

            gc.collect()

            self_frame = inspect.currentframe()
            ignore_ids: Set[int] = {id(self_frame), id(attachments)}

            # The result is the function's contract with its caller, so
            # retention *through* the result is "carried out" rather than
            # "clinging" — unless the user explicitly disables this with
            # transitive_depth=0.
            if result is not None and transitive_depth > 0:
                ignore_ids |= _walk_referents(result, transitive_depth)

            stuck: List[Tuple[str, List[Any]]] = []
            for label, pos, kw, att in attachments:
                if not att.alive:
                    continue
                # Allow-list short circuit
                if pos in allow_set or (kw is not None and kw in allow_set):
                    continue
                obj = att.get()
                if obj is None:
                    continue
                refs = [
                    r
                    for r in gc.get_referrers(obj)
                    if id(r) not in ignore_ids and not _is_infrastructure(r)
                ]
                refs = [r for r in refs if r is not attachments]
                if refs:
                    stuck.append((label, refs))

            if stuck:
                summary = "; ".join(
                    f"{label} held by {len(refs)} ref(s) "
                    f"({', '.join(_safe_type_name(r) for r in refs[:3])})"
                    for label, refs in stuck
                )
                msg = (
                    f"{f.__qualname__}: clinging detected. "
                    f"The following arguments were retained beyond the call: {summary}"
                )
                if raise_on_clinging:
                    raise ClingingDetected(msg)
                warnings.warn(msg, RuntimeWarning, stacklevel=2)
            return result

        return inner

    if fn is None:
        return _wrap
    return _wrap(fn)


# --------------------------------------------------------------------------- #
# RetentionPath — structured wrapper around retention_path()
# --------------------------------------------------------------------------- #


@dataclass
class RetentionPath:
    """A structured retention path ``[root, …, target]``.

    Iterable and indexable like a list, so existing v0.1 callers that
    treated the result as a ``List[Any]`` continue to work.
    """

    path: List[Any] = field(default_factory=list)

    @property
    def path_types(self) -> List[str]:
        """Type names for each step in the path."""
        return [_safe_type_name(o) for o in self.path]

    def format(self, *, indent: int = 2, repr_limit: int = 60) -> str:
        """Render the path as a numbered, indented list."""
        if not self.path:
            return "(no retention path found)"
        pad = " " * indent
        lines = []
        for i, obj in enumerate(self.path):
            kind = _safe_type_name(obj)
            short = _safe_repr(obj, limit=repr_limit)
            lines.append(f"{pad}[{i}] {kind:>16}  {short}")
        return "\n".join(lines)

    # List-compat surface
    def __iter__(self) -> Iterator[Any]:
        return iter(self.path)

    def __len__(self) -> int:
        return len(self.path)

    def __getitem__(self, i):  # type: ignore[no-untyped-def]
        return self.path[i]

    def __bool__(self) -> bool:
        return bool(self.path)

    def __repr__(self) -> str:
        return f"RetentionPath(len={len(self.path)})"


# --------------------------------------------------------------------------- #
# retention_path — show one path of clinging
# --------------------------------------------------------------------------- #


@pure
def retention_path(
    target: Any,
    *,
    max_depth: int = 6,
    include_infrastructure: bool = False,
) -> RetentionPath:
    """Return one short referrer path leading to ``target``.

    The search proceeds breadth-first from ``target`` outward (along
    referrer edges), stopping at the first object that looks like a
    "rooted" container — a module, a class, or a frame's local namespace.

    The returned :class:`RetentionPath` is iterable and indexable like a
    list, ordered ``[root, …, target]``.
    """
    skip = _dukkha_internal_ids()
    skip_referrers = set(skip)

    visited: Set[int] = {id(target)}
    next_step_toward_target: Dict[int, Tuple[int, Any]] = {}
    next_step_toward_target[id(target)] = (id(target), target)

    frontier: List[Any] = [target]
    root_obj: Optional[Any] = None
    root_id: Optional[int] = None

    for _depth in range(max_depth):
        next_frontier: List[Any] = []
        for node in frontier:
            try:
                refs = gc.get_referrers(node)
            except Exception:
                continue
            for r in refs:
                rid = id(r)
                if rid in visited or rid in skip_referrers:
                    continue
                if not include_infrastructure and _is_infrastructure(r):
                    continue
                visited.add(rid)
                next_step_toward_target[rid] = (id(node), node)
                if isinstance(r, (type, types.ModuleType)):
                    root_obj = r
                    root_id = rid
                    break
                next_frontier.append(r)
            if root_obj is not None:
                break
        if root_obj is not None:
            break
        if not next_frontier:
            break
        frontier = next_frontier

    if root_obj is None:
        try:
            direct = [
                r for r in gc.get_referrers(target)
                if not _is_infrastructure(r) and id(r) not in skip_referrers
            ]
        except Exception:
            direct = []
        if not direct:
            return RetentionPath([])
        return RetentionPath([direct[0], target])

    path: List[Any] = [root_obj]
    cur_id: int = root_id  # type: ignore[assignment]
    while cur_id != id(target):
        step = next_step_toward_target.get(cur_id)
        if step is None:
            break
        next_id, next_obj = step
        path.append(next_obj)
        if next_id == cur_id:
            break
        cur_id = next_id
    return RetentionPath(path)
