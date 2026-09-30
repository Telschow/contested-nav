# Publication readiness


> **Point-in-time snapshot (2026-09-29).** This document records the
> repository as the audit found it, before the remediation in
> `CHANGELOG.md` was applied. Counts, line numbers, and findings here are
> deliberately not updated: several of them are what the work was for. For
> the current state see `CHANGELOG.md` and re-run the commands quoted
> above.

Audit date: 2026-09-29. Scope: the working tree of this repository, all 4 local
commits, and the 2 dangling commits in the object store. Nothing was published,
pushed, or rewritten during this audit.

**Verdict: NOT READY TO PUBLISH AS-IS.** One CRITICAL item (a live API key one
`git add` away from public) and one HIGH item (a red CI lint gate) stand between
the current tree and a public repository. Neither requires code changes to fix.

---

## 1. CRITICAL — Live API key in the working tree, not gitignored

**File:** `opencode.json` (repo root, untracked, 728 bytes, owned by `root`)

It contains a real-looking provider key:

```json
"apiKey": "<REDACTED 2026-09-29 — the value was live and was committed here; see Status update at end of document>"
```

> **The literal value was removed on 2026-09-29.** It was quoted here as audit
> evidence and was therefore itself an exposure: this document is tracked and was
> published, so the evidence became the leak. The finding below is unchanged and
> still correct — only the quoted secret is gone. Removing the value does not
> invalidate the key; only rotation does.

It points at `http://localhost:3001/v1`, so the value is a local-development
token rather than a production cloud secret. That lowers the severity; it does
not remove the risk, because the token is still a credential, still reusable by
anyone who can reach that local port, and still reveals an internal service
topology.

**Why this is CRITICAL rather than MEDIUM:** the file is **not covered by
`.gitignore`**. `.gitignore` ignores `.opencode/` (the directory of skills and
references) but not `opencode.json` (the config file at the root). Verified:

```
$ git check-ignore -v opencode.json
-> *** NOT IGNORED ***
$ git add -An .
add 'opencode.json'
```

So the single most common way to stage work — `git add .` followed by a commit —
publishes this token. The repository currently has 20 modified tracked files and
8 untracked paths, which is exactly the state in which someone commits with a
broad `git add`.

**This has never been committed.** Verified by scanning all 4 local commits and
both dangling commits for key-shaped patterns and credential keywords: no match.
The remote repository is a one-file stub and does not contain it either. **The
GitHub history is clean.**

**Recommended remediation, in order:**

1. Add `opencode.json` to `.gitignore`. This is the actual fix and is a one-line
   change.
2. Rotate the token. It has been sitting in a world-readable file
   (`-rw-rw-r--`) since 2026-09-28.
3. Replace the literal with an environment-variable reference if the tool
   supports it, so the config is shareable.
4. Re-run `git add -An . | grep opencode` to confirm the fix.

I did not perform any of these. Adding a `.gitignore` entry is a repo change and
belongs in a reviewed commit, not in an audit; rotating a credential is the
owner's action; and deleting the file would remove active local tooling.

---

## 2. HIGH — CI lint gate is red on the current tree

`ci.yml` runs four checks in the `lint` job. Two fail, so the job is red and the
`build` job, which `needs: [test, lint]`, never runs.

| Check | Command | Result |
|---|---|---|
| ruff | `ruff check src tests scripts` | **131 errors** |
| format | `ruff format --check src tests scripts` | **35 files would be reformatted**, 12 already clean |
| mypy | `mypy src --ignore-missing-imports` | **15 errors in 3 files** |
| tests | `python -m pytest -q` | pass (563 passed, 2 skipped, 2 xfailed) |
| coverage | `coverage_report.py --ratchet` | pass |
| benchmark | run twice, diff | reproducible |
| doc tables | `check_doc_tables.py` | pass |
| build | `python -m build` | pass (sdist + wheel build and import) |

