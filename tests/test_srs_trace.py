"""``scripts/check_srs_trace.py`` fails on every kind of broken link, and the real matrix passes."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_srs_trace.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_srs_trace", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_srs_trace"] = module
    spec.loader.exec_module(module)
    return module


srs = _load()

SRS = """\
| OUN | Supporting requirements | Met | Not met | Not verified / contradicted |
|---|---|---:|---:|---:|
| OUN-01 | TR-01…TR-02 (support); **TR-03** | 2 | 0 | 1 (TR-03) |

| ID | Parameter | Verdict |
|---|---|---|
| TR-01 | a | MET |
| TR-02 | b | MET (at budget) |
| TR-03 | c | **NOT VERIFIED** |

| ID | Criterion |
|---|---|
| AC-01 | thing |

| AC | Measured | Verdict |
|---|---|---|
| AC-01 | 1 | **PASS at the tested offsets** |
"""


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "def test_top():\n    pass\n\n\nclass TestK:\n    def test_method(self):\n        pass\n"
    )
    (tmp_path / "cfg.yaml").write_text("a:\n  b: 0.5\n  flag: true\n")
    (tmp_path / "real.txt").write_text("x")
    return tmp_path


def _row(rid: str, tests: str = "", config: str = "", gap: str = "") -> dict[str, str]:
    return {"id": rid, "tests": tests, "config": config, "gap": gap}


OK = [
    _row("TR-01", tests="tests/test_x.py::test_top"),
    _row("TR-02", config="yaml:cfg.yaml:a.b=0.5"),
    _row("TR-03", gap="no hardware"),
    _row("AC-01", tests="tests/test_x.py::TestK::test_method"),
]


# --- parsing -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("MET", "MET"),
        ("**MET (at budget)**", "MET"),
        ("**NOT MET**", "NOT MET"),
        ("**NOT VERIFIED**", "NOT VERIFIED"),
        ("**CONTRADICTED** as worded", "CONTRADICTED"),
        ("**PASS at the tested offsets**", "PASS"),
        ("**PASS**, but see note", "PASS"),
        ("FAIL", "FAIL"),
        ("see below", None),
        ("METHOD", None),
    ],
)
def test_the_verdict_is_the_legend_word_the_cell_starts_with(cell: str, expected: str | None) -> None:
    assert srs.verdict_of(cell) == expected


def test_a_range_expands_and_a_list_is_kept() -> None:
    assert srs.expand("TR-20…TR-22, TR-28; **TR-30**") == ["TR-20", "TR-21", "TR-22", "TR-28", "TR-30"]


def test_the_ac_verdict_comes_from_the_row_that_has_one() -> None:
    verdicts, ids = srs.parse_srs(SRS)
    assert verdicts["AC-01"] == "PASS" and verdicts["TR-03"] == "NOT VERIFIED"
    assert ids == {"TR-01", "TR-02", "TR-03", "AC-01"}


# --- the checks ----------------------------------------------------------------------------


def test_a_complete_matrix_passes(tmp_path: Path) -> None:
    assert srs.check(SRS, OK, _repo(tmp_path)) == []


def test_a_requirement_with_no_row_and_a_row_with_no_requirement_both_fail(tmp_path: Path) -> None:
    rows = [r for r in OK if r["id"] != "TR-02"] + [_row("TR-99", gap="x")]
    problems = srs.check(SRS, rows, _repo(tmp_path))
    assert any("TR-02" in p and "no row" in p for p in problems)
    assert any("TR-99" in p and "not in the document" in p for p in problems)


def test_a_duplicate_row_fails(tmp_path: Path) -> None:
    problems = srs.check(SRS, [*OK, _row("TR-01", gap="again")], _repo(tmp_path))
    assert any("TR-01" in p and "more than one" in p for p in problems)


def test_silence_fails(tmp_path: Path) -> None:
    rows = [_row("TR-03") if r["id"] == "TR-03" else r for r in OK]
    assert any("TR-03" in p and "no test" in p for p in srs.check(SRS, rows, _repo(tmp_path)))


def test_a_met_verdict_cannot_rest_on_a_gap_alone(tmp_path: Path) -> None:
    rows = [_row("TR-01", gap="trust me") if r["id"] == "TR-01" else r for r in OK]
    assert any("TR-01" in p and "gap alone" in p for p in srs.check(SRS, rows, _repo(tmp_path)))


def test_a_not_verified_verdict_may_rest_on_a_gap(tmp_path: Path) -> None:
    assert not [p for p in srs.check(SRS, OK, _repo(tmp_path)) if "TR-03" in p]


def test_an_unknown_verdict_fails(tmp_path: Path) -> None:
    text = SRS.replace("| TR-02 | b | MET (at budget) |", "| TR-02 | b | probably fine |")
    assert any("TR-02" in p and "verdict" in p for p in srs.check(text, OK, _repo(tmp_path)))


def test_non_consecutive_requirement_ids_fail(tmp_path: Path) -> None:
    text = SRS.replace("| TR-03 | c |", "| TR-05 | c |").replace("TR-01…TR-02 (support); **TR-03**", "TR-01…TR-02")
    rows = [_row("TR-05", gap="x") if r["id"] == "TR-03" else r for r in OK]
    assert any("consecutive" in p for p in srs.check(text, rows, _repo(tmp_path)))


@pytest.mark.parametrize(
    ("ref", "fragment"),
    [
        ("tests/test_x.py::test_missing", "no top-level function"),
        ("tests/test_gone.py::test_top", "does not exist"),
        ("tests/test_x.py::TestK::test_missing", "no method"),
        ("tests/test_x.py::TestNope::test_method", "no class"),
        ("tests/test_x.py", "expected path::name"),
    ],
)
def test_a_test_reference_that_does_not_resolve_fails(tmp_path: Path, ref: str, fragment: str) -> None:
    rows = [_row("TR-01", tests=ref) if r["id"] == "TR-01" else r for r in OK]
    assert any("TR-01" in p and fragment in p for p in srs.check(SRS, rows, _repo(tmp_path)))


@pytest.mark.parametrize(
    ("expr", "fragment"),
    [
        ("yaml:cfg.yaml:a.b=0.6", "the repository has 0.5"),
        ("yaml:cfg.yaml:a.missing=1", "KeyError"),
        ("yaml:cfg.yaml:a.flag=1", "the repository has True"),
        ("py:json:nothing=1", "AttributeError"),
        ("py:no_such_module_xyz:x=1", "ModuleNotFoundError"),
        ("fn:json:dumps.indent=3", "the repository has None"),
        ("file:missing.txt", "no such file"),
        ("weird:x=1", "unknown kind"),
        ("yaml:cfg.yaml:a.b=not_a_literal", "not a literal"),
        ("yaml:cfg.yaml:a.b", "expected kind"),
    ],
)
def test_a_config_check_that_does_not_hold_fails(tmp_path: Path, expr: str, fragment: str) -> None:
    rows = [_row("TR-02", config=expr) if r["id"] == "TR-02" else r for r in OK]
    assert any("TR-02" in p and fragment in p for p in srs.check(SRS, rows, _repo(tmp_path)))


def test_config_checks_that_hold_pass(tmp_path: Path) -> None:
    config = "yaml:cfg.yaml:a.flag=True;file:real.txt;fn:json:dumps.skipkeys=False;py:math:pi=3.141592653589793"
    rows = [_row("TR-02", config=config) if r["id"] == "TR-02" else r for r in OK]
    assert srs.check(SRS, rows, _repo(tmp_path)) == []


# --- the roll-up ---------------------------------------------------------------------------


def test_a_roll_up_that_disagrees_with_the_verdicts_fails(tmp_path: Path) -> None:
    text = SRS.replace("| 2 | 0 | 1 (TR-03) |", "| 3 | 0 | 0 (TR-03) |")
    problems = srs.check(text, OK, _repo(tmp_path))
    assert any("OUN-01" in p and "3/0/0" in p and "2/0/1" in p for p in problems)


def test_a_roll_up_that_names_a_missing_requirement_fails(tmp_path: Path) -> None:
    text = SRS.replace("TR-01…TR-02 (support)", "TR-01…TR-07 (support)")
    assert any("TR-07" in p for p in srs.check(text, OK, _repo(tmp_path)))


# --- the real matrix -----------------------------------------------------------------------


def _real() -> tuple[str, list[dict[str, str]]]:
    return srs.SRS_PATH.read_text(encoding="utf-8"), srs.read_trace(srs.TRACE_PATH)


def test_the_real_matrix_passes() -> None:
    text, trace = _real()
    assert srs.check(text, trace) == []


def test_the_real_matrix_has_every_requirement_and_criterion() -> None:
    text, trace = _real()
    verdicts, ids = srs.parse_srs(text)
    assert len([i for i in ids if i.startswith("TR-")]) == 32
    assert len([i for i in ids if i.startswith("AC-")]) == 11
    assert all(v is not None for v in verdicts.values())
    assert {r["id"] for r in trace} == ids


def test_removing_a_requirement_row_from_the_real_document_is_noticed() -> None:
    text, trace = _real()
    cut = "\n".join(line for line in text.splitlines() if not line.startswith("| TR-31 |"))
    assert any("TR-31" in p for p in srs.check(cut, trace))


def test_renaming_a_real_test_is_noticed() -> None:
    text, trace = _real()
    broken = [dict(r) for r in trace]
    for r in broken:
        r["tests"] = r["tests"].replace("test_a_rejected_update_leaves_the_prediction_untouched", "test_renamed")
    assert any("test_renamed" in p for p in srs.check(text, broken))


def test_changing_a_quoted_default_is_noticed() -> None:
    text, trace = _real()
    broken = [dict(r) for r in trace]
    for r in broken:
        r["config"] = r["config"].replace("max_drift_sigma_mps=0.5", "max_drift_sigma_mps=0.6")
    assert any("max_drift_sigma_mps" in p for p in srs.check(text, broken))


def test_a_real_roll_up_number_changed_by_hand_is_noticed() -> None:
    text, trace = _real()
    bad = text.replace("| 9 | 0 | 1 (TR-30) |", "| 8 | 0 | 1 (TR-30) |")
    assert bad != text and any("OUN-01" in p for p in srs.check(bad, trace))


# --- the command ---------------------------------------------------------------------------


def test_main_succeeds_on_the_real_matrix_and_prints_a_summary(capsys: pytest.CaptureFixture[str]) -> None:
    assert srs.main(["--summary"]) == 0
    out = capsys.readouterr().out
    assert "| TR-01 | NOT MET |" in out and "traceability OK" in out


def test_main_fails_and_lists_each_problem(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = tmp_path / "srs.md"
    doc.write_text(SRS.replace("| TR-03 | c | **NOT VERIFIED** |", "| TR-03 | c | **MET** |"), encoding="utf-8")
    trace = tmp_path / "t.csv"
    trace.write_text("id,tests,config,gap\nTR-01,,,x\nTR-02,,,x\nTR-03,,,x\nAC-01,,,x\n", encoding="utf-8")
    assert srs.main(["--srs", str(doc), "--trace", str(trace)]) == 1
    err = capsys.readouterr().err
    assert "traceability problem" in err and "gap alone" in err


def test_a_trace_file_with_the_wrong_columns_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "t.csv"
    bad.write_text("id,test\nTR-01,x\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="columns"):
        srs.read_trace(bad)
