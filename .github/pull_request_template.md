## Context

What problem does this solve, and where did it come from (an issue, an audit finding, a failing check)?

## Change

What changed, in a few lines. List any file or behaviour that moves a published number.

## How tested

The commands you ran and what they showed. For a behaviour-preserving change, say how you
know nothing moved (the golden snapshot, a byte comparison against `main`). For a claim about
speed or accuracy, give the measurement, not the adjective.

## Risks

What could go wrong, what you did not verify, and anything a reviewer should look at first.

## Checklist

- [ ] `make check` passes (ruff, ruff format, mypy, tests, coverage ratchet), or the equivalent commands in CONTRIBUTING
- [ ] Every number I quote in a doc comes from a command I ran; `scripts/check_doc_tables.py` still passes
- [ ] No `# noqa`, no new mypy error-code suppression, no skipped or weakened test
- [ ] A change to the filter or the fixture regenerates `tests/golden/benchmark.json` with the reason in the commit
- [ ] No credential, key or personal data in the diff
- [ ] Conventional Commit title; one logical change
