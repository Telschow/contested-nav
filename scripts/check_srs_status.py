#!/usr/bin/env python
"""Generate and check the benchmark-backed rows of the SRS acceptance status (section 3.2).

AC-01 to AC-04 are measured by the benchmark, so their rows and the pass/fail tally are produced from the committed
golden snapshot ``tests/golden/benchmark.json``. ``--check`` fails when the document differs, ``--write`` rewrites it.
The other rows are not benchmark measurements and are left as written.

AC-04 uses the isotropic-ellipsoid 2-sigma coverage (see GLOSSARY.md), the statistic the criterion names today. The
statistic and the threshold are a maintainer decision, so the row says so.

    python scripts/check_srs_status.py
    python scripts/check_srs_status.py --write
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRS_PATH = ROOT / "docs" / "product_management" / "01_system_requirements_spec.md"
GOLDEN_PATH = ROOT / "tests" / "golden" / "benchmark.json"

ATE_LIMIT_M = 3.0
NEES_RATIO_LIMIT = 2.0
COVERAGE_MIN = 0.95
COVERAGE_CASES = (
    "outage_visual",
    "outage_visual_degraded_camera",
    "outage_visual_degraded_camera_rereferenced",
    "vision_anchor_in_measurement_noise",
)
PENDING = "statistic pending maintainer decision"
TALLY = re.compile(r"^\*\*(\d+) pass, (\d+) fail\.\*\*", re.M)


def _verdict(ok: bool) -> str:
    return "**PASS**" if ok else "**FAIL**"


def rows(cases: dict) -> dict[str, str]:
    """The four generated table rows, keyed by acceptance id."""
    out: dict[str, str] = {}
    for ac, name in (("AC-01", "outage_visual"), ("AC-02", "outage_visual_degraded_camera")):
        ate = cases[name]["headline"]["ate_rmse_m"]
        out[ac] = f"| {ac} | < {ATE_LIMIT_M:.1f} m | {ate:.3f} m | {_verdict(ate < ATE_LIMIT_M)} |"
    cal = cases["outage_visual"]["outage_calibration"]
    ratio = cal["nees_mean"] / cal["nees_expected"]
    out["AC-03"] = (
        f"| AC-03 | ratio ≤ {NEES_RATIO_LIMIT:.1f} | {ratio:.1f} ({cal['nees_mean']:.1f} / {cal['nees_expected']:.0f})"
        f" | {_verdict(ratio <= NEES_RATIO_LIMIT)} |"
    )
    cover = [cases[n]["headline"]["coverage"]["2sigma"] for n in COVERAGE_CASES]
    shown = ", ".join(f"{100 * c:.1f}%" for c in cover)
    out["AC-04"] = (
        f"| AC-04 | ≥ {100 * COVERAGE_MIN:.0f}% ({PENDING}) | {shown} | {_verdict(min(cover) >= COVERAGE_MIN)} |"
    )
    return out


def section(text: str) -> tuple[int, int]:
    start = text.index("### 3.2 Current acceptance status")
    end = text.index("### 3.3", start)
    return start, end


def render(text: str, cases: dict) -> str:
    """The section with the generated rows and the tally replaced."""
    start, end = section(text)
    lines = text[start:end].split("\n")
    wanted = rows(cases)
    for i, line in enumerate(lines):
        m = re.match(r"\| (AC-\d\d) \|", line)
        if m and m.group(1) in wanted:
            lines[i] = wanted[m.group(1)]
    body = "\n".join(lines)
    verdicts = [re.search(r"\*\*(PASS|FAIL)", line) for line in lines if re.match(r"\| AC-\d\d \|", line)]
    passes = sum(1 for v in verdicts if v and v.group(1) == "PASS")
    fails = sum(1 for v in verdicts if v and v.group(1) == "FAIL")
    body = TALLY.sub(f"**{passes} pass, {fails} fail.**", body)
    return text[:start] + body + text[end:]


def check(srs: Path = SRS_PATH, golden: Path = GOLDEN_PATH) -> int:
    cases = json.loads(golden.read_text(encoding="utf-8"))["cases"]
    text = srs.read_text(encoding="utf-8")
    want = render(text, cases)
    if want == text:
        return 0
    old, new = text.split("\n"), want.split("\n")
    for a, b in zip(old, new, strict=False):
        if a != b:
            print(f"{srs.name}: document says  {a}\n{srs.name}: benchmark gives {b}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true", help="rewrite the document from the benchmark")
    args = parser.parse_args(argv)
    if args.write:
        cases = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["cases"]
        SRS_PATH.write_text(render(SRS_PATH.read_text(encoding="utf-8"), cases), encoding="utf-8")
        return 0
    return check()


if __name__ == "__main__":
    sys.exit(main())
