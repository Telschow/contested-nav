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
- Workflows are pinned to major version tags. If you add a third-party action,
  pin it to a commit digest instead and say why in a comment.
- Dependabot tracks both GitHub Actions and pip, so an action or dependency
  update arrives as a reviewable pull request rather than silently.
- CodeQL analyses Python on push, pull request, and weekly.
