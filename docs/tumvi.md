# TUM VI: recorded IMU, simulated GNSS

The second recorded dataset, with a different IMU from [the EuRoC page](euroc.md) (a BMI160, where EuRoC has an
ADIS16448). The decision behind it is [ADR-0016](adr/0016-tum-vi-as-a-second-recorded-dataset.md); the method is
the one of [ADR-0013](adr/0013-recorded-imu-with-simulated-gnss.md).

## Read this before quoting anything

- **The GNSS is simulated.** TUM VI has none. The fixes are generated from the motion-capture ground truth with the
  noise model of the synthetic benchmark, and an outage is cut out of them. This tests the filter against real
  inertial noise. It is not GNSS-denied navigation in the field.
- **The start bias is estimated, not known.** The ground truth is a pose stream with no bias columns. The filter
  starts from biases estimated over the quietest stretch of the first seconds, using the ground-truth attitude, and
  declares a bias prior. Some rooms never rest at the start, so for them the estimate is only a guess. The EuRoC
  runs start from the dataset's own bias estimate, so the two pages differ in this as well as in the sensor.
- **The motion capture has dropouts.** Its stream is nominally about 120 Hz but has gaps of up to a few seconds, and
  two rooms spend roughly a tenth of the recording inside them ([timing](product_management/04_sensor_sync_and_calibration_spec.md)).
  Inside a dropout the simulated GNSS and the scoring reference follow a straight line between the nearest samples.
  Every setting sees the same data, so the comparison between settings is not a product of the dropouts, but the
  absolute errors in those two rooms are less trustworthy.
- **The start pose and velocity come from the ground truth.** Velocity is a local straight-line fit to the
  motion-capture positions.
- **The settings were not tuned on this dataset.** `file` is the dataset authors' own noise figures. `allan` is the
  raw figures they measured, which they kept in comments. `file-walk10` is `file` with the two bias random walks
  multiplied by a further 10, the adjustment found on EuRoC, applied here unchanged. Any setting chosen from this
  page from now on is in-sample.
- **The authors inflated their own figures.** Their file says the active values are the raw ones with the white
  noise multiplied by 2 and the bias random walk by 10, "to account for unmodelled effects". So `file` against
  `allan` changes both. `file-walk10` against `file` changes the bias random walk only, with the white noise
  identical.
- **Runs can still fail.** Any run lost with a setting other than the baseline is listed under the table.
- **The data is not in the repository.** It is published under CC BY 4.0, which asks for attribution: D. Schubert,
  T. Goll, N. Demmel, V. Usenko, J. Stueckler and D. Cremers, "The TUM VI Benchmark for Evaluating Visual-Inertial
  Odometry", IROS 2018. Fetch it yourself; only the results below are committed.

## Results

A run is **lost** when the filter rejects more than a fifth of the GNSS fixes it sees. **Flag** counts the runs in
which the FDIR layer declared the GNSS channel faulty; it is shown next to the count and not used for it. Each case
is one 20 s GNSS outage, starting at one of several times that fit in the recording, with two noise seeds. The table
is generated from [`data/tumvi_compare.csv`](data/tumvi_compare.csv); a test fails if they disagree. CI cannot
regenerate it, because the dataset is not vendored.

<!-- tumvi:start -->

Lost = more than 20% of GNSS fixes rejected. Flag = FDIR declared the channel faulty.

