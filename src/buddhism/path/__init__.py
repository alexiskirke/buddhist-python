"""
buddhism.path — the Eightfold Path: a project-quality checker.

Eight static/dynamic checks against a target package, each with a
concrete technical correlate to a step on the Eightfold Path.

CLI: ``python -m buddhism.path [package]`` or ``buddhism path``.

Configuration: ``[tool.buddhism.path]`` table in ``pyproject.toml``,
with per-check thresholds and disable flags.
"""

from __future__ import annotations

from .checks import (
    CheckResult,
    PathReport,
    PathConfig,
    run_all,
)

__all__ = [
    "CheckResult",
    "PathReport",
    "PathConfig",
    "run_all",
]
