# ADR-0026: UrbanNav as a dataset with real GNSS outages

- Status: proposed
- Date: 2026-10
- Related: [ADR-0013](0013-recorded-imu-with-simulated-gnss.md), [ADR-0016](0016-tum-vi-as-a-second-recorded-dataset.md), [UrbanNav](../urbannav.md)

## Context

Every recorded-data result so far uses a real IMU with GNSS simulated from the ground truth, as decided in ADR-0013 and ADR-0016. Both
records name a dataset with real GNSS and real outages as the honest test and left it open pending a licence.
The UrbanNav authors state that the dataset files are MIT licensed, and the LICENSE in their repository says so. The
Tunnel-1 sequence passes through a sea tunnel and contains a real GNSS outage. Its files have been fetched and read, and the
measurements are on [the UrbanNav page](../urbannav.md).

## Options

1. **Stay on simulated GNSS.** Nothing new is learned about calibration under real fixes.
2. **Tunnel-1, with the F9P's own NMEA fixes.** One real outage, real fix errors, an outage rule read from the
   receiver's fix flag. The reference is an estimate, and the rotation between the reference unit and the IMU is not
   in the files.
3. **Tunnel-1, with positions computed from the RINEX observations.** Needs navigation files that the download does not
   contain, and a position solver. More work, and the result would be this project's solver.
4. **Deep-Urban-1 as well.** Dense streets and small tunnels. Its outages are not annotated, so the rule would apply
   to a receiver file that has not been looked at yet.

## Decision

To be written by the maintainer.

## Evidence

The measurements and the run are generated on [the UrbanNav page](../urbannav.md) from committed CSVs. In short: the
Tunnel-1 files read cleanly, the two clocks agree to within the search step, the F9P stream has one outage, and the
fixes next to that outage are badly wrong while marked valid. The outage rule was fixed before any filter ran and has
not been changed since.

The filter was then run on it with the settings of option 2. Through the real outage it ends several times further
from the reference than its own sigma says, the error is far more than the accelerometer alone would give, and the
GNSS channel is declared faulty and never taken back. A second variant, weighting each fix with the receiver's own
error estimate, was added after the first result and is labelled as not blind. Both variants agree on the outage.

## What this does not settle

- The run is one sequence, one receiver and five start perturbations, not five independent tests. Deep-Urban-1, the
  planned unseen check, has not been fetched or run.
- The reference inside the outage is an inertial estimate of unknown error.
- The start attitude needs the rotation between the NovAtel and Xsens units, which is not in the files.
- The F9P height is biased differently on the two sides of the outage, so a run would use the horizontal axes or declare
  a large vertical noise. That is a modelling choice and belongs in the decision.
- The noise of a real fix is metres and heavy-tailed. The filter's default for the simulated GNSS is far smaller.
- One sequence, one receiver, one day.
