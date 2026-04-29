"""
dukkha — the profiler of clinging.

  "What, monks, is the noble truth of the origin of dukkha?
   It is craving — clinging — taṇhā — which leads to renewed becoming."
                                        — Dhammacakkappavattana Sutta

In Python, *clinging* is the technical name for: reference cycles you didn't
mean to create, caches that keep growing, closures that capture more than
they should, and listeners that outlive their listened-to.  The garbage
collector is willing to let go; we are the ones holding on.

This module gives you tools to *see* clinging:

* :func:`observe`         — a context manager that diffs the live-object set
                            before and after a block, returning everything
                            that was retained.
* :class:`Attachment`     — a weak handle to one specific object, with
                            ``alive`` and ``referrers()`` for tracing who
                            holds it.
* :func:`find_cycles`     — walks the GC graph for cycles among recently
                            allocated user objects.
* :func:`let_go`          — decorator that asserts a function does not
                            retain its inputs after returning.
* :func:`retention_path`  — show one shortest path of strong references
                            from a GC root to a target object (the
                            "thread of clinging").

Implementation notes:

* We deliberately filter out frames, modules, and the dukkha module's own
  bookkeeping containers from referrer graphs, so reports describe *user*
  retention rather than CPython internals.
* We avoid ``gc.get_referents`` for invalidation logic; we use ``id()`` keys
  in a snapshot so we can safely diff sets without touching object identity
  comparators that may have side effects.
"""

from __future__ import annotations

import functools
import gc
import inspect
import sys
import types
import weakref
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
)

__all__ = [
    "Attachment",
    "RetentionReport",
    "observe",
    "find_cycles",
    "let_go",
    "retention_path",
    "ClingingDetected",
]


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #

# Types we should not attribute as "clinging" because they are essentially
# infrastructure: frames the GC walks, the snapshot containers we ourselves
# create, etc.
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
    # CPython internal mappings / cells.
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
    """Snapshot of objects that belong to dukkha itself.

    These are filtered out of every reachability report so users never see
    the profiler's own state mistakenly attributed to their code.
    """
    # Walk this module's own globals + the typing/dataclass frames.
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
            # Some builtins (e.g. tuple, int, str) cannot be weak-referenced.
            # Fall back to id-based liveness via gc.
            self._ref = None

    @property
    def alive(self) -> bool:
        if self._ref is not None:
            return self._ref() is not None
        # Fallback: scan gc.get_objects() for a matching id().  Slow, but
        # honest about the limitation.
        for obj in gc.get_objects():
            if id(obj) == self._id:
                return True
        return False

    @property
    def typename(self) -> str:
        return self._typename

    def get(self) -> Any:
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
# observe() — diff live objects across a block
# --------------------------------------------------------------------------- #


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

    def text_report(self, *, top_n: int = 12) -> str:
        lines = []
        if not self.new_objects:
            lines.append("No clinging detected. The block let go of everything it took up.")
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
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.text_report()


