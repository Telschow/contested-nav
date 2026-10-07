#!/usr/bin/env python
"""Run ``navkit sweep seeds`` from a source checkout, without installing.

The implementation is :mod:`navkit.seed_sweep`. This file stays so that
``python scripts/seed_sweep.py`` keeps working.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from navkit.seed_sweep import main

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
