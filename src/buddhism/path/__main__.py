"""``python -m buddhism.path`` entry point."""
from __future__ import annotations

import sys

from .cli import _main

if __name__ == "__main__":
    sys.exit(_main())
