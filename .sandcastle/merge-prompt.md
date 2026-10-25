# TASK

Merge these branches into the current branch, one at a time:

{{BRANCHES}}

For each: `git merge <branch> --no-edit`. On conflict, read both sides and resolve to keep both intents. Never force-push or rewrite history.

After the last merge, run once:

1. `ruff check src tests scripts`
2. `ruff format --check src tests scripts`
3. `mypy src --ignore-missing-imports`
4. `make docs-fast`

Do not run the full pytest suite. CI runs it on the pull request. Run each check in the foreground and wait for it. Do not start background watchers.

If something fails, fix it and rerun only what failed. If the doc tables or metric markers fail, regenerate them with the repo scripts. Do not type numbers by hand.

# ISSUES

Only when every check above passes, close each merged issue with `gh issue close <ID> --comment "Merged by Sandcastle; full tests run in CI on the pull request"`:

{{ISSUES}}

If any check still fails, close nothing and say which one failed.

Output <promise>COMPLETE</promise> when done.
