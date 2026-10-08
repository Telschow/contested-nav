# Demo

A 25-frame visualisation of the headline case, generated from the benchmark.

## What it does

`scripts/generate_demo.py` calls `navkit.benchmark.run_case` for the `outage_visual` case of
`configs/benchmark.yaml`. That is the function behind every number in the documentation, so
the demo cannot disagree with the benchmark. It then draws 25 frames at evenly spaced times
across the 30 s run.

Each frame shows:

| Element | Source |
|---|---|
| Ground truth (green) and estimate (red), north against east, up to the frame time | `trajectory_ref` and `trajectory_est` in the record |
| Orange underlay on the part of the path flown with GNSS denied | the scenario's `gnss_outages` |
| GNSS available or denied at the frame time | the same outage windows |
| Vision fused or off | the estimator configuration |
| Gate counters, whole run | `summary.fdir_gnss_accepted` and `fdir_gnss_rejected` |
| Position error at the frame time | `error_time_series` |
| Claimed 1-sigma, mean NEES, 2-sigma-per-axis coverage, verdicts | the headline of the run |

The claimed sigma, NEES and coverage are whole-run values, not values up to the frame time.

## Run it

```bash
python scripts/generate_demo.py --out artifacts/demo
```

Outputs: `frames/frame_00001.png` to `frame_00025.png`, `snapshot.png` (a copy of the last
frame), `results.json` (the benchmark record plus `trajectory_est` and `trajectory_ref`) and
`metadata.json`. The committed preview is `docs/architecture/demo-snapshot.png`.

## What the final frame must show

ATE RMSE 2.506 m, claimed 1-sigma 0.161 m, mean NEES 391.2, coverage 20.0%, verdict
overconfident. `tests/test_demo_generation.py` compares the demo's headline with the
committed benchmark snapshot and fails on any difference.

For the same result as a figure, see `docs/figures/`.

## History

An earlier version of this demo had its own copy of the filter configuration and drifted from
the benchmark: it reported mean NEES 1.4e10 and a claimed sigma of 7 mm while the README said
419.4 and 0.161 m, and its tests only checked that the values were plausible. It also showed
"VISION DISABLED" until 8 s and "FDIR MONITORING" after 19 s, which the run does not do, and
shaded the GNSS outage on the position axis as if it were time. An interactive page,
`docs/architecture/demo.html` (11 MB), embedded a raw pixel buffer labelled as a PNG that a
browser cannot render, and typed the headline numbers by hand. All of that was removed.

## Limitations

* One run of one case. There is no seed sweep, scene sweep or outage sweep in the demo.
* The uncertainty drawn is the position sigma only; attitude and the full ellipsoid are not shown.
* There is no animation file. The frames are PNGs.
