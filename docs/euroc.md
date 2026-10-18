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
| all | default | 72 | 39 | 32 | 10.84 | 59.6% | 91.5 |
| all | preset | 72 | 2 | 1 | 3.23 | 96.7% | 22.1 |
| all | walk10 | 72 | 0 | 0 | 2.57 | 99.4% | 26.0 |
| Machine Hall | default | 36 | 14 | 7 | 6.31 | 73.9% | 20.0 |
| Machine Hall | preset | 36 | 0 | 0 | 3.17 | 99.1% | 21.6 |
| Machine Hall | walk10 | 36 | 0 | 0 | 2.51 | 99.6% | 20.1 |
| Vicon room | default | 36 | 25 | 25 | 23.19 | 45.3% | 214.2 |
| Vicon room | preset | 36 | 2 | 1 | 3.36 | 94.3% | 25.9 |
| Vicon room | walk10 | 36 | 0 | 0 | 2.63 | 99.2% | 29.8 |
| MH_01_easy | default | 8 | 5 | 5 | 18.62 | 45.6% | 1039.1 |
| MH_01_easy | preset | 8 | 0 | 0 | 3.05 | 98.5% | 15.8 |
| MH_01_easy | walk10 | 8 | 0 | 0 | 2.51 | 99.8% | 21.9 |
| MH_02_easy | default | 8 | 2 | 0 | 5.31 | 84.4% | 13.4 |
| MH_02_easy | preset | 8 | 0 | 0 | 3.04 | 99.3% | 18.6 |
| MH_02_easy | walk10 | 8 | 0 | 0 | 2.42 | 99.7% | 19.8 |
| MH_03_medium | default | 8 | 1 | 0 | 4.71 | 92.9% | 13.5 |
| MH_03_medium | preset | 8 | 0 | 0 | 2.93 | 99.4% | 20.2 |
| MH_03_medium | walk10 | 8 | 0 | 0 | 2.53 | 99.5% | 26.6 |
| MH_04_difficult | default | 6 | 3 | 2 | 8.97 | 69.5% | 63.9 |
| MH_04_difficult | preset | 6 | 0 | 0 | 3.20 | 99.1% | 21.0 |
| MH_04_difficult | walk10 | 6 | 0 | 0 | 2.47 | 99.4% | 17.1 |
| MH_05_difficult | default | 6 | 3 | 0 | 7.52 | 77.0% | 52.6 |
| MH_05_difficult | preset | 6 | 0 | 0 | 3.30 | 99.4% | 27.5 |
| MH_05_difficult | walk10 | 6 | 0 | 0 | 2.58 | 99.6% | 25.5 |
| V1_01_easy | default | 8 | 8 | 8 | 129.95 | 8.1% | 1394.3 |
| V1_01_easy | preset | 8 | 2 | 1 | 6.72 | 77.6% | 32.1 |
| V1_01_easy | walk10 | 8 | 0 | 0 | 3.11 | 98.1% | 44.3 |
| V1_02_medium | default | 4 | 0 | 0 | 3.44 | 99.1% | 7.5 |
| V1_02_medium | preset | 4 | 0 | 0 | 2.84 | 99.5% | 14.3 |
| V1_02_medium | walk10 | 4 | 0 | 0 | 2.39 | 99.5% | 17.5 |
| V1_03_difficult | default | 6 | 6 | 6 | 32.86 | 30.2% | 245.3 |
| V1_03_difficult | preset | 6 | 0 | 0 | 3.36 | 99.0% | 25.6 |
| V1_03_difficult | walk10 | 6 | 0 | 0 | 2.62 | 99.5% | 22.9 |
| V2_01_easy | default | 6 | 2 | 2 | 6.36 | 78.5% | 9.5 |
| V2_01_easy | preset | 6 | 0 | 0 | 3.38 | 98.9% | 31.1 |
| V2_01_easy | walk10 | 6 | 0 | 0 | 2.58 | 99.5% | 35.1 |
| V2_02_medium | default | 6 | 5 | 5 | 28.19 | 42.4% | 468.5 |
| V2_02_medium | preset | 6 | 0 | 0 | 3.16 | 99.0% | 21.5 |
| V2_02_medium | walk10 | 6 | 0 | 0 | 2.66 | 99.6% | 22.8 |
| V2_03_difficult | default | 6 | 4 | 4 | 19.25 | 44.1% | 124.2 |
| V2_03_difficult | preset | 6 | 0 | 0 | 3.62 | 99.0% | 19.0 |
| V2_03_difficult | walk10 | 6 | 0 | 0 | 2.81 | 99.4% | 28.0 |

Runs still lost with `preset`:

| Sequence | Outage start s | Seed | GNSS fixes rejected | Max position error m |
|---|---:|---:|---:|---:|
| V1_01_easy | 15 | 0 | 88% | 7168.8 |
| V1_01_easy | 35 | 0 | 29% | 140.3 |

<!-- euroc:end -->

## Checks run after the settings were chosen

Different outage starts, different seeds, and a longer outage than the main table uses, over the same
eleven sequences. Generated from [`data/euroc_validation.csv`](data/euroc_validation.csv).

<!-- euroc-validation:start -->

Lost = more than 20% of GNSS fixes rejected.

| Outage s | Config | Runs | Lost | Median NEES (expected 3) | Mean 2σ coverage |
|---:|---|---:|---:|---:|---:|
| 20 | default | 62 | 21 | 6.83 | 67.5% |
| 20 | preset | 62 | 0 | 2.74 | 98.2% |
| 20 | walk10 | 62 | 0 | 2.34 | 99.5% |
| 30 | default | 42 | 25 | 14.45 | 51.6% |
| 30 | preset | 42 | 2 | 3.27 | 94.0% |
| 30 | walk10 | 42 | 0 | 2.39 | 99.4% |

<!-- euroc-validation:end -->

## What it shows

Each statement below is checked against the CSV files by `tests/test_euroc_page.py`.

1. **Both presets lose fewer runs than the default**, over all sequences and within each of the two
   environments, Machine Hall and the Vicon rooms.
2. **The default loses a larger share of runs on the Vicon rooms** than on Machine Hall.
3. **The bias-walk preset loses fewer runs than the noise-scale preset** in the main table.
4. **In the later checks the bias-walk preset loses no run**, for either outage length. The noise-scale preset
   loses no run at the shorter outage and some at the longer one.
5. **The bias-walk preset is slightly conservative.** Over all runs, its mean 2σ coverage is at
   or above the nominal 99.3% in each table, and its median NEES is below the expected 3.
6. **The FDIR flag undercounts the lost runs of the default.** More runs are lost than are flagged.

**INTERPRETATION:** Which runs are lost changed between two filter versions, so read individual lost runs as sensitive and the counts as approximate.

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
