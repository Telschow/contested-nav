# ISSUES

<issues-json>

!`gh issue list --state open --label Sandcastle --limit 20 --json number,title,body,labels --jq '[.[] | {number, title, body, labels: [.labels[].name]}]'`

</issues-json>

# TASK

Pick the issues that can be worked in parallel now.

Issue B is blocked by A if B needs code or a decision from A, or if A and B edit overlapping files. Do not pick blocked issues.

Never pick an issue that changes `vision_enabled`, a B1 gate decision, or an ADR decision section. Those belong to the maintainer.

An issue is also blocked if it names an ADR whose Decision section still says "To be written by the maintainer". Check with `grep -l "To be written by the maintainer" docs/adr/*.md`.

Branch name is exactly `sandcastle/issue-{id}`.

If every issue is blocked, pick nothing and emit an empty plan.

# OUTPUT

Emit only this, even when there is nothing to do:

<plan>
{"issues": [{"id": "42", "title": "Fix auth bug", "branch": "sandcastle/issue-42"}]}
</plan>

Use `<plan>{"issues": []}</plan>` when there is no work.