def _live_object_ids() -> Set[int]:
    """Return the set of ids of currently tracked objects.

    We force a collection first so we don't count objects that are
    *about* to die.
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


@contextmanager
def observe(*, ignore_types: Sequence[type] = ()) -> Iterator[RetentionReport]:
    """Diff live objects across a block. Yields a :class:`RetentionReport`.

    Usage::

        with observe() as r:
            do_some_work()
        print(r.text_report())
    """
    report = RetentionReport()
    # Snapshot before
    before = _live_object_ids()
    # Also snapshot dukkha's internal ids so they never appear in the diff.
    internal = _dukkha_internal_ids()

    try:
        yield report
    finally:
        gc.collect()
        after = _live_object_ids()
        new_ids = after - before - internal
        # Materialise objects.
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

        # Estimate cycles among retained.  We use gc.collect with DEBUG_SAVEALL
        # off; instead we walk the retained set and detect strongly-connected
        # components naively (only for small reports, to keep cost bounded).
        cycles = 0
        if 0 < len(new_objs) <= 5000:
            cycles = _count_cycles_among(new_objs)

        report.new_objects = new_objs
        report.type_counts = type_counts
        report.cycles_found = cycles


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
    pass-through. This is what makes "user-level cycles" visible: ``a.peer = b``
    is reachable through ``a.__dict__`` even though ``a.__dict__`` itself is
    not in our candidate set.
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


def _count_cycles_among(objs: Sequence[Any]) -> int:
    """Count strongly-connected components with internal cycles.

    Uses an iterative Tarjan SCC over the referent graph induced by
    ``objs``, with transparent-container expansion.
    """
    obj_by_id: Dict[int, Any] = {id(o): o for o in objs}
    in_set: Set[int] = set(obj_by_id)
    indices: Dict[int, int] = {}
    lowlinks: Dict[int, int] = {}
    on_stack: Set[int] = set()
    stack: List[int] = []
    counter = [0]
    sccs_with_cycle = 0

    def referents(x_id: int) -> List[int]:
        return _expand_referents(obj_by_id[x_id], in_set)

    def strongconnect(v: int) -> None:
        nonlocal sccs_with_cycle
        # Iterative Tarjan to avoid recursion limit on big graphs.
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
                    members = []
                    while True:
                        x = stack.pop()
                        on_stack.discard(x)
                        members.append(x)
                        if x == node:
                            break
                    if len(members) > 1 or (
                        len(members) == 1 and node in referents(node)
                    ):
                        sccs_with_cycle += 1
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
    return sccs_with_cycle


# --------------------------------------------------------------------------- #
# find_cycles — discover reference cycles among recently allocated objects
# --------------------------------------------------------------------------- #


def find_cycles(objects: Optional[Iterable[Any]] = None) -> List[List[Any]]:
    """Return strongly-connected components of size >1 (or self-loops).

    Each returned inner list is one cycle.  If ``objects`` is None, we
    operate over all gc-tracked, non-infrastructure objects.
    """
    if objects is None:
        gc.collect()
        objects = [
            o for o in gc.get_objects()
            if not _is_infrastructure(o) and id(o) not in _dukkha_internal_ids()
        ]
    objs = list(objects)
    obj_by_id: Dict[int, Any] = {id(o): o for o in objs}
    in_set: Set[int] = set(obj_by_id)
    indices: Dict[int, int] = {}
    lowlinks: Dict[int, int] = {}
    on_stack: Set[int] = set()
    stack: List[int] = []
    counter = [0]
    cycles: List[List[Any]] = []

    def referents(x_id: int) -> List[int]:
        return _expand_referents(obj_by_id[x_id], in_set)

    def strongconnect(v: int) -> None:
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
                        cycles.append([obj_by_id[m] for m in members])
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
    return cycles


# --------------------------------------------------------------------------- #
# let_go decorator
# --------------------------------------------------------------------------- #


class ClingingDetected(AssertionError):
    """Raised by :func:`let_go` when a function retains arguments past return."""


def let_go(fn: Optional[Callable] = None, *, raise_on_clinging: bool = True):
    """Decorator: assert that ``fn`` does not retain its arguments.

    After ``fn`` returns, we check that none of its argument objects are
    still referenced by anything other than the caller's frame and the
    standard infrastructure.  If they are, we either raise
    :class:`ClingingDetected` or emit a warning, depending on
    ``raise_on_clinging``.

    Limitations:
      * Only works for objects that support :func:`weakref.ref`.
      * Cannot detect retention via C extension internals.
      * "Caller's frame" is approximated as the immediate caller; deeper
        re-entry may produce false positives.
    """

    def _wrap(f: Callable) -> Callable:
        @functools.wraps(f)
        def inner(*args, **kwargs):
            attachments: List[Tuple[str, Attachment]] = []
            for i, a in enumerate(args):
                try:
                    attachments.append((f"arg[{i}]:{_safe_type_name(a)}", Attachment(a)))
                except TypeError:
                    pass
            for k, v in kwargs.items():
                try:
                    attachments.append((f"kw:{k}:{_safe_type_name(v)}", Attachment(v)))
                except TypeError:
                    pass

            result = f(*args, **kwargs)

            # Drop our local references to the inputs as best we can.
            args = ()  # noqa: F841 — defensive
            kwargs = {}  # noqa: F841

            gc.collect()

            # Skip refs that are the caller frame, the result itself, or
            # bookkeeping.  We exclude the function's own frame because the
            # `result` variable in inner() is a strong reference.
            self_frame = inspect.currentframe()
            ignore_ids = {id(self_frame), id(result), id(attachments)}
            for o in gc.get_referents(result) if result is not None else ():
                ignore_ids.add(id(o))

            stuck: List[Tuple[str, List[Any]]] = []
            for label, att in attachments:
                if not att.alive:
                    continue
                obj = att.get()
                if obj is None:
                    continue
                refs = [
                    r
                    for r in gc.get_referrers(obj)
                    if id(r) not in ignore_ids
                    and not _is_infrastructure(r)
                ]
                # gc.get_referrers will include our own attachments list and
                # the inner() frame's locals; filter those.
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
                else:
                    import warnings
                    warnings.warn(msg, RuntimeWarning, stacklevel=2)
            return result

        return inner

    if fn is None:
        return _wrap
    return _wrap(fn)


# --------------------------------------------------------------------------- #
# retention_path — show one path of clinging
# --------------------------------------------------------------------------- #


def retention_path(
    target: Any,
    *,
    max_depth: int = 6,
    include_infrastructure: bool = False,
) -> List[Any]:
    """Return one short referrer path leading to ``target``.

    The search proceeds breadth-first from ``target`` outward (along
    referrer edges), stopping at the first object that looks like a
    "rooted" container — a module, a class, or a frame's local namespace.

    The returned list is ordered ``[root, …, target]``.
    """
    skip = _dukkha_internal_ids()
    # Don't skip target's id — we anchor the reconstruction there.
    skip_referrers = set(skip)

    visited: Set[int] = {id(target)}
    # next_step_toward_target[id(referrer)] = (id_of_next, next_obj)
    # i.e. from `referrer`, take one step toward `target` via `next_obj`.
    next_step_toward_target: Dict[int, Tuple[int, Any]] = {}
    # Anchor: target's "next step" is itself.
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
            return []
        return [direct[0], target]

    # Reconstruct path from root_obj down to target.
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
    return path
