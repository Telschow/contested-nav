# Engineering baseline


> **Point-in-time snapshot (2026-09-29).** This document records the
> repository as the audit found it, before the remediation in
> `CHANGELOG.md` was applied. Counts, line numbers, and findings here are
> deliberately not updated: several of them are what the work was for. For
> the current state see `CHANGELOG.md` and re-run the commands quoted
> above.

Audit date: 2026-09-29. Findings only — **nothing was modified.** Every severity
below is justified by a command or a file:line reference that can be re-run.

Classification: **CRITICAL** (blocks publication or correctness) · **HIGH**
(blocks a stated project goal or CI) · **MEDIUM** (real defect or gap with
contained impact) · **LOW** (hygiene) · **COSMETIC**.

---

## 1. Summary

The codebase is in better shape than the CI badge suggests. Source is well
documented, has a 3:1 test-to-source ratio, passes its own ratchets, and shows no
TODO/FIXME markers, no debug code, and no bare `except:` clauses. The problems
are concentrated in three places: an unreachable security mitigation, a red lint
gate, and a handful of small correctness-adjacent defects.

| Severity | Count | Items |
|---|---:|---|
| CRITICAL | 1 | F1 |
| HIGH | 3 | F2, F3, F4 |
| MEDIUM | 5 | F5–F9 |
| LOW | 6 | F10–F15 |
| COSMETIC | 3 | F16–F18 |

---

## 2. CRITICAL / HIGH

### F1 — CRITICAL: live API key in the working tree, not gitignored

`opencode.json` holds `apiKey: "freellmapi-e4a9…"` and is **not** covered by
`.gitignore` (which covers `.opencode/`, the directory — not the root config
file). `git add -An .` confirms `add 'opencode.json'`. The tree has 20 modified
files, so a broad `git add` is plausible.

Not in any commit — verified across all 4 local commits and both dangling
commits. Fix: one `.gitignore` line plus token rotation. Full detail and
remediation in `PUBLICATION_READINESS.md` §1.

### F2 — HIGH: CI lint gate is red, and it gates the build job

`ruff check` → 131 errors. `ruff format --check` → 35 files would be reformatted.
`mypy src --ignore-missing-imports` → 15 errors in 3 files (11 in `eskf.py`).
`build` declares `needs: [test, lint]`, so **packaging is never verified in CI
while this is red**, even though `python -m build` succeeds locally.

Ruff breakdown (dominant): `ISC004` 17, `I001` 15, `RUF046` 13, `RUF100` 13,
`UP037` 11, `RUF022` 10, `RUF015` 9, `F401` 8, `RUF059` 7, `EXE001` 5, `F811` 4.
Most are auto-fixable (76 fixable, 49 needing `--unsafe-fixes`).

*Severity note:* `ruff` and `mypy` are **unpinned** in both `ci.yml` and the
`dev` extra, so these counts drift with upstream releases. The gate is partly
failing on rules that did not exist when the code was written. Fixing this
properly means declaring explicit `[tool.ruff.lint] select` and pinning versions,
so the standard is stable rather than "whatever ruff defaults to today".

### F3 — HIGH: the ADR-0008 frozen-anchor cross-check is unreachable

`eskf.py:521-548` implements a second-modality spoof check: on an inflated GNSS
grant, refuse the fix if its Mahalanobis distance from the anchor frozen at
outage start exceeds 15² = 225.

The guard requires `gnss_grants_since_verified > 0` **and** `decision.inflated`
on the same epoch. The grant at `:559-561` increments the counter, and the clean
accept at `:563-565` resets it. **Measured: zero reachable epochs** across a
truthful return and 5/12/20/22/40/100 m of offset.

Consequence: a documented security mitigation contributes nothing. It is not
counted as working anywhere in the docs, and the test that pins the gap is
`strict=True` so it fails loudly when fixed. **The defect is in the guard's
reachability, not its arithmetic** — in the forced-grant harness the thresholds
separate cleanly (5 m → d² 15.2 accepted; 12.5 m → 236.7 refused; 60 m → 5454.5
refused) and 7 threshold mutants are killed.

