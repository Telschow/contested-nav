# Prioritisation

How the Phase 5 backlog was ordered, and how much to trust the order.

## Method

Each candidate gets a RICE score: **reach x impact x confidence / effort**. The inputs are
in [`product_management/rice.csv`](product_management/rice.csv). The table below is generated
from that file by `scripts/rice_table.py`, and a test fails if the two disagree.

**These inputs are judgements, not measurements.** Nothing here was timed or counted except
where the rationale cites a file size or a code location. The point of writing them down is
that they can be argued with.

| Input | Scale | Meaning in this project |
|---|---|---|
| Reach | 1 to 10 | How much of the repository's evidence the item touches. 10 changes the headline result or every case; 5 several cases or a major claim; 2 one case or one document. |
| Impact | 0.25, 0.5, 1, 2, 3 | How much it improves what a reviewer can trust or reproduce. 3 is massive, 0.25 is minimal. |
| Confidence | 50%, 80%, 100% | How sure I am of the reach, impact and effort together. 50% means the approach itself is unproven. |
| Effort | ideal working days | One engineer, including tests and docs. My estimate, grounded where possible in the size of the code it touches. |

A tie is broken by the lower effort, then by the id.

## Ranking

<!-- rice:start -->

| Rank | ID | Item | Reach | Impact | Confidence | Effort (days) | Score | Depends on |
|---:|---|---|---:|---:|---:|---:|---:|---|
| 1 | P5-01 | Noise-mismatch robustness sweep | 8 | 2 | 80% | 5 | 2.56 | none |
| 2 | P5-02 | Benchmark the fault matrix with detection and false-alarm rates | 6 | 2 | 80% | 8 | 1.20 | none |
| 3 | P5-08 | Check the SRS traceability matrix with a script | 4 | 1 | 80% | 3 | 1.07 | none |
| 4 | P5-07 | Sensor synchronisation and calibration specification | 3 | 1 | 80% | 3 | 0.80 | none |
| 5 | P5-04 | Wire the inert bias sigmas and add velocity process noise | 5 | 1 | 80% | 5 | 0.80 | none |
| 6 | P5-03 | Fix visual overconfidence structurally (multi-anchor or sliding window) | 10 | 3 | 50% | 21 | 0.71 | none |
| 7 | P5-05 | Rename the per-second drift keys to per-square-root-second with an alias | 2 | 0.5 | 100% | 2 | 0.50 | P5-04 |
| 8 | P5-09 | Rewrite the baseline records and fix stale statements | 3 | 0.5 | 100% | 3 | 0.50 | none |
| 9 | P5-11 | Comparison against an established consistent estimator | 8 | 2 | 50% | 21 | 0.38 | P5-03 |
| 10 | P5-06 | Accelerometer-bias falsification experiment | 3 | 1 | 50% | 5 | 0.30 | P5-04 |
| 11 | P5-12 | Housekeeping: review Dependabot 5, decide on uv.lock, close stale PR 34 | 1 | 0.25 | 100% | 1 | 0.25 | none |
| 12 | P5-10 | Release hygiene: provenance attestation and digest-pinned base image | 3 | 0.5 | 80% | 5 | 0.24 | none |
| 13 | P5-13 | Documented fetch path for the TUM VI reference data | 2 | 0.5 | 50% | 3 | 0.17 | none |

### Why each item scored as it did

