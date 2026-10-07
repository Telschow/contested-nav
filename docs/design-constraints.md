# Design constraints

These are decisions, not preferences, and they are why the dependency list is
short. See [CONSTRAINTS.md](https://github.com/Telschow/contested-nav/blob/main/CONSTRAINTS.md).

- Pure Python + NumPy at runtime. No compiled extension to build, no BLAS
  requirement to satisfy, no solver to license.
- Seeded and reproducible. Two runs of the benchmark must be identical apart
  from wall-clock timings, and CI fails if they are not.
- Coverage is a ratchet, not a report. Every module has a floor; a drop fails
  the build.
- No vendored datasets. Reproducibility comes from seeded configs and committed
  figures, not from committing megabytes of capture.
- Claims are typed `FACT`, `MEASUREMENT`, `INTERPRETATION` or `HYPOTHESIS`, and
  a synthetic result is never presented as a field measurement.
