# CLAUDE.md

## Project
navkit / contested-nav: NumPy-only 21-state error-state Kalman filter (IMU, GNSS position,
simulated visual-odometry relative pose), FDIR layer, and a calibration harness (NEES, 2-sigma
coverage). Synthetic evidence only unless a results row says otherwise.

## Commands
- Install: `python -m venv .venv && .venv/bin/pip install -e ".[dev]"`
- Tests: `.venv/bin/python -m pytest -q` (about 4 to 5 min)
- Lint/format/types: `ruff check src tests scripts`, `ruff format --check src tests scripts`, `mypy src --ignore-missing-imports`
- Benchmark tables: `navkit run --markdown`; doc check: `python scripts/check_doc_tables.py`
- Coverage: `python scripts/coverage_report.py`

## Invariants (see CONSTRAINTS.md)
- Runtime deps stay numpy, matplotlib, pyyaml (S1). No vendored third-party data (S2).
- `vision_enabled` stays False until the B1 gate is met (mean NEES < 10, coverage > 90%).
- Quaternions (w, x, y, z) internally; poses are T_wb; Joseph-form covariance update.
- Every number in README/docs is generated and checked by CI. Never type a number by hand.
- Keep the overconfident single-anchor case as a control row after any fix.

## Writing rules
- No em dashes. Short sentences. No new markdown file unless a reviewer will read it.
- Solo project: never invent teams or owners.
- Counts (tests, coverage, ADRs) are generated, not written.

## Workflow
- Small PRs, each with tests, green CI before merge.
- Decisions get an ADR; the maintainer writes the decision section.
- Ask before: force-push, history rewrite, deleting docs other pages link to, tagging releases.
