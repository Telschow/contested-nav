# Coding standards (review checklist)

Project rules live in CLAUDE.md and CONSTRAINTS.md. They load on their own. This file only lists what to check in a diff.

## Code

- NumPy only. No new runtime dependency.
- Quaternions are (w, x, y, z). Poses are T_wb. Covariance update is Joseph form.
- No third-party data is vendored.
- Every behaviour change has a test. A fix keeps the overconfident single-anchor control row.

## Writing

- No em dashes. Short sentences.
- No invented teams or owners.
- No hand-typed measured number or count on README.md, docs/index.md, docs/getting-started.md, docs/results.md or docs/status.md. Use the generated tables and markers.

## Decisions and safety

- `vision_enabled` stays False. A passing gate does not change it.
- An ADR gets created for a decision, but the decision section is left for the maintainer.
- No force-push, history rewrite, release tag, or deletion of a doc that other pages link to.
