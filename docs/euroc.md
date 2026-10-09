# EuRoC: recorded IMU, simulated GNSS

The filter run on a recorded inertial stream. Every other page measures it on a synthetic generator.
This one uses the IMU recorded in the EuRoC MAV dataset and the dataset's own ground truth. The
decision behind it is [ADR-0013](adr/0013-recorded-imu-with-simulated-gnss.md); the noise settings
are discussed in [ADR-0014](adr/0014-textbook-imu-process-noise-by-default.md).

## Read this before quoting anything

- **The GNSS is simulated.** EuRoC has no GNSS. The fixes are generated from the ground truth with
  the noise model of the synthetic benchmark, at the IMU origin, and an outage is cut out of them.
  This tests the filter against real inertial noise. It is not GNSS-denied navigation in the field.
- **The start state comes from the ground truth**, with a seeded perturbation drawn from the
  filter's declared initial uncertainty. That is an ideal initial alignment.
- **The ground truth is an estimate.** The dataset's own notes say its synchronisation with the
  sensors is limited.
- **The presets are tunings for one sensor.** `--preset adis16448` multiplies every assumed IMU noise
  term by 3. `--preset adis16448-walk` leaves the white noise as the sensor file gives it and
  multiplies only the two bias random walks by 10. Both declare a bias prior. Neither is a filter
  default, and neither has been tried on another IMU.
- **The second preset was chosen after looking at failures.** Its scale was picked on the runs that
  failed under the first, so the main table is partly in-sample for it. The second table is not: it
  holds runs made after the choice, with outage starts, seeds and an outage length that the main
  table does not use.
- **The sensor file understates the bias random walk.** That is the best reading of why the second
  preset works. It is a hypothesis, not a measurement of the sensor.
- **Runs can still fail.** Any run that is still lost is listed under its table. A median alone would
  hide it.
- **The data is not in the repository.** Its rights statement is "In Copyright - Non-Commercial Use
  Permitted". Fetch it yourself; only the results below are committed.

## Results

A run is **lost** when the filter rejects more than a fifth of the GNSS fixes it sees. That is a
measure of the outcome. **Flag** counts the runs in which the FDIR layer declared the GNSS channel
faulty. It is shown next to the count and not used for it, because some runs reject hundreds of
fixes and are never declared faulty.

Each case is one 20 s GNSS outage, starting at one of several times that fit in the recording, with
two noise seeds. In the table, `default` is the filter as shipped, `preset` is `adis16448` and
`walk10` is `adis16448-walk`. The table is generated from
[`data/euroc_compare.csv`](data/euroc_compare.csv); a test fails if they disagree. CI cannot
regenerate it, because the dataset is not vendored.

<!-- euroc:start -->

Lost = more than 20% of GNSS fixes rejected. Flag = FDIR declared the channel faulty.

| Scope | Config | Runs | Lost | Flag | Median NEES (expected 3) | Mean 2σ coverage | Median max error m |
|---|---|---:|---:|---:|---:|---:|---:|
| all | default | 72 | 40 | 33 | 11.29 | 59.2% | 90.8 |
| all | preset | 72 | 4 | 2 | 3.36 | 94.7% | 24.7 |
| all | walk10 | 72 | 0 | 0 | 2.63 | 99.4% | 31.7 |
| Machine Hall | default | 36 | 15 | 8 | 6.34 | 73.0% | 19.4 |
| Machine Hall | preset | 36 | 2 | 2 | 3.20 | 95.2% | 23.3 |
| Machine Hall | walk10 | 36 | 0 | 0 | 2.57 | 99.6% | 29.5 |
| Vicon room | default | 36 | 25 | 25 | 23.68 | 45.5% | 216.7 |
| Vicon room | preset | 36 | 2 | 0 | 3.43 | 94.2% | 25.3 |
| Vicon room | walk10 | 36 | 0 | 0 | 2.65 | 99.2% | 33.0 |
| MH_01_easy | default | 8 | 6 | 6 | 23.04 | 38.7% | 1233.1 |
| MH_01_easy | preset | 8 | 0 | 0 | 3.13 | 98.4% | 16.5 |
| MH_01_easy | walk10 | 8 | 0 | 0 | 2.53 | 99.8% | 20.2 |
| MH_02_easy | default | 8 | 2 | 0 | 5.32 | 84.3% | 13.5 |
| MH_02_easy | preset | 8 | 0 | 0 | 2.93 | 99.3% | 22.2 |
| MH_02_easy | walk10 | 8 | 0 | 0 | 2.40 | 99.7% | 25.3 |
| MH_03_medium | default | 8 | 1 | 0 | 4.71 | 93.0% | 13.3 |
| MH_03_medium | preset | 8 | 0 | 0 | 2.92 | 99.5% | 20.1 |
| MH_03_medium | walk10 | 8 | 0 | 0 | 2.54 | 99.6% | 28.8 |
| MH_04_difficult | default | 6 | 3 | 2 | 8.85 | 69.9% | 62.9 |
| MH_04_difficult | preset | 6 | 1 | 1 | 5.39 | 88.3% | 62.4 |
| MH_04_difficult | walk10 | 6 | 0 | 0 | 2.84 | 99.5% | 49.0 |
| MH_05_difficult | default | 6 | 3 | 0 | 6.56 | 79.9% | 46.1 |
| MH_05_difficult | preset | 6 | 1 | 1 | 3.32 | 86.9% | 31.5 |
| MH_05_difficult | walk10 | 6 | 0 | 0 | 2.72 | 99.4% | 32.0 |
| V1_01_easy | default | 8 | 8 | 8 | 137.03 | 8.1% | 1432.9 |
| V1_01_easy | preset | 8 | 2 | 0 | 5.38 | 77.1% | 30.4 |
| V1_01_easy | walk10 | 8 | 0 | 0 | 2.77 | 98.1% | 44.1 |
| V1_02_medium | default | 4 | 0 | 0 | 3.42 | 99.1% | 7.6 |
| V1_02_medium | preset | 4 | 0 | 0 | 3.29 | 99.5% | 19.4 |
| V1_02_medium | walk10 | 4 | 0 | 0 | 2.54 | 99.5% | 20.3 |
| V1_03_difficult | default | 6 | 6 | 6 | 32.07 | 30.4% | 244.2 |
| V1_03_difficult | preset | 6 | 0 | 0 | 3.64 | 99.0% | 28.8 |
| V1_03_difficult | walk10 | 6 | 0 | 0 | 2.73 | 99.4% | 34.9 |
| V2_01_easy | default | 6 | 2 | 2 | 6.36 | 78.4% | 9.5 |
| V2_01_easy | preset | 6 | 0 | 0 | 3.41 | 99.2% | 27.7 |
| V2_01_easy | walk10 | 6 | 0 | 0 | 2.62 | 99.6% | 35.4 |
| V2_02_medium | default | 6 | 5 | 5 | 28.87 | 42.6% | 466.5 |
| V2_02_medium | preset | 6 | 0 | 0 | 3.03 | 99.1% | 24.6 |
| V2_02_medium | walk10 | 6 | 0 | 0 | 2.72 | 99.6% | 29.8 |
| V2_03_difficult | default | 6 | 4 | 4 | 18.88 | 44.6% | 123.6 |
| V2_03_difficult | preset | 6 | 0 | 0 | 3.28 | 98.8% | 21.4 |
| V2_03_difficult | walk10 | 6 | 0 | 0 | 2.67 | 99.5% | 25.1 |

