# Reducing CI time

Status: research note, not a decision. A decision would need an ADR with the maintainer's decision section.
Not linked from any first-read page. Measured on 2026-10-25 from GitHub Actions run logs and one local run.

## Tracking

The first three levers are issues for Sandcastle, in this order:

- Lever 1, xdist on the plain legs: #231.
- Lever 2, parallel reproducibility jobs: #232.
- Lever 3, parallel coverage: #233, blocked by #231.

Levers 4 to 7 have no issue yet. Lever 4 (trim the PR matrix) waits until these three are measured.
The Sandcastle merger pushes to `main` after its local checks, so workflow changes land without a CI run first. Check the next CI run on `main` by hand after each of these issues.

## Why this matters

A pull request takes about 50 minutes of wall-clock CI, and some runs take more than 70. Sandcastle agents are about to open many small pull requests. Every one pays this cost, and the ruleset setting "require branches to be up to date" (see side findings) would serialise them.

## 1. Where the time goes

Runs read with `gh run view <id> --json jobs`. Job and step times come from `startedAt` and `completedAt`.

Workflow file: all jobs are in `.github/workflows/ci.yml`. `ensemble reproducibility` and `sweep reproducibility` are jobs `ensemble` and `sweeps` in that same file, both `needs: [changes, lint]`.

### Per-job wall-clock, minutes

| Job | PR run 40190525630 | Push to main 40191955358 | PR run 40184787397 |
|---|---|---|---|
| test (py3.13, windows-latest) | 46.5 | 46.5 | 46.5 |
| test (py3.13), the coverage leg | 46.2 | 70.8 | 71.4 |
| test (py3.12) | 41.7 | 41.7 | 42.0 |
| test (py3.11) | 36.5 | 37.1 | 24.0 |
| ensemble reproducibility | 32.5 | 32.7 | 31.4 |
| test (py3.13, macos-latest) | 25.4 | 24.6 | 20.9 |
| sweep reproducibility | 19.8 | 19.9 | 19.9 |
| lint, build, container, benchmark, docs, changes | 0.1 to 2.1 each | same | same |

Whole-workflow wall-clock from `gh run list -w CI`: 42 to 75 minutes for code changes, 13 to 14 minutes for docs-only pull requests (for example 40190524673).

### Findings from the step timings

1. Install is not the problem. In every test job the `Install` step took 0.2 to 0.6 minutes. The `setup-python` pip cache hit ("Cache hit for: setup-python-Linux-x64-24.04-Ubuntu-python-3.12.15-pip-...", 170 MB restored in about 1 s, run 40190525630 job 121160435451). Caching has nothing left to give.
2. The test step is the whole cost: 36 to 46 minutes of 41 to 46 minute jobs. The suite runs in one process. CI log for py3.12 ends with the pytest summary line `... in 2478.11s (0:41:18)` (counts are in that log line; not copied here).
3. The critical path is the slowest job, because all legs run in parallel. Windows (46.5 min) and the coverage leg (46 to 71 min) set it. Trimming any other leg does not shorten the pull request.
4. Runner variance is large. The same coverage leg took 46.2, 70.8 and 71.4 minutes across three runs of near-identical trees. py3.11 took 36.5 and 24.0. I did not find the cause. The coverage leg is 3.13 and the others differ in version, so I cannot separate "tracer overhead" from "runner speed" from these logs. Plain Python 3.13 on Linux is never run in CI, so a clean comparison does not exist.
5. The two reproducibility jobs run the same kind of work as some tests. `ensemble` steps: ensemble 13.5 min, start-draw 4.5, correlated-GNSS 1.1, development gate 3.7, candidate gate 9.4 (run 40190525630, job 121160600565). `sweeps` steps: sweeps twice 8.3, mismatch 3.0, fault matrix 3.7, FDIR 4.3. The suite has 12 `rerun`-marked tests (`pytest.mark.rerun`) that re-run studies, and the slowest-test list below shows tests that re-run the same studies. I did not measure the overlap, so I do not claim the work is duplicated, only that it is likely partly.
6. Concurrency already cancels superseded runs. In the 30 most recent CI runs, 9 were `cancelled`, 5 of them push runs on main. See lever 5.

### Slowest tests

