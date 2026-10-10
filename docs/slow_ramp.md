# Slow-ramp GNSS spoofing

The [separability](separability.md) study covers the first fix after an outage. This page covers a spoof that starts
small and grows. It is the case [ADR-0018](adr/0018-honest-return-separability.md) left open.

## Method

Real recorded IMU (EuRoC, TUM VI), with GNSS simulated from the ground truth. From an onset 35 s into the recording,
every GNSS position is shifted along world x by `rate * (t - onset)`, and the shift keeps growing to the end of the
recording. Rates are 0.05, 0.2, 0.5, 1 and 2 m/s, and 0 is the control. Two arms: GNSS healthy before the onset
(clean), and a 20 s outage that ends at the onset (after outage). Two settings per dataset: the default noise, and the
calibrated bias walk. One seed, so a row is one run per sequence. There is no vision, so the IMU is the only check on
GNSS.

Columns. *Over the gate*: at least one fix after the onset exceeded the shipped chi-square threshold. *Declared
faulty*: the FDIR layer declared the GNSS channel faulty. *Re-accepted*: it re-accepted GNSS with inflation.
*Captured*: the final position error is more than half the final spoof offset, that is, the filter followed the
spoof. *Final offset* is what the spoof has added by the end of the recording, so it differs between datasets.

This is one direction, one onset time, simulated GNSS, and two datasets.

## GNSS healthy until the onset

<!-- ramp-clean:start -->

| Dataset | Setting | Ramp m/s | Runs | Over the gate | Declared faulty | Re-accepted | Captured | First over the gate, s after onset (median) | Final error m (median) | Final offset m (median) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| euroc | default | 0 | 11 | 9% | 0% | 0% | 0% | 0 | 0.4 | 0.0 |
| euroc | default | 0.05 | 11 | 9% | 0% | 0% | 100% | 0 | 3.9 | 4.0 |
| euroc | default | 0.2 | 11 | 9% | 0% | 0% | 100% | 0 | 15.4 | 16.0 |
| euroc | default | 0.5 | 11 | 18% | 0% | 0% | 100% | 15 | 39.1 | 39.9 |
| euroc | default | 1 | 11 | 64% | 0% | 0% | 100% | 5 | 79.0 | 79.8 |
| euroc | default | 2 | 11 | 100% | 36% | 0% | 100% | 5 | 160.8 | 159.7 |
| euroc | walk10 | 0 | 11 | 0% | 0% | 0% | 0% | - | 0.5 | 0.0 |
| euroc | walk10 | 0.05 | 11 | 0% | 0% | 0% | 100% | - | 3.9 | 4.0 |
| euroc | walk10 | 0.2 | 11 | 0% | 0% | 0% | 100% | - | 15.7 | 16.0 |
| euroc | walk10 | 0.5 | 11 | 0% | 0% | 0% | 100% | - | 39.6 | 39.9 |
| euroc | walk10 | 1 | 11 | 0% | 0% | 0% | 100% | - | 79.5 | 79.8 |
| euroc | walk10 | 2 | 11 | 0% | 0% | 0% | 100% | - | 159.3 | 159.7 |
| tumvi | file | 0 | 6 | 17% | 0% | 0% | 0% | 8 | 0.3 | 0.0 |
| tumvi | file | 0.05 | 6 | 17% | 0% | 0% | 100% | 8 | 5.0 | 5.3 |
| tumvi | file | 0.2 | 6 | 17% | 0% | 0% | 100% | 8 | 21.0 | 21.2 |
| tumvi | file | 0.5 | 6 | 17% | 0% | 0% | 100% | 8 | 52.9 | 53.0 |
| tumvi | file | 1 | 6 | 33% | 0% | 0% | 100% | 7 | 105.9 | 106.0 |
| tumvi | file | 2 | 6 | 100% | 17% | 0% | 100% | 6 | 213.1 | 212.0 |
| tumvi | file-walk10 | 0 | 6 | 0% | 0% | 0% | 0% | - | 0.4 | 0.0 |
| tumvi | file-walk10 | 0.05 | 6 | 0% | 0% | 0% | 100% | - | 5.1 | 5.3 |
| tumvi | file-walk10 | 0.2 | 6 | 0% | 0% | 0% | 100% | - | 21.1 | 21.2 |
| tumvi | file-walk10 | 0.5 | 6 | 0% | 0% | 0% | 100% | - | 52.9 | 53.0 |
| tumvi | file-walk10 | 1 | 6 | 0% | 0% | 0% | 100% | - | 105.9 | 106.0 |
| tumvi | file-walk10 | 2 | 6 | 50% | 0% | 0% | 100% | 5 | 211.9 | 212.0 |

<!-- ramp-clean:end -->

## After a 20 s outage

<!-- ramp-after-outage:start -->

