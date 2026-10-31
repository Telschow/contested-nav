# ADR-0039: pytest-xdist in the dev extra

- Status: proposed
- Date: 2026-10
- Related: [ADR-0011](0011-ci-and-supply-chain.md), S1 in `CONSTRAINTS.md`

## Context

The test step of each pull request job runs the suite in one process and takes 36 to 46 minutes. Public-repository runners have 4 vCPU on `ubuntu-latest` and `windows-latest`, and 3 vCPU on `macos-latest`. The suite uses one.

S1 constrains runtime dependencies only. The `dev` extra is not runtime. S1 does say no `pytest-cov`, because coverage is measured by the project's own tracer. `pytest-xdist` does not measure coverage and does not change the count markers.

## Options

(a) Leave the suite serial. Rejected: the wall-clock cost is the largest part of the CI time.

(b) Add `pytest-xdist` to the `dev` extra. Run the plain test legs with `-n auto --dist loadfile` (`-n 3` on macOS). The coverage leg stays serial.

(c) Split the suite across more jobs. Rejected for now: it adds required check names.

## Decision

To be written by the maintainer.

## Consequences

To be confirmed with the decision. If (b) is chosen:

- One new dev dependency. The runtime dependencies stay numpy, matplotlib and pyyaml.
- `loadfile` keeps each file on one worker, so module-scoped fixtures are built once per file.
- A test that fails only under xdist is a bug in the test or the code, not a reason to skip it.
- The CI lines print `--durations=25`, so the next measurement needs no change.
