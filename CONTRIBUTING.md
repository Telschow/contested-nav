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

### Make targets, hooks and the container

`make help` lists them. The ones you will use:

```bash
make install     # editable install with the pinned dev tools
make hooks       # install the pre-commit hooks (ruff, ruff format, mypy, file hygiene)
make check       # lint + SRS traceability + test + coverage ratchet: the gates a pull request faces
make srs         # only the SRS traceability check
make repro       # regenerate every figure and table from scratch (measured 321 s, about 5 minutes)
make docker      # build the container image and run the CLI inside it
make docs        # build the documentation site (pip install -e ".[docs]" first)
```

The `Dockerfile` builds a clean environment, and `.devcontainer/devcontainer.json` reuses
it for VS Code and Codespaces. CI builds the image on every pull request, but the image is
not published anywhere.

### Local agent configuration

`opencode.json` in the repository root configures the coding agent used on this
project. It carries a provider API key, so it is listed in `.gitignore` and must
stay there: `git add opencode.json` is refused, which is the intended behaviour,
not a mistake to work around with `git add -f`.

`opencode.example.json` is the committed, credential-free template. Copy it and
supply the key through the environment:

```bash
cp opencode.example.json opencode.json
export FREELLMAPI_API_KEY=...        # never written to the config file
```

OpenCode substitutes `{env:FREELLMAPI_API_KEY}` at load time. If the variable is
unset the substitution yields an empty string, so the config parses and the
provider fails to authenticate rather than the file failing to load. Rotating
the key is a manual step for the key's owner; ignore rules keep it out of Git but
do not invalidate it anywhere it has already been exposed.

## Before opening a pull request

All five must pass locally. These are the same five CI runs.

```bash
pytest                                    # 855 passed, 3 skipped, 2 xfailed
python scripts/coverage_report.py --ratchet
ruff check src tests scripts
ruff format --check src tests scripts
mypy src --ignore-missing-imports
```

`ruff format src tests scripts` applies formatting; the `--check` form is the
gate.

The expected suite result on a fresh clone is `855 passed, 3 skipped, 2 xfailed`.
Two skips need TUM VI reference data that is not vendored (see below). The third
is the doc-table check, which runs once `python scripts/run_benchmark.py` has
written `results/benchmark.json` (then `856 passed, 2 skipped, 2 xfailed`). The
two xfails
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
python scripts/run_benchmark.py --out results/benchmark.json   # ~16 s, 7 cases
python scripts/seed_sweep.py --seeds 10 --markdown             # sensor noise
python scripts/scene_sweep.py --seeds 8  --markdown            # trajectory
python scripts/outage_sweep.py --markdown --figure docs/figures/outage-sweep.png   # outage window, ~2.5 min
python scripts/make_figures.py                                 # docs/figures/*.png
python scripts/check_doc_tables.py --results results/benchmark.json
```

After `pip install -e .` each script has an installed equivalent with the same options:
`navkit run`, `navkit sweep seeds`, `navkit sweep scenes`, `navkit sweep outages` and `navkit figures`. The
scripts are thin wrappers around the same code in `src/navkit/`.

The benchmark is bit-reproducible: running it twice gives byte-identical output
once wall-clock timings are stripped, and CI enforces that. The sweeps are
reproducible too: CI checks the seed and scene sweeps at three seeds and the outage sweep on a reduced grid (one start, two durations, two seeds).

`results/` is gitignored. The numbers in the docs are verified against a fresh
run rather than committed, so a stale artifact can never be mistaken for
evidence.

The PNGs under `docs/figures/` are the exception: they are committed, so they
must be regenerated with `scripts/make_figures.py` in the same change that
alters any published number, or they will contradict the tables beside them.
Nothing checks this automatically, because pixel output depends on the
Matplotlib build and a byte comparison would fail on a different machine for
reasons that have nothing to do with the data. Compare the underlying
`results/benchmark.json` instead, which CI does verify.

## Commits and pull requests

Conventional commit prefixes, one coherent change each. In this repository the
subject line is the explanation; the body says why, and says what was measured.

```
fix(io): repair the EuRoC IMU loader, which raised on every call
```

A commit that reformats most of the tree is a separate commit, even when it
belongs to the same piece of work -- otherwise the behavioural change cannot be
reviewed on its own.

## Coverage

Coverage is measured by `scripts/coverage_report.py`, the project's own tracer, because
constraint S1 keeps `pytest-cov` out. `--ratchet` fails a pull request if the total falls
below 75% or any module falls below its floor, and it runs in CI on Linux. There is **no
coverage badge**: a badge needs either a third-party service or a committed file that goes
stale, and neither is a live source of this project's number. The figure that counts is the
one `scripts/coverage_report.py` prints, and the quoted copies in `CONSTRAINTS.md` are
re-measured when they drift.

## Branch protection (recommended settings)

These are settings for the repository owner to apply, in Settings, Branches, Branch
protection rules, for `main`. Nothing here is changed by a pull request.

| Setting | Value | Why |
|---|---|---|
| Require a pull request before merging | on | `main` never receives a direct push |
| Required approvals | 0 while there is one maintainer, 1 when there are two | GitHub does not let an author approve their own pull request |
| Require status checks to pass | on, and "require branches to be up to date" on | the checks below |
| Require conversation resolution | on | a review thread is answered before merge |
| Restrict force pushes and deletions | on (the default) | history on `main` is not rewritten |
| Include administrators | on | the owner is bound by the same gates |
| Require linear history | **off** | pull requests are merged with merge commits here |
| Require signed commits | off | not part of this project's workflow |

Required checks, by the names GitHub shows (they come from the `name:` of each job):

- `lint`, `build`, `docs`
- `test (py3.11)`, `test (py3.12)`, `test (py3.13)`
- `test (py3.13, macos-latest)`, `test (py3.13, windows-latest)`
- `benchmark reproducibility`, `sweep reproducibility`
- `analyze (python)` (CodeQL)
- once those workflows are merged: `container`, `secret scan`, `pip-audit`, `dependency review`,
  `relative links`

Do **not** require `github-advanced-security`: it is an automated review service, not a gate
(it failed on every pull request for a month on a quota error that has nothing to do with the
code). `SBOM` and `external links` are informational.

## Pull requests and issues

Pull requests start from `.github/pull_request_template.md`, issues from the templates in
`.github/ISSUE_TEMPLATE/` (bug report, feature request, roadmap item). `CODEOWNERS` routes
review to the maintainer. The issue forms apply the labels `bug`, `enhancement` and `roadmap`;
create them once under Issues, Labels, or GitHub drops the label silently. Conduct is covered
by `CODE_OF_CONDUCT.md`; security reports go through `SECURITY.md`.
