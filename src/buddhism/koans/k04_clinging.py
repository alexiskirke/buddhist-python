"""Koan 04 — Clinging (Upādāna).

  "What is the cause of dukkha? Clinging."
                                — Saṃyutta Nikāya

Python feature: ``weakref``, ``gc``, and reference graphs.

We don't fail to release because objects refuse — we hold them ourselves.
The garbage collector is willing.  When a memory leak is not in C code,
it is always *us*: a closure, a registry, a cache, a listener list.

This koan uses :mod:`buddhism.dukkha` to make clinging visible.
"""

from __future__ import annotations

import gc
import weakref

from buddhism.dukkha import Attachment, observe

from . import __  # noqa: F401
from buddhism.karma import pure

TITLE = "Clinging — the GC is willing; we hold on."

HINT = (
    "Strong references in lists, dicts, closures, and class registries "
    "keep objects alive. weakref.ref lets you observe an object without "
    "keeping it. The gc module lets you see who is holding what."
)


class _Bell:
    """A tiny class so we can use weakref on it."""

    def __init__(self, name: str) -> None:
        self.name = name


def _step_a_lone_object_is_collected() -> None:
    bell = _Bell("morning")
    a = Attachment(bell)
    assert a.alive

    bell = None  # release the only strong reference
    gc.collect()
    assert not a.alive  # the bell was let go


def _step_a_strong_reference_clings() -> None:
    bell = _Bell("morning")
    a = Attachment(bell)
    keepers = [bell]  # one strong reference, in a list
    bell = None
    gc.collect()
    assert a.alive  # still clinging because the list holds it

    keepers.clear()
    gc.collect()
    assert not a.alive  # released


def _step_weakref_observes_without_clinging() -> None:
    bell = _Bell("morning")
    ref = weakref.ref(bell)
    assert ref() is bell  # we can see it through the weakref

    bell = None
    gc.collect()
    assert ref() is None  # the weakref does not keep it alive


def _step_a_closure_silently_clings() -> None:
    def make_logger():
        bell = _Bell("captured")
        a = Attachment(bell)

        def log() -> str:
            return bell.name  # the closure captures `bell`

        return log, a

    log, a = make_logger()
    gc.collect()
    # The closure holds `bell` in its __closure__; releasing our local
    # name does not release the bell.
    assert a.alive
    assert log() == "captured"

    # But once we drop the closure itself, the captured bell goes free.
    log = None
    gc.collect()
    assert not a.alive


def _step_observe_diffs_clinging() -> None:
    # observe() snapshots the live-object set before/after a block, then
    # reports anything that survived. It is the core diagnostic.
    leaked: list = []

    with observe() as report:
        for i in range(5):
            leaked.append(_Bell(f"bell-{i}"))

    # Five bells were retained because we put them in `leaked`.
    type_count = report.type_counts.get("_Bell", 0)
    assert type_count == 5
    assert "_Bell" in report.text_report()


@pure
def KOAN() -> None:
    """Run all steps of this koan; raises AssertionError on first failure."""
    _step_a_lone_object_is_collected()
    _step_a_strong_reference_clings()
    _step_weakref_observes_without_clinging()
    _step_a_closure_silently_clings()
    _step_observe_diffs_clinging()
