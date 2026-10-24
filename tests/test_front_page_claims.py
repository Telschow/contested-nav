"""The "What the evidence shows" table on the README is tied to the committed CSVs, so the claims cannot drift.

Each row of the table makes one claim. The test reads the committed data and fails if the claim stops being true.
Row 6 and the close-out follow ADR-0036.
It reads only committed files and runs no filter. It also fails if the old B1 gate comes back as the current gate on
the first-read pages.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
README = ROOT / "README.md"
STATUS = ROOT / "docs" / "status.md"
CONSTRAINTS = ROOT / "CONSTRAINTS.md"

CLONE = "outage_visual_clone"
TABLE_TITLE = "What the evidence shows"


def _rows(name: str) -> list[dict[str, str]]:
    with (DATA / name).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _flat(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


def _evidence_table_rows() -> list[str]:
    """The data rows of the first table after the title, header and separator excluded."""
    lines = README.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if TABLE_TITLE in line)
    table: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("|"):
            table.append(line)
        elif table:
            break
    return table[2:]


def test_row_1_the_single_anchor_is_overconfident_in_both_scopes() -> None:
    rows = [r for r in _rows("ensemble_nees.csv") if r["case"] == "outage_visual"]
    assert {r["scope"] for r in rows} == {"full", "outage"}
    assert all(float(r["fraction_above"]) >= 0.99 for r in rows)


def test_row_2_the_clone_passes_the_s1_gate_on_the_development_seeds() -> None:
    rows = [r for r in _rows("candidate_gate_dev.csv") if r["subject"] == CLONE and r["scenario"] == "S1"]
    assert rows
    assert {r["seeds"] for r in rows} == {"25-49"}
    assert all(r["passed"] == "true" for r in rows)
    assert all(r["scenario_passed"] == "true" for r in rows)


def test_row_3_the_measured_front_end_clone_failed_the_held_out_gate_on_the_lower_bound() -> None:
    rows = _rows("b1_gate_heldout.csv")
    lower = [r for r in rows if r["condition"] == "nees_lower"]
    assert lower
    assert all(r["passed"] == "false" for r in lower)
    ledger = [r for r in _rows("heldout_ledger.csv") if r["block"] == "1"]
    assert len(ledger) == 1
    assert ledger[0]["outcome"].startswith("failed")


def test_row_4_the_clone_fails_the_s2_gate_on_the_development_seeds() -> None:
    rows = [r for r in _rows("candidate_gate_dev.csv") if r["subject"] == CLONE and r["scenario"] == "S2"]
    assert rows
    assert all(r["scenario_passed"] == "false" for r in rows)
    assert any(r["passed"] == "false" for r in rows)


def test_row_5_no_adaptive_scale_point_qualifies() -> None:
    rows = _rows("adaptive_scale_tuning.csv")
    assert rows
    assert all(r["qualifies"] == "false" for r in rows)
    assert all(r["chosen"] == "false" for r in rows)


def test_the_old_gate_is_not_stated_as_current_on_the_front_pages() -> None:
    for path in (README, STATUS):
        assert "mean NEES below 10" not in _flat(path), path.name


def test_row_6_the_gauss_markov_model_failed_on_development_seeds_and_is_not_robust_to_the_correlation_time() -> None:
    tuning = _rows("gm_tuning.csv")
    assert tuning
    assert all(r["qualifies"] == "false" for r in tuning)
    assert all(r["chosen"] == "false" for r in tuning)
    robustness = [r for r in _rows("gm_tuning_robustness.csv") if r["condition"] == "lower"]
    holds = {float(r["corr_time_s"]): r["holds"] == "true" for r in robustness}
    assert set(holds) == {0.0, 0.25, 0.5, 1.0, 2.0}
    assert not any(holds[t] for t in (0.0, 0.25, 0.5))  # conservative when the correlation time is short
    assert all(holds[t] for t in (1.0, 2.0))  # the NEES conditions hold only near the time it was built for


def test_row_6_the_usefulness_conditions_are_not_met_even_with_a_near_exact_model() -> None:
    rows = [r for r in _rows("gm_s2_usefulness.csv") if r["subject"].startswith("Gauss-Markov")]
    assert {r["subject"] for r in rows} == {
        "Gauss-Markov model, tau 2 s, rho 0.9",
        "Gauss-Markov model, tau 2 s, rho 0.99",
    }
    for subject in {r["subject"] for r in rows}:
        mine = {r["condition"]: r["holds"] == "true" for r in rows if r["subject"] == subject}
        assert all(mine[c] for c in ("upper", "lower", "coverage"))
        assert not all(mine[c] for c in ("better", "median_ratio", "worst_ratio"))


def test_the_readme_table_has_six_data_rows() -> None:
    rows = _evidence_table_rows()
    assert len(rows) == 6
    assert all(row.count("|") == 4 for row in rows)
    assert "Gauss-Markov" in rows[-1]


def test_the_close_out_is_recorded_and_the_pages_point_at_it() -> None:
    adr = ROOT / "docs" / "adr" / "0036-b1-is-closed-as-characterised-not-solved.md"
    text = adr.read_text(encoding="utf-8")
    assert "B1 is closed as characterised, not solved." in text
    for path in (README, STATUS, CONSTRAINTS):
        assert "ADR-0036" in path.read_text(encoding="utf-8"), path.name
    assert "work stopped" in _flat(CONSTRAINTS)


def test_the_b1_status_block_markers_are_still_in_constraints() -> None:
    text = CONSTRAINTS.read_text(encoding="utf-8")
    assert text.count("<!-- b1-heldout-status:start -->") == 1
    assert text.count("<!-- b1-heldout-status:end -->") == 1