CI does not print durations: `addopts` in `pyproject.toml` is only `--strict-markers`, and the logs have no `slowest` section. I ran `python -m pytest --durations=40 -q -p no:cacheprovider` once, locally, in a venv at `/private/tmp/claude-501/-Users-daniel-Development-contested-nav/6c735db7-59ef-4062-bd95-42f8d7fa6480/scratchpad/venv` (Python 3.13.5, outside the repo tree). Result: single process, 8-core Apple-silicon Mac, `1182.40s (0:19:42)`.

This contradicts the "about 4 to 5 min" in CLAUDE.md. On this machine the suite takes about 20 minutes. CLAUDE.md should be corrected by the maintainer.

Time per file, summed over the 40 slowest entries only (so a lower bound; the top 40 account for 757 s of the 1182 s):

| File | Seconds in top 40 |
|---|---|
| tests/test_vo_page.py | 220 |
| tests/test_candidate_gate_run.py | 85 |
| tests/test_b1_gate_run.py | 67 |
| tests/test_fdir_false_alarm.py | 61 |
| tests/test_vo_error.py | 44 |
| tests/test_fault_classification_page.py | 39 |
| tests/test_mismatch_ensemble.py | 34 |
| tests/test_attribution.py | 32 |

The single slowest test is 81.7 s (`test_vo_page.py::test_a_replay_stream_with_no_errors_is_the_true_body_motion`). No test is longer than 82 s. This matters for parallelism: the longest single test is far below any target time, so work can be balanced well.

Mid-suite progress timestamps in the CI log show the time is spread, not in one place: stretches of consecutive tests took from 1 s up to 8 minutes (last block, 97% to 100%).

Local run left no new tracked or untracked files from the tests (`git status` showed only `node_modules/`, `package.json`, `package-lock.json`, which I did not create and which were not in the initial status snapshot).

## 2. What the primary docs say

Cited by page. Quotes are short.

- Runner size. GitHub-hosted runners reference (docs.github.com, `actions/reference/runners/github-hosted-runners`): public repositories get 4 vCPU and 16 GB on `ubuntu-latest` and `windows-latest`; private repositories get 2 vCPU and 8 GB; `macos-latest` (arm64, M1) has 3 vCPU and 7 GB in both. "Use of the standard GitHub-hosted runners is free and unlimited on public repositories." The repo is public (`gh repo view`: `PUBLIC`). So minutes are free, and Linux and Windows jobs have 4 cores that the suite does not use today. macOS has 3 cores and 7 GB, which limits worker count there.
- Concurrency. "Control the concurrency of workflows and jobs": by default a running job is not interrupted and only `pending` ones are replaced; with `cancel-in-progress: true` the running one is cancelled. It can be an expression, for example `${{ !contains(github.ref, 'release/') }}`.
- Required checks and skipping. "Troubleshooting required status checks": a workflow skipped by path or branch filtering leaves its checks "Pending" and blocks merging. A job skipped by a conditional reports Success. The page does not address matrix jobs. The repo comment in `ci.yml` (matrix jobs skipped as a whole never expand their check names) matches that gap, and is why the `changes` job exists. Any trimmed matrix must keep the check names that a ruleset requires, or reports them.
- pytest-xdist, "Running tests across multiple CPUs" and distribution page (`pytest-xdist.readthedocs.io/en/stable/distribution.html`): `-n auto` uses "as many processes as your computer has physical CPU cores". `--dist load` is the default and sends tests to any free worker. `loadfile` keeps all tests of a file on one worker. `loadscope` groups by class or module and helps with expensive module or class fixtures. `loadgroup` honours `xdist_group` marks. `worksteal` splits tests evenly and lets idle workers take from others, suited to tests of very different durations.
- pytest-cov with xdist (`pytest-cov.readthedocs.io/en/latest/xdist.html`): works in `load` and `each` modes and merges worker data. The page does not describe parallel data files. Not usable here anyway: CONSTRAINTS.md says S1 forbids adding `pytest-cov`.
- coverage.py config (`coverage.readthedocs.io/en/latest/config.html`): `[run] core` has `ctrace`, `pytrace` and `sysmon`. `sysmon` "requires Python 3.12+", is the default from 3.14, and does not support branch coverage on 3.12 and 3.13. The page makes no speed claim. `[run] parallel` writes one data file per process, which must be combined before reporting. I did not find a speedup figure in the config page, so I make none.
- Not fetched, so unverified here: actions/setup-python caching docs, GitHub merge queue docs, scheduled workflow docs, `pytest-split` docs. Statements about them below are from general knowledge and marked as such.