| Scope | Config | Runs | Lost | Flag | Median NEES (expected 3) | Mean 2σ coverage | Median max error m |
|---|---|---:|---:|---:|---:|---:|---:|
| all | file | 46 | 2 | 2 | 4.25 | 91.0% | 10.6 |
| all | allan | 46 | 6 | 6 | 8.20 | 71.8% | 12.9 |
| all | file-walk10 | 46 | 1 | 1 | 2.85 | 97.6% | 13.7 |
| room1 | file | 8 | 0 | 0 | 3.98 | 97.9% | 13.5 |
| room1 | allan | 8 | 0 | 0 | 7.90 | 78.5% | 13.7 |
| room1 | file-walk10 | 8 | 0 | 0 | 2.78 | 99.7% | 19.3 |
| room2 | file | 8 | 0 | 0 | 3.85 | 97.9% | 5.2 |
| room2 | allan | 8 | 0 | 0 | 7.30 | 81.3% | 4.8 |
| room2 | file-walk10 | 8 | 0 | 0 | 2.72 | 99.4% | 6.0 |
| room3 | file | 8 | 0 | 0 | 4.74 | 95.4% | 8.6 |
| room3 | allan | 8 | 1 | 1 | 9.08 | 72.5% | 11.8 |
| room3 | file-walk10 | 8 | 0 | 0 | 2.80 | 99.3% | 7.9 |
| room4 | file | 6 | 0 | 0 | 3.84 | 95.7% | 13.3 |
| room4 | allan | 6 | 0 | 0 | 8.10 | 76.6% | 14.0 |
| room4 | file-walk10 | 6 | 0 | 0 | 2.83 | 99.4% | 12.0 |
| room5 | file | 8 | 2 | 2 | 8.21 | 66.8% | 29.1 |
| room5 | allan | 8 | 4 | 4 | 45.40 | 40.6% | 72.2 |
| room5 | file-walk10 | 8 | 1 | 1 | 3.18 | 89.0% | 31.3 |
| room6 | file | 8 | 0 | 0 | 4.21 | 93.2% | 14.7 |
| room6 | allan | 8 | 1 | 1 | 6.24 | 82.3% | 18.7 |
| room6 | file-walk10 | 8 | 0 | 0 | 2.88 | 99.3% | 11.6 |

Runs still lost with `allan`:

| Sequence | Outage start s | Seed | GNSS fixes rejected | Max position error m |
|---|---:|---:|---:|---:|
| room3 | 60 | 1 | 51% | 130.4 |
| room5 | 15 | 0 | 51% | 508.7 |
| room5 | 35 | 0 | 71% | 2076.3 |
| room5 | 60 | 1 | 51% | 199.0 |
| room5 | 90 | 0 | 28% | 107.9 |
| room6 | 15 | 1 | 66% | 455.6 |

Runs still lost with `file-walk10`:

| Sequence | Outage start s | Seed | GNSS fixes rejected | Max position error m |
|---|---:|---:|---:|---:|
| room5 | 35 | 0 | 71% | 2124.0 |

<!-- tumvi:end -->

## What it shows

Each statement below is checked against the CSV (and, for statement 5, the timing CSV) by `tests/test_tumvi_page.py`.

1. **The raw figures lose more runs than the authors' inflated figures**, and the inflated figures lose more than
   the bias-walk setting, which loses one run.
2. **The same ordering holds for calibration.** The median NEES falls and the mean 2σ coverage rises from `allan`
   to `file` to `file-walk10`.
3. **With only the bias random walk changed, the loss falls from some runs to fewer.** `file-walk10` differs from
   `file` in the bias random walks alone, and still loses a run.
4. **The bias-walk setting is close to nominal.** Over all runs its median NEES is below the expected 3, and its
   mean 2σ coverage is within two points of the nominal 99.3%.
5. **The ordering also holds in the rooms with the fewest dropouts.** Leaving out the two rooms that spend most of their
   time in motion-capture dropouts, the raw figures still lose more runs than the inflated ones, which lose more
   than the bias-walk setting.
6. **The ordering is the one found on EuRoC**, on a different IMU, from different authors and with a different
   start. What carries over is the direction: the bias random walk the figures give is too small. The size of
   the factor does not: here the adjustment is applied to figures that were already inflated.

**INTERPRETATION:** Which runs are lost changed between two filter versions, so read individual lost runs as sensitive and the counts as approximate.

## Reproduce

```bash
navkit tumvi fetch --sequence room1          # repeat for each room; about 1.7 GB each, deleted after extraction
navkit euroc compare --dataset tumvi --configs file,allan,file-walk10 --csv docs/data/tumvi_compare.csv --page docs/tumvi.md --block tumvi
navkit euroc compare --from-csv docs/data/tumvi_compare.csv --page docs/tumvi.md --block tumvi   # rebuild the table only
```
