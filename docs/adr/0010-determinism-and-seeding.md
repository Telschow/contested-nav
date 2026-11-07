# ADR-0010: Determinism and seeding policy

- Status: accepted
- Date: 2026-10

## Context

Every number in the documentation is meant to be reproducible, and the central claim is
about a distribution (is the filter calibrated across draws?), so how randomness enters the
code decides whether a result can be trusted. The code already follows a policy; this ADR
writes it down so the next stochastic stream follows it too.

## Decision

1. **No global random state.** Every stochastic step draws from an explicitly seeded
   `numpy.random.Generator`. Nothing calls `np.random.seed` or the legacy global functions.
2. **Each stream has its own seed, and the seed is configuration.** GNSS noise
   (`gnss.seed`), vision noise (`vision.seed`) and camera drops (`camera_drop.seed`) are
   scenario fields. They are serialised into the result, and the result's `config_hash`
   covers them, so two results with different seeds cannot claim the same provenance.
3. **Derived seeds use a stable hash.** The IMU noise stream is seeded from
   `sha256("<scenario name>:imu:<gnss seed>:<vision seed>")`. Python's built-in `hash()` is
   salted per process and is not used for this.
4. **Sweeps override seeds, they do not add randomness.** `navkit sweep seeds` sets all three
   stream seeds to the same integer, which also changes the derived IMU seed.
   `navkit sweep scenes` varies the trajectory with `seeded_scene(cfg, seed)` and leaves noise
   alone, so the two axes are independent. Statistics that need randomness (the bootstrap
   intervals, 10,000 resamples) use a fixed seed in the code.
5. **Reproducibility is claimed in two scopes, and only these.**
   - *Same platform:* byte-identical output once wall-clock fields are stripped. CI runs the
     benchmark and the sweeps twice and diffs them.
   - *Across platforms and runners:* equal within the tolerances of the golden snapshot (a
     relative 1e-9 plus an absolute floor of 1e-9, and 1e-6 for the claimed-sigma series), set
     out in [ADR-0009](0009-cross-platform-numerics.md).
6. **Tests that search are derandomised.** Hypothesis runs with `derandomize=True` in CI, so a
   failure replays; a wider random search is a separate profile for exploring.

## Consequences

- A new stochastic stream needs a seed field in its config, a place in the config hash, and a
  test that two runs with the same seed agree and two seeds differ.
- **Renaming a scenario changes its IMU noise draw,** because the scenario name is part of the
  derived seed. The case names in `configs/benchmark.yaml` are therefore part of the result.
- Changing the order in which streams are generated changes every number downstream. The
  golden snapshot is what catches it.
- Results from different machines are comparable at the stated tolerances, not bit for bit.

## Alternatives rejected

- **A single global seed.** It would make every stream depend on the order of draws, so
  adding one sensor would silently change the others.
- **`hash()` for derived seeds.** Not stable across processes.
- **Tighter cross-platform tolerances.** They failed on identical code on different GitHub
  runners (see ADR-0009), which would have made the build flaky for a reason that is not a bug.

## Amendment (2026-11): one seed gives GNSS and visual rotation noise the same normals

[Issue #251](https://github.com/Telschow/contested-nav/issues/251), from the independent audit of 2026-11-01 (finding CN-01), found that decision 2 holds for the seed fields and not for the generators behind them. `gnss.seed` and `vision.seed` are separate fields, but the base cases and `navkit sweep seeds` give them the same integer (decision 4), and both streams then start `np.random.default_rng` from it. At equal seeds the GNSS white noise and the visual rotation noise are the same normal sequence. The filter assumes independent sensor noise. The visual translation noise already has a stream of its own ([ADR-0033](0033-one-convention-for-the-synthetic-visual-translation-noise.md)).

**What was measured.** The development seeds, 10 of them, were run twice: as they are, and with the vision seed derived from the case seed and a stream id ([issue #259](https://github.com/Telschow/contested-nav/issues/259), `docs/data/shared_stream_effect.csv`, `docs/calibration.md`). The result was within seed noise for the aggregate. The sign of the per-seed change was mixed, and the mean paired difference was within about one standard error of zero for ATE RMSE and mean NEES in all four cases. The single-anchor control stayed overconfident and the clone stayed calibrated. Single seeds moved far (seed 0 of `outage_visual`, 17.6 m to 7.9 m ATE). The comparison also changes the IMU noise draw, which is hashed from both seeds, so it measures both changes together. Ten seeds exclude a large systematic effect, not a small one.

**Follow-up: the two changes apart.** The study now has a third seeding, `streams_only`: the independent vision seed with the IMU noise pinned to its shared draw, for the duration of one run and with nothing in `src/navkit/degrade` changed. It gives the stream relationship alone, with the IMU fixed. The medians under it are generated on `docs/calibration.md` from `docs/data/shared_stream_effect.csv`. For every case the streams-only change is of the same size and sign as the combined change, so redrawing the IMU explains little of it. `outage_control`, which has no vision, comes out identical to the shared run, as it must. The sample is the same ten development seeds, so the earlier limit stands: a large systematic effect is excluded, a small one is not.

**Decision.** The streams are not changed. No committed number, table or golden is regenerated, and the B1 result in [ADR-0028](0028-the-b1-gate.md) stands as it was produced. The shared stream is documented instead, in `docs/MODEL.md` and in the calibration page, where the measurement is generated from its CSV.

- Decision 2 is read as: each stream has its own seed field. It does not say the generators differ when the values are equal.
- A new stochastic stream takes its own generator from `np.random.SeedSequence([seed, STREAM_ID])`, as the translation noise does, so it never repeats another stream.
- A value quoted for one seed carries the caveat above. Aggregates over the development seeds do not need it.

**What would reopen this.** A candidate or study whose result depends on the independence of the GNSS and visual rotation noise, or a measurement on more seeds that shows a systematic shift. The switch is then one change to `SeedSequence` streams for GNSS and vision, with every generated table and the golden snapshot regenerated, and a dated note on the calibration page.
