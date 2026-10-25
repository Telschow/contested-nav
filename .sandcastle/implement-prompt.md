# TASK

Issue {{TASK_ID}}: {{ISSUE_TITLE}}. Branch {{BRANCH}}.

Read it with `gh issue view {{TASK_ID}}`. Work on this issue only.

Recent commits:

!`git log -n 5 --format="%h %ad %s" --date=short`

# METHOD

Read only the files the issue names and the tests next to them. Do not scan the repo. CLAUDE.md has the project rules.

Work test first. Write one failing test, make it pass, repeat. Then tidy.

# CHECKS

Run these before each commit:

1. `ruff check src tests scripts`
2. `ruff format --check src tests scripts`
3. `mypy src --ignore-missing-imports`
4. `python -m pytest -q -x` on the test files for the area you changed

Do not run the full suite. It takes 4 to 5 minutes and the merge step runs it once.

If you change benchmark output or a doc table, also run `navkit run --markdown` and `python scripts/check_doc_tables.py`.

# COMMIT

One commit per working step. Use a conventional subject, such as `feat(eval): ...` or `fix(fdir): ...`. In the body, write what changed and why, in a few short lines.

# STOP

If the issue is not done, comment on it with what was done. Do not close it.

When done, output <promise>COMPLETE</promise>.

Single task only.
