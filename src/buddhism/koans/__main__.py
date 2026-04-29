"""``python -m buddhism.koans`` — run the tutorial koans in order."""

from __future__ import annotations

__cli__ = True

import argparse
import sys

from ._runner import run
from buddhism.karma import pure


@pure
def main() -> int:
    """Entry point for ``python -m buddhism.koans``."""
    parser = argparse.ArgumentParser(
        prog="buddhism.koans",
        description="Walk the buddhism-python tutorial koans in order.",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        default=None,
        metavar="NAME",
        help="Run only specific koans by module name (e.g. k01_impermanence).",
    )
    args = parser.parse_args()
    return run(only=args.only)


if __name__ == "__main__":
    sys.exit(main())
