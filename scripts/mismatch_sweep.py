#!/usr/bin/env python
"""Run ``navkit sweep mismatch`` from a source checkout, without installing.

The implementation is :mod:`navkit.mismatch_sweep`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from navkit.mismatch_sweep import main

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
