"""
examine — the Three Marks of Existence as runtime introspection.

  "All conditioned things are anitya (impermanent).
   All conditioned things are dukkha (subject to clinging).
   All things are anatta (without independent self)."
                                  — Tilakkhaṇa, the Three Marks

A single function: ``examine(obj)`` returns a :class:`ThreeMarksReading`
with three orthogonal views of any Python object — change-over-time,
what is currently clinging to it, and how it is configured.

The reading is *progressively richer* as the object adopts more of the
package's primitives. It works on plain objects, with extra detail for
:class:`buddhism.pratitya.Conditioned` instances, decorated functions, and
:class:`buddhism.anatta.StructuralEq` types.
"""

from __future__ import annotations

import gc
import weakref
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .anatta import _public_attrs as _anatta_public_attrs
from .dukkha import RetentionPath, _is_infrastructure, retention_path

from .karma import pure
__all__ = [
    "AnityaReading",
    "AnattaReading",
    "DukkhaReading",
    "ThreeMarksReading",
    "examine",
]


# --------------------------------------------------------------------------- #
# Sub-readings
# --------------------------------------------------------------------------- #


@dataclass
class AnityaReading:
    """How does this object change over time?

    Fields are populated only when the relevant primitives apply:

    * ``is_impermanent``: the value is wrapped or returned by an
      ``@impermanent`` function.
    * ``staleness``: if a :class:`Stale` wrapper, the age and validity.
    * ``decay_dict_membership``: keys in any :class:`DecayDict` that
      reference this object as their value (best-effort scan).
    """

    is_impermanent: bool = False
    validity: Optional[float] = None
    staleness: Optional[Dict[str, float]] = None
    decay_dict_membership: List[str] = field(default_factory=list)


@dataclass
class DukkhaReading:
    """What is currently clinging to this object?"""

    is_alive: bool = True
    direct_referrer_count: int = 0
    direct_referrer_types: List[str] = field(default_factory=list)
    retention_path: Optional[RetentionPath] = None
    reactive_subscribers: int = 0


@dataclass
class AnattaReading:
    """What is this object's configuration of conditions?"""

    type_name: str = ""
    public_attrs: Dict[str, Any] = field(default_factory=dict)
    structural_hash: Optional[int] = None
    reactive_dependencies: List[str] = field(default_factory=list)
    pure_form_available: bool = False


@dataclass
class ThreeMarksReading:
    """Three orthogonal views of a Python object."""

    obj_repr: str
    anitya: AnityaReading = field(default_factory=AnityaReading)
    dukkha: DukkhaReading = field(default_factory=DukkhaReading)
    anatta: AnattaReading = field(default_factory=AnattaReading)

    def text_report(self) -> str:
        """Render the three views as a human-readable text block."""
        lines = [f"examine({self.obj_repr})", ""]
        lines.append("  Anitya — change over time:")
        if self.anitya.is_impermanent:
            lines.append(
                f"    impermanent: validity={self.anitya.validity}s"
            )
            if self.anitya.staleness:
                lines.append(
                    f"    staleness:   age={self.anitya.staleness['age']:.2f}s "
                    f"validity={self.anitya.staleness['validity']:.2f}s"
                )
        else:
            lines.append("    (no time-relevant decoration found)")

        lines.append("")
        lines.append("  Dukkha — what is clinging:")
        lines.append(f"    alive:                 {self.dukkha.is_alive}")
        lines.append(
            f"    direct referrers:      {self.dukkha.direct_referrer_count}"
        )
        if self.dukkha.direct_referrer_types:
            ts = ", ".join(self.dukkha.direct_referrer_types[:5])
            lines.append(f"    referrer types:        {ts}")
        if self.dukkha.retention_path is not None:
            lines.append(f"    retention path:        {len(self.dukkha.retention_path)} hop(s)")
        if self.dukkha.reactive_subscribers:
            lines.append(
                f"    reactive subscribers:  {self.dukkha.reactive_subscribers}"
            )

        lines.append("")
        lines.append("  Anatta — configuration of conditions:")
        lines.append(f"    type:                  {self.anatta.type_name}")
        if self.anatta.public_attrs:
            n = len(self.anatta.public_attrs)
            sample = list(self.anatta.public_attrs)[:5]
            lines.append(f"    public attrs ({n}):       {sample}")
        if self.anatta.structural_hash is not None:
            lines.append(
                f"    structural hash:       {self.anatta.structural_hash}"
            )
        if self.anatta.reactive_dependencies:
            lines.append(
                f"    reactive dependencies: "
                f"{self.anatta.reactive_dependencies}"
            )
        if self.anatta.pure_form_available:
            lines.append("    pure form:             available via without_self()")

        return "\n".join(lines)

    def __str__(self) -> str:
        return self.text_report()


