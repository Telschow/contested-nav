# A second source against a slow-ramp spoof

[ADR-0019](adr/0019-slow-ramp-spoofing.md) found that an IMU and GNSS alone follow a slow ramp. A visual relative pose
measures motion between frames, not absolute position. A ramp whose velocity disagrees with it should show as a
growing GNSS innovation. This page repeats the [slow-ramp](slow_ramp.md) runs with a simulated visual source added.

## Method

The same runs as the slow-ramp study: recorded IMU (EuRoC, TUM VI), simulated GNSS, a ramp along world x from an
onset 35 s in, two arms (healthy before the onset, and after a 20 s outage), one seed, the calibrated bias walk. The
visual source is a surrogate generated from the ground truth, never images, fused by the stochastic clone
([ADR-0017](adr/0017-stochastic-clone-for-the-visual-update.md)). Two front ends:

- **Independent**: independent errors at the filter's assumed noise. This is the case the clone is calibrated for.
- **Correlated**: errors correlated over one second, with the filter's assumed visual noise four times larger. This is
  the setting ADR-0017 found by trial for correlated errors.

Columns are those of the slow-ramp page. `vision_enabled` stays False in the shipped configuration, and this changes
nothing there. Simulated GNSS, a surrogate camera, one direction and two datasets.

## GNSS healthy until the onset

<!-- vision-ramp-clean:start -->

| Front end | Dataset | Ramp m/s | Runs | Over the gate | Declared faulty | Captured | First over the gate, s after onset (median) | Final error m (median) | Final offset m (median) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| independent | euroc | 0 | 11 | 0% | 0% | 0% | - | 0.4 | 0.0 |
| independent | euroc | 0.05 | 11 | 0% | 0% | 100% | - | 3.9 | 4.0 |
| independent | euroc | 0.2 | 11 | 0% | 0% | 100% | - | 15.6 | 16.0 |
| independent | euroc | 0.5 | 11 | 18% | 0% | 100% | 83 | 39.1 | 39.9 |
| independent | euroc | 1 | 11 | 100% | 27% | 82% | 5 | 68.5 | 79.8 |
| independent | euroc | 2 | 11 | 100% | 100% | 0% | 5 | 6.9 | 159.7 |
| independent | tumvi | 0 | 6 | 0% | 0% | 0% | - | 0.4 | 0.0 |
| independent | tumvi | 0.05 | 6 | 0% | 0% | 100% | - | 5.1 | 5.3 |
| independent | tumvi | 0.2 | 6 | 0% | 0% | 100% | - | 20.8 | 21.2 |
| independent | tumvi | 0.5 | 6 | 33% | 0% | 100% | 83 | 52.2 | 53.0 |
| independent | tumvi | 1 | 6 | 100% | 0% | 100% | 5 | 104.6 | 106.0 |
| independent | tumvi | 2 | 6 | 100% | 100% | 0% | 5 | 6.4 | 212.0 |
| correlated | euroc | 0 | 11 | 0% | 0% | 0% | - | 0.5 | 0.0 |
| correlated | euroc | 0.05 | 11 | 0% | 0% | 100% | - | 4.0 | 4.0 |
| correlated | euroc | 0.2 | 11 | 0% | 0% | 100% | - | 15.8 | 16.0 |
| correlated | euroc | 0.5 | 11 | 0% | 0% | 100% | - | 39.7 | 39.9 |
| correlated | euroc | 1 | 11 | 0% | 0% | 100% | - | 79.5 | 79.8 |
| correlated | euroc | 2 | 11 | 0% | 0% | 100% | - | 159.2 | 159.7 |
| correlated | tumvi | 0 | 6 | 0% | 0% | 0% | - | 0.4 | 0.0 |
| correlated | tumvi | 0.05 | 6 | 0% | 0% | 100% | - | 5.1 | 5.3 |
| correlated | tumvi | 0.2 | 6 | 0% | 0% | 100% | - | 21.0 | 21.2 |
| correlated | tumvi | 0.5 | 6 | 0% | 0% | 100% | - | 52.8 | 53.0 |
| correlated | tumvi | 1 | 6 | 0% | 0% | 100% | - | 105.7 | 106.0 |
| correlated | tumvi | 2 | 6 | 50% | 0% | 100% | 5 | 211.6 | 212.0 |

<!-- vision-ramp-clean:end -->

## After a 20 s outage

<!-- vision-ramp-after-outage:start -->

