# ADR-0006: NIS window monitor with adaptive covariance inflation

- Status: accepted
- Date: 2026-09
- Closes: B5 in `CONSTRAINTS.md`
- Builds on: ADR-0005 (chi-square gating), ADR-0002 (Joseph form)

## Context

ADR-0005 made the filter's rejections honest by giving them a false-alarm
rate and a memory. Applying it to the benchmark exposed a defect that the
gate could not fix, because the gate was not what was wrong.

With GNSS denied for 15 s, the filter dead-reckons. Its position covariance
collapses along with the visual anchor error it never modelled. When GNSS
returns, the healthy fixes produce innovations that are enormous against that
collapsed covariance, and the gate — correctly, given its premise — rejects
them. The filter then dead-reckons the rest of the run while a working sensor
shouts at it.

Measured: 51 of 75 fixes rejected, ATE 5.059 m, mean NEES 1996.5 against an
expected 3, 16.0% coverage. The filter was confidently wrong while being
useless.

The rejection is not a bug in the arithmetic. `d² = yᵀ S⁻¹ y` with
`S = H P Hᵀ + R` is correct, and the threshold is right for the covariance it
was given. The premise is wrong: the covariance is not calibrated, so a
correctly computed gate has nothing true to be strict about.

Two things follow, and they pull in opposite directions.

**The filter is at fault here.** It went blind, so it should not hold its
position as tightly as it claims to.

**The sensor is not.** Those fixes are correct. Rejecting them is a filter
error, not a sensor fault, and isolating the channel makes it worse.

So the fix cannot be a wider gate. A wider gate is the same decision with a
larger number attached, and it costs the false-alarm rate ADR-0005 was written
to establish — it would admit the sustained spoof that the whole subsystem
exists to catch.

The distinction that makes it decidable is not the size of the innovation. It
is whether the channel was silent. Silence is observable, comes from the
filter's own state, and needs no assumption about the threat model. A channel
that has been streaming at 5 Hz has not been starved, so an innovation it now
produces is not something a covariance grown by its own outage explains.

## Decision

- Add `fdir/nis_monitor.py`: a bounded per-channel window of
  `(d², accepted)` pairs, and `is_persistent_divergence`, which reads a
  trailing run of `consecutive_rejection_threshold` rejections rather than a
  count. A count cannot distinguish consecutive failures from a 90% rejection
  rate; a trailing run can, and the difference is what the second pass turns on.
- `FdirManager.evaluate_and_adapt` gates as before, then, only if the monitor
  reports a trailing run, re-gates under an inflated covariance. The first
  gate is unchanged: a rejection is a rejection, and one bad sample buys
  nothing.
- Inflate the state block the measurement actually constrains, and recompute
  `S' = S + H ΔP Hᵀ`. That is not an optimisation — it is exactly the `S` the
  estimator will have once it honours the decision, because `S = H P Hᵀ + R`
  and the inflation adds to `P` only. Deriving it the other way would need `R`
  from the caller too, and would leave two chances for the re-gate and the
  fusion to disagree.
- Bound the grant three ways, because each one closes a hole the other two
  leave:
  - **By the factor cap** — `max_inflation_factor`, so no innovation, including
    a non-finite one, buys unbounded covariance.
  - **By the drift bound** — at most `max_drift_sigma_mps` of sigma per second
    of the channel's longest single silence. A stream at 5 Hz has 200 ms of
    silence and so has almost no budget, however long the attack runs. This is
    the property that separates a genuine outage from a sustained spoof, and it
    is the reason the budget is measured from the longest *gap* rather than
    from elapsed time.
  - **By the re-gate** — the inflated innovation must pass with headroom, not
    merely pass. A second pass that only has to reach the line is one rounding
    step from reintroducing the original failure.
- Apply at most one grant per divergence episode. A filter that can re-inflate
  indefinitely is a filter walking itself onto whatever the measurements say.
- **Only a genuine outlier is eligible for relief.** The two ways a channel can
  be excluded both read `accepted = False` and are not the same thing: the
  numbers said the sample was impossible, or the numbers were happy and a
  declared fault is holding the channel out anyway. Only the first is evidence
  that the filter's own covariance is wrong.

  This distinction is load-bearing, and getting it wrong inverts the mechanism
  over the range an attacker would actually pick. A 1 m sustained spoof is not a
  1 m innovation for long: the filter is pulled toward it, the residual shrinks,
  and within a few epochs the innovation is comfortably *inside* the threshold.
  The gate is entirely happy. The channel is excluded by the fault it correctly
  declared — and a second pass that could not tell the two apart spent the drift
  budget on that exclusion, re-gated successfully, and moved the estimate 2.1 m.
  A 3 m spoof, whose innovation stays out of range, was refused. Measured
  before the fix: 1 m and 2 m each obtained a grant; 3 m and above obtained
  none.

  A fault is a security decision, and a 0.1 m drift budget must not be able to
  overturn one. `GatingDecision.outlier` carries the distinction. Both halves
  are pinned by test, because a test on a large offset alone passes against the
  broken code.
