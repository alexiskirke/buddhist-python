"""CLI for the Eightfold Path checker.

Usage::

    python -m buddhism.path                   # examines the buddhism package itself
    python -m buddhism.path src/some_pkg/     # examines an explicit directory
    python -m buddhism.path src/some_pkg --json
"""
from __future__ import annotations

# This module is the CLI entry point; print() calls are intentional.
__cli__ = True

import argparse
import json
import pathlib
import sys
from typing import List, Optional

from .checks import PathConfig, run_all


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="buddhism.path",
        description=(
            "Examine a Python package against the Eightfold Path of "
            "engineering disciplines."
        ),
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help=(
            "Directory to examine (defaults to the buddhism package itself "
            "if a `src/buddhism/` directory exists in the current directory)."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of a human-readable report.",
    )
    args = parser.parse_args(argv)

    if args.target is None:
        candidate = pathlib.Path("src/buddhism")
        if candidate.is_dir():
            target = candidate
        else:
            target = pathlib.Path(".")
    else:
        target = pathlib.Path(args.target)

    if not target.is_dir():
        print(f"error: {target} is not a directory", file=sys.stderr)
        return 2

    report = run_all(target)

    if args.json:
        print(json.dumps(report.to_json(), indent=2))
    else:
        print(report.text_report())

    return 0 if report.passed_count == report.total_count else 1


if __name__ == "__main__":
    sys.exit(_main())
