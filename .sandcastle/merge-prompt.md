# TASK

Merge these branches into the current branch, one at a time:

{{BRANCHES}}

For each: `git merge <branch> --no-edit`. On conflict, read both sides and resolve to keep both intents. Never force-push or rewrite history.

After the last merge, run once:

1. `ruff check src tests scripts`
2. `ruff format --check src tests scripts`
3. `mypy src --ignore-missing-imports`
4. `python -m pytest -q`

If something fails, fix it and rerun only what failed. If the doc tables or metric markers fail, regenerate them with the repo scripts. Do not type numbers by hand.

# ISSUES

Close each merged issue with `gh issue close <ID> --comment "Completed by Sandcastle"`:

{{ISSUES}}

Output <promise>COMPLETE</promise> when done.
