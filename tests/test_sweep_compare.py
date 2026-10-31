"""``--compare`` of faults, mismatch and start-draw: equal output exits 0, different output exits 1 (#229)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from navkit import fault_matrix, mismatch_sweep, start_draw_study
from navkit.report.runner import Study, run_study

DATA = Path(__file__).resolve().parent.parent / "docs" / "data"
CASES = [
    (fault_matrix.STUDY, "fault_matrix.csv", "level"),
    (mismatch_sweep.STUDY, "mismatch_sweep.csv", "scale"),
    (start_draw_study.STUDY, "start_draw_study.csv", "ate_rmse_m"),
]


def _with_rows(study: Study, path: Path, nudge: str | None = None, by: float = 0.0) -> Study:
    rows = study.table.read(path)
    if nudge is not None:
        rows[0][nudge] = rows[0][nudge] + by
    return replace(study, run_args=lambda args: rows)


@pytest.mark.parametrize(("study", "name", "column"), CASES, ids=[c[1] for c in CASES])
def test_compare_exit_codes(study: Study, name: str, column: str, tmp_path: Path) -> None:
    committed = DATA / name
    argv = ["--compare", str(committed)]
    if study is start_draw_study.STUDY:
        argv += ["--csv", str(tmp_path / "x.csv")]
    assert run_study(_with_rows(study, committed), argv) == 0
    # inside 1e-6 relative: still equal
    assert run_study(_with_rows(study, committed, column, 1e-9), argv) == 0
    assert run_study(_with_rows(study, committed, column, 1.0), argv) == 1
