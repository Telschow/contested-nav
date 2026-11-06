# ADR-0043: Camera-IMU extrinsic and time-offset sensitivity

- Status: proposed
- Date: 2026-11
- Related: [ADR-0036](0036-b1-is-closed-as-characterised-not-solved.md), [fault matrix](../faults.md), [model assumptions](../MODEL.md), [issue #117](https://github.com/Telschow/contested-nav/issues/117)

This record has its context and options. The decision section is the maintainer's to write. No code is written until it is.

## Context

**What the filter assumes. FACT, from `docs/MODEL.md` and the sensor models.** The camera-to-IMU extrinsic is the identity. Each visual measurement is applied at the next IMU tick. Neither is estimated.

**What exists today.** Timestamp offsets for the IMU, GNSS and vision streams can be injected (`imu_time_offset_s`, `gnss_time_offset_s`, `vision_time_offset_s`). The fault matrix measures the GNSS and the vision offsets. It does not measure the IMU offset. On recorded data, the UrbanNav page runs a GNSS clock shift on Deep-Urban-1 only. No run perturbs the rotation part of the extrinsic, on synthetic or recorded data.

**What a run would answer.** How far a rotation error in the extrinsic and a time offset move NEES and the gate verdict. This is a sensitivity measurement. Estimating either as a state is out of scope.

**What it does not change.** `vision_enabled` stays False (B1 is closed as characterised, ADR-0036). A result here is a statement about the identity assumption, not a proposal to switch vision on.

## Options

(a) Leave the assumption as documented. Cost: none. The identity extrinsic stays an unmeasured assumption.

(b) A synthetic sensitivity sweep. Perturb the extrinsic rotation and the visual time offset on the synthetic vision stream, on development seeds only, and report NEES and the gate verdict per setting. Grid and scenario declared before the run. The IMU offset can join the same grid. Cost: one study module, one CSV, one page section, tests tying the prose to the rows.

(c) Option (b), plus a perturbation of the known calibration of a recorded front end, so the sweep also has a recorded case. Cost: only the recordings that carry a calibration qualify, and a fetched dataset is needed to rerun.

(d) Estimate extrinsic and offset as filter states. Out of scope of the issue. Listed so the choice not to is on record.

## Decision

To be written by the maintainer.

## Consequences

To be confirmed with the decision. If (b) or (c) is chosen:

- The grid (angles, offsets), the scenarios and the definition of "moves the verdict" are declared in code before any run.
- Development seeds only. No held-out seed is run.
- The measurement is added next to the fault matrix, generated and checked in CI, labelled synthetic where it is.
- A result that shows large sensitivity is a limitation on the identity assumption. It is not a reason to change a default.
- No runtime dependency changes.