Dev dependency rule. CONSTRAINTS.md S1: "S1 constrains the runtime (`[project] dependencies`). Test-only tools in `[project.optional-dependencies] dev` are allowed when they add no runtime import: pytest, Hypothesis for property tests, ruff and mypy." So `pytest-xdist` in `dev` is allowed by the rule's wording. But the coverage paragraph of CONSTRAINTS.md says S1 forbids `pytest-cov`, so a reviewer may still ask for an ADR. I recommend the maintainer decides, with a short ADR.

## 3. What would break under parallel execution

Checked by reading tests and `tests/conftest.py`. Not proven: I did not run the suite under xdist.

- Shared files. Writers use `tmp_path` or `tmp_path_factory` (many test files use temp paths; `test_demo_generation.py` uses a module-scoped `tmp_path_factory` directory, which xdist makes per worker). `test_golden_benchmark.py` writes the golden only under `__main__ --update`. `test_coverage_report.py` redirects `COV` to `tmp_path`. I found no test that writes into the repo or into `docs/data`. `results/benchmark.json` is only read, and its test skips when absent.
- Committed CSVs. Read only.
- Global state. `test_coverage_report.py` calls `sys.settrace` and relies on restoring an outer tracer. That is per process and safe under xdist, but it is the key coupling to the coverage tool (lever 3). `test_cli.py` and `test_coverage_report.py` use `monkeypatch.chdir`, which is per process.
- Hypothesis. `conftest.py` uses profile `ci` with `derandomize=True`. `.hypothesis/` holds only `constants/`, no examples database, so there is no shared database file contention.
- Module-scoped fixtures. Many test files declare fixtures with a scope. With `--dist load` or `worksteal`, each worker that gets a test from a module builds that module's expensive fixture again. Use `--dist loadfile` first. The largest file (`test_vo_page.py`, at least 220 s) then sets a floor of about 4 minutes per run, which is fine.
- Ordering. I did not find ordering dependence, but there is no proof. Test: run with `-p no:randomly` and xdist, compare to serial.
- Memory. The Linux and Windows public runners have 16 GB. macOS has 7 GB and 3 cores, so use `-n 3` there, or leave macOS serial.
- Determinism. Seeds are set per call (ADR-0010). Parallelism changes which process runs a test, not the test's seed. The risk is only floating-point differences from BLAS threads, which exist today and the golden test already compares with a tolerance.

## 4. Levers, ranked by time saved over effort and risk

Estimates assume a roughly 3x speedup on a 4-core runner, and are estimates, not measurements. Re-measure after each step. All times are minutes for the slowest leg.

| Rank | Lever | Saves | Effort | Risk |
|---|---|---|---|---|
| 1 | Run pytest under xdist inside each non-coverage job | Windows 46 to about 15; py3.11/3.12 36-41 to about 12-14; macOS 25 to about 10 | Low | Low to medium |
| 2 | Split `ensemble` and `sweeps` into step-level parallel jobs | 32 to about 14; 20 to about 8 | Low | Low |
| 3 | Make coverage parallel, or move it off the PR path | 46-71 to about 15 (parallel), or removes the leg | Medium | Medium |
| 4 | Trim the PR matrix | Removes Windows, macOS, py3.12 from PR path | Low | Medium (required checks) |
| 5 | Fix `cancel-in-progress` for main | Does not save time; stops main being unvalidated | Trivial | Low |
| 6 | Test-impact selection | Large on small PRs | High | High |
| 7 | Cache dependencies | About 0 (already hit) | None | None |

Estimated PR wall-clock after ranks 1 to 3: about 15 minutes (set by the coverage leg and the split ensemble). After rank 4 as well: about 12 to 15 minutes, without the platform legs. These follow from the above numbers; they are not measured.

### Lever 1. xdist inside a job

What: add `pytest-xdist` to `dev`, run `pytest -n auto --dist loadfile` on the Linux legs and Windows, `-n 3` on macOS. Not on the coverage leg yet.

What could break: module fixtures (use `loadfile`); the coverage leg is untouched so the ratchet and the recorded figure are unchanged; test count is the same, but the progress output differs. Goldens: unchanged, tests are seeded. Quoted-numbers and doc-table checks: they read files, not run order; `scripts/metrics.py --check` collects tests, and xdist must not change `--collect-only`. Check this explicitly.

