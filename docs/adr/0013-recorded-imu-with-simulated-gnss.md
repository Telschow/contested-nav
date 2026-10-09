# ADR-0013: Evaluate on recorded IMU data with GNSS simulated from the ground truth

- Status: accepted
- Date: 2026-10

## Context

Every result so far comes from a synthetic generator. The filter has never run on a recorded
inertial stream, so nothing here says how its covariance behaves on real noise, real bias drift
and real vibration.

The EuRoC MAV dataset has a recorded IMU and a ground-truth estimate, and no GNSS. Its rights
statement is "In Copyright - Non-Commercial Use Permitted", which is not an open licence. The
repository is MIT. Constraint S2 already forbids vendoring third-party data, so the files are
fetched locally and results (aggregate figures) are the only thing that may be committed.

Visual fusion stays off (S3), so the images are not used.

## Options

1. **Recorded IMU, GNSS simulated from the ground truth.** The code in `navkit.euroc_eval` does
   this. It reuses the benchmark's GNSS model and outage mechanism, and the same NEES and
   coverage scoring. The inertial side is real. The aiding side is not.
2. **Recorded IMU, no aiding.** Scores drift against the reference. It says nothing about
   calibration under aiding, which is the question the project asks.
3. **Recorded IMU and recorded images.** Needs a visual front end this project does not have, and
   S3 keeps fusion off.
4. **Wait for a dataset with real GNSS and real outages.** The honest test, and not yet
   available to this project.

## Decision

Option 1. The filter is evaluated on recorded EuRoC IMU data with GNSS simulated from the
ground truth. It is the only option available now that tests calibration under aiding, which is the
question the project asks. Options 2 and 3 do not test it or need a front end that constraint S3
keeps off, and option 4 needs a dataset that is not usable yet.

Results from this path may appear in the README or the docs only if the simulated GNSS, the preset
and the runs that still fail are stated next to them. A median alone would hide the failures.

This stands until a dataset with real GNSS and real outages can be used. UrbanNav is the intended
next step if its licence allows it. If it does not, this record is unchanged.

## What the code does in the meantime

It implements option 1, labels every result `data_class: real_imu_simulated_gnss`, and lists the
caveats in the record. Nothing in the README or docs quotes a result from it. `navkit euroc
selftest` exercises the whole path on a synthetic sequence in the EuRoC file layout, so the tool
chain can be checked before any real file is on disk.

## What this does not settle

- Simulated fixes have no multipath, no lever arm, and perfect time alignment with the reference.
  A result is not GNSS-denied performance in the field.
- The start pose and velocity come from the ground truth. That is an ideal initial alignment.
- The ground truth is itself an estimate, and the dataset's notes say its synchronisation with the
  sensors is limited.
- The process-noise form that made real-data covariances look overconfident was found while building
  this and is handled separately in [ADR-0014](0014-textbook-imu-process-noise-by-default.md).
- The IMU noise the datasheet gives understates the real error growth of the EuRoC IMU. `navkit euroc run
  --preset adis16448` inflates it; that is a tuning for one sensor. It was checked on all eleven EuRoC sequences and still fails on a few runs.
