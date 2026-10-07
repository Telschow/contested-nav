# Audit documents

| File | What it is | Status |
|---|---|---|
| [AUDIT.md](AUDIT.md) | Verified audit of the repository, 2026-10-06: scores, findings table, verification of the earlier GitHub audit, B1 feasibility | Current |
| [PLAN.md](PLAN.md) | Phased implementation plan for the findings in `AUDIT.md`, with decisions and acceptance criteria | Current |
| `01-` to `06-*.md` | An earlier audit round, 2026-09-29 | Point-in-time snapshots |

The `01-` to `06-` files record the repository as that audit found it, before the
remediation listed in [`CHANGELOG.md`](https://github.com/Telschow/contested-nav/blob/main/CHANGELOG.md). Their counts, line numbers
and findings are deliberately not updated (for example, 567 tests and 86.58% coverage),
so read them as history, not as the current state. For the current state, use
`AUDIT.md` and re-run the commands in its "Reproducing this audit" section.

They stay in this folder because other documents link to them by path
(ADR-0006, ADR-0008, `docs/PROJECT_STATE.md`, `docs/REPOSITORY_MAP.md` and others).