### Lever 2. Parallel reproducibility jobs

The steps in `ensemble` and `sweeps` are independent. Turn each job into a matrix over steps, keeping the original job name as an aggregate job so the check name `sweep reproducibility` (required in ruleset "Main") still exists. Estimated critical path: ensemble 13.5 min (the 25-seed ensemble) plus 0.3 min install; the candidate gate step (9.4 min) is next. Further splitting needs changes inside `scripts/seed_sweep.py`, which is outside this note.

What could break: the aggregate job must `needs` every matrix leg and use `if: always()` with an explicit result check, or a failed leg shows as skipped. Skipped legs on docs-only pull requests: the aggregate must treat `skipped` as pass only when `changes.code != 'true'`.

### Lever 3. Coverage

Today `scripts/coverage_report.py` runs `pytest.main` in process under a `sys.settrace` line tracer, then checks floors, then `scripts/metrics.py --check-coverage` compares the figure to `docs/data/metrics.json`. The executable-line denominator is Python-version specific, so the figure is recorded for 3.13 only. Under xdist the parent process tracer sees nothing from workers. Options:

- A. Worker-side tracer. In a `conftest.py` hook, when an env var is set, each xdist worker installs the same tracer and writes its hit lines to a JSON file at the end. `coverage_report.py` runs `pytest -n auto`, then unions the files. Same denominator, same tracer logic, so the figure should be identical. Medium effort. The `test_the_script_leaves_an_outer_tracer_in_place` test must keep passing.
- B. Shard the coverage leg by file across jobs, each uploading hit-line JSON, and a final job unions and applies floors. Higher effort, more moving parts.
- C. Move the coverage leg off the PR path: run it on push to main and nightly. Then a pull request that lowers coverage is found after merge. That conflicts with the intent of the ratchet ("a build failure rather than something a reviewer has to notice"). Not recommended for the ratchet; acceptable for the "matches the recorded figure" step only if the maintainer accepts the delay.
- D. Use `sys.monitoring` instead of `settrace` on 3.12+. The floor is 3.11, and the tracer is the recorded measurement, so changing it risks the figure. I found no speed claim in the coverage.py docs. Not recommended now.

Overhead of the tracer is not separable in the available data (finding 4). Measure it first: run `python scripts/coverage_report.py` and plain `pytest` on one 3.13 Linux runner in one workflow_dispatch job.

What could break: the "Coverage matches the recorded figure" step compares within a tolerance (`scripts/metrics.py`); a changed hit set from a missed worker file would lower coverage and fail it. Good: it fails loudly. A worker that crashes before writing its file would silently lose hits, so the merge step must assert one file per worker.

### Lever 4. Trim the PR matrix

Idea: on pull requests run py3.13 (coverage leg) and the floor py3.11 on Linux. Run py3.12, macOS and Windows on push to main and on a nightly `schedule`.

Required checks. The effective rules on `main` currently require nothing (see side findings). If the ruleset is fixed to `main`, the required list includes `test (py3.12)`, `test (py3.13, windows-latest)` and `test (py3.13, macos-latest)`. A check that is never reported blocks merging, and per GitHub's troubleshooting page a skipped conditional job reports Success. So keep the jobs and gate their steps with `if: github.event_name != 'pull_request'`, the same trick already used for `changes`. Then the check names exist and pass fast on PRs. Alternatively edit the required list; that is a repository setting, outside this note.

What could break: a Windows or 3.12 only failure is found after merge. The comment in `ci.yml` says macOS and Windows exist "to find platform dependence in the maths", which is a slow-moving risk, so a nightly run is a reasonable cost. The sandcastle merger already pushes to main after local checks (commit e196132), so main needs a full run anyway.

### Lever 5. Avoid double runs and fix cancellation

Triggers are `push: main` and `pull_request`, so a merged PR is tested twice: once on the branch and once on main. With the merge commit identical to what was tested, the second run is redundant only if the branch was up to date. Concurrency group `ci-${{ github.ref }}` with `cancel-in-progress: true` means: (a) a new push to a PR branch cancels its old run, which is good for agents; (b) back-to-back merges to main cancel each other. In the last 30 runs, push runs on main such as 40190517877, 40190150789 and 40175904198 were cancelled, so some main commits never got a complete CI result. Suggested change:

