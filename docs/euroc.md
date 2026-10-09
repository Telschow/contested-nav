# EuRoC: recorded IMU, simulated GNSS

The filter run on a recorded inertial stream, for the first time in this repository. Every other
page measures it on a synthetic generator. This one uses the IMU recorded in the EuRoC MAV dataset
and the dataset's own ground truth. The decision behind it is
[ADR-0013](adr/0013-recorded-imu-with-simulated-gnss.md); the noise settings are in
[ADR-0014](adr/0014-textbook-imu-process-noise-by-default.md).

## Read this before quoting anything

- **The GNSS is simulated.** EuRoC has no GNSS. The fixes are generated from the ground truth with
  the noise model of the synthetic benchmark, at the IMU origin, and an outage is cut out of them.
  This tests the filter against real inertial noise. It is not GNSS-denied navigation in the field.
- **The start state comes from the ground truth**, with a seeded perturbation drawn from the
  filter's declared initial uncertainty. That is an ideal initial alignment.
- **The ground truth is an estimate.** The dataset's own notes say its synchronisation with the
  sensors is limited.
- **The preset is a tuning.** `--preset adis16448` scales the IMU noise the filter assumes by 3 and
  declares a bias prior. The scale was chosen on `MH_01_easy`, so that sequence is in-sample, and
  then checked on the other ten. It is a property of this sensor and these recordings, not of the
  filter. It has not been tried on another IMU.
- **Runs still fail with the preset.** They are listed under the table. A median alone would hide
  them.
- **The data is not in the repository.** Its rights statement is "In Copyright - Non-Commercial Use
  Permitted". Fetch it yourself; only the results below are committed.

## Results

A run is **lost** when the filter rejects more than a fifth of the GNSS fixes it sees. That is a
measure of the outcome. **Flag** counts the runs in which the FDIR layer declared the GNSS channel
faulty. It is shown next to the count and not used for it, because some runs reject hundreds of
fixes and are never declared faulty.

Each case is one 20 s GNSS outage, starting at one of several times that fit in the recording, with
two noise seeds. The table is generated from [`data/euroc_compare.csv`](data/euroc_compare.csv); a
test fails if they disagree. CI cannot regenerate it, because the dataset is not vendored.

<!-- euroc:start -->

Lost = more than 20% of GNSS fixes rejected. Flag = FDIR declared the channel faulty.

| Scope | Config | Runs | Lost | Flag | Median NEES (expected 3) | Mean 2σ coverage | Median max error m |
|---|---|---:|---:|---:|---:|---:|---:|
| all | default | 72 | 40 | 33 | 11.29 | 59.2% | 90.8 |
| all | preset | 72 | 4 | 2 | 3.36 | 94.7% | 24.7 |
| Machine Hall | default | 36 | 15 | 8 | 6.34 | 73.0% | 19.4 |
| Machine Hall | preset | 36 | 2 | 2 | 3.20 | 95.2% | 23.3 |
| Vicon room | default | 36 | 25 | 25 | 23.68 | 45.5% | 216.7 |
| Vicon room | preset | 36 | 2 | 0 | 3.43 | 94.2% | 25.3 |
| MH_01_easy | default | 8 | 6 | 6 | 23.04 | 38.7% | 1233.1 |
| MH_01_easy | preset | 8 | 0 | 0 | 3.13 | 98.4% | 16.5 |
| MH_02_easy | default | 8 | 2 | 0 | 5.32 | 84.3% | 13.5 |
| MH_02_easy | preset | 8 | 0 | 0 | 2.93 | 99.3% | 22.2 |
| MH_03_medium | default | 8 | 1 | 0 | 4.71 | 93.0% | 13.3 |
| MH_03_medium | preset | 8 | 0 | 0 | 2.92 | 99.5% | 20.1 |
| MH_04_difficult | default | 6 | 3 | 2 | 8.85 | 69.9% | 62.9 |
| MH_04_difficult | preset | 6 | 1 | 1 | 5.39 | 88.3% | 62.4 |
| MH_05_difficult | default | 6 | 3 | 0 | 6.56 | 79.9% | 46.1 |
| MH_05_difficult | preset | 6 | 1 | 1 | 3.32 | 86.9% | 31.5 |
| V1_01_easy | default | 8 | 8 | 8 | 137.03 | 8.1% | 1432.9 |
| V1_01_easy | preset | 8 | 2 | 0 | 5.38 | 77.1% | 30.4 |
| V1_02_medium | default | 4 | 0 | 0 | 3.42 | 99.1% | 7.6 |
| V1_02_medium | preset | 4 | 0 | 0 | 3.29 | 99.5% | 19.4 |
| V1_03_difficult | default | 6 | 6 | 6 | 32.07 | 30.4% | 244.2 |
| V1_03_difficult | preset | 6 | 0 | 0 | 3.64 | 99.0% | 28.8 |
| V2_01_easy | default | 6 | 2 | 2 | 6.36 | 78.4% | 9.5 |
| V2_01_easy | preset | 6 | 0 | 0 | 3.41 | 99.2% | 27.7 |
| V2_02_medium | default | 6 | 5 | 5 | 28.87 | 42.6% | 466.5 |
| V2_02_medium | preset | 6 | 0 | 0 | 3.03 | 99.1% | 24.6 |
| V2_03_difficult | default | 6 | 4 | 4 | 18.88 | 44.6% | 123.6 |
| V2_03_difficult | preset | 6 | 0 | 0 | 3.28 | 98.8% | 21.4 |

Runs still lost with `preset`:

| Sequence | Outage start s | Seed | GNSS fixes rejected | Max position error m |
|---|---:|---:|---:|---:|
| MH_04_difficult | 60 | 0 | 24% | 372.2 |
| MH_05_difficult | 15 | 0 | 71% | 2039.6 |
| V1_01_easy | 15 | 0 | 81% | 6695.1 |
| V1_01_easy | 35 | 1 | 29% | 132.1 |

<!-- euroc:end -->

## What it shows

Each statement below is checked against the CSV by `tests/test_euroc_page.py`.

1. **The preset loses fewer runs than the default**, over all sequences and within each of the two
   environments, Machine Hall and the Vicon rooms.
2. **The default loses a larger share of runs on the Vicon rooms** than on Machine Hall.
3. **The preset is close to calibrated in the middle and not in every case.** Its median NEES is
   within a factor of two of the expected value of 3 over all runs, and some runs are still lost.
4. **The FDIR flag undercounts the lost runs of the default.** More runs are lost than are flagged.
5. **Most of the runs still lost with the preset start their outage early in the recording.** Why is
   not tested here. One hypothesis is that the filter has not settled when the outage begins.

## Reproduce

```bash
navkit euroc fetch --sequence MH_01_easy     # repeat for each sequence; or fetch whole archives
navkit euroc compare --csv docs/data/euroc_compare.csv --page docs/euroc.md
navkit euroc compare --from-csv docs/data/euroc_compare.csv --page docs/euroc.md   # rebuild the page only
```

The fetch step and the archive layout are described in [Path to real systems](REAL_SYSTEMS.md) and in
the `navkit.io.euroc_fetch` module.
