# Limitations and path to real systems

A note, not an implementation. A ROS integration is out of scope for this repository
([ROADMAP](../ROADMAP.md)), so nothing below exists as code. It records where the gap
between this simulator and a real system sits, and what a bridge would have to do, so
that the gap is visible before anyone builds on the numbers. The full list of
limitations is in [defense/LIMITATIONS.md](defense/LIMITATIONS.md); this page maps them
to concrete interfaces and does not repeat them. The model the code implements is in
[MODEL.md](MODEL.md).

## What the repository shows, and does not

It shows one reproducible result on a synthetic fixture: with GNSS denied, visual
aiding can make a navigation filter more accurate in position while its reported
uncertainty becomes badly wrong. It is a tool for measuring that, not a navigation
system.

It does not show performance on any real sensor, a comparison with an established
consistent estimator, or an integrity guarantee (limitations L1, L3, L4).

## Where the sim-to-real gap sits

| Assumption in the simulator | Real systems | Consequence for the numbers |
|---|---|---|
| Ground truth is an analytic trajectory; the filter starts exactly at it | Truth comes from a motion-capture or survey rig with its own error; the filter must find its own initial attitude, gravity direction and biases | Every error here is the estimator's. A real run adds an initialisation error this fixture cannot produce (L1) |
| IMU noise is white noise plus a bias random walk | Bias instability, temperature drift, scale-factor and axis misalignment, vibration response | Accelerometer bias faults are not tested (L8). The `*_bias_sigma` keys in the model do nothing |
| The filter is told the true GNSS and vision noise | Noise is unknown and non-stationary | The benchmark has no mismatch case; calibration under mismatch is unmeasured |
| Vision is a relative pose with Gaussian noise, generated from the truth | A front end produces failures that depend on the scene: texture loss, blur, repeated structure, scale ambiguity | The camera is a noise source, not a vision pipeline. The overconfidence result is about the filter's treatment of the anchor, and says nothing about real imagery |
| GNSS is a position with Gaussian noise and a clean binary outage | Receivers report geodetic position with their own covariance, multipath, partial degradation, jamming and spoofing | Interference is binary; plausible-but-wrong fixes are tested in unit tests only (L6) |
| Timestamps are exact and measurements are applied at the next IMU tick | Clocks drift, sensors are triggered at different times, latency varies | There is no latency compensation, and timestamp offsets have no benchmark case |
| Offline replay of a finished stream | Online, bounded latency and memory | The code is synchronous and has no wall-clock budget |

## How the interfaces would map to ROS 2

The mapping is a proposal. The standard message types below exist; whether each field
suffices has not been checked against any driver.

| Repository object | ROS 2 side | What the bridge has to do |
|---|---|---|
| `ImuSample` (200 Hz in the benchmark) | `sensor_msgs/msg/Imu` | Convert frames and signs: this code puts gravity at `(0, 0, +9.80665)` and expects an accelerometer at rest to read about `-9.80665` on z, which is the opposite sign of the z-up convention used by REP 103. Use header stamps as the time base |
| `GnssFix` (local metric position) | `sensor_msgs/msg/NavSatFix` | Convert latitude, longitude and altitude to a local metric frame; the repository has no geodetic conversion. Map the reported covariance to the filter's sigma instead of a fixed constant |
| `VisionUpdate` (relative pose, `R_rel`, `t_rel`) | `geometry_msgs/msg/PoseWithCovarianceStamped` or a visual-odometry `nav_msgs/msg/Odometry` | The filter wants the relative pose between consecutive frames and a per-block covariance. A front end that publishes absolute poses needs differencing and a covariance model |
| `EstimatorResult` (pose, `position_cov`) | `nav_msgs/msg/Odometry` | Emit the pose and the 6x6 covariance at the IMU rate; the repository only reports the position block |
| FDIR counters and events (`stats`, `fdir_events`) | `diagnostic_msgs/msg/DiagnosticArray` | Publish channel status (accepted, rejected, faulty, locked out) as diagnostics. The filter says "this channel is faulty", not why (L7) |

The filter itself is a batch function today: `ErrorStateKalmanFilter.run` takes whole
streams and returns whole trajectories. Its steps (`_propagate`, `_gnss_update`,
`_vision_update`) are private. A node needs an incremental interface, which means
promoting those to a public, tested API and deciding how to order late or out-of-order
messages. That is a design task, not a wrapper.

## What would have to change before real data

In rough order of how much each would change the conclusions:

1. **A consistent visual fusion.** The central finding is that single-anchor relative-pose
   fusion is overconfident under GNSS denial. A real-data evaluation of this filter would
   reproduce a known failure. Established remedies are listed in LIMITATIONS L2.
2. **A real capture with ground truth.** The IMU reader (`read_euroc_imu`) and trajectory
   reader (`read_trajectory`) exist and the TUM VI checks skip without the data. No
   dataset is vendored, by design.
3. **Initialisation.** Estimate initial attitude and biases from the first seconds of
   data instead of starting at the truth.
4. **Extrinsics and time offsets.** IMU to camera calibration and a time-offset estimate;
   the model currently has neither.
5. **Measurement-noise handling.** Estimate or adapt the noise instead of being told it,
   and measure calibration under mismatch.
6. **An integrity target.** A protection level and alert limit derived from a fault
   model (L4).

## Consistency with LIMITATIONS.md

L1 to L8 are referenced above and not restated. Two statements in
`defense/LIMITATIONS.md` need a qualifier. L5 lists outage start time and duration as
not varied; the outage sweep (`navkit sweep outages`) varies both. L6 says there is no
multipath; the GNSS model has a Gauss-Markov bias surrogate (`multipath_sigma_m`),
which no benchmark case enables. Neither file is edited here, to keep this change to
new documents.
