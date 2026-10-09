# ADR-0016: TUM VI as a second recorded dataset

- Status: proposed
- Date: 2026-10
- Related: [ADR-0013](0013-recorded-imu-with-simulated-gnss.md), [ADR-0014](0014-textbook-imu-process-noise-by-default.md)

## Context

Everything measured on a recorded IMU so far comes from one dataset, EuRoC, with one IMU (ADIS16448). The
noise settings that work there (ADR-0014, the bias random walk scaled up) are tunings for that sensor and
those recordings, and the question of whether they carry over to another sensor has no answer.

TUM VI is published under CC BY 4.0, which fits an MIT repository so long as the data is attributed and not
redistributed. Its six room sequences have motion-capture ground truth for the whole trajectory, in the IMU
frame and time-aligned to it by the authors, and it has a different IMU (a BMI160). Its authors also
publish noise figures twice in one file: the raw ones from their Allan plots, and ones they inflated "to
account for unmodelled effects", with the white noise multiplied by 2 and the bias random walk by 10. That
makes a test that was not designed around the EuRoC finding: if the bias random walk is what the raw figures
understate, the raw set should lose runs and the inflated set should lose fewer.

## Options

1. **Stay on EuRoC.** One sensor. The settings stay unchecked elsewhere.
2. **Add TUM VI, simulated GNSS as for EuRoC.** Same method and the same caveats as ADR-0013. A second
   sensor, a second set of recordings, and a clear licence.
3. **Add a dataset with real GNSS.** The honest test. The candidate (UrbanNav) has no confirmed licence yet.

## Decision

_To be written by the maintainer._

## What the code does in the meantime

It implements option 2. `navkit tumvi fetch` downloads whole archives (a TAR has no index at the end, so the
byte-range reading used for EuRoC does not apply), checks them against the publisher's MD5 file, keeps three
small files per sequence and deletes the archive. `navkit euroc run` and `navkit euroc compare` take
`--dataset tumvi`. The ground truth has no velocity or bias columns, so the start velocity is a local line fit
to the motion-capture positions and the start biases are estimated from the quietest stretch of the first
seconds, using the ground-truth attitude. A result says which, and the sequences that never rest are flagged.

The results and the statements checked against them are on [the TUM VI page](../tumvi.md).

## What this does not settle

- GNSS is still simulated, so nothing here is GNSS-denied navigation in the field.
- The start bias is an estimate and not the truth, which makes a TUM VI run harder to start than a EuRoC one.
  The two datasets differ in that, as well as in sensor, so a difference between them is not only the sensor.
- The settings compared on TUM VI were not tuned on it. They were chosen from the EuRoC work or are the
  dataset authors' own. Any setting chosen on TUM VI from here on is in-sample on it.