```yaml
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
```

With this a main push is never cancelled (runs queue as `pending`, only the newest pending survives, per the GitHub docs, so some intermediate commits are still skipped; for a strict one-run-per-commit use `group: ci-${{ github.sha }}` on pushes). Risk: more queued main runs. Combined with lever 4, main runs are the expensive full matrix, so this has a cost; the maintainer decides.

### Lever 6. Test-impact selection

Run only tests that import changed modules (for example by a map from `src/navkit/x.py` to tests). Risks: this repo has many tests that read generated pages, committed CSVs and goldens, and cross-module reproducibility checks (the `rerun` tests). A change to a shared module such as `eskf.py` changes nearly everything, so the saving is for leaf changes only. A wrong map gives a green PR that breaks main. The coverage ratchet needs the full suite, so selection cannot apply to the coverage leg. Not recommended until levers 1 to 4 are measured. I did not evaluate any tool for this.

### Lever 7. Caching

Not worth doing. Pip cache hit already; install is 0.2 to 0.6 min. Caching study outputs (hash of `src/` and the config as key) would skip the `ensemble` and `sweeps` re-runs but defeats their purpose, which is to check that a fresh run reproduces the committed file.

## 5. Plan as small PRs

Each PR changes one lever and states how to check it. The check for all: the same pass, skip and xfail counts as the baseline log (read them from the pytest summary line; do not type them), the same coverage figure from `scripts/metrics.py --check-coverage`, and the golden test unchanged.

### PR A. Measure first (no behaviour change)

Add durations to CI logs so the next measurement is free.

```diff
--- a/pyproject.toml
+++ b/pyproject.toml
 [tool.pytest.ini_options]
-addopts = "--strict-markers"
+addopts = "--strict-markers --durations=25"
```

Verify: counts line unchanged; the log gains a `slowest 25 durations` section. Risk: the line is printed on every local run too. If the maintainer dislikes that, pass `--durations=25` in the CI `run:` lines instead.

### PR B. xdist on the plain legs

```diff
--- a/pyproject.toml
+++ b/pyproject.toml
-dev = ["pytest>=7.4", "hypothesis>=6.100", "pre-commit>=3.7", "ruff==0.17.1", "mypy==2.4.0"]
+dev = ["pytest>=7.4", "pytest-xdist>=3.6", "hypothesis>=6.100", "pre-commit>=3.7", "ruff==0.17.1", "mypy==2.4.0"]
```

```diff
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
       - name: Test
         if: needs.changes.outputs.code == 'true' && matrix.python-version != '3.13'
-        run: python -m pytest -q
+        run: python -m pytest -q -n auto --dist loadfile
```

For `test-os`, use `-n auto --dist loadfile` on Windows and `-n 3 --dist loadfile` on macOS (matrix `include` with a `workers` value). Add an ADR note for the new dev dependency, written by the maintainer.

Verify: compare the pytest summary line to a serial run on the same commit (counts equal); run `python -m pytest --collect-only -q` with and without `-n` (the xdist controller collects too) and diff the node-id lists; run `python scripts/metrics.py --check`. Rollback: delete `-n auto`.

Before merging, run it twice on a draft PR. If a test fails only under xdist, it is a hidden shared state or order dependency, which is itself a finding.

### PR C. Cancel only pull requests

The `concurrency` diff from lever 5.

Verify: push two commits to main quickly and see both complete; push two commits to a PR branch and see the first cancelled.

### PR D. Parallel reproducibility jobs

Convert `ensemble` into a matrix over its five commands and add an aggregate job named `ensemble reproducibility`. Same for `sweeps`, aggregate named `sweep reproducibility` (required by ruleset "Main").

```yaml
  ensemble-step:
    name: ensemble (${{ matrix.step }})
    runs-on: ubuntu-latest
    needs: [changes, lint]
    if: needs.changes.outputs.code == 'true'
    strategy:
      fail-fast: false
      matrix:
        step: [ensemble, start-draw, correlated-gnss, dev-gate, candidate-gate]
    steps:
      # checkout, setup-python, install as today
      - name: Run one step
        run: python scripts/ci_ensemble_step.py ${{ matrix.step }}   # a new script holding today's five commands
  ensemble:
    name: ensemble reproducibility
    needs: [changes, ensemble-step]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - run: |
          [ "${{ needs.changes.outputs.code }}" != "true" ] && exit 0
          [ "${{ needs.ensemble-step.result }}" = "success" ]
```

