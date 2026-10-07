#!/usr/bin/env python
"""Run the reproducible benchmark from a source checkout, without installing.

The implementation is :mod:`navkit.benchmark`, and the installed equivalent is
``navkit run``. This file stays so that ``python scripts/run_benchmark.py`` keeps
working, and so the sweep scripts and tests can keep importing ``run_case``,
``MEASUREMENT`` and friends from it.

    python scripts/run_benchmark.py --out results/benchmark.json
    python scripts/run_benchmark.py --only gnss_only outage_visual
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from navkit.benchmark import MEASUREMENT, _jsonable, as_markdown_table, main, run_case

__all__ = ["MEASUREMENT", "ROOT", "_jsonable", "as_markdown_table", "main", "run_case"]

if __name__ == "__main__":
    raise SystemExit(main())
