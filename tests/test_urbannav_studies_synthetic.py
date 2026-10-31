"""The two data-section studies (``urbannav_check``, ``urbannav_fix_errors``) end to end on the made-up sequence.

The fixture comes from ``test_urbannav_synthetic`` (S2: generated from code, no data file committed). These tests do
not skip when the real dataset is absent, so CI exercises the measuring code and the command line that the real
data would.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from navkit import urbannav_check as uc
from navkit import urbannav_fix_errors as fe
from navkit.recorded import SequenceError
from navkit.report.page import write_block
from test_urbannav_synthetic import SEQ, write_tunnel

PAGE = "x\n<!-- {name}:start -->\n<!-- {name}:end -->\ny\n"


@pytest.fixture(scope="module")
def tunnel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_tunnel(tmp_path_factory.mktemp("studies"))


@pytest.fixture(scope="module")
def check_rows(tunnel: Path) -> list[dict]:
    return uc.measure(tunnel, SEQ)


@pytest.fixture(scope="module")
def fix_rows(tunnel: Path) -> list[dict]:
    return fe.measure(tunnel, SEQ)


def test_the_check_reports_the_documented_quantities_for_the_made_up_sequence(check_rows):
    q = {r["quantity"]: r for r in check_rows}
    assert {"imu_samples", "clock_offset", "gnss_outages", "gnss_denied_epochs"} <= set(q)
    assert q["gnss_outages"]["value"] == 1
    assert all(r["sequence"] == SEQ for r in check_rows)
    assert all(r["quantity"] in uc.LABELS for r in check_rows)


def test_the_fix_errors_are_measured_against_the_reference_for_every_lag(fix_rows):
    q = {r["quantity"]: r for r in fix_rows}
    assert int(q["fix_error_fixes"]["value"]) > 0
    for lag in fe.LAGS_S:
        assert f"fix_error_pairs_lag{lag}s" in q
    assert all(r["quantity"] in fe.LABELS for r in fix_rows)


def test_the_fix_error_series_has_one_row_of_east_north_per_valid_fix(tunnel):
    t, err = fe.fix_errors(tunnel, SEQ)
    assert err.shape == (len(t), 2)
    assert (t[1:] > t[:-1]).all()


@pytest.mark.parametrize("mod, name", [(uc, "urbannav-data"), (fe, "urbannav-fix-errors")])
def test_a_csv_round_trips_and_fills_its_page_block(mod, name, check_rows, fix_rows, tmp_path):
    rows = check_rows if mod is uc else fix_rows
    csv_path, page = tmp_path / "r.csv", tmp_path / "p.md"
    mod.write_csv(csv_path, rows)
    back = mod.rows_from_csv(csv_path)
    assert [r["quantity"] for r in back] == [r["quantity"] for r in rows]
    page.write_text(PAGE.format(name=name), encoding="utf-8")
    write_block(page, name, mod.table_markdown(back))
    assert mod.table_markdown(back) in page.read_text(encoding="utf-8")


@pytest.mark.parametrize("mod, name", [(uc, "urbannav-data"), (fe, "urbannav-fix-errors")])
def test_main_measures_writes_the_csv_and_fills_the_page(mod, name, tunnel, tmp_path):
    csv_path, page = tmp_path / "r.csv", tmp_path / "p.md"
    page.write_text(PAGE.format(name=name), encoding="utf-8")
    argv = ["--root", str(tunnel), "--sequence", SEQ, "--csv", str(csv_path), "--page", str(page)]
    assert mod.main(argv) == 0
    assert csv_path.exists() and "| Sequence |" in page.read_text(encoding="utf-8")


@pytest.mark.parametrize("mod", [uc, fe])
def test_main_prints_the_table_when_given_no_output(mod, tunnel, capsys):
    assert mod.main(["--root", str(tunnel), "--sequence", SEQ]) == 0
    assert "| Sequence |" in capsys.readouterr().out


def test_fix_errors_main_needs_a_csv_to_fill_a_page(tmp_path, capsys):
    assert fe.main(["--page", str(tmp_path / "p.md")]) == 2
    assert "--page needs" in capsys.readouterr().err


def test_fix_errors_main_reports_missing_data_and_a_page_without_markers(tunnel, tmp_path):
    assert fe.main(["--root", str(tmp_path), "--sequence", SEQ]) == 1
    page = tmp_path / "p.md"
    page.write_text("no markers\n", encoding="utf-8")
    argv = ["--root", str(tunnel), "--sequence", SEQ, "--csv", str(tmp_path / "r.csv"), "--page", str(page)]
    assert fe.main(argv) == 1


def test_fix_errors_main_refuses_a_csv_with_another_header(tunnel, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b\n1,2\n", encoding="utf-8")
    assert fe.main(["--root", str(tunnel), "--sequence", SEQ, "--csv", str(bad)]) == 1
    assert bad.read_text(encoding="utf-8") == "a,b\n1,2\n"


def test_too_few_fixes_is_a_sequence_error(monkeypatch, tunnel):
    import numpy as np

    monkeypatch.setattr(fe, "fix_errors", lambda root, seq: (np.arange(3.0), np.zeros((3, 2))))
    with pytest.raises(SequenceError):
        fe.measure(tunnel, SEQ)
