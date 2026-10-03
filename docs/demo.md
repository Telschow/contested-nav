# Demo – GNSS‑Denied Navigation with Visual Aiding

## Overview

This repository ships a deterministic, end‑to‑end visualisation of the headline scientific result:

> **The filter can become highly confident while being materially wrong under GNSS denial / visual aiding.**

The animation is generated from the actual navkit estimator/FDIR pipeline – no numbers are hand‑typed into the source code. It reproduces the same computation that produces every number in the documentation, so the rendered sequence is an exact, machine‑readable slice of the repository’s CI output.

## What the Demo Shows

The visual follows the storyboard described in the implementation plan:

| Phase | Time (s) | What happens |
|-------|----------|--------------|
| **Normal** | 0‑4 | GNSS‑aided navigation; filter follows ground truth. |
| **GNSS denial** | 4‑8 | GNSS measurements stop; outage marker appears. |
| **Visual aiding** | 8‑14 | Visual odometry continues; estimated trajectory begins to diverge from truth. |
| **Calibration problem** | 14‑19 | Actual position error exceeds the filter’s claimed uncertainty; NEES and coverage shown. |
| **FDIR response** | 19‑23 | Fault‑isolation detector monitors the situation. |
| **Freeze** | 23‑25 | Final quantitative result displayed.

The key distinction is **CONFIDENT ≠ CORRECT** – the filter reports tiny uncertainty while being tens of metres wrong.

## How to Run the Demo

```bash
# From the repository root:
cd /mnt/immich/projects/contested-nav
python scripts/generate_demo.py --out artifacts/demo
```

This command runs the deterministic ``outage_visual`` scenario through navkit and creates three artefacts:

* ``artifacts/demo/results.json`` – full per‑epoch data (timestamps, position error, covariance, NEES, coverage, etc.)
* ``artifacts/demo/metadata.json`` – reproducibility metadata (seed, scenario, estimator version, etc.)
* ``artifacts/demo/snapshot.png`` – a static 1920×1080 thumbnail of the final frame (also stored as the 25th animation frame)

All numbers in the output are derived from the navkit execution; no constants such as ``2.541``, ``0.161``, ``419.4`` or ``20.0%`` are hard‑coded.

If the implementation changes (e.g., a new estimator version or a fix to the covariance model), the demo will automatically update and reflect the new values.

## Visual Design

* **Aesthetic** – dark neutral background, restrained technical typography, monospace numbers.
* **Composition** – ground‑truth trajectory (green), estimated trajectory (red), uncertainty ellipse where available, GNSS outage marker, status panel.
* **Animation** – 25 frames, one per logical second, showing the progression from normal navigation through the divergence phase.
* **Metrics panel** – live display of position error, claimed ``1σ``, mean NEES and ``2σ`` coverage.
* **Headline panel** – the final quantitative result (ATE RMSE, claimed 1σ, NEES, coverage, verdict).

The animation is intended as an engineering aid – it makes the mismatch between claimed and actual error visible without sensationalism.

## Data Integrity

All visualised numbers are taken from:

1. **navkit execution** – the `ErrorStateKalmanFilter` run for ``outage_visual``.
2. **results.json** – machine‑readable record of the per‑epoch state.
3. **metadata.json** – provenance information (seed, scenario, etc.).

No manual copying or hard‑coding of metrics occurs. The demo therefore satisfies the repository’s requirement that “no figure or table in this README is typed in by hand”.

## Reuse and Extension

* The script ``scripts/generate_demo.py`` can be adapted for other scenarios (e.g., ``vision_only``, ``gnss_only``).
* The JSON output can be consumed by downstream analysis tools or documentation generators.
* The animation frames can be assembled into a video (MP4/GIF) if a codec is available, though the repository currently ships the PNG sequence as the primary artefact.

## Limitations

* The animation is a single‑run demonstration; it does not include statistical sweeps (seed sweep, scene sweep).
* The visual representation of uncertainty is limited to the position covariance reported by the filter – attitude uncertainty and higher‑dimensional ellipsoids are not shown.
* The demo does not reproduce the ``vision_anchor_modelled = False`` defect row, which is kept only as a regression control in the benchmark suite.

## License

The demo is released under the same MIT licence as the rest of the repository. Use, modification and distribution are permitted provided the licensing terms are preserved.

## References

* Project README – the demo implements the scenario described in the ``README.md`` ``Results`` section.
* `CONTRIBUTING.md` – guidelines for running local quality gates (pytest, ruff, mypy, coverage).
* `docs/product_management/01_system_requirements_spec.md` – acceptance criteria for the GNSS‑denied case.
* `scripts/run_benchmark.py` – the underlying benchmark driver that powers the demo.
* `docs/adr/` – design decisions (e.g., ADR‑0001, ADR‑0003, ADR‑0006) that shape the visualised scenario.