# --------------------------------------------------------------------------- #
# examine()
# --------------------------------------------------------------------------- #


def _safe_repr(obj: Any, limit: int = 80) -> str:
    try:
        r = repr(obj)
    except Exception:
        return f"<{type(obj).__name__} (repr failed)>"
    return r if len(r) <= limit else r[: limit - 1] + "…"


def _read_anitya(obj: Any, out_reading: AnityaReading) -> None:
    """Populate the Anitya view: time-related decorators and wrappers."""
    try:
        from .anitya import Stale
    except Exception:
        return
    if isinstance(obj, Stale):
        out_reading.is_impermanent = True
        out_reading.validity = obj.validity
        out_reading.staleness = {"age": obj.age, "validity": obj.validity}
        return
    if callable(obj) and getattr(obj, "__buddhism_anitya__", False):
        out_reading.is_impermanent = True
        out_reading.validity = getattr(obj, "__validity__", None)


def _read_dukkha(obj: Any, out_reading: DukkhaReading) -> None:
    """Populate the Dukkha view: liveness, referrers, retention path,
    reactive subscribers."""
    try:
        wref = weakref.ref(obj)
        out_reading.is_alive = wref() is not None
    except TypeError:
        out_reading.is_alive = True

    try:
        refs = [r for r in gc.get_referrers(obj) if not _is_infrastructure(r)]
        out_reading.direct_referrer_count = len(refs)
        out_reading.direct_referrer_types = [type(r).__name__ for r in refs[:8]]
    except Exception:
        pass

    try:
        path = retention_path(obj)
        if path:
            out_reading.retention_path = path
    except Exception:
        pass

    try:
        from .pratitya import Cell, Derived
        if isinstance(obj, (Cell, Derived)):
            out_reading.reactive_subscribers = len(obj._subscribers)
    except Exception:
        pass


def _read_anatta(obj: Any, out_reading: AnattaReading) -> None:
    """Populate the Anatta view: type, public configuration, structural
    hash, reactive dependencies, pure-form availability."""
    out_reading.type_name = type(obj).__name__
    try:
        out_reading.public_attrs = {
            k: _safe_repr(v, limit=30)
            for k, v in _anatta_public_attrs(obj).items()
        }
    except Exception:
        pass

    try:
        from .anatta import StructuralEq
        if isinstance(obj, StructuralEq):
            try:
                out_reading.structural_hash = hash(obj)
            except Exception:
                pass
    except Exception:
        pass

    try:
        from .pratitya import Conditioned
        if isinstance(obj, Conditioned):
            nodes = obj.__pratitya_nodes__()
            out_reading.reactive_dependencies = sorted(nodes.keys())
    except Exception:
        pass

    try:
        cls = type(obj)
        for name, attr in cls.__dict__.items():
            if name.startswith("_") or not callable(attr):
                continue
            out_reading.pure_form_available = True
            break
    except Exception:
        pass


@pure
def examine(obj: Any) -> ThreeMarksReading:
    """Return a :class:`ThreeMarksReading` for any Python object.

    Output is progressively richer when the object is one of:

    * :class:`Stale` — Anitya gets staleness info.
    * :class:`buddhism.pratitya.Conditioned` instance — Anatta gets
      reactive dependencies.
    * :class:`buddhism.anatta.StructuralEq` instance — Anatta gets a
      structural hash.
    * Any class with a public method — Anatta notes that a pure form
      is available via :func:`buddhism.anatta.without_self`.
    """
    reading = ThreeMarksReading(obj_repr=_safe_repr(obj))
    _read_anitya(obj, reading.anitya)
    _read_dukkha(obj, reading.dukkha)
    _read_anatta(obj, reading.anatta)
    return reading