| Front end | Dataset | Ramp m/s | Runs | Over the gate | Declared faulty | Captured | First over the gate, s after onset (median) | Final error m (median) | Final offset m (median) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| independent | euroc | 0 | 11 | 0% | 0% | 0% | - | 0.4 | 0.0 |
| independent | euroc | 0.05 | 11 | 0% | 0% | 100% | - | 3.9 | 4.0 |
| independent | euroc | 0.2 | 11 | 0% | 0% | 100% | - | 15.6 | 16.0 |
| independent | euroc | 0.5 | 11 | 18% | 0% | 100% | 83 | 39.1 | 39.9 |
| independent | euroc | 1 | 11 | 100% | 27% | 82% | 5 | 68.5 | 79.8 |
| independent | euroc | 2 | 11 | 100% | 100% | 0% | 5 | 6.2 | 159.7 |
| independent | tumvi | 0 | 6 | 0% | 0% | 0% | - | 0.4 | 0.0 |
| independent | tumvi | 0.05 | 6 | 0% | 0% | 100% | - | 5.1 | 5.3 |
| independent | tumvi | 0.2 | 6 | 0% | 0% | 100% | - | 20.8 | 21.2 |
| independent | tumvi | 0.5 | 6 | 33% | 0% | 100% | 83 | 52.2 | 53.0 |
| independent | tumvi | 1 | 6 | 100% | 0% | 100% | 5 | 104.6 | 106.0 |
| independent | tumvi | 2 | 6 | 100% | 100% | 0% | 5 | 6.6 | 212.0 |
| correlated | euroc | 0 | 11 | 9% | 0% | 0% | 0 | 0.5 | 0.0 |
| correlated | euroc | 0.05 | 11 | 9% | 0% | 100% | 0 | 4.0 | 4.0 |
| correlated | euroc | 0.2 | 11 | 9% | 0% | 100% | 0 | 15.8 | 16.0 |
| correlated | euroc | 0.5 | 11 | 9% | 0% | 100% | 0 | 39.7 | 39.9 |
| correlated | euroc | 1 | 11 | 18% | 0% | 100% | 3 | 79.5 | 79.8 |
| correlated | euroc | 2 | 11 | 27% | 0% | 100% | 5 | 159.1 | 159.7 |
| correlated | tumvi | 0 | 6 | 0% | 0% | 0% | - | 0.4 | 0.0 |
| correlated | tumvi | 0.05 | 6 | 0% | 0% | 100% | - | 5.1 | 5.3 |
| correlated | tumvi | 0.2 | 6 | 0% | 0% | 100% | - | 21.0 | 21.2 |
| correlated | tumvi | 0.5 | 6 | 0% | 0% | 100% | - | 52.8 | 53.0 |
| correlated | tumvi | 1 | 6 | 0% | 0% | 100% | - | 105.7 | 106.0 |
| correlated | tumvi | 2 | 6 | 0% | 0% | 100% | - | 211.6 | 212.0 |

<!-- vision-ramp-after-outage:end -->

## What it shows

1. **With independent visual errors a 2 m/s ramp is caught and not followed.** In both datasets and both arms, every
   run goes over the gate, the channel is declared faulty in every run, and no run is captured. The median final error
   is under 10 m, against a final offset above 150 m.
2. **A 1 m/s ramp is seen and still followed.** Every run goes over the gate, but the channel is declared faulty in at
   most 27% of the EuRoC runs and none of the TUM VI runs, and 82% to 100% of the runs are captured.
3. **At 0.2 m/s and below nothing is seen.** No run goes over the gate, and every run is captured.
4. **No control run alarms with independent errors.** The gate does not fire on the unspoofed runs.
5. **Correlated visual errors remove most of the benefit.** With the setting needed to keep the clone calibrated, no
   spoofed run is declared faulty and every spoofed run is captured.
6. **The floor is a ramp of the order of 1 to 2 m/s.** That is what a visual source with independent errors adds to
   an IMU and GNSS. Slower ramps are still followed.

## What follows

A second source lowers the detection floor from "none" to about 2 m/s, and only if the front end's errors are
independent. Whether a real front end's errors are independent is not known here ([ADR-0017](adr/0017-stochastic-clone-for-the-visual-update.md)).
Track A's exit test for spoofing is still not met: slow ramps below the floor are followed. A barometer or a map would
be a different second source, not tested. See [ADR-0020](adr/0020-second-source-against-a-ramp.md).
