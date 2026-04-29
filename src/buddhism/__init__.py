"""buddhism — load-bearing Buddhist concepts for Python.

This package treats four Buddhist ideas as engineering primitives:

  * **Pratītyasamutpāda** (Dependent Origination) — values arising from
    conditions, propagating automatically.  See :mod:`buddhism.pratitya`.
  * **Dukkha** (Clinging / unsatisfactoriness) — the engineering form of
    dukkha is a reference leak.  See :mod:`buddhism.dukkha`.
  * **Anitya** (Impermanence) — to be released in v0.2 as decay containers.
  * **Anatta** (Non-self) — to be released in v0.2 as identity tools.

A guided tutorial (:mod:`buddhism.koans`) teaches both the philosophy and
the underlying Python internals.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .pratitya import (
    Cell,
    Conditioned,
    Derived,
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
    RetentionReport,
    find_cycles,
    let_go,
    observe,
    retention_path,
)

__all__ = [
    "__version__",
    # pratitya
    "Cell",
    "Derived",
    "Conditioned",
    "SamsaraError",
    "cell",
    "derive",
    "derived",
    "batch",
    "on_change",
    # dukkha
    "Attachment",
    "RetentionReport",
    "ClingingDetected",
    "observe",
    "find_cycles",
    "let_go",
    "retention_path",
]