The dominant ruff categories are stylistic (`ISC004` ×17, `I001` ×15,
`RUF046` ×13, `RUF100` ×13, `UP037` ×11, `RUF022` ×10) plus 8 `F401` unused
imports and 4 `F811` redefinition. The mypy errors are concentrated in
`eskf.py` (11 of 15) and share one root cause: the filter state is annotated
`dict[str, np.ndarray]` while actually holding scalars, bools and `None`
(`eskf.py:561,565,669,752,793-795,824`).

Two caveats on the severity. First, `ruff` and `mypy` are installed unpinned in
`ci.yml` and in the `dev` extra, so the exact error counts move with upstream
releases — the 131 includes rules selected by ruff's current defaults that an
older ruff would not report. Second, the `build` job is gated behind `lint`, so
packaging is currently never verified in CI even though it passes locally.

**Recommendation:** add explicit `[tool.ruff]` rule selection and pin
`ruff`/`mypy` to the versions that are then clean. Treating "whatever ruff's
defaults are today" as the standard makes the gate a moving target that fails
for reasons unrelated to the code.

---

## 3. MEDIUM — 22 of the tree's uncommitted files would be committed in one sweep

`git add .` would stage 20 modified files plus `opencode.json`, `uv.lock`,
`scripts/seed_sweep.py`, `tests/test_seed_sweep.py`, ADR-0007, ADR-0008 and the
whole `docs/audit/` directory. The uncommitted work is coherent and worth
keeping (see `PROJECT_STATE.md`), but the security finding above makes the
absence of a staging discipline a live risk rather than a tidiness issue.

**Recommendation:** add `opencode.json` to `.gitignore`, then commit in logical
slices with the audit documents first.

---

## 4. MEDIUM — Repository URLs point at a non-existent organisation

`README.md` (2 refs), `docs/index.html` (12 refs) and `pyproject.toml` (2 refs,
under `[project.urls]`) all reference `github.com/contested-nav/contested-nav`.
The actual repository is `github.com/Telschow/contested-nav`. The badge URLs
point at a different account, so the CI and Pages badges cannot resolve and
`pip install`'s project links are wrong.

`uv.lock` contains 100+ `pypi.org` and `files.pythonhosted.org` URLs. These are
expected and correct for a Python lockfile; they are not private information.

**Recommendation:** update the 16 references and add a repo-identity check to CI.

---

## 5. LOW — Personal email in Git history (expected, not a leak)

All 4 commits are authored by a single author whose commit email is a personal
address. No `.mailmap` is present, so GitHub will not link these commits to a
profile. This is normal for a solo project and is not a leak.

**Amended 2026-09-29:** the original finding recommended leaving history
unchanged. That advice is withdrawn. The author has since stated that a personal
email address must not be published, and the same address is still present in
commit metadata, so publishing this history as-is would publish it. Two
follow-ups are now required, and neither is a code change:

1. Add a `.mailmap` and use a GitHub-provided `noreply` address for all future
   commits, so the address stops appearing in new objects.
2. Decide, before any push, whether to publish a sanitized history. A history
   rewrite is destructive and needs explicit approval; it has not been
   performed. Until it is, this repository must not be pushed.

No other personal data, no `Co-authored-by` trailers, and no employer-internal
information were found. The only machine-specific absolute path in a tracked
file was in this document's own scope line and has been removed. A local
credential file at `opencode.json` sits outside version control by design; see
`SECURITY.md`.

---

## 6. LOW — No `.env`, key, or credential files, and none in history

Searched the working tree and all commits for `.env*`, `*.pem`, `id_rsa*`,
`.netrc`, `credentials*`, `*.key`, plus AWS (`AKIA…`), GitHub (`ghp_…`) and
OpenAI (`sk-…`) token patterns: no matches. There is no `Dockerfile`, no
container config, and no deployment configuration to leak credentials.

The `.github/workflows/pages.yml` `id-token: write` permission is the standard
GitHub OIDC grant for Pages deployment, not a stored secret.