This needs a new small script (or inline `case`) that holds today's commands unchanged. Verify: the five commands and their arguments are byte-identical to today's (diff the YAML `run:` text); each leg passes; an intentionally broken committed CSV on a throwaway branch fails the right leg and the aggregate.

### PR E. Parallel coverage (lever 3, option A)

A `tests/conftest.py` hook (or a plugin file loaded only when `NAVKIT_COV_DIR` is set) installs the tracer in each worker and writes `hits-<worker>.json`; `scripts/coverage_report.py` runs `pytest -n auto --dist loadfile` and unions the files. Needs a test that a missing worker file fails the run.

Verify: run old and new on the same commit and diff `coverage.json`: `hit`, `exec` and `total_pct` must be equal per module. Then `scripts/metrics.py --check-coverage` passes with no change to `docs/data/metrics.json`.

### PR F. PR matrix trim (only if still needed)

```diff
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
       - name: Test
-        if: needs.changes.outputs.code == 'true' && matrix.python-version != '3.13'
+        if: needs.changes.outputs.code == 'true' && matrix.python-version != '3.13' && (github.event_name != 'pull_request' || matrix.python-version == '3.11')
```

Same pattern for the OS job. Add a nightly trigger:

```diff
 on:
   push:
     branches: [main]
   pull_request:
+  schedule:
+    - cron: "17 3 * * *"
   workflow_dispatch:
```

Note: `changes` sets `code=true` for non-PR events, so the nightly runs everything. Scheduled workflows run on the default branch (general knowledge; I did not fetch the page). Verify: check names for all matrix legs still appear on a PR and are green.

## 6. Side findings

- Ruleset "Main" (id 24655004) lists 16 required status checks, with `strict_required_status_checks_policy: true`, but its `ref_name.include` is `refs/heads/Main` (capital M). The default branch is `main`. `gh api repos/Telschow/contested-nav/rules/branches/main` returns only `deletion` and `non_fast_forward` (from ruleset 24207506 "Admin active branch"). `branches/main/protection` returns 404. So no required checks apply to `main` today. Ref matching is case sensitive as far as I know (not verified in docs). If the maintainer fixes the case, strict mode means every PR must be rebased after any other merge and re-tested, so with 50-minute CI the throughput would be about one PR per hour. That makes this note more urgent, not less. `ensemble reproducibility` is not in the required list.
- CLAUDE.md says the suite takes "about 4 to 5 min". I measured 19.7 minutes on an 8-core Apple-silicon Mac (single process). The maintainer should correct it; I did not edit it.
- Untracked `node_modules/`, `package.json`, `package-lock.json` appeared in `git status` during the session. I did not create them.

## 7. Open questions and what I could not verify

- Why the coverage leg takes 46 to 71 minutes on near-identical trees. Possibly runner variance. Needs a controlled run (lever 3 measurement).
- Tracer overhead of `settrace` versus plain pytest on the same Python and runner. Not measurable from existing logs.
- Whether the suite passes under xdist. I did not run it. Module-scoped fixtures and unseen ordering assumptions are the risk.
- Speedup under xdist is an estimate (about 3x on 4 cores). Real speedup depends on file balance under `loadfile` and BLAS threading. Setting `OMP_NUM_THREADS=1` and `OPENBLAS_NUM_THREADS=1` in the job env may avoid oversubscription; untested.
- Overlap between tests and the reproducibility jobs: not measured.
- GitHub docs for merge queue, scheduled workflows and setup-python caching, and `pytest-split` docs, were not read. A merge queue needs a `merge_group` trigger on the workflow (general knowledge). `pytest-split` needs a stored durations file (general knowledge). I did not recommend either.
- Answered: the Sandcastle merger pushes directly to `main` after its local checks (ruff, mypy, `make docs-fast`). PR CI is not in that path, so the CI run on the `main` push is the only full gate.
- MkDocs: this page is not in `nav`. `mkdocs.yml` sets `validation.omitted_files: info`, so `mkdocs build --strict` should not fail on it. I did not run the build. `scripts/check_links.py` checks Markdown links, not the nav. A docs-only pull request that adds this file runs the lighter docs gate, and `tests/test_ci_docs_tests.py`, the em-dash test and the framing test may scan it; run `make docs-fast` before committing.