- **P5-01, Noise-mismatch robustness sweep.** Source: MODEL.md finding 5. Every calibrated result assumes the filter is told the true sensor noise. Mismatch is not exercised by any case. The sweep pattern already exists (outage_sweep.py is about 200 lines) and the filter sigmas are set in one place (benchmark.py).
- **P5-02, Benchmark the fault matrix with detection and false-alarm rates.** Source: Track A exit test; FMEA-lite gaps. Spoofing, slow GNSS bias, IMU loss, timestamp offset and vision outages are injectable but unit-tested only. Measuring them closes the biggest gap in the FMEA-lite table. The modest-offset-after-outage spoof case is a known open problem, so scope is measure and report, not fix.
- **P5-08, Check the SRS traceability matrix with a script.** Source: Track C exit test. The matrix can drift today. A script that fails CI when a requirement names a missing test turns it into a checked claim, which is the pattern this repository already uses for tables.
- **P5-07, Sensor synchronisation and calibration specification.** Source: Track C. Documentation. The timing model and what is measured versus assumed. Feeds P5-02 (timestamp offset). Done: docs/product_management/04_sensor_sync_and_calibration_spec.md, with timing measured on the recordings.
- **P5-04, Wire the inert bias sigmas and add velocity process noise.** Source: MODEL.md findings 1 3 4. Correctness hygiene. Moves the golden snapshot, so it needs a deliberate regeneration and a review of every published number. Done: the velocity process noise (ADR-0014) and the inert bias sigmas (ADR-0015).
- **P5-03, Fix visual overconfidence structurally (multi-anchor or sliding window).** Source: Blocker B1; L2. Changes the headline result, but the formulation is undecided, ADR-0003 deferred it, and the exit gate (NEES below 10, coverage above 90%) may not be reachable with a NumPy-only filter.
- **P5-05, Rename the per-second drift keys to per-square-root-second with an alias.** Source: MODEL.md finding 2. Units bug in names only. Breaking for configs unless an alias is kept. Done: the new names are anchor_pos_drift_sigma_m_sqrt_s and anchor_rot_drift_sigma_deg_sqrt_s, and the old names are accepted with a warning.
- **P5-09, Rewrite the baseline records and fix stale statements.** Source: Phase 4 decision 2. The records that predated the work were deleted. The eskf.py module docstring still quotes an old measurement.
- **P5-11, Comparison against an established consistent estimator.** Source: L3. Needs an external reference implementation and a scene export, which strains the zero-dependency rule (S1).
- **P5-06, Accelerometer-bias falsification experiment.** Source: L8. Cannot be run honestly while the bias sigma fields are inert. Done: docs/attribution.md. The hypothesis that accelerometer bias dominates the outage error is falsified on the synthetic fixture.
- **P5-12, Housekeeping: review Dependabot 5, decide on uv.lock, close stale PR 34.** Source: Phase 4 open items. Small but leaves no stale items on the board.
- **P5-10, Release hygiene: provenance attestation and digest-pinned base image.** Source: ADR-0011 gaps. Closes the not-done list in ADR-0011 before a tagged release.
- **P5-13, Documented fetch path for the TUM VI reference data.** Source: B4; L9. Two tests skip without it. Must not vendor the data (S2).

### How stable the ranking is

Top 3 by score: P5-01, P5-02, P5-08.

I perturbed one input of one item at a time (69 perturbations: effort doubled or halved, impact and confidence moved one step). The top 3 set changed in 12 of them.

Perturbations that change the set:

- P5-02 effort x2
- P5-02 impact 1
- P5-02 confidence 50
- P5-03 effort x0.5
- P5-03 confidence 80
- P5-04 effort x0.5
- P5-04 impact 2
- P5-07 effort x0.5
- P5-07 impact 2
- P5-08 effort x2
- P5-08 impact 0.5
- P5-08 confidence 50

<!-- rice:end -->

## What this ranking does not say

- It ranks the cheapest evidence first. The structural fix for visual overconfidence (P5-03)
  has the largest reach and impact in the table and still ranks sixth, because its
  confidence is low and its effort is high. That is the intended behaviour of the method, and
  it is also its blind spot: a score cannot see that one item is the reason the project exists.
- Dependencies are in the table. An item that depends on another cannot start before it.
- Items that change the golden snapshot (P5-04) need a deliberate regeneration and a review of
  every published number, which the score does not price in.

## Not scored

