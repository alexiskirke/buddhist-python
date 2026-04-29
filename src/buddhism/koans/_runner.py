"""Koan runner.

Walks koans in order; for each koan, runs its ``KOAN()`` function, which
should raise an :class:`AssertionError` on the first not-yet-fixed step.
The runner prints a brief context for the failure, including the koan
file path and the line number, and stops.

When all koans pass, prints a final mark.
"""

from __future__ import annotations

import importlib
import sys
import traceback
from types import ModuleType
from typing import List, Tuple

from . import KOAN_ORDER

_BANNER_TOP = "─" * 72
_BANNER_BOT = "─" * 72


def _load(name: str) -> ModuleType:
    return importlib.import_module(f"buddhism.koans.{name}")


def _format_failure(koan_name: str, mod: ModuleType, exc: BaseException) -> str:
    tb = traceback.TracebackException.from_exception(exc)
    last = None
    for frame in tb.stack:
        # Find the frame inside the koan module.
        if frame.filename == getattr(mod, "__file__", None):
            last = frame
    out = []
    out.append(_BANNER_TOP)
    out.append(f"  Koan: {koan_name}")
    title = getattr(mod, "TITLE", None)
    if title:
        out.append(f"  Title: {title}")
    if last is not None:
        out.append(f"  At: {last.filename}:{last.lineno}")
        if last.line:
            out.append(f"      {last.line.strip()}")
    msg = str(exc).strip()
    if msg:
        out.append("")
        out.append("  " + msg.replace("\n", "\n  "))
    hint = getattr(mod, "HINT", None)
    if hint:
        out.append("")
        out.append("  hint: " + hint.replace("\n", "\n        "))
    out.append(_BANNER_BOT)
    return "\n".join(out)


def run(only: List[str] = None) -> int:
    targets: Tuple[str, ...] = tuple(only) if only else KOAN_ORDER
    completed = 0
    for name in targets:
        try:
            mod = _load(name)
        except Exception:
            print(f"failed to load koan: {name}", file=sys.stderr)
            traceback.print_exc()
            return 2
        koan_fn = getattr(mod, "KOAN", None)
        if not callable(koan_fn):
            print(f"koan {name} has no KOAN() function", file=sys.stderr)
            return 2
        try:
            koan_fn()
        except AssertionError as e:
            print(_format_failure(name, mod, e))
            print(f"  {completed}/{len(targets)} koans completed.")
            return 1
        except Exception as e:  # noqa: BLE001 — re-raise non-assertion as failure
            print(_format_failure(name, mod, e))
            print("  Something unexpected happened. Read the error above.")
            return 1
        completed += 1
        print(f"  ✓ {name}")

    print()
    print(_BANNER_TOP)
    print("  All koans completed.")
    print()
    print("  'In the seen, only the seen.")
    print("   In the heard, only the heard.")
    print("   In the cognised, only the cognised.'")
    print("                              — Bāhiya Sutta, Udāna 1.10")
    print(_BANNER_BOT)
    return 0
