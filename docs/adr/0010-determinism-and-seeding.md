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
