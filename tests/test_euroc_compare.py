"""The EuRoC comparison, run on synthetic sequences written in the EuRoC layout.

The fixtures carry real sequence names so that discovery and grouping are exercised, but they are
synthetic. Nothing here says anything about the filter on real data; it checks the bookkeeping:
which runs are made, how a lost run is counted, and what the output files contain.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from navkit import euroc_compare as ec
from navkit import euroc_eval as ee

MH, V1 = "MH_01_easy", "V1_01_easy"
ARGS = ["--starts", "5", "--outage", "10", "--seeds", "1"]


@pytest.fixture(scope="module")
def root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("compare")
    ee.write_fixture(path, MH, seed=1)
    ee.write_fixture(path, V1, seed=2)
    manifest = {"sequences": {MH: {"files": [{"path": f"{MH}/mav0/imu0/data.csv", "sha256": "ab" * 32, "bytes": 1}]}}}
    (path / "MANIFEST.json").write_text(json.dumps(manifest))
    return path


@pytest.fixture(scope="module")
def table(root: Path):
    return ec.compare(root, [MH, V1], ("default", "preset"), (5.0,), 10.0, 1, 0.2)


def test_discovery_finds_only_known_sequences_with_both_files(tmp_path):
    ee.write_fixture(tmp_path, MH)
    ee.write_fixture(tmp_path, "NOT_A_SEQUENCE")
    ee.write_fixture(tmp_path, V1)
    (tmp_path / V1 / ee.TRUTH_CSV).unlink()
    assert ec.fetched_sequences(tmp_path) == [MH]


def test_every_start_seed_and_config_runs_once(table):
    rows, skipped = table
    assert len(rows) == 2 * 1 * 1 * 2  # sequences x starts x seeds x configs
    assert skipped == {}
    assert {(r.sequence, r.config) for r in rows} == {(s, c) for s in (MH, V1) for c in ("default", "preset")}


def test_groups_come_from_the_sequence_name():
    assert ec.group_of("MH_03_medium") == "Machine Hall"
    assert ec.group_of("V2_01_easy") == "Vicon room"
    assert ec.group_of("anything") == "other"


def test_starts_that_do_not_fit_are_dropped():
    assert ec.fitting_starts(100.0, (15.0, 35.0, 60.0, 90.0), 20.0) == [15.0, 35.0, 60.0]
    assert ec.fitting_starts(30.0, (15.0,), 20.0) == []


def test_a_sequence_with_no_fitting_start_is_skipped_and_named(root, tmp_path):
    ee.write_fixture(tmp_path, MH)
    ee.write_fixture(tmp_path, "MH_02_easy", duration_s=12.0)
    rows, skipped = ec.compare(tmp_path, [MH, "MH_02_easy"], ("default",), (5.0,), 10.0, 1, 0.2)
    assert {r.sequence for r in rows} == {MH}
    assert list(skipped) == ["MH_02_easy"] and "no outage start fits" in skipped["MH_02_easy"]
    with pytest.raises(ec.CompareError, match="nothing ran"):
        ec.compare(root, [MH], ("default",), (500.0,), 10.0, 1, 0.2)


def test_lost_follows_the_rejected_fraction_and_the_threshold(root):
    seq = ee.load_sequence(root, MH)
    row = ec.run_one(seq, "default", 5.0, 10.0, 0, 0.2)
    assert row.lost == (row.rejected_fraction > 0.2)
    assert 0.0 <= row.rejected_fraction <= 1.0
    never = ec.run_one(seq, "default", 5.0, 10.0, 0, 0.999999)
    assert never.lost is False
    always = ec.run_one(seq, "default", 5.0, 10.0, 0, 0.0)
    assert always.lost == (always.gnss_rejected > 0)


def test_a_wrong_gravity_filter_is_counted_as_lost(root, monkeypatch):
    """The sign convention that fails on a physical IMU must show up as lost runs, not as a good score."""
    from navkit.types import GRAVITY

    monkeypatch.setattr(ee, "GRAVITY_Z_UP", GRAVITY)
    row = ec.run_one(ee.load_sequence(root, MH), "default", 5.0, 10.0, 0, 0.2)
    assert row.lost is True


def test_runs_are_reproducible(root):
    seq = ee.load_sequence(root, MH)
    a = ec.run_one(seq, "preset", 5.0, 10.0, 0, 0.2).as_dict()
    assert ec.run_one(seq, "preset", 5.0, 10.0, 0, 0.2).as_dict() == a
    assert ec.run_one(seq, "preset", 5.0, 10.0, 1, 0.2).as_dict() != a


def test_the_breakdown_has_all_groups_and_sequences_for_each_config(table):
    rows, _ = table
    scopes = {(b["scope"], b["config"]) for b in ec.breakdown(rows)}
    for config in ("default", "preset"):
        assert {("all", config), ("Machine Hall", config), ("Vicon room", config), (MH, config), (V1, config)} <= scopes
    total = next(b for b in ec.breakdown(rows) if (b["scope"], b["config"]) == ("all", "default"))
    assert total["runs"] == 2.0
    assert 0.0 <= total["lost"] <= total["runs"]


def test_markdown_comes_from_the_rows_and_names_the_measure(table):
    rows, _ = table
    text = ec.as_markdown(rows, 0.2)
    assert "more than 20% of GNSS fixes rejected" in text
    assert text.count("\n| ") == 1 + len(ec.breakdown(rows))  # header row plus one row per scope and config
    assert "| all | default | 2 |" in text


def test_the_record_carries_the_caveats_the_class_and_the_input_hashes(table, root):
    rows, skipped = table
    record = ec.build_record(rows, skipped, root, {"seeds": 1}, 0.2)
    assert record["data_class"] == ee.DATA_CLASS
    assert any("simulated" in c for c in record["caveats"])
    assert record["inputs"]["sha256"][MH][f"{MH}/mav0/imu0/data.csv"] == "ab" * 32
    assert record["inputs"]["sha256"][V1] == {}
    assert record["configs"]["preset"]["noise_scale"] == 3.0
    assert len(record["runs"]) == len(rows)
    json.dumps(record)


def test_provenance_survives_a_broken_manifest(tmp_path):
    (tmp_path / "MANIFEST.json").write_text("{not json")
    assert ec.provenance(tmp_path, [MH])["sha256"] == {MH: {}}


def test_cli_writes_csv_json_and_a_table(root, tmp_path, capsys):
    out_csv, out_json = tmp_path / "r.csv", tmp_path / "r.json"
    code = ec.main(["--root", str(root), *ARGS, "--csv", str(out_csv), "--json", str(out_json), "--markdown"])
    assert code == 0
    with out_csv.open() as fh:
        reader = csv.DictReader(fh)
        assert tuple(reader.fieldnames or ()) == ec.CSV_COLUMNS
        rows = list(reader)
    assert len(rows) == 4 and {r["config"] for r in rows} == {"default", "preset"}
    assert json.loads(out_json.read_text())["options"]["sequences"] == [MH, V1]
    assert capsys.readouterr().out.startswith("Lost = more than")


def test_cli_with_nothing_fetched_says_how_to_fetch(tmp_path, capsys):
    assert ec.main(["--root", str(tmp_path)]) == 1
    assert "navkit euroc fetch" in capsys.readouterr().err


def test_cli_rejects_an_unknown_config_and_bad_numbers(root, capsys):
    assert ec.main(["--root", str(root), "--configs", "nope", *ARGS]) == 1
    assert "unknown configuration" in capsys.readouterr().err
    assert ec.main(["--root", str(root), "--seeds", "0", *ARGS[:4]]) == 1
    with pytest.raises(SystemExit):
        ec.main(["--root", str(root), "--starts", "x"])


def test_the_command_is_routed_from_navkit_euroc(root, capsys):
    assert ee.main(["compare", "--root", str(root), "-s", MH, *ARGS, "--configs", "default"]) == 0
    assert "| all | default | 1 |" in capsys.readouterr().out
    assert ee.main(["--help"]) == 0
    assert "compare" in capsys.readouterr().err


# ------------------------------------------------------------- page and saved CSV


def test_the_csv_round_trips_through_rows_from_csv(root, tmp_path, table):
    out = tmp_path / "r.csv"
    assert ec.main(["--root", str(root), *ARGS, "--csv", str(out)]) == 0
    back = ec.rows_from_csv(out)
    direct, _ = table
    assert [r.as_dict() for r in back] == [r.as_dict() for r in direct]
    assert ec.as_markdown(back, 0.2) == ec.as_markdown(direct, 0.2)


def test_from_csv_rebuilds_the_page_without_running_anything(root, tmp_path, capsys):
    out, page = tmp_path / "r.csv", tmp_path / "page.md"
    page.write_text("before\n<!-- euroc:start -->\nold\n<!-- euroc:end -->\nafter\n")
    assert ec.main(["--root", str(root), *ARGS, "--csv", str(out)]) == 0
    assert ec.main(["--from-csv", str(out), "--page", str(page)]) == 0
    text = page.read_text()
    assert text.startswith("before\n<!-- euroc:start -->") and text.endswith("<!-- euroc:end -->\nafter\n")
    assert "old" not in text and "| all | default | 2 |" in text
    assert ec.main(["--from-csv", str(out), "--json", str(tmp_path / "x.json")]) == 1


def test_a_page_without_the_markers_is_refused(tmp_path):
    page = tmp_path / "p.md"
    page.write_text("no markers here")
    with pytest.raises(ec.CompareError, match="euroc:start"):
        ec.write_page(page, "x")
    page.write_text("<!-- euroc:end -->\n<!-- euroc:start -->")
    with pytest.raises(ec.CompareError):
        ec.write_page(page, "x")


def test_the_failing_runs_list_names_each_lost_run_or_says_there_are_none(table):
    rows, _ = table
    assert ec.failing_runs_markdown(rows) == "No run was lost with `preset`."
    forced = [ec.Row(**{**r.__dict__, "lost": True, "rejected_fraction": 0.5}) for r in rows if r.config == "preset"]
    text = ec.failing_runs_markdown(forced)
    assert text.startswith("Runs still lost with `preset`:") and "| 50% |" in text


def test_first_seed_shifts_the_seeds_that_run(root):
    rows, _ = ec.compare(root, [MH], ("default",), (5.0,), 10.0, 2, 0.2, first_seed=3)
    assert sorted(r.seed for r in rows) == [3, 4]
    base, _ = ec.compare(root, [MH], ("default",), (5.0,), 10.0, 1, 0.2)
    assert rows[0].as_dict() != base[0].as_dict()


def test_the_validation_block_has_one_line_per_outage_length_and_config(table):
    rows, _ = table
    longer = [ec.Row(**{**r.__dict__, "outage_s": 30.0}) for r in rows]
    text = ec.validation_block(rows + longer, 0.2)
    assert text.count("\n| 10 | ") == 2 and text.count("\n| 30 | ") == 2
    assert "| 10 | default | 2 |" in text and "| 30 | preset | 2 |" in text


def test_the_page_block_names_for_each_config_the_runs_it_lost(table):
    rows, _ = table
    forced = [
        ec.Row(**{**r.__dict__, "lost": True, "rejected_fraction": 0.4}) if r.config == "preset" else r for r in rows
    ]
    text = ec.page_block(forced, 0.2)
    assert "Runs still lost with `preset`:" in text and "with `default`" not in text


def test_the_block_option_fills_the_named_block_only(root, tmp_path):
    out, page = tmp_path / "r.csv", tmp_path / "p.md"
    page.write_text(
        "<!-- euroc:start -->\nA\n<!-- euroc:end -->\n"
        "<!-- euroc-validation:start -->\nB\n<!-- euroc-validation:end -->\n"
    )
    assert ec.main(["--root", str(root), *ARGS, "--csv", str(out)]) == 0
    assert ec.main(["--from-csv", str(out), "--page", str(page), "--block", "euroc-validation"]) == 0
    text = page.read_text()
    assert "\nA\n" in text and "\nB\n" not in text and "| Outage s | Config |" in text
    assert ec.main(["--from-csv", str(out), "--page", str(page)]) == 0
    assert "\nA\n" not in page.read_text()


def test_the_walk_config_is_the_adis16448_walk_preset():
    assert ec.CONFIGS["walk10"]["preset"] == "adis16448-walk"
    assert ec.CONFIGS["walk10"]["bias_walk_scale"] == 10.0 and ec.CONFIGS["walk10"]["noise_scale"] == 1.0