Also worth recording: even if reachable, its measured reach is ~12 m of
displacement, so it would **not** close the 1–2 m modest-spoof case that ADR-0007
identifies as the hard case.

*This is a deliberate deferral with documentation, not an oversight.* ADR-0008 and
roadmap item N1 both track it, and the decision to fix it belongs with the
pose-graph work because it changes what the filter does with post-outage GNSS.

### F4 — HIGH: documented benchmark numbers are single draws, and the docs now say so

`README.md` headline, ADR-0006 and `calibration.md` quote seed-0 values. The
10-seed sweep (2026-09-29) shows NEES spanning 211.7–2103.4 for `outage_visual`
and 280–12537 for `vision_anchor_in_measurement_noise`.

The *direction* is robust — overconfidence at every seed, worst case NEES 211.7 —
so B1 stands and the project's central claim survives. The *magnitudes* do not,
and ADR-0006's "1996.5 → 419.4" reads as a 4.8× improvement where the sweep means
suggest less. All three documents now carry an explicit single-draw caveat, and
`calibration.md` correctly reframes the claim as "two orders of magnitude, but not
two orders of magnitude *specifically*".

Remaining gap: the two controls the tables present as calibrated
(`gnss_only`, `outage_control`) flip verdict across seeds, and `outage_control` is
never clean in 10 draws.

---

## 3. MEDIUM

### F5 — `status_rejected_persistent` imported and exported twice

`src/navkit/fdir/__init__.py:29` and `:31` both import
`STATUS_REJECTED_PERSISTENT`; `:55` and `:57` both export it. Confirmed at
runtime: `__all__` has 22 entries, 21 unique. Harmless today (Python collapses
the duplicate) but it is a ruff `F811` and it obscures the module's real API
surface. Cosmetic in effect, mechanical in fix.

### F6 — mypy cannot narrow `None` through a boolean guard

`eskf.py:801-803`:

```python
use_gnss = gnss is not None and cfg.gnss_enabled
gnss_outages = gnss.outage_intervals() if use_gnss else []
```

**Verified safe at runtime** — the guard is correct, and mypy simply cannot
follow the implication. Not a bug. The 15 mypy errors are therefore *not* 15
defects; they are 1 real annotation problem (F7) plus type-narrowing noise. Worth
knowing before spending effort on them.

### F7 — the filter state dict is mis-annotated, which is the root of 11 mypy errors

`eskf.py:423,440` annotate state as `dict[str, np.ndarray]`, but it holds
`int` (`:561,565,752,793,794`), `bool` (`:669`), `None` (`:795`) and a nested
`dict` (`:824`). `eskf.py:797` needs a `# type: ignore[assignment]` because of
it. The fix is a `TypedDict` or a small state dataclass — a real improvement in
safety on the project's most safety-critical file, and the reason the type
checker is currently useless there.

### F8 — two untyped seams in the IO layer, lowest coverage in the repo

`io/imu.py` is **63.6%** covered — the lowest of any module, and it is below
several other modules' ratchet floors. It is also where the only mypy error
outside `eskf.py`/`metrics.py` lives. IMU noise models (bias random walk, scale
factor, axis misalignment) are exactly the kind of code where a silent sign error
would corrupt every downstream number without failing a test.

`io/trajectory.py` is 90.8% but its 2 TUM VI tests **skip** because reference
ground truth is not vendored. So the one place that converts quaternion order —
the project's C1 invariant — is only fully validated by unit round-trips against
known rotations, not against a real dataset.

### F9 — no `SECURITY.md`, `CONTRIBUTING.md`, or pre-commit hooks

For a repository whose entire value proposition is auditable, disciplined
measurement, the absence of a `SECURITY.md` (where to report a vulnerability) and
`CONTRIBUTING.md` is a real gap for a public portfolio project. A pre-commit hook
running the fast gates would have prevented F2 from ever reaching `main`.

---

## 4. LOW

