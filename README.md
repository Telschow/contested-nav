# contested-nav

**Is the filter right about how wrong it is?**

[![CI](https://github.com/Telschow/contested-nav/actions/workflows/ci.yml/badge.svg)](https://github.com/Telschow/contested-nav/actions/workflows/ci.yml)
[![Security](https://github.com/Telschow/contested-nav/actions/workflows/security.yml/badge.svg)](https://github.com/Telschow/contested-nav/actions/workflows/security.yml)
[![Docs](https://github.com/Telschow/contested-nav/actions/workflows/pages.yml/badge.svg)](https://telschow.github.io/contested-nav/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## In 60 seconds

**Problem.** A navigation filter has to be right about its own position and also right about how
sure it is. A drone that has lost GNSS and is steered by a filter that is wrongly confident will
trust a position it should not.

**Decision.** Should camera-based motion tracking be switched on when GNSS is denied? It makes the
position error smaller (3.760 m to 2.322 m) but the filter then claims to be within 0.162 m. It
is accurate and confidently wrong, so it **ships off by default**
([ADR-0003](docs/adr/0003-ship-visual-disabled.md)).

**Evidence.** The result held for every one of 10 noise seeds and every one of 40 outage runs, and
the numbers in the table below are regenerated and checked by CI. It is synthetic data, not a field
test.

**Next step.** The fix is a change to how the filter treats the visual anchor, which the
[roadmap](ROADMAP.md) calls B1. It is not built. The bar for turning vision on is written down: a
mean NEES below 10 and a 2σ coverage above 90% with GNSS denied.

![Position error against the uncertainty the filter claims, through a GNSS outage, without and with vision](docs/figures/hero.png)

A 21-state error-state Kalman filter and an evaluation harness for GNSS-denied navigation.
It measures not only how accurate the trajectory is, but whether the uncertainty the filter
reports is honest. With GNSS denied and visual odometry on, the filter's position error
falls from 3.760 m to 2.322 m while its claimed uncertainty collapses to 0.162 m:

| Configuration | ATE RMSE | Claimed 1σ | Mean NEES (expected 3) | 2σ-per-axis coverage (expected 99.3%) |
|---|---:|---:|---:|---:|
| GNSS denied, vision off | 3.760 m | 0.567 m | 4.1 | 100.0% |
| GNSS denied, vision on | **2.322 m** | **0.162 m** | **286.2** | **20.5%** |

**Accuracy improved. Calibration failed.** The filter converges and is confidently wrong, so
visual fusion ships **off by default**. Across 8 outage windows the overconfidence held in
every run; the accuracy gain did not (see [what the sweeps show](#what-the-sweeps-show)).

A stochastic clone of the previous pose (opt-in, `vision_model: clone`,
[ADR-0017](docs/adr/0017-stochastic-clone-for-the-visual-update.md)) is calibrated on the same fixture; see the
clone rows in the table below. It is a synthetic result, the default is unchanged, and visual fusion still ships
off.

> **Synthetic evidence only.** Every number comes from a deterministic known-answer fixture: an
> analytic trajectory with generated sensor streams. No real sensor capture is evaluated and
> no number here is a field measurement.

## Quickstart

Python 3.11 to 3.13. From a fresh clone this took **18.7 s** (clone, environment, install and a
three-case run) on the machine that wrote this page:

```bash
git clone https://github.com/Telschow/contested-nav.git && cd contested-nav
python -m venv .venv && .venv/bin/pip install -e .
.venv/bin/navkit run --only gnss_only outage_control outage_visual --markdown
```

`make repro` regenerates every figure and table from scratch in about 5 minutes (321 s
measured). More in [Getting started](docs/getting-started.md).

## Results

Synthetic 30 s run, 5 Hz GNSS, 20 Hz vision, noisy IMU, seed 0. ATE uses `alignment=none`: the
filter starts in the reference frame, so there is no offset for a fitted transform to absorb.

| Scenario | ATE RMSE (m) | Claimed 1σ (m) | Mean NEES (exp. 3) | Coverage @ 2σ | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| GNSS only (control) | 0.528 | 0.254 | 4.3 | 100.0% | mixed: bulk overconfident, tail underconfident |
| Dead reckoning (no aiding) | 2.359 | n/a | n/a | n/a | no covariance reported |
| Anchor as measurement noise (defect) | 1.063 | 0.094 | 163.7 | 16.3% | overconfident |
| Vision only | 2.321 | 0.158 | 264.2 | 0.7% | overconfident |
| GNSS denied 5–20 s, vision off (control) | 3.760 | 0.567 | 4.1 | 100.0% | mixed: bulk overconfident, tail underconfident |
| GNSS denied 5–20 s, vision on | 2.322 | 0.162 | 286.2 | 20.5% | overconfident |
| GNSS denied, 30% camera frames dropped | 2.008 | 0.192 | 203.7 | 17.8% | overconfident |
| GNSS denied 5–20 s, vision on, stochastic clone | 0.725 | 0.375 | 2.5 | 100.0% | underconfident |
| GNSS denied, 30% frames dropped, re-referenced, single anchor | 1.973 | 0.192 | 191.5 | 17.7% | overconfident |
| GNSS denied, 30% frames dropped, re-referenced, stochastic clone | 0.503 | 0.307 | 2.2 | 100.0% | underconfident |
| Vision only, stochastic clone | 1.959 | 1.326 | 2.3 | 100.0% | underconfident |
| Stochastic clone, 5% gross visual outliers | 0.727 | 0.382 | 2.5 | 100.0% | underconfident |
| Stochastic clone, drifting translation scale | 0.787 | 0.375 | 2.9 | 100.0% | underconfident |
| Stochastic clone, visual errors correlated over 2 s | 1.931 | 0.375 | 13.1 | 58.3% | overconfident |
| Stochastic clone, correlated errors, visual noise assumed 4x | 2.259 | 0.531 | 4.9 | 100.0% | mixed: bulk overconfident, tail underconfident |

This table is generated by `navkit run --markdown`, and CI fails if any cell disagrees with the
code. Interpretation, the four ATE alignments and the figures are on the
[Results page](docs/results.md).

## What the sweeps show

- **Not a bad seed.** Over 10 noise seeds, `outage_visual` is overconfident at every one: mean
  NEES 656, range 113.5 to 1589.1, coverage 6.8% to 35.2%. Over 8 synthetic trajectories all
  seven case verdicts are unchanged.
- **Not a long-outage effect.** Over 8 outage windows (start 5 s or 10 s, length 5 to 20 s, 5
  seeds each) the visual case had a 2σ coverage of 10.4% to 39.0% in all 40 runs, including 5 s
  outages. The no-vision control stayed at 98.0% to 100.0%.
- **The accuracy gain is not general.** With the outage starting at 5 s, vision beat the
  control in every seed for outages of 10 s or longer. With it starting at 10 s, vision was
  worse in all 20 runs. The cause is not tested here.

## Limits

- **Not field validated.** Synthetic fixture only; no real capture is vendored or evaluated.
- **Visual fusion under GNSS denial is not trustworthy.** The cause is structural (the visual
  anchor is a pose the filter itself produced) and the established remedies are not implemented
  here. See [Concepts](docs/concepts.md#the-one-thing-this-cannot-do).
- **FDIR detects implausible updates but does not explain them,** and one spoofing case
  (a modest offset after an outage) is documented as undetected
  ([ADR-0007](docs/adr/0007-spoof-permanence-hysteresis.md),
  [ADR-0008](docs/adr/0008-frozen-anchor-cross-check.md)).
- **Not flight-ready:** no sensor driver, no live front end, no real-time loop.

All of it, with sources, is in [Status and limits](docs/status.md) and
[Limitations](docs/defense/LIMITATIONS.md).

## How this was built

- The code was written mostly by an AI coding assistant (Claude Code). The commit trailers and the
  `claude/*` branch names show which changes.
- The maintainer sets the scope and the order of work, and decides what ships. Changes land through a
  pull request that the maintainer merges, and releases are tagged by the maintainer.
- The assistant's work is not trusted on sight. Gates decide: finite-difference checks on the
  Jacobians, property tests, a golden snapshot of the benchmark, a coverage ratchet, CI on three
  Python versions and three operating systems, CodeQL and a secret scan.
- Every number in the README is generated, and a test fails when a table cell disagrees with the
  code.
- Defects found this way are in the [changelog](CHANGELOG.md), including one in this repository's
  own test setup ([ADR-0012](docs/adr/0012-every-scenario-is-injected.md)).
- What stays with a person: which claims to make. The headline is a negative result, and it was
  kept.

## Scope and responsible use

This is a research and evaluation library built from public sources and synthetic data. It
contains no real sensor data or drivers, no radio-frequency model (a GNSS outage is a gap in a
stream; spoofing tests inject offsets into the filter), and no guidance, targeting or platform
integration code. It is not a navigation product and is not qualified for any platform. To the
maintainer's knowledge nothing in it is classified or restricted, but that is not a legal
determination: check your own obligations before using it in a regulated or operational setting.
Details in [Scope and responsible use](docs/scope.md); report a vulnerability through the
[security policy](SECURITY.md).

## Documentation

The site is at [telschow.github.io/contested-nav](https://telschow.github.io/contested-nav/);
every page is also a Markdown file under `docs/`.

| If you want | Read |
|---|---|
| To run it | [Getting started](docs/getting-started.md) |
| The argument and the mechanism | [Concepts](docs/concepts.md), [calibration](docs/calibration.md) |
| What the filter assumes, every config key, the result format | [Model and interface contract](docs/MODEL.md) |
| How fast it is, measured | [Performance](docs/PERFORMANCE.md) |
| Decisions of record | [Architecture decision records](docs/adr/index.md) |
| What is planned | [ROADMAP](ROADMAP.md), [CHANGELOG](CHANGELOG.md) |
| How to contribute | [CONTRIBUTING](CONTRIBUTING.md), [code of conduct](CODE_OF_CONDUCT.md) |

## Layout

```text
src/navkit/   estimators (ESKF, dead reckoning), fdir, sensors, degrade, eval, geometry, io
configs/      benchmark scenarios (configs/benchmark.yaml)
scripts/      thin wrappers, coverage ratchet, doc-table and link checks, secret scan
benchmarks/   timing harness for docs/PERFORMANCE.md
docs/         site pages, ADRs, figures, defense assessment, product management
tests/        unit, property, golden-snapshot and documentation consistency tests
```

## License

MIT. See [LICENSE](LICENSE).
