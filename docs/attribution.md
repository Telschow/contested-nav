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
| baseline | 21.87 | +0% |
| no accelerometer bias | 21.78 | +0% |
| no gyroscope bias | 21.85 | +0% |
| no accelerometer white noise | 21.87 | +0% |
| no gyroscope white noise | 21.83 | +0% |
| no inertial errors | 21.72 | -1% |
| start known exactly | 1.94 | -91% |
| start known exactly, no inertial errors | 1.88 | -91% |
| GNSS noise x0.5 | 17.30 | -21% |
| GNSS noise x0.1 | 4.90 | -78% |

<!-- attribution-ablation:end -->

## 2. How large a source has to be before it matters

Each source is scaled up alone, in the data and in the filter's model. The cell is the peak error and its change from
the baseline.

<!-- attribution-escalation:start -->

| Source scaled up | x3 | x10 | x30 | x100 |
|---|---:|---:|---:|---:|
| accelerometer bias | 22.08 (+1%) | 22.96 (+5%) | 25.74 (+18%) | 34.37 (+57%) |
| gyroscope bias | 21.91 (+0%) | 22.08 (+1%) | 22.76 (+4%) | 26.81 (+23%) |
| accelerometer white noise | 21.88 (+0%) | 21.98 (+0%) | 22.83 (+4%) | 31.14 (+42%) |
| gyroscope white noise | 22.01 (+1%) | 23.11 (+6%) | 33.02 (+51%) | 86.80 (+297%) |

<!-- attribution-escalation:end -->

## 3. How the error grows with the length of the outage

The peak error for outages of increasing length on a fixture four times as long, with the same motion, and the
exponent of the power law fitted to it. Each source has its own textbook exponent, listed under the table, so a fitted
exponent points to the source. The inflated rows make one source clearly the largest and check that the method finds
its exponent.

<!-- attribution-growth:start -->

| Case | 5 s | 15 s | 45 s | 90 s | Fitted exponent |
|---|---:|---:|---:|---:|---:|
| baseline | 5.4 | 28.1 | 204.4 | 781.1 | 1.72 |
| no inertial errors | 5.4 | 28.0 | 202.6 | 764.8 | 1.72 |
| accelerometer bias x100 | 6.5 | 37.7 | 276.7 | 1070.4 | 1.77 |
| gyroscope bias x300 | 6.8 | 48.1 | 741.1 | 6186.2 | 2.35 |
| accelerometer white noise x100 | 6.3 | 28.1 | 192.1 | 724.5 | 1.64 |
| gyroscope white noise x30 | 6.4 | 42.6 | 343.2 | 1249.2 | 1.83 |

Textbook exponents: velocity error at the start 1, accelerometer white noise 1.5, accelerometer bias 2, attitude error at the start 2, gyroscope white noise 2.5, gyroscope bias 3.

<!-- attribution-growth:end -->

## 4. A bias fault

A step in the accelerometer bias on one axis at the start of the outage, of several sizes. During the denial nothing is
measured, so nothing can notice it. The question is what happens when GNSS returns.

<!-- attribution-fault:start -->

| Bias step, m/s² | Peak error inside the outage, m | Change | GNSS fixes rejected after the outage | Runs with the GNSS channel declared faulty | Error 4 s after the outage, m |
|---:|---:|---:|---:|---:|---:|
| 0 | 26.6 | +0% | 0 | 0% | 0.3 |
| 0.05 | 27.4 | +3% | 0 | 0% | 0.3 |
| 0.2 | 36.3 | +37% | 0 | 0% | 0.6 |
| 1 | 114.6 | +331% | 51 | 100% | 183.6 |

<!-- attribution-fault:end -->

## What it shows

Each statement is checked against the CSV by `tests/test_attribution_page.py`.

1. **Removing an inertial error source does not change the outage error.** No single source, and not all of them
   together, moves the peak error inside the outage by as much as two percent.
2. **Making the filter's start exact does.** Telling the filter that its starting pose, velocity and attitude are
   exact cuts the peak error by more than eighty-five percent, with or without the inertial errors; and a GNSS ten
   times quieter cuts it by more than seventy percent. The error is set by how the filter handled the GNSS noise
   before the outage, not by the inertial unit.
3. **A source has to be far larger than the unit's before it matters.** Scaled by three or by ten, no source moves
   the error by as much as ten percent; scaled by a hundred, every source raises it by more than twenty percent, and
   gyroscope white noise is the first to matter.
4. **The error grows the same way with or without inertial errors.** The fitted exponent of the baseline equals that
   of the run without any inertial error to within a twentieth, and lies between one and two, which is a mixture of
   a velocity error and an attitude error at the start and not a constant accelerometer bias (two) or gyroscope
   bias (three).
5. **The method finds a source when there is one.** Inflating the gyroscope bias raises the exponent by more than
   half; inflating any other source leaves it within a fifth of the baseline's.
6. **A small bias fault is not noticed and a moderate one is not either.** A step of 0.05 m/s² changes the peak error
   by under ten percent, and a step of 0.2 m/s² by about a third; in neither case is a GNSS fix rejected when GNSS
   returns, or the channel declared faulty.
7. **A large bias fault makes the filter reject the healthy GNSS.** A step of 1 m/s² makes the filter reject the fixes
   that follow the outage and declare the receiver faulty in every run, and four seconds after the return the error
   is larger than at the worst point of the outage. The receiver is blamed for a fault in the inertial unit. This is
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
