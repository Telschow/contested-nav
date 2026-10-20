# Where the outage error comes from

The repository's mechanism library said that when GNSS is lost the error "accumulates from accelerometer bias", that
it would grow linearly with the length of the outage if a constant bias dominated, and it gave the tests that would
show otherwise. The research baseline listed those tests as the most valuable unrun experiment, and the limitations
page (L8) listed a related one: would a bias fault be noticed? This page runs them.

## Read this first

- **Synthetic fixture only.** Everything here is the `outage_control` case: GNSS lost from 5 s, no vision, the
  benchmark's inertial unit. That unit is good relative to its GNSS. This says what drives the error *in this
  fixture*. It says nothing about the dominant source in a recording; on the [EuRoC](euroc.md) and [TUM VI](tumvi.md)
  recordings the bias random walk turned out to matter a great deal.
- **The metric is the peak error inside the outage.** Not the error at the outage's last instant. The first GNSS fix
  after the outage collapses the error, so the last instant measures the recovery. (An early version of this
  experiment used the last instant, and concluded wrongly that inertial errors did not matter and that GNSS noise sets
  the floor. A test now pins the distinction.)
- **Recovery is measured over a window.** Where this page says where the error is after GNSS returns, it uses two
  numbers over the epochs from 2 s to 6 s after the outage ends, the window being half-open (it includes its first
  instant and not its last). The *median* error is where the run is a few seconds after the return. The *largest*
  error shows a late spike that the median hides. A window with fewer than ten epochs is an error and not a guess.
  The older figure, the error at a single instant 4 s after the outage ends, is kept as the **legacy** column in the
  CSV and the fault table. It is not a measure of the end state: a recovery that happens slightly earlier or later
  moves it a lot while the run ends up in the same place.
- **The generator and the filter are told the same noise.** Removing a source removes it from the data and from the
  filter's model together. The filter is re-tuned for what remains.
- **Means over a few seeds.** Eight for the first two tables, five for the third and six for the fourth, so the
  baseline differs a little between them. The seeds vary the sensor noise only; the motion is the same.

## 1. What happens when one source is removed

Each row changes one thing and reports the peak position error inside the 15 s outage, averaged over seeds. "Start
known exactly" tells the filter that its starting pose, velocity and attitude are exact, which in this fixture they
are. The generated table is from [`data/attribution.csv`](data/attribution.csv); a test fails if they disagree.

<!-- attribution-ablation:start -->

| What changes | Peak error inside the outage, m | Change from baseline |
|---|---:|---:|
| baseline | 26.92 | +0% |
| no accelerometer bias | 26.90 | +0% |
| no gyroscope bias | 26.92 | +0% |
| no accelerometer white noise | 26.89 | +0% |
| no gyroscope white noise | 26.95 | +0% |
| no inertial errors | 26.89 | +0% |
| start known exactly | 0.95 | -96% |
| start known exactly, no inertial errors | 0.03 | -100% |
| GNSS noise x0.5 | 19.40 | -28% |
| GNSS noise x0.1 | 5.59 | -79% |

<!-- attribution-ablation:end -->

## 2. How large a source has to be before it matters

Each source is scaled up alone, in the data and in the filter's model. The cell is the peak error and its change from
the baseline.

<!-- attribution-escalation:start -->

| Source scaled up | x3 | x10 | x30 | x100 |
|---|---:|---:|---:|---:|
| accelerometer bias | 26.99 (+0%) | 27.32 (+1%) | 28.86 (+7%) | 35.03 (+30%) |
| gyroscope bias | 26.94 (+0%) | 27.01 (+0%) | 27.34 (+2%) | 29.86 (+11%) |
| accelerometer white noise | 26.99 (+0%) | 27.25 (+1%) | 28.34 (+5%) | 35.84 (+33%) |
| gyroscope white noise | 26.93 (+0%) | 27.44 (+2%) | 33.07 (+23%) | 84.32 (+213%) |

<!-- attribution-escalation:end -->

## 3. How the error grows with the length of the outage

The peak error for outages of increasing length on a fixture four times as long, with the same motion, and the
exponent of the power law fitted to it. Each source has its own textbook exponent, listed under the table, so a fitted
exponent points to the source. The inflated rows make one source clearly the largest and check that the method finds
its exponent.

<!-- attribution-growth:start -->

