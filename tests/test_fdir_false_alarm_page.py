"""The false-alarm and sensitivity blocks of ``docs/faults.md`` are the committed CSVs, and the sentences follow.

This reads only the two CSVs, the fault matrix CSV and the page, so it runs in a documentation-only pull request. The
producer is tested in ``test_fdir_false_alarm.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from navkit import fault_matrix
from navkit import fdir_false_alarm as fa
from navkit.benchmark import default_config_path
from navkit.eval.calibration import wilson_interval
from navkit.fdir.config import FdirConfig
from navkit.report.page import splice_block

pytestmark = pytest.mark.docs_only

ROOT = Path(__file__).resolve().parent.parent
RATE_CSV = ROOT / "docs" / "data" / "fdir_false_alarm.csv"
SENS_CSV = ROOT / "docs" / "data" / "fdir_sensitivity.csv"
MATRIX_CSV = ROOT / "docs" / "data" / "fault_matrix.csv"
PAGE = ROOT / "docs" / "faults.md"
HEADING = "## FDIR false alarms and constant sensitivity"

#: Words that would turn a measurement into a verdict. The section reports numbers and where they fall.
VERDICT_WORDS = ("calibrated", "miscalibrated", "well-tuned", "overly sensitive", "acceptable")


@pytest.fixture(scope="module")
def rate_rows() -> list[dict]:
    return fa.parse_rate_csv(RATE_CSV.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sens_rows() -> list[dict]:
    return fa.parse_sensitivity_csv(SENS_CSV.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def section() -> str:
    text = PAGE.read_text(encoding="utf-8")
    assert HEADING in text
    return text[text.index(HEADING) :]


def _words(text: str) -> str:
    return " ".join(text.split())


# --- the page is the CSV ----------------------------------------------------------------------


def test_the_false_alarm_block_is_the_committed_csv(rate_rows):
    page = PAGE.read_text(encoding="utf-8")
    assert page == splice_block(page, "fdir-false-alarm", fa.rate_tables(rate_rows))


def test_the_sensitivity_block_is_the_committed_csv(sens_rows):
    page = PAGE.read_text(encoding="utf-8")
    assert page == splice_block(page, "fdir-sensitivity", fa.sensitivity_tables(sens_rows))


def test_the_csv_files_are_written_by_the_writers_byte_for_byte(rate_rows, sens_rows):
    assert RATE_CSV.read_text(encoding="utf-8") == fa.rate_csv_text(rate_rows)
    assert SENS_CSV.read_text(encoding="utf-8") == fa.sensitivity_csv_text(sens_rows)


def test_the_headers_are_the_documented_columns():
    assert RATE_CSV.read_text(encoding="utf-8").splitlines()[0] == ",".join(fa.RATE_FIELDS)
    assert SENS_CSV.read_text(encoding="utf-8").splitlines()[0] == ",".join(fa.SENSITIVITY_FIELDS)


def test_the_section_documents_both_commands(section):
    assert "navkit sweep fdir rate --csv docs/data/fdir_false_alarm.csv --page docs/faults.md" in section
    assert "navkit sweep fdir sensitivity --csv docs/data/fdir_sensitivity.csv --page docs/faults.md" in section


# --- part A: the rows are what they say -------------------------------------------------------


def test_the_runs_are_seeds_0_to_24_and_never_a_reserved_seed(rate_rows):
    for case, scope in {(r["case"], r["scope"]) for r in rate_rows}:
        seeds = [r["seed"] for r in rate_rows if r["case"] == case and r["scope"] == scope and r["seed"] != "all"]
        assert seeds == list(range(25)), (case, scope)
    assert all(r["seed"] == "all" or r["seed"] < fa.RESERVED_SEED_START for r in rate_rows)
    assert _words(fa.rate_setup(rate_rows)[0]).startswith("Seeds 0 to 24 (25 runs per case).")


def test_the_cases_and_scopes_are_the_stated_ones(rate_rows):
    assert {(r["case"], r["scope"]) for r in rate_rows} == {
        ("gnss_only", "all"),
        ("outage_control", "counted"),
        ("outage_control", "settling"),
    }


def test_each_pooled_row_is_rebuilt_from_its_per_seed_rows(rate_rows):
    for pooled in (r for r in rate_rows if r["seed"] == "all"):
        runs = [
            r for r in rate_rows if r["case"] == pooled["case"] and r["scope"] == pooled["scope"] and r["seed"] != "all"
        ]
        want = fa.pooled_row(pooled["case"], pooled["scope"], runs, fa.gate_threshold())
        for key in fa.RATE_FIELDS:
            if isinstance(want[key], str):  # case, scope and seed are labels, and pytest 9.2 rejects approx on a str
                assert pooled[key] == want[key], (pooled["case"], key)
            else:
                assert pooled[key] == pytest.approx(want[key], rel=1e-9, abs=1e-12), (pooled["case"], key)


def test_the_stated_alpha_and_threshold_are_the_configs(rate_rows):
    for r in rate_rows:
        if r["seed"] == "all":
            assert r["alpha"] == pytest.approx(FdirConfig().alpha)
            assert r["threshold"] == fa.gate_threshold()


def test_the_raw_interval_is_the_wilson_interval_of_the_raw_count(rate_rows):
    for r in rate_rows:
        if r["seed"] == "all":
            assert (r["wilson_lo"], r["wilson_hi"]) == pytest.approx(wilson_interval(r["rejections"], r["updates"]))
            assert (r["eff_wilson_lo"], r["eff_wilson_hi"]) == pytest.approx(
                wilson_interval(r["eff_rejections"], r["ess"])
            )
            assert r["ess"] <= r["updates"] + 1e-9


def test_the_settling_row_holds_the_fixes_of_the_first_stated_seconds_after_the_return(rate_rows):
    doc = yaml.safe_load(default_config_path().read_text(encoding="utf-8"))
    rate_hz = float(doc["cases"]["outage_control"]["scenario"]["gnss"]["rate_hz"])
    windows = fa.outage_windows(doc["cases"]["outage_control"])
    ((start, end),) = windows
    counted = next(r for r in rate_rows if r["scope"] == "counted" and r["seed"] == 0)
    settling = next(r for r in rate_rows if r["scope"] == "settling" and r["seed"] == 0)
    gnss = next(r for r in rate_rows if r["case"] == "gnss_only" and r["seed"] == 0)
    assert settling["updates"] == round(fa.SETTLE_S * rate_hz)
    # The outage removes its fixes, so the two scopes together are what is left of the run's fixes.
    assert counted["updates"] + settling["updates"] == gnss["updates"] - round((end - start) * rate_hz)


# --- part A: the sentences follow from the numbers --------------------------------------------


def test_each_sentence_says_inside_or_outside_as_the_numbers_do(rate_rows, section):
    bullets = [line for line in section.splitlines() if line.startswith("- **")]
    pooled = [r for r in rate_rows if r["seed"] == "all"]
    assert len(bullets) == len(pooled)
    for row, bullet in zip(pooled, bullets, strict=True):
        text = _words(bullet)
        assert text.startswith(f"- **{row['case']}, ")
        for name, x, lo_key, hi_key in (
            ("alpha raw", row["alpha"], "wilson_lo", "wilson_hi"),
            ("alpha eff", row["alpha"], "eff_wilson_lo", "eff_wilson_hi"),
            ("pred raw", row["predicted_rate"], "wilson_lo", "wilson_hi"),
            ("pred eff", row["predicted_rate"], "eff_wilson_lo", "eff_wilson_hi"),
        ):
            want = "inside" if row[lo_key] <= x <= row[hi_key] else "outside"
            pattern = {
                "alpha raw": r"which is (inside|outside) the raw-count interval",
                "alpha eff": r"and (inside|outside) the effective-count interval \[[^\]]*\]\. The mean NIS",
                "pred raw": r"The predicted rate is (inside|outside) the raw-count interval",
                "pred eff": r"and (inside|outside) the effective-count interval, and it is",
            }[name]
            found = re.search(pattern, text)
            assert found and found.group(1) == want, (row["case"], row["scope"], name)
        closer = abs(row["predicted_rate"] - row["rate"]) < abs(row["alpha"] - row["rate"])
        ending = "the observed rate than \N{GREEK SMALL LETTER ALPHA} is."
        assert f"and it is {'closer to' if closer else 'farther from'} {ending}" in text


def test_the_predicted_rate_is_the_tail_at_threshold_over_c(rate_rows):
    for r in rate_rows:
        if r["seed"] == "all":
            assert r["c"] == pytest.approx(r["mean_nis"] / 3.0)
            assert r["predicted_rate"] == pytest.approx(fa.predicted_rate(r["c"], r["threshold"], 3))


def test_the_page_states_the_autocorrelation_caveat_and_the_effective_count_limit(section):
    text = _words(section)
    for phrase in (
        "Successive updates in one run are not independent",
        "the raw Wilson interval, which treats them as independent, is too narrow",
        "the sum over runs of the effective sample size of the rejection indicator",
        "A run with a lone rejection gets a value equal to its length",
        "equality there does not show that the updates are independent",
        "It enters neither interval.",
        "carries its own sampling error",
        "The settling period was chosen before the first run and has not been varied.",
        "rejecting the first fixes after an outage is the gate doing its job",
    ):
        assert phrase in text, phrase


def test_the_section_has_no_verdict_words(section):
    low = section.lower()
    for word in VERDICT_WORDS:
        assert word not in low, word


def test_point_1_of_the_matrix_stays(section):
    text = _words(PAGE.read_text(encoding="utf-8"))
    assert "1. **False alarms are zero on two controls and not on the third" in text


# --- part B -----------------------------------------------------------------------------------


def test_the_sensitivity_grid_is_every_matrix_cell_at_seven_settings(sens_rows):
    cells = {(r["fault"], r["base"], r["level"]) for r in sens_rows}
    expected = {("control", b, 0.0) for b in fault_matrix.BASES}
    expected |= {(f.id, f.base, lv) for f in fault_matrix.FAULTS for lv in f.levels}
    assert cells == expected
    settings = {(r["constant"], r["setting"]) for r in sens_rows}
    assert settings == {("default", "default")} | {(c, s) for c in fa.CONSTANTS for s in ("half", "double")}
    assert len(sens_rows) == len(cells) * len(settings)
    assert {r["n_seeds"] for r in sens_rows} == {5}
    for r in sens_rows:
        assert 0 <= r["declared_n"] <= r["n_seeds"] and 0 <= r["detected_n"] <= r["n_seeds"]


def test_the_half_and_double_values_are_the_live_defaults_scaled(sens_rows):
    """Fails if a default moves, which is also the guard that this change moved none."""
    cfg = FdirConfig()
    for r in sens_rows:
        if r["constant"] == "default":
            assert r["value"] is None
        else:
            factor = 0.5 if r["setting"] == "half" else 2.0
            assert r["value"] == fa.scaled_value(getattr(cfg, r["constant"]), factor)


def test_the_counts_at_the_defaults_are_the_fault_matrix_counts(sens_rows):
    matrix = fault_matrix.read_csv(MATRIX_CSV)
    want = {(m["fault"], m["base"], m["level"]): (m["detected_n"], m["declared_n"]) for m in matrix}
    got = {
        (r["fault"], r["base"], r["level"]): (r["detected_n"], r["declared_n"])
        for r in sens_rows
        if r["constant"] == "default"
    }
    assert got == want


def test_a_declared_fault_was_detected(sens_rows):
    # Declaring a channel needs rejections, so declared_n cannot exceed detected_n.
    for r in sens_rows:
        assert r["declared_n"] <= r["detected_n"], r


def test_the_false_alarm_table_row_counts_are_the_control_rows(sens_rows, section):
    text = _words(section)
    for r in sens_rows:
        if r["fault"] == "control" and r["setting"] == "default":
            assert f"{r['base']} control declared" in text
    seeds = sens_rows[0]["n_seeds"]
    assert f"seeds in which the no-fault control declared a channel faulty, out of {seeds}" in text


def test_the_changed_cells_named_on_the_page_are_the_ones_that_differ_in_the_csv(sens_rows, section):
    text = _words(section)
    by_key = {(r["constant"], r["setting"], r["fault"], r["base"], r["level"]): r for r in sens_rows}
    changed = 0
    for r in sens_rows:
        if r["constant"] == "default":
            continue
        ref = by_key[("default", "default", r["fault"], r["base"], r["level"])]
        moved = (r["detected_n"], r["declared_n"]) != (ref["detected_n"], ref["declared_n"])
        said = f"detected {ref['detected_n']} to {r['detected_n']}, declared {ref['declared_n']} to {r['declared_n']}"
        if moved:
            changed += 1
            assert said in text, (r["constant"], r["setting"], r["fault"], r["level"])
    lines = [ln for ln in section.splitlines() if " cell(s) differ from the defaults" in ln]
    counts = [re.search(r": (\d+) cell", ln) for ln in lines]
    assert all(counts)
    assert sum(int(m.group(1)) for m in counts if m) == changed
    quiet = [ln for ln in section.splitlines() if "no cell differs from the defaults" in ln]
    assert len(lines) + len(quiet) == len(fa.CONSTANTS) * 2


def test_the_control_sentences_follow_the_control_rows(sens_rows, section):
    text = _words(section)
    for base in fault_matrix.BASES:
        counts = {r["declared_n"] for r in sens_rows if r["fault"] == "control" and r["base"] == base}
        if len(counts) == 1:
            (only,) = counts
            assert f"The `{base}` control declared a channel faulty in {only} of 5 seeds at every setting." in text
        else:
            assert f"The `{base}` control declared a channel faulty in between" in text


def test_the_page_states_what_is_changed_and_what_is_not_shown(section):
    text = _words(section)
    for phrase in (
        "no `FdirConfig` default changes here",
        "An integer is rounded half up.",
        "One constant at a time says nothing about two moved together.",
        "so it would not show a change in error or coverage that leaves every count as it was.",
        "Nothing here ranks the settings or says which one to use.",
    ):
        assert phrase in text, phrase
