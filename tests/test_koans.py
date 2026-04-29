"""All koans must pass out-of-the-box. Editing them is for the student."""

from __future__ import annotations

import importlib

import pytest

from buddhism.koans import KOAN_ORDER


@pytest.mark.parametrize("name", KOAN_ORDER)
def test_koan_passes(name: str) -> None:
    mod = importlib.import_module(f"buddhism.koans.{name}")
    koan_fn = getattr(mod, "KOAN", None)
    assert callable(koan_fn), f"{name} missing KOAN()"
    koan_fn()  # raises AssertionError on failure