- A throwaway pull request that fails a quality gate on purpose, to show branch protection
  blocking the merge. It is a demonstration, not a feature, and needs the owner's approval.
- Latency compensation. It is not worth designing until P5-02 measures what a timestamp offset
  actually does to the filter.

## Open issues, October 2026

Scored on 24 October 2026 with the scales above. The audit boost multiplies Impact by 1.5 for issues that close a finding of the 24 October docs audit. Each issue carries the same numbers in its own `## RICE` section, and the issue is the source if the two differ. These are judgements, not measurements. The table lists the open contested-nav issues; P5-03 and P5-11 keep the scores above.

| Issue | Item | Reach | Impact | Audit boost | Confidence | Effort (days) | Score |
|---|---|---:|---:|---|---:|---:|---:|
| #197 | Docs audit: one B1 status phrase, FAQ coverage wording | 10 | 1 | x1.5 | 80% | 0.5 | 24.00 |
| #168 | Re-measure the start-attitude-draw study on the corrected fixture, as a generated CSV | 6 | 1 | x1.5 | 80% | 1 | 7.20 |
| #165 | Integrity status record: a per-epoch output for downstream decision logic | 8 | 2 | none | 80% | 2 | 6.40 |
| #188 | Select docs-only tests by pytest marker, not a hand-kept list in CI | 2 | 1 | none | 80% | 0.5 | 3.20 |
| #183 | Show the innovation gate is blind to slow, correlated GNSS error (synthetic) | 6 | 1 | none | 80% | 2 | 2.40 |
| #166 | Dead-reckoning horizon: time until the claimed bound exceeds an alert limit | 6 | 2 | none | 50% | 3 | 2.00 |
| #190 | Compare the run-record summary helpers across the sweeps | 2 | 0.25 | none | 80% | 0.25 | 1.60 |
| #193 | Remove the old page and CSV helper copies and forbid new ones | 2 | 0.5 | none | 80% | 0.5 | 1.60 |
| #182 | UrbanNav: commit the scratch sanity checks as generated rows | 4 | 1 | none | 80% | 2 | 1.60 |
| #181 | Integrity status record v2: staleness of the NIS windows | 4 | 1 | none | 50% | 1.5 | 1.33 |
| #119 | Consolidate overlapping documentation pages | 4 | 0.5 | none | 80% | 1.5 | 1.07 |
| #131 | UrbanNav follow-up: Deep-Urban-1 rows and the INSPVAX decision (left over from #95) | 4 | 1 | none | 80% | 3 | 1.07 |
| #118 | Protection level from the calibrated covariance | 6 | 1 | none | 50% | 3 | 1.00 |
| #189 | Generated-page module: one place for splice, table and CSV, with mismatch_sweep moved onto it | 2 | 0.5 | none | 80% | 1 | 0.80 |
| #191 | Move the splice and table studies onto the generated-page module | 2 | 0.5 | none | 80% | 1 | 0.80 |
| #192 | Move the remaining CSV-writing studies onto the generated-page module | 2 | 0.5 | none | 80% | 1 | 0.80 |
| #186 | UrbanNav: start alignment versus gyro bias in the attitude NEES excess | 4 | 0.5 | none | 80% | 2 | 0.80 |
| #117 | Camera-IMU extrinsic and time-offset sensitivity | 4 | 1 | none | 50% | 3 | 0.67 |
| #184 | Run Deep-Urban-1 with a correlated-error GNSS model | 4 | 1 | none | 50% | 3 | 0.67 |
| #185 | Imposed outages on Deep-Urban-1 | 4 | 1 | none | 50% | 3 | 0.67 |
| #194 | Extract the shared run-record summary module, if the comparison supports it | 2 | 0.5 | none | 50% | 1 | 0.50 |
| #116 | Covariance intersection as a visual-update baseline | 4 | 1 | none | 50% | 5 | 0.40 |