- Record the longest material silence per channel and reset the health counters
  across it. A run of 26 accepted updates accumulated before a 15 s denial says
  nothing about the first update after it, and carrying that count across is
  what let a healthy history wipe the drift budget on exactly the epoch that
  needed it.
- Grant inflation to the GNSS position block only. The units are metres per
  second of translational drift, and a metre-derived variance added to a
  radian block is a dimensional mistake that still yields a valid covariance —
  so nothing downstream would object. The visual blocks keep the gate ADR-0005
  gave them, unrelaxed, which is the conservative direction for a
  security-relevant channel.

## Consequences

- B5 closes. On the benchmark case: ATE 5.059 m to 2.541 m, rejections 51 to 5,
  mean NEES 1996.5 to 419.4. With 30% of camera frames dropped, 3.339 m to
  2.005 m and 931.4 to 264.8.
- **The blockage is not the same as calibration.** A 2.54 m error with 0.161 m
  claimed is still overconfident, and the coverage column still says so. What
  is resolved is the filter's refusal to hear a working sensor; what is not
  resolved is the modelled visual anchor error that made the covariance wrong
  in the first place. The two are separate defects and only one is closed.
- **The ATE column loses its accidental warning.** Before this change the
  dishonest aided case was also the inaccurate one, so sorting by error
  happened to separate them. Recovering the error put the dishonest filter
  back on top, and the table no longer flags it by itself. Ranking by error is
  not a calibration check; `CONSTRAINTS.md` now requires both columns.
- A sustained offset delivered continuously earns no drift budget, so it never
  becomes plausible. Verified at 1, 2, 3, 5, 10, 20, 40 and 100 m: zero grants
  throughout, and at 1 m and 2 m the channel escalates to a declared fault. The
  1 m and 2 m cases reject 49 and 60 fixes and then coast on the inertial
  solution, which is the intended trade: refusing a plausible-looking sensor is
  a smaller error than following it.
- The manager can be driven without `P` and `H` (as ADR-0005's tests do), in
  which case the second pass declines. The `REJECTED_PERSISTENT` label still
  applies, because it reports what the monitor observed rather than what the
  second pass could do with it.
- Cost is one trailing-run check per rejection and, on a grant, one 3×3
  recomputation. No new dependency.
- `STATUS_REJECTED_TRANSIENT` became `STATUS_REJECTED_SPOOF`. This is a policy
  name, not a diagnosis: the gate cannot distinguish multipath from a spoof
  from a miscalibrated filter, and ADR-0005 says so. The name records what the
  filter does — an unproven channel gets no relief — and the module docstring
  says the rest.

## Alternatives rejected

- **Widen the gate for reacquisition.** No measurement distinguishes it from
  the sustained spoof it must not admit, and it discards the false-alarm rate
  ADR-0005 exists to provide.
- **Reset `P` to a nominal covariance on the first rejected update after
  silence.** Simpler, and it is what a bank of pre-outage covariance would do.
  It needs the same silence evidence but spends the whole covariance on one
  epoch, discarding what the filter had actually learned, and it has no bound
  on what "nominal" is.
- **Trust the sensor on return, unconditionally.** This is the failure mode
  in the other direction, and it is the one an attacker actually wants.
- **Inflate the full 21×21 state.** Valid covariance, wrong filter: a position
  innovation would make the filter suddenly unsure of its own gyro bias.
- **Apply the metre-based bound to the visual blocks.** Dimensionally wrong in
  a way no test would catch, and the visual channels are the ones where
  relaxing protection is most expensive.

## Follow-up

- The modelled visual anchor error is the remaining cause of the NEES gap, and
  is tracked separately in `CONSTRAINTS.md`. B5's closure is not a claim that
  the aided case is calibrated.
- `reacq_sigma_m` and `max_drift_sigma_mps` were chosen from the benchmark's
  own outage length and drift rate, not from a target error budget. They are
  numbers that can be argued with, which is why they are named in
  `FdirConfig` rather than hard-coded, and why the ADR records them.