---

## 7. Information verified as safe to publish

- `LICENSE` is MIT, with a placeholder copyright holder. Confirm the holder name
  before publishing.
- `README.md` states plainly and prominently that **all results are synthetic**,
  that no real sensor capture is vendored or evaluated, and that no number is a
  field measurement. This is the single strongest publication asset here and
  should not be softened.
- The requirements document records that only one of three operational user needs
  passes in full, and marks the others `PARTIAL`, `NOT MET`, `NOT VERIFIED` and
  `CONTRADICTED`. A public repository that publishes its own unmet requirements
  is far more credible to a technical reviewer than one that claims completeness.
- No third-party datasets are vendored. `TUM VI` and `EuRoC` are referenced by
  name as things a user must fetch locally, which is correct attribution and
  avoids redistributing licensed data.

---

## 8. Pre-publication checklist

| # | Item | Severity | Status |
|---|---|---|---|
| 1 | `opencode.json` API key not gitignored | CRITICAL | open |
| 2 | Rotate the exposed token | CRITICAL | open |
| 3 | CI lint gate red (131 ruff, 35 format, 15 mypy) | HIGH | open |
| 4 | Commit the 22-file uncommitted work in slices | MEDIUM | open |
| 5 | Fix 16 wrong-org GitHub URLs | MEDIUM | open |
| 6 | Pin `ruff`/`mypy`; declare explicit rule selection | MEDIUM | open |
| 7 | Verify CI status badges resolve after URL fix | LOW | open |
| 8 | Confirm LICENSE copyright holder | LOW | open |
| 9 | Consider `.mailmap` | LOW | optional |
| 10 | Add a secret-scanning workflow (e.g. `gitleaks`) | LOW | recommended |

Items 1 and 2 are prerequisites for publication. Item 3 is a prerequisite for
the portfolio framing, because a reviewer who sees a red badge on a repository
advertising a "measured, reproducible" discipline will reasonably doubt the rest.

**Nothing in this audit was published, pushed, or committed. No Git history was
altered. No file was deleted.**

---

## Status update — 2026-09-29 (portfolio hardening pass)

Appended after publication. Nothing above this line has been edited except the one
redaction noted here; the findings are a point-in-time record and are left as
written.

### The audit's own evidence became the leak

Item 1 was correct that `opencode.json` held a live key and that the file was not
gitignored. Both were fixed, in commit `df68ab1` and later hardening. What the
audit did not anticipate is that §1 quoted the key verbatim as evidence, at line
28. This document is tracked, so quoting the secret in it committed the secret.
The value was therefore published on `main`, and it is byte-identical to the key
still configured locally.

The quoted value has been replaced with `<REDACTED>`. The finding is unchanged:
the file held a credential, and the ignore rule was missing.

### Why the automated scanners did not catch it

`gitleaks` 8.28.0 reports "no leaks found" for the working tree and for all
published commits, and it is correct on its own terms. Its rules key on known
provider prefixes — `sk-`, `ghp_`, `AKIA` and similar. `freellmapi-` is a
self-hosted provider's token format and matches no rule, so a clean scan here
means "no *recognised* provider token", not "no credentials". Any conclusion of
the form "we scanned and it is clean" needs that qualifier.

### What remains, and it is manual

1. **Rotate the key.** This is the only action that actually closes the exposure.
   Redacting a published value limits who can find it by browsing; it does not
   invalidate it. Two commits contain the literal and will keep containing it for
   as long as history is intact: `fbeb429` and `d83e9ea`.
2. **Removing it from history** would need a rewrite, which this pass is
   instructed not to do, and which invalidates every published commit hash. It is
   worth doing only if the key is not rotated, and rotation makes it unnecessary.
3. **Close the scanner gap** by giving the secret scanner a rule for this token
   format, so the next self-hosted provider key is caught rather than waved
   through.
