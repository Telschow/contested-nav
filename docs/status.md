# Status and limits

- **Not field validated.** The benchmark is a synthetic fixture. Recorded IMU data
  ([EuRoC](euroc.md), [TUM VI](tumvi.md)) and one set of real camera frames
  ([a real front end](real_front_end.md)) are used with GNSS simulated from the ground truth. None of that
  data is vendored, and no number is a field measurement.
- **Visual aiding under GNSS denial is untrustworthy with the shipped single anchor**, and disabled by default.
  See [concepts](concepts.md#the-one-thing-this-cannot-do). The opt-in stochastic clone
  ([ADR-0017](adr/0017-stochastic-clone-for-the-visual-update.md)) is calibrated for independent visual errors.
  Against the measured errors of a real two-view front end it stays inside the gate only with the assumed
  noise inflated by four, in all six windows measured, which is a named opt-in setting
  ([ADR-0023](adr/0023-clone-against-a-measured-front-end.md), [ADR-0024](adr/0024-assumed-noise-for-the-opt-in-clone.md)).
- **FDIR detects implausible updates and can name only some causes.** The chi-square gate in `fdir/` isolates a
  channel and says how long it was out ([ADR-0005](adr/0005-chi-square-fdir-gating.md)). A multipath call exists as
  a function ([ADR-0022](adr/0022-multipath-signature.md)). Spoofing and degradation are called correctly
  in most injected runs, weak faults are missed and the false-alarm rate is not zero; the rates are on the
  [fault classification](fault_classification.md) page
  ([ADR-0021](adr/0021-fault-classification-from-innovations.md)).
- **A slow-ramp spoof is followed.** With an IMU and GNSS alone the filter follows a ramp of any rate tested
  ([ADR-0019](adr/0019-slow-ramp-spoofing.md)). A simulated visual source catches a fast ramp when its errors are
  independent ([ADR-0020](adr/0020-second-source-against-a-ramp.md)).
- **The calibrated-covariance failure is mitigated, not fixed.** The ADR-0005
  gate assumed a calibrated innovation covariance the filter does not have once
  position covariance has collapsed, and in `outage_visual` that cost accuracy. That was blocker B5, closed by
  [ADR-0006](adr/0006-nis-window-monitor.md): a per-channel NIS window plus
  adaptive GNSS covariance inflation, which re-gates a returning fix once
  under an inflated covariance. The ATE and the number of rejected fixes both fell, with the false-alarm
  rate unchanged (R2 in [CONSTRAINTS.md](https://github.com/Telschow/contested-nav/blob/main/CONSTRAINTS.md)
  records the figures at the time). B1 is still open, see below.
- **The filter is still overconfident under visual aiding.** Over the GNSS outage window, `outage_visual`
  has a mean NEES of <!-- metric:outage_visual_window_nees -->478.6<!-- /metric --> against a nominal 3 and a
  2σ coverage of <!-- metric:outage_visual_window_coverage_percent -->0.0<!-- /metric -->% where the SRS requires
  95% (AC-04) and the roadmap gate for turning vision on is above 90%. The full-run values are in the table in
  the [README](https://github.com/Telschow/contested-nav/blob/main/README.md). It converges and
  is confidently wrong. This is blocker B1, and it is a pose-graph problem that
  no threshold in the FDIR subsystem will move. In the sweeps it held across 10 noise seeds and
  across all 8 scenes (see the dated note on the sweeps below).

- **ADR-0008 frozen-anchor cross-check: implemented but unreachable under the
  current state-transition logic; the security gap remains documented as open.**
- **The published numbers are single draws.** A 10-seed sweep showed the NEES varying
  by large factors between cases, and the two controls
  (`gnss_only`, `outage_control`) flip verdict across seeds, and `outage_control` is
  never clean in 10 draws. The shipped tables remain the seed-0 benchmark, which
  is the committed artefact; treat the magnitudes as order-of-magnitude and the
  verdicts as the claim.
- **Provenance of the sweep results.** The seed, scene and outage sweeps below were last measured at
  2026-10-09, before the attitude reset fix (R6 in
  [CONSTRAINTS.md](https://github.com/Telschow/contested-nav/blob/main/CONSTRAINTS.md)). Their outputs are not
  committed and were not re-run, so this page quotes their conclusions and counts, not their figures.
  `navkit sweep seeds`, `navkit sweep scenes` and `navkit sweep outages` regenerate them.
- **Scene generalisation is demonstrated, external validity is not.** The
  8-scene sweep varied trajectory geometry over a wide path-length range and all
  seven verdicts held, so the failure above is not a property of one path. What is
  *not* shown: any real capture, any measured sensor characteristic, or any scene
  outside an analytic trajectory generator. Eight synthetic scenes bound the
  claim "the anchor model is structurally wrong under visual aiding"; they do not
  bound its behaviour on real imagery. Scenario duration remains fixed at 30 s.
- **The outage window matters for accuracy, not for calibration.** The outage
  sweep (`navkit sweep outages`, 8 windows, 5 seeds each, one synthetic path)
  gave `outage_visual` a 2-sigma coverage far below its expected value and a mean NEES far above it in
  **all 40 runs**, including 5 s outages; `outage_control` stayed well covered in all 40. Accuracy is
  different. With the
  outage starting at 5 s, vision beats the control in all 5 seeds for 10 s, 15 s
  and 20 s outages and in 2 of 5 for 5 s. With the outage
  starting at 10 s, vision is **worse** than the control in all 20 runs. The cause is not tested here.
  So "vision improves ATE"
  is a property of the benchmark's early outage, not a general result.

  ![Outage sweep](figures/outage-sweep.png)
- **Not flight-ready.** No sensor driver, no live front end, no real-time loop,
  no failure-mode handling beyond a measurement gate.
- **Recorded-data checks skip without the data.** The trajectory reader's orientation is checked against the
  recorded gyroscope on every fetched sequence, and always on a synthetic one. The claim of reproducing a
  published TUM VI ATE was retired (R5 in `CONSTRAINTS.md`).
