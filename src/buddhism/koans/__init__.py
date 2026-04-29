"""buddhism.koans — a tutorial track.

Each koan is a small Python module that pairs one Buddhist concept with one
deep Python feature, expressed as a series of broken assertions that the
student fixes.  Run them with::

    python -m buddhism.koans

The runner reports the first failure, with the relevant hint, and stops.
Fix it, re-run, advance.
"""

from __future__ import annotations

__all__ = ["KOAN_ORDER", "__"]


# The placeholder token. Failing assertions compare some computed value to
# this sentinel; the student replaces it with the correct answer.
class _Blank:
    def __repr__(self) -> str:
        return "__"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Blank)

    def __ne__(self, other: object) -> bool:
        return not isinstance(other, _Blank)

    def __hash__(self) -> int:
        return 0


__ = _Blank()


# Ordered list of koan module names (without the package prefix).
KOAN_ORDER = (
    "k01_impermanence",
    "k02_dependent_origination",
    "k03_non_self",
    "k04_clinging",
    "k05_emptiness",
    "k06_karma",
    "k07_three_marks",
)
