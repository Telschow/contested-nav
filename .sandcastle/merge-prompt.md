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

# PUSH

Only when every check above passes:

1. `git fetch origin`
2. `git merge origin/main --no-edit`. If this brings in changes, rerun the four checks.
3. `git push origin HEAD:main`

Never force-push and never rewrite history. If the push is rejected, fetch, merge `origin/main` once more and try once more. If it is rejected again, stop and say so. Do not close any issue after a failed push.

# ISSUES

Only when every check above passes and the push succeeded, close each merged issue with `gh issue close <ID> --comment "Merged by Sandcastle; full tests run in CI on the pull request"`:

{{ISSUES}}

If any check or the push failed, close nothing and say which one failed.

Output <promise>COMPLETE</promise> when done.
