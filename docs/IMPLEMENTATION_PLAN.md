# Implementation plan

Derived from `docs/ENGINEERING_BASELINE.md` and `docs/PUBLICATION_READINESS.md`
(audit 2026-09-29). Prioritised by impact on correctness, reproducibility,
research credibility, and publication safety. Not a wish list: every item cites
the finding it closes.

Baselines recorded before any edit (HEAD `c81c6f9`):

| Gate | Baseline |
|---|---|
| pytest | 563 passed, 2 skipped, 2 xfailed |
| coverage | 86.58% (3620/4181) |
| ruff check | 131 errors |
| ruff format --check | 35 files would reformat |
| mypy | 15 errors in 3 files |
| build | sdist + wheel OK |
| benchmark | bit-reproducible |
| doc tables | match |

---

## P0 — correctness / security / blocking

| ID | Change | Closes | Why first |
|---|---|---|---|
| P0-1 | Add `opencode.json` to `.gitignore` | F1 CRITICAL | A live API key is one `git add .` from public. One line, unblocks all other work. |
| P0-2 | Pin `ruff`/`mypy` versions; declare explicit `[tool.ruff.lint] select`; resolve all findings | F2 HIGH | CI `lint` is red and gates the `build` job, so packaging is unverified. Also stops the gate drifting with upstream defaults. |
| P0-3 | Remove duplicate `STATUS_REJECTED_PERSISTENT` import/export | F5 MEDIUM | Real `F811`; `__all__` has 22 entries, 21 unique. Obscures the module's API surface. |
| P0-4 | Correct stale test counts (534/532 → 567/563) | F10 LOW | Public-facing, and wrong numbers undercut the whole "no hand-typed numbers" claim. |
| P0-5 | Fix 16 wrong-org GitHub URLs | F11 MEDIUM | Badges cannot resolve; `[project.urls]` points at a non-existent org. |

## P1 — evaluation / reproducibility / research credibility

| ID | Change | Closes | Why |
|---|---|---|---|
| P1-1 | Multi-scene sweep: seed the *trajectory* so generalisation is testable | F4, Q7 | The largest threat to the headline claim. `synthetic.py` is analytic and takes no seed, so all 10 draws replay identical motion. The project's own words: "the numbers characterise a configuration, not a distribution over scenes." |
| P1-2 | Baseline-vs-current comparison under identical conditions | §4 of task | Makes "does this change help?" answerable. Reuses existing cases; no new claims. |
| P1-3 | Add statistical reporting to the sweep (bootstrap CI, not just range) | F4 | A range over 10 draws is weak. Confidence intervals cost ~20 lines and remove a stated weakness. |
| P1-4 | Commit `uv.lock` | reproducibility | 293 KB lockfile, untracked. Without it, "reproducible" is aspirational. |
| P1-5 | Run falsification test **Q1** (is anchor error really dominant?) | Q1 | `MECHANISM_LIBRARY` states the experiment; it was never run. Highest research value per hour in the repo, and it is a *published claim* currently supported only by assertion. |

## P2 — architecture / maintainability

| ID | Change | Closes | Why |
|---|---|---|---|
| P2-1 | Type the ESKF state as a `TypedDict` | F7 MEDIUM | 11 of 15 mypy errors share one root cause. Real safety win on the most safety-critical file. |
| P2-2 | Raise `io/imu.py` coverage (63.6%, lowest in repo) | F8 MEDIUM | IMU noise models are where a silent sign error corrupts every downstream number without failing a test. |
| P2-3 | Typed test layout without breaking the existing suite | §3 of task | Current flat `tests/` is fine; add subdirectories only where they earn it. |

## P3 — developer experience / public-repo readiness

| ID | Change | Closes | Why |
|---|---|---|---|
| P3-1 | `SECURITY.md` + `CONTRIBUTING.md` | F9 | Expected in a public portfolio repo; absence reads as unfinished. |
| P3-2 | `CHANGELOG.md` with the 4 requested categories | §12 | Four commits exist and none are described. |
| P3-3 | Dependabot + CodeQL + secret scanning workflows | §9 | The key in `opencode.json` is exactly what secret scanning catches. |
| P3-4 | Fix `README.md` install instructions (venv path, stale count) | §7 | A clone-and-run path is the first thing a technical reviewer tries. |
| P3-5 | Pre-commit config running the fast gates | F9 | Would have prevented P0-2 from reaching `main`. |

## P4 — cosmetic (deferred unless trivial)

- `F16` `base == base` NaN check — correct, flagged by `PLR0124`
- `F12` matplotlib-version figure drift — document, do not chase
- `F13` `EXE001` shebang/executable bit — resolved incidentally by `ruff` config
- `F15` `.mailmap` — only if the owner wants commit attribution linked

## Explicitly not in this plan

- **Refactoring the ESKF formulation.** Working, tested, and documented as a
  deliberate first-order choice. `CONSTRAINTS.md` C1–C5 forbid casual changes.
- **Deleting the wrong-config regression control.** Required for reproducibility
  of the pre-ADR-0001 failure.
- **Fixing the ADR-0008 guard.** A security-relevant refusal path starting to
  fire is an architectural decision for Track B, not a cleanup.
- **Any claim of novelty.** Not supported by the evidence, and not requested.
- **`git add -A` of the whole tree as one commit.** The prior work is committed in
  coherent slices so it stays reviewable.