| # | Finding | Evidence |
|---|---|---|
| F10 | README code block says "534 collected: 532 pass"; badge and `CONSTRAINTS.md` say 567/563. Measured: 567/563. | `README.md:53`, `:259` |
| F11 | 16 references to `github.com/contested-nav/contested-nav`; actual repo is `Telschow/contested-nav`. Badges cannot resolve; `[project.urls]` wrong. | `README.md` ×2, `index.html` ×12, `pyproject.toml` ×2 |
| F12 | Committed PNGs differ from a fresh `make_figures.py` run. **Deterministic run-to-run**, difference is matplotlib version metadata (3.11.2). Not a code defect, but a reviewer diffing figures will see noise. | `docs/figures/*.png`, `strings` shows `Matplotlib version3.11.2` |
| F13 | `EXE001` ×5: scripts have shebangs without the executable bit. | `scripts/*.py` |
| F14 | `RUF100` ×13 unused `# noqa`, i.e. suppressions that no longer suppress anything. Project-wide `CONSTRAINTS.md` watches for exactly this pattern. | ruff |
| F15 | No `.mailmap`; 4 commits by `48818540+Telschow@users.noreply.github.com` will not link to a GitHub profile. | `git log` |

---

## 5. COSMETIC

| # | Finding | Evidence |
|---|---|---|
| F16 | `base == base` NaN check. **Intentional and correct**, flagged by `PLR0124`. | `analysis/findings.py:418` |
| F17 | `as_dict` ×29 across modules. A dataclass-serialisation idiom, not duplication. Uniformity is arguably a feature. | grep |
| F18 | `time_offset` ×3, one per container class. A deliberate uniform interface. | `types.py:97,211,362` |

---

## 6. Explicitly *not* findings

Checked and clean. Recording these so their absence is not read as an oversight.

- **No `TODO`/`FIXME`/`HACK`/`XXX` markers** in `src/`, `tests/`, `scripts/`.
  (Hits for the word "bug" are all in prose explaining *historical* bugs and their
  regression tests — which is the project documenting prior mistakes properly.)
- **No debug code**: no `print()`, `breakpoint()`, or `pdb` in `src/`.
- **No bare `except:` and no `except Exception`.**
- **No duplicated logic.** The 3 repeated method names are interfaces, not copies.
- **Stale comments**: none found. Where behaviour changed, ADR-0007/0008 were added
  and the affected docs were corrected.
- **Test dependency direction is sound**: 3:1 test:source, and the doc-table
  checker has its own tests (`test_doc_tables.py`) — the thing that enforces
  "no hand-typed numbers" is itself tested.
- **Benchmark is genuinely reproducible** (CI's strongest gate, and it passes).

---

## 7. Local-vs-remote divergence (no action taken)

The local and GitHub histories **share no commits**. See `PROJECT_STATE.md` §5
for the full picture. Recommended non-destructive sequence, in order:

1. Fix F1 first (`.gitignore` + rotate token). Publishing anything before this
   risks exposing the key.
2. Commit the working tree in logical slices (audit docs, then ADRs, then the
   filter changes with their tests, then the sweep tool, then `uv.lock`).
3. `git remote add origin https://github.com/Telschow/contested-nav.git`
4. Because histories are unrelated, `git pull --rebase` **cannot** work. Fetch
   the remote stub and merge with `--allow-unrelated-histories`, keeping the
   remote's `README.md` stub in the history (never force-push; the remote's one
   commit must remain reachable).
5. Verify `git log --all` shows all 5 commits and `git ls-remote origin` matches
   local `HEAD` afterwards.

**No history was rewritten, no branch deleted, nothing pushed during this audit.**

---

## 8. Priority order

1. **F1** — `.gitignore` line + token rotation. Trivial, and gates everything.
2. **F2** — pin ruff/mypy, declare rule selection, fix the 14 real errors. Makes
   the portfolio claim ("measured, reproducible, gated") actually true.
3. **F10/F11** — stale counts and wrong-org URLs. Public-facing.
4. **F7** — `TypedDict` for filter state. Real safety win on the critical file.
5. **F5** — duplicate export. One-line mechanical fix.
6. **F8** — raise `io/imu.py` coverage to the ratchet floor; consider vendoring a
   small TUM VI subset to un-skip the 2 IO tests.
7. **F3** — reachability decision, with the pose-graph work (not a drive-by).
8. **F9** — `SECURITY.md`, `CONTRIBUTING.md`, pre-commit.
