# ADR-0004: Fix the internal quaternion order and centralise conversion

- Status: accepted
- Date: 2026-09

## Context

`navkit` stores quaternions as `(w, x, y, z)` internally. TUM and Plotly files
store `(x, y, z, w)`. EuRoC stores `(w, x, y, z)`.

Six call sites in `io/trajectory.py` got this wrong, in both directions:

| Function | On disk | Behaviour | Correct? |
|---|---|---|---|
| `_read_tum` | `qx qy qz qw` | passed slice straight through | wrong |
| `_read_plotly` | `qx qy qz qw` | passed slice straight through | wrong |
| `_read_euroc` | `qw qx qy qz` | needlessly rotated to `x y z w` | wrong |
| `_read_euroc_txt` | `qw qx qy qz` | needlessly rotated to `x y z w` | wrong |
| `write_tum` | wants `qx qy qz qw` | wrote `w x y z` | wrong |
| `write_euroc` | wants `qw qx qy qz` | wrote `w x y z` | correct |

Every one of these produced a **unit quaternion and a perfectly orthonormal,
right-handed rotation matrix of the wrong orientation**. Shape checks pass,
`R @ R.T == I` passes, `det(R) == 1` passes. Only comparison against a known
rotation catches it.

Concretely, the first pose of the TUM VI room1 basalt estimate was read as a
near-180-degree flip about a vertical axis. End-to-end ATE against the
published ground truth was 0.098 m after the fix, versus an orientation that
was simply wrong before it. The module docstring had claimed "the conversion
is unit tested"; the module sat at 10.6% coverage.

## Decision

- Add two named helpers, `xyzw_to_wxyz` and `wxyz_to_xyzw`, and require all
  conversion to go through them. A bare `[3, 0, 1, 2]` at a call site is a
  review-blocking defect.
- Make the per-format layout a documented, tested property of each reader.
- Test against *specific known rotations*, not structural invariants.
- Add an end-to-end check against the published TUM VI room1/512/16 ATE
  (0.069 m), skipped when the dataset is absent. (Replaced later: the reference files could not be fetched, so the
  test always skipped. A gyroscope check on recorded data took its place; see R5 in `CONSTRAINTS.md`.)

## Consequences

- `io/trajectory.py` coverage 10.6% -> 89.7%.
- Real dataset ingestion works for the first time.
- Two further defects surfaced while fixing these and were fixed in the same
  change: `_read_rows` truncated every row to 8 columns, making the EuRoC
  velocity branch unreachable; and that branch sliced `a[:, 14:17]`
  (accelerometer bias) instead of `a[:, 8:11]` (linear velocity).
- The lesson is recorded as constraint C2 in `CONSTRAINTS.md`: a
  mathematically valid but semantically wrong quantity must be tested against
  a known answer, never only against its invariants.