| Case | 5 s | 15 s | 45 s | 90 s | Fitted exponent |
|---|---:|---:|---:|---:|---:|
| baseline | 5.9 | 31.5 | 230.8 | 880.3 | 1.73 |
| no inertial errors | 5.9 | 31.5 | 229.5 | 867.6 | 1.73 |
| accelerometer bias x100 | 6.9 | 39.4 | 286.9 | 1107.3 | 1.76 |
| gyroscope bias x300 | 7.0 | 47.5 | 777.3 | 6532.7 | 2.36 |
| accelerometer white noise x100 | 6.1 | 27.5 | 197.5 | 761.8 | 1.68 |
| gyroscope white noise x30 | 6.7 | 41.4 | 332.8 | 1319.7 | 1.83 |

Textbook exponents: velocity error at the start 1, accelerometer white noise 1.5, accelerometer bias 2, attitude error at the start 2, gyroscope white noise 2.5, gyroscope bias 3.

<!-- attribution-growth:end -->

## 4. A bias fault

A step in the accelerometer bias on one axis at the start of the outage, of several sizes. During the denial nothing is
measured, so nothing can notice it. The question is what happens when GNSS returns. The last three columns are the
recovery: the median and the largest error over the window, then the legacy single instant.

<!-- attribution-fault:start -->

| Bias step, m/s² | Peak error inside the outage, m | Change | GNSS fixes rejected after the outage | Runs with the GNSS channel declared faulty | Median error 2 to 6 s after the outage, m | Largest error 2 to 6 s after the outage, m | Error at 4 s after the outage (legacy, one instant), m |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 29.6 | +0% | 0 | 0% | 0.3 | 0.7 | 0.3 |
| 0.05 | 29.9 | +1% | 0 | 0% | 0.3 | 0.6 | 0.3 |
| 0.2 | 35.1 | +19% | 0 | 0% | 0.6 | 0.8 | 0.6 |
| 1 | 113.0 | +282% | 51 | 100% | 181.1 | 220.8 | 181.2 |

<!-- attribution-fault:end -->

## What it shows

Each statement is checked against the CSV by `tests/test_attribution_page.py`.

1. **Removing an inertial error source does not change the outage error.** No single source, and not all of them
   together, moves the peak error inside the outage by as much as two percent.
2. **Making the filter's start exact does, partly by construction.** Telling the filter that its starting pose,
   velocity and attitude are exact cuts the peak error by more than eighty-five percent, with or without the
   inertial errors; and a GNSS ten times quieter cuts it by more than seventy percent. But the baseline now injects a
   start error drawn from the filter's declared prior ([ADR-0027](adr/0027-how-the-synthetic-runs-are-initialised.md)),
   so removing the start error removes that error. The experiment shows how large a prior-sized start error is next
   to the other error sources in this fixture. It does not show that the start error happens to dominate in nature.
   The error is not set by the inertial unit here.
3. **A source has to be far larger than the unit's before it matters.** Scaled by three or by ten, no source moves
   the error by as much as ten percent; scaled by a hundred, every source raises it by more than ten percent, and
   gyroscope white noise is the first to matter and by far the largest.
4. **The error grows the same way with or without inertial errors.** The fitted exponent of the baseline equals that
   of the run without any inertial error to within a twentieth, and lies between one and two, which is a mixture of
   a velocity error and an attitude error at the start and not a constant accelerometer bias (two) or gyroscope
   bias (three).
5. **The method finds a source when there is one.** Inflating the gyroscope bias raises the exponent by more than
   half; inflating any other source leaves it within a fifth of the baseline's.
6. **A small bias fault is not noticed and a moderate one is not either.** A step of 0.05 m/s² changes the peak error
   by under ten percent, and a step of 0.2 m/s² by about a fifth; in neither case is a GNSS fix rejected when GNSS
   returns, or the channel declared faulty.
7. **A large bias fault makes the filter reject the healthy GNSS.** A step of 1 m/s² makes the filter reject the fixes
   that follow the outage and declare the receiver faulty in every run, and over the window after the return the
   median error is larger than at the worst point of the outage (the legacy single instant says the same). The receiver is blamed for a fault in the inertial unit. This is
   the lockout mechanism behind the lost runs on the [EuRoC](euroc.md) and [TUM VI](tumvi.md) recordings.

## What it does not show

- It does not say that inertial errors never matter. It says that in this fixture, with this inertial unit and this
  GNSS, they do not, until a source is far larger than the unit's. A recording's unit is not this good, and there the
  bias random walk is what the filter needs to be told about.
- It does not separate the declared initial uncertainty from the GNSS noise: "start known exactly" removes both
  routes by which the filter's start state is wrong.
- The fault test uses one axis and a step. A ramp, a drift or a fault on another axis could behave differently.

## Reproduce

```bash
navkit sweep attribution --csv docs/data/attribution.csv --page docs/attribution.md   # about ten minutes
navkit sweep attribution --from-csv docs/data/attribution.csv --page docs/attribution.md   # the tables only
```
