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
- `vision_enabled` stays False until a candidate passes the B1 gate on its held-out seeds (ADR-0028 for the first candidate, ADR-0030 for any new one) and the maintainer decides to change the default. Passing the gate alone does not change it.
- Quaternions (w, x, y, z) internally; poses are T_wb; Joseph-form covariance update.
- Numbers on the first-read pages (README.md, docs/index.md, docs/getting-started.md, docs/results.md, docs/status.md) are generated and checked by CI: benchmark tables by `scripts/check_doc_tables.py`, counts and two headline values through metric markers (`scripts/metrics.py`), and `tests/test_quoted_numbers.py` fails on any other measured number there. Figures labelled "measured once on one machine, not checked by CI" or "measured at <date>" are not checked, and neither are other pages. Never type a number by hand.
- Keep the overconfident single-anchor case as a control row after any fix.

## Writing rules
- No em dashes. Short sentences. No new markdown file unless a reviewer will read it.
- Solo project: never invent teams or owners.
- Counts (tests, coverage, ADRs) are generated, not written.

## Workflow
- Small PRs, each with tests, green CI before merge.
- Decisions get an ADR; the maintainer writes the decision section.
- Ask before: force-push, history rewrite, deleting docs other pages link to, tagging releases.

## Agent skills

### Issue tracker

GitHub Issues on Telschow/contested-nav, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one root `GLOSSARY.md` plus `docs/adr/`. See `docs/agents/domain.md`.
