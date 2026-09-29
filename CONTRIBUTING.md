# Contributing

## Getting set up

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

`pip install -e ".[dev]"` resolves the pinned `ruff` and `mypy` versions, so the
local gates match CI. If you use `uv`, `uv run pytest` works from a clean
checkout.

No install step is strictly required to run the tests: `pyproject.toml` puts
`src` on `pythonpath` for pytest, so a fresh clone needs only `pytest`.

## Before opening a pull request

All five must pass locally. These are the same five CI runs.

```bash
pytest                                    # 597 passed, 2 skipped, 2 xfailed
python scripts/coverage_report.py --ratchet
ruff check src tests scripts
ruff format --check src tests scripts
mypy src --ignore-missing-imports
```

`ruff format src tests scripts` applies formatting; the `--check` form is the
gate.

The expected suite result is `597 passed, 2 skipped, 2 xfailed`. The two skips
need TUM VI reference data that is not vendored (see below), and the two xfails
are deliberate: they pin ADR-0007's spoof-permanence signal, which is inert for
every reachable configuration. They are meant to keep failing until Track B
lands, at which point they become real tests.

## Datasets

No real-sensor data is vendored, and none will be. TUM-VI is available from
[TUM](https://cvg.cit.tum.de/research/vision/vi-dataset/) under its own terms;
download it separately if you want to run the reference checks. Until then those
tests skip, and the skip is visible in the suite output rather than hidden.

Every published number comes from `configs/benchmark.yaml`, a synthetic
known-answer fixture. Adding a real dataset does not change a number already in
the docs; it adds a new claim, and new claims need the claim-type tagging in
`navkit/analysis/findings.py`.

## Conventions worth knowing

**Never hand-type a number.** Every figure in `README.md` and `docs/` is
generated and checked by `scripts/check_doc_tables.py`, which CI runs. If you
change a result, regenerate rather than editing prose, and let the check tell
you what moved.

**Do not add `# noqa`.** The repository has none, deliberately. A rule the
project does not want is disabled in `[tool.ruff.lint]` in `pyproject.toml`
with a comment saying why, so the decision is visible and reviewable. A
`noqa` hides it at the call site.

**No error-code suppression for mypy.** `pyproject.toml` disables none. Three
codes were disabled once; they were hiding 12 real errors on a mis-annotated
state dict, which has since been made a `TypedDict`.

**Tag claims by type.** `ClaimType` is `FACT`, `MEASUREMENT`, `INTERPRETATION`,
or `HYPOTHESIS`, and `validate_claims` enforces what each may assert. If your
change makes a previously-falsifiable claim untestable, that is a regression
even if the code still runs.

**Record an ADR for a decision, not an implementation.** Anything that closes
off an alternative belongs in `docs/adr/`. ADR-0008 is the model: it records
that a cross-check was implemented, tested, and left *disabled*, and why.

**Keep the tests able to fail.** A test that asserts `X or True`, or indexes
`[0]` into a list it expects to have one element of, verifies nothing. If a
mutation to the code would not fail your test, it is not a test yet. Both
patterns existed in this repository and both were found during the 2026-09-29
audit.

## Reproducing the published results

```bash
python scripts/run_benchmark.py --out results/benchmark.json   # ~40 s, 7 cases
python scripts/seed_sweep.py --seeds 10 --markdown             # sensor noise
python scripts/scene_sweep.py --seeds 8  --markdown            # trajectory
python scripts/check_doc_tables.py --results results/benchmark.json
```

The benchmark is bit-reproducible: running it twice gives byte-identical output
once wall-clock timings are stripped, and CI enforces that. Both sweeps are
reproducible too, and CI checks them at three seeds.

`results/` is gitignored. The numbers in the docs are verified against a fresh
run rather than committed, so a stale artifact can never be mistaken for
evidence.

## Commits and pull requests

Conventional commit prefixes, one coherent change each. In this repository the
subject line is the explanation; the body says why, and says what was measured.

```
fix(io): repair the EuRoC IMU loader, which raised on every call
```

A commit that reformats most of the tree is a separate commit, even when it
belongs to the same piece of work -- otherwise the behavioural change cannot be
reviewed on its own.
