# Scenarios

The benchmark is seven named cases in [`configs/benchmark.yaml`](https://github.com/Telschow/contested-nav/blob/main/configs/benchmark.yaml). They differ only in what is
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
