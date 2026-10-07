#!/usr/bin/env python
"""Run ``navkit sweep outages`` from a source checkout, without installing.

The implementation is :mod:`navkit.outage_sweep`. This file stays so that
``python scripts/outage_sweep.py`` keeps working.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from navkit.outage_sweep import main

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