Runs still lost with `preset`:

| Sequence | Outage start s | Seed | GNSS fixes rejected | Max position error m |
|---|---:|---:|---:|---:|
| MH_04_difficult | 60 | 0 | 24% | 372.2 |
| MH_05_difficult | 15 | 0 | 71% | 2039.6 |
| V1_01_easy | 15 | 0 | 81% | 6695.1 |
| V1_01_easy | 35 | 1 | 29% | 132.1 |

<!-- euroc:end -->

## Checks run after the settings were chosen

Different outage starts, different seeds, and a longer outage than the main table uses, over the same
eleven sequences. Generated from [`data/euroc_validation.csv`](data/euroc_validation.csv).

<!-- euroc-validation:start -->

Lost = more than 20% of GNSS fixes rejected.

| Outage s | Config | Runs | Lost | Median NEES (expected 3) | Mean 2σ coverage |
|---:|---|---:|---:|---:|---:|
| 20 | default | 62 | 21 | 6.81 | 67.4% |
| 20 | preset | 62 | 3 | 2.92 | 95.4% |
| 20 | walk10 | 62 | 0 | 2.37 | 99.7% |
| 30 | default | 42 | 25 | 14.96 | 51.6% |
| 30 | preset | 42 | 5 | 3.49 | 91.4% |
| 30 | walk10 | 42 | 0 | 2.54 | 99.4% |

<!-- euroc-validation:end -->

## What it shows

Each statement below is checked against the CSV files by `tests/test_euroc_page.py`.

1. **Both presets lose fewer runs than the default**, over all sequences and within each of the two
   environments, Machine Hall and the Vicon rooms.
2. **The default loses a larger share of runs on the Vicon rooms** than on Machine Hall.
3. **The bias-walk preset loses fewer runs than the noise-scale preset** in the main table.
4. **In the later checks the bias-walk preset loses no run**, for either outage length, and the
   noise-scale preset loses some.
5. **The bias-walk preset is slightly conservative.** Over all runs, its mean 2σ coverage is at
   or above the nominal 99.3% in each table, and its median NEES is below the expected 3.
6. **The FDIR flag undercounts the lost runs of the default.** More runs are lost than are flagged.

## Reproduce

```bash
navkit euroc fetch --sequence MH_01_easy     # repeat for each sequence; or fetch whole archives
navkit euroc compare --configs default,preset,walk10 --csv docs/data/euroc_compare.csv --page docs/euroc.md
navkit euroc compare --configs default,preset,walk10 --starts 25,45,75 --first-seed 2 --csv a.csv
navkit euroc compare --configs default,preset,walk10 --starts 20,50 --outage 30 --csv b.csv
# merge a.csv and b.csv into docs/data/euroc_validation.csv, then:
navkit euroc compare --from-csv docs/data/euroc_validation.csv --page docs/euroc.md --block euroc-validation
navkit euroc compare --from-csv docs/data/euroc_compare.csv --page docs/euroc.md     # rebuild the main table only
```

The fetch step and the archive layout are described in [Path to real systems](REAL_SYSTEMS.md) and in
the `navkit.io.euroc_fetch` module.