| Dataset | Setting | Ramp m/s | Runs | Over the gate | Declared faulty | Re-accepted | Captured | First over the gate, s after onset (median) | Final error m (median) | Final offset m (median) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| euroc | default | 0 | 11 | 45% | 45% | 0% | 0% | 0 | 0.7 | 0.0 |
| euroc | default | 0.05 | 11 | 45% | 45% | 0% | 100% | 0 | 5.3 | 4.0 |
| euroc | default | 0.2 | 11 | 45% | 45% | 0% | 100% | 0 | 19.7 | 16.0 |
| euroc | default | 0.5 | 11 | 64% | 45% | 0% | 100% | 0 | 48.7 | 39.9 |
| euroc | default | 1 | 11 | 64% | 45% | 0% | 100% | 0 | 96.9 | 79.8 |
| euroc | default | 2 | 11 | 91% | 55% | 0% | 100% | 1 | 193.4 | 159.7 |
| euroc | walk10 | 0 | 11 | 9% | 0% | 0% | 0% | 83 | 0.5 | 0.0 |
| euroc | walk10 | 0.05 | 11 | 9% | 0% | 0% | 100% | 83 | 4.0 | 4.0 |
| euroc | walk10 | 0.2 | 11 | 9% | 0% | 0% | 100% | 83 | 15.7 | 16.0 |
| euroc | walk10 | 0.5 | 11 | 9% | 0% | 0% | 100% | 83 | 39.6 | 39.9 |
| euroc | walk10 | 1 | 11 | 9% | 9% | 0% | 100% | 83 | 79.5 | 79.8 |
| euroc | walk10 | 2 | 11 | 9% | 9% | 0% | 100% | 41 | 159.3 | 159.7 |
| tumvi | file | 0 | 6 | 17% | 17% | 0% | 0% | 13 | 0.3 | 0.0 |
| tumvi | file | 0.05 | 6 | 17% | 17% | 0% | 100% | 13 | 5.3 | 5.3 |
| tumvi | file | 0.2 | 6 | 17% | 17% | 0% | 100% | 13 | 21.2 | 21.2 |
| tumvi | file | 0.5 | 6 | 17% | 17% | 0% | 100% | 13 | 52.9 | 53.0 |
| tumvi | file | 1 | 6 | 17% | 17% | 0% | 100% | 13 | 105.9 | 106.0 |
| tumvi | file | 2 | 6 | 67% | 17% | 0% | 100% | 11 | 211.8 | 212.0 |
| tumvi | file-walk10 | 0 | 6 | 0% | 0% | 0% | 0% | - | 0.4 | 0.0 |
| tumvi | file-walk10 | 0.05 | 6 | 0% | 0% | 0% | 100% | - | 5.1 | 5.3 |
| tumvi | file-walk10 | 0.2 | 6 | 0% | 0% | 0% | 100% | - | 21.1 | 21.2 |
| tumvi | file-walk10 | 0.5 | 6 | 0% | 0% | 0% | 100% | - | 52.9 | 53.0 |
| tumvi | file-walk10 | 1 | 6 | 0% | 0% | 0% | 100% | - | 105.9 | 106.0 |
| tumvi | file-walk10 | 2 | 6 | 0% | 0% | 0% | 100% | - | 211.9 | 212.0 |

<!-- ramp-after-outage:end -->

## What it shows

1. **Every spoofed run is captured.** At every rate, from 0.05 to 2 m/s, in both datasets, both settings and both
   arms, the filter ends up following the spoof. None of the spoofed rows has a captured share below 100%.
2. **With the calibrated bias walk the gate does not react to a ramp up to 1 m/s on EuRoC.** No clean-arm run
   goes over the gate, at any rate. On TUM VI the first reaction, in half the runs, is at 2 m/s.
3. **With the default noise the gate reacts to the faster ramps, and the filter is still captured.** It also fires on
   some control runs, which is the overconfidence of [ADR-0014](adr/0014-textbook-imu-process-noise-by-default.md).
   At no rate is a channel declared faulty in every run, and the capture is 100% regardless. A detection is not a
   protection.
4. **The error equals the offset.** In the calibrated settings the median final error is within 5% of the median
   final offset in every row. Nothing in the filter pushes back, because nothing independent of GNSS constrains
   position.

## What follows

A slow ramp is not detectable with an IMU and GNSS alone, and the FDIR layer's lockout does not stop the filter
being led away. This is a limit of the sensor set, not a tuning problem: a drift rate below what the IMU can
distinguish from its own error growth cannot be seen. The consequence for Track A's exit test is that detection of
spoofing is not met and cannot be met without a second independent source (vision, a barometer, a map). The shipped
configuration is unchanged. The decision is for
[ADR-0019](adr/0019-slow-ramp-spoofing.md).
