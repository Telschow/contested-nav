# TASK

Review branch `{{BRANCH}}` against its issue. Fix problems in place. Do not change behaviour.

# CONTEXT

Standards:

!`cat .sandcastle/CODING_STANDARDS.md`

Commits:

!`git log {{TARGET_BRANCH}}..{{BRANCH}} --oneline`

Diff:

!`git diff {{TARGET_BRANCH}}...{{BRANCH}}`

# CHECK

1. Does the diff match the intent? Edge cases covered by tests?
2. Does it break any rule in the standards above or in CLAUDE.md?
3. Any hand-typed measured number on a first-read page?
4. Any simplification that keeps behaviour exactly the same?

Do not re-read files that the diff already shows.

# ACT

If you change anything, run ruff, mypy and the tests for the touched files, then commit.

If the branch is clean, change nothing.

Output <promise>COMPLETE</promise>.
