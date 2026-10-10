# Scenarios

The benchmark is fifteen named cases in [`configs/benchmark.yaml`](https://github.com/Telschow/contested-nav/blob/main/configs/benchmark.yaml). They differ only in what is
degraded, so a difference between two rows is a difference in the scenario and not in the initial
conditions. Every case runs the same 30 s synthetic path at seed 0. The synthetic motion, the
sensor models and every configuration key are described in the [model reference](MODEL.md), and the
results are on the [Results page](results.md).

Run one with `navkit run --only <name>`; list them with `navkit run --list`.

## gnss_only

GNSS at 5 Hz, no outage, no vision. The reference every other case is read against. Its verdict is mixed rather than clean: mean NEES sits slightly above the expected value while no epoch leaves the 2-sigma ellipsoid.

**Configuration:** GNSS 5.0 Hz, sigma 0.8 m; vision off.

## dead_reckoning

Inertial integration with no aiding at all. Reported as the control for "how much of the result is the filter and how much is the motion model".

**Configuration:** GNSS off; vision off; estimator DeadReckoning.

## vision_anchor_in_measurement_noise

The pre-refactor arrangement, where the visual anchor error is folded into the measurement covariance. Retained as a regression control, not as a supported configuration.

**Configuration:** GNSS 5.0 Hz, sigma 0.8 m; vision 20.0 Hz, fused; anchor error folded into measurement noise.

## vision_only

Visual odometry at 20 Hz with no GNSS. In this fixture it is less accurate than dead reckoning and severely overconfident: nothing constrains the absolute pose, and the claimed uncertainty is far smaller than the error.

**Configuration:** GNSS off; vision 20.0 Hz, fused.

## outage_control

15 s GNSS outage, 5 s to 20 s, with vision off. The baseline for a contested receiver: the error grows and so does the claimed uncertainty, and coverage stays at or above nominal. The verdict is mixed because mean NEES is slightly above the expected value.

**Configuration:** GNSS 5.0 Hz, sigma 0.8 m; vision off; GNSS outage 5 s to 20 s.

## outage_visual

The same 15 s outage with vision on. Position error is lower than the control in this window, but the claimed uncertainty stays small and coverage collapses: accurate and confidently wrong. That is why vision_enabled defaults to false. The accuracy gain depends on when the outage starts (see the outage sweep); the overconfidence does not.

**Configuration:** GNSS 5.0 Hz, sigma 0.8 m; vision 20.0 Hz, fused; GNSS outage 5 s to 20 s.

## outage_visual_degraded_camera

Visual aiding through the outage with 30% of camera frames dropped in 1 s bursts. Checks whether an intermittent visual stream changes the result. It does not: the filter is still overconfident, with a smaller error than the clean case.

**Configuration:** GNSS 5.0 Hz, sigma 0.8 m; vision 20.0 Hz, fused; GNSS outage 5 s to 20 s; camera drop 30% in 1 s bursts.

## outage_visual_clone

The outage_visual scenario with the previous visual pose carried as a stochastic clone instead of a stored anchor. Same data, same seeds, same gate.

**Configuration:** GNSS 5.0 Hz, sigma 0.8 m; vision 20.0 Hz, fused; GNSS outage 5 s to 20 s; previous visual pose as a stochastic clone.

## outage_visual_degraded_camera_rereferenced

The degraded-camera scenario with every delivered measurement taken against the last delivered frame, and the single-anchor model. Separates the effect of the generator from the effect of the clone: the anchor is no better calibrated.

**Configuration:** GNSS 5.0 Hz, sigma 0.8 m; vision 20.0 Hz, fused, re-referenced to the last delivered frame; GNSS outage 5 s to 20 s; camera drop 30% in 1 s bursts; single anchor.

## outage_visual_degraded_camera_clone

The degraded-camera scenario with re-referenced measurements and the stochastic clone.

**Configuration:** GNSS 5.0 Hz, sigma 0.8 m; vision 20.0 Hz, fused, re-referenced to the last delivered frame; GNSS outage 5 s to 20 s; camera drop 30% in 1 s bursts; stochastic clone.

## vision_only_clone

Visual odometry at 20 Hz with no GNSS, with the stochastic clone. Nothing constrains the absolute pose, so the claimed uncertainty has to grow with the error and not stay small.

**Configuration:** GNSS off; vision 20.0 Hz, fused; stochastic clone.

## outage_visual_clone_outliers

The clone with 5% of visual frames carrying an error twenty times the nominal one, as with a wrong feature match. The chi-square gate rejects them and the filter stays calibrated.

**Configuration:** GNSS 5.0 Hz, sigma 0.8 m; vision 20.0 Hz, fused, 5% of frames with a twenty-fold error; GNSS outage 5 s to 20 s; stochastic clone.

## outage_visual_clone_scale_drift

The clone with a slowly drifting error of up to 10% on the translation scale, as monocular scale drifts. The inertial unit holds the metric scale, so the filter stays calibrated.

**Configuration:** GNSS 5.0 Hz, sigma 0.8 m; vision 20.0 Hz, fused, translation scale drifting up to 10% (correlation time 30 s); GNSS outage 5 s to 20 s; stochastic clone.

## outage_visual_clone_correlated

The clone with visual errors correlated over 2 s, as they are when consecutive frames share features. The clone assumes independent errors, so it is overconfident again. This is the case the clone does not survive.

**Configuration:** GNSS 5.0 Hz, sigma 0.8 m; vision 20.0 Hz, fused, errors correlated over 2 s; GNSS outage 5 s to 20 s; stochastic clone.

## outage_visual_clone_correlated_inflated

The same correlated errors with the filter told the visual noise is four times larger than the generator drew. Calibration is restored, at a cost in accuracy that still leaves the position error well inside the no-vision control's.

**Configuration:** As the previous case, with the filter assuming four times the visual noise; stochastic clone.
