"""buddhism — load-bearing Buddhist concepts for Python.

Engineering-first elevator pitch: a reactive dependency graph, a
clinging/retention profiler, decay containers, a side-effect ledger,
structural identity tools, runtime three-marks introspection, and a
project-quality checker — all dependency-free, in roughly 2,000 lines
of Python.

Doctrinal mapping (one-to-one with engineering primitives):

* **Pratītyasamutpāda** (Dependent Origination) — :mod:`buddhism.pratitya`
* **Dukkha** (clinging) — :mod:`buddhism.dukkha`
* **Anitya** (impermanence) — :mod:`buddhism.anitya`
* **Anatta** (non-self) — :mod:`buddhism.anatta`
* **Karma** (side-effect accounting) — :mod:`buddhism.karma`
* **Three Marks** (runtime introspection) — :func:`buddhism.examine`
* **Eightfold Path** (project-quality checker) — :mod:`buddhism.path`

A guided tutorial (:mod:`buddhism.koans`) teaches the philosophy and
the underlying Python internals together.
"""

from __future__ import annotations

__version__ = "0.2.0"

from .pratitya import (
    Cell,
    Conditioned,
    Derived,
    EqualityCheck,
    SamsaraError,
    batch,
    cell,
    derive,
    derived,
    on_change,
)
from .dukkha import (
    Attachment,
    ClingingDetected,
    RetentionPath,
    RetentionReport,
    find_cycles,
    let_go,
    observe,
    retention_path,
)
from .anitya import (
    DecayDict,
    DecaySet,
    MemoryPressureRegistry,
    Stale,
    StalenessError,
    exponential_decay,
    impermanent,
    linear_decay,
)
from .anatta import (
    ConfigurationDiff,
    StructuralEq,
    diff,
    without_self,
)
from .karma import (
    IOEvent,
    KarmaDebt,
    KarmaLedger,
    KarmicResult,
    KarmicViolation,
    karmic,
    pure,
)
from .examine import (
    AnattaReading,
    AnityaReading,
    DukkhaReading,
    ThreeMarksReading,
    examine,
)

__all__ = [
    "__version__",
    # pratitya
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
    # dukkha
    "Attachment",
    "RetentionReport",
    "RetentionPath",
    "ClingingDetected",
    "observe",
    "find_cycles",
    "let_go",
    "retention_path",
    # anitya
    "DecayDict",
    "DecaySet",
    "Stale",
    "StalenessError",
    "MemoryPressureRegistry",
    "impermanent",
    "exponential_decay",
    "linear_decay",
    # anatta
    "StructuralEq",
    "ConfigurationDiff",
    "without_self",
    "diff",
    # karma
    "karmic",
    "pure",
    "KarmaLedger",
    "KarmicResult",
    "KarmaDebt",
    "KarmicViolation",
    "IOEvent",
    # examine
    "examine",
    "ThreeMarksReading",
    "AnityaReading",
    "DukkhaReading",
    "AnattaReading",
]
