# Security policy

## Supported versions

`main` is the only supported ref. This is a research library with no release
cadence, so there is nothing to backport a fix into.

## Reporting a vulnerability

Open a [private security advisory](https://github.com/Telschow/contested-nav/security/advisories/new)
rather than a public issue. Please include the commit SHA, the input or
configuration that triggers the problem, and the observed versus expected
behaviour.

You should get an acknowledgement within a week. This is a solo-maintained
repository, so a fix may take longer than a fixed SLA would imply; if the report
is severe enough that you would rather not wait, say so in the advisory and it
will be triaged first.

## What counts as a vulnerability here

- Code execution or arbitrary file access through a documented input path.
- A parser that trusts attacker-controlled input -- `read_euroc_imu` and the
  trajectory readers accept external files, so a malformed one is in scope.
- A measurement path that silently produces a plausible but wrong number. The
  project is an estimator whose output is evidence, so a silent numerical fault
  is treated as a correctness bug with security relevance, not a cosmetic one.
- An unfiltered third-party value in a generated result file.

## What does not

- Failure of the estimator on an outage it is documented to fail at. Underconfident
  or overconfident behaviour under GNSS denial is the measured subject of the
  project, not a bug; the docs distinguish the two cases deliberately.
- Anything requiring an API key or credential that a user supplies themselves.
  The repository ships no credentials and asks for none.

## Credential hygiene in this repository

- `opencode.json` is ignored in `.gitignore` because it carries a provider API
  key. Do not remove that rule, and do not commit the file under another name.
- CI runs with `contents: read` at the top level. The only job granted more is
  CodeQL, which needs `security-events: write` to upload its results.
- Third-party actions are pinned to full commit SHAs, with the release version in a
  trailing comment (`uses: owner/action@<sha> # v1.2.3`). A tag can be moved; a SHA
  cannot. Dependabot updates the SHA and the comment together.
- Dependabot tracks both GitHub Actions and pip, so an action or dependency
  update arrives as a reviewable pull request rather than silently.
- CodeQL analyses Python on push, pull request, and weekly.
- `.github/workflows/security.yml` runs on every pull request, on pushes to `main` and
  weekly:
  - a secret scan (`scripts/scan_secrets.py`) of the tracked files and of every line ever
    added to any ref, with a rule for the shape of the provider key this project once
    leaked;
  - dependency review on pull requests, failing on a high-severity advisory;
  - `pip-audit` of the installed dependencies against the PyPI advisory database;
  - a CycloneDX SBOM of the runtime dependencies, kept as a workflow artifact.

  The same scanner runs locally as a pre-commit hook and as `make secrets`. It finds
  well-known credential shapes; it will miss an arbitrary high-entropy string, so it is
  a tripwire and not a replacement for keeping credentials out of the tree.

## Known incident

A provider API key was committed in `docs/PUBLICATION_READINESS.md` on 2026-09-29
(commit `fbeb429`, as evidence in an audit), redacted on 2026-09-30 (`ccb812a`) and
rotated by the maintainer. The value is still readable in git history. History has not
been rewritten, because the key is revoked and a rewrite would invalidate every open
reference to the old commits. The secret scan lists this one finding as known and
accepted (`KNOWN_HISTORY` in the script) and fails on anything new.
