# TASK

Merge these branches into the current branch, one at a time:

{{BRANCHES}}

For each: `git merge <branch> --no-edit`. On conflict, read both sides and resolve to keep both intents. Never force-push or rewrite history.

After the last merge, run once:

1. `ruff check src tests scripts`
2. `ruff format --check src tests scripts`
3. `mypy src --ignore-missing-imports`
4. `make docs-fast`

Do not run the full pytest suite. CI runs it on `main` after the push. Run each check in the foreground and wait for it. Do not start background watchers.

If something fails, fix it and rerun only what failed. If the doc tables or metric markers fail, regenerate them with the repo scripts. Do not type numbers by hand.

# PUSH

`main` rejects pushes from this sandbox (403), so deliver through a pull request. Only when every check above passes:

1. `git fetch origin`
2. `git merge origin/main --no-edit`. If this brings in changes, rerun the four checks.
3. `git push origin HEAD` (the current branch, never `main`)

Never force-push and never rewrite history. If the push is rejected, fetch, merge `origin/main` once more and try once more. If it is rejected again, stop and say so.

# PULL REQUEST

1. Look for an open PR from the current branch: `gh pr list --head "$(git branch --show-current)" --state open --json number`.
2. If none, create one with `gh pr create --base main --title "<short summary of the merged work>" --body-file <file>`. If one exists, update its body with `gh pr edit <number> --body-file <file>`.
3. The body lists the merged branches and the checks that passed, and has one line `Closes #<ID>` per issue below. GitHub closes the issues when the PR merges, so do not run `gh issue close`.
4. Try `gh pr merge <number> --merge`. If it is refused (required checks pending, no permission), leave the PR open and say so. Do not use `--admin` and do not wait for CI.

Issues:

{{ISSUES}}

If any check or the push failed, create no PR and say which step failed.

Output <promise>COMPLETE</promise> when done.
