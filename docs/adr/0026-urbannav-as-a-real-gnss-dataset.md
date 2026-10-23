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

What the dataset gives: a real receiver's own fixes with their reported error estimates, one continuous real outage
in a tunnel, a post-processed reference at 1 Hz, and a 400 Hz industrial MEMS IMU. The outage is the receiver's, not
one cut into simulated fixes, which is the test ADR-0013 and ADR-0016 left open.

What it cannot show: how the filter does in general. It is one sequence, one receiver and one day, and the five
seeds perturb only the start state. The reference inside the tunnel is an inertial estimate of unknown error. The
antenna offset from the IMU is not corrected. The data is third party and cannot be committed (S2), so CI checks the
page against a committed CSV of aggregates and cannot rerun the filter.

What a decision commits the repository to: any option that runs the filter on this data adds a result about real GNSS
that sits next to the synthetic ones, under constraint C6 (real data, one sequence, one receiver, said next to every
number). The page must stay generated and checked from the CSV, and the CSV must stay aggregate-only. Diagnostic
variants that use the reference (the oracle rows) are labelled as such and are not filters. Sensitivity runs showed
that the outage error depends strongly on the declared IMU noise. Those runs are not blind, are not reproduced by
any code here and are not a result of this repository. They are in the pull request that added the run.

## Options

1. **Stay on simulated GNSS.** Nothing new is learned about calibration under real fixes. Commits the repository to
   nothing new, and leaves the question in ADR-0013 and ADR-0016 open.
2. **Tunnel-1, with the F9P's own NMEA fixes.** One real outage, real fix errors, an outage rule read from the
   receiver's fix flag. The reference is an estimate, and the rotation between the reference unit and the IMU is not
   in the files. Commits the repository to a data page and a CSV that CI checks, to a dataset credit and to the
   fetch command, and to a result that is currently a failure of the filter.
3. **Tunnel-1, with positions computed from the RINEX observations.** Needs navigation files that the download does not
   contain, and a position solver. More work, and the result would be this project's solver. Commits the repository to
   maintaining a solver that is outside the filter's scope.
4. **Deep-Urban-1 as well.** Dense streets and small tunnels. Its outages are not annotated, so the rule would apply
   to a receiver file that has not been looked at yet. Commits the repository to a second reader and to not tuning the
   outage rule on it.

## Decision

To be written by the maintainer.

## Evidence

The measurements and the run are generated on [the UrbanNav page](../urbannav.md) from committed CSVs. In short: the
Tunnel-1 files read cleanly, the offset search found no clock offset within its step, the F9P stream has one outage,
and the fixes next to that outage are badly wrong while marked valid. The outage rule was fixed before any filter ran
and has not been changed since.

The filter was then run on it with the settings of option 2. With GNSS available it is already inconsistent on this
sequence. Through the real outage it ends several times further from the reference than its own sigma says. The oracle
diagnostics on the page show that this error is driven by roll and pitch growth through the outage, and not by yaw. A
link between the inconsistency before the outage and the tilt growth is not shown, and the cause of the tilt growth
is not explained. The GNSS channel is then declared faulty and never taken back, which follows from the position
error. A second variant, weighting each fix with the receiver's own error estimate, was added after the first result
and is labelled as not blind. Both variants agree on the outage. One sequence, one receiver.

## What this does not settle

- The run is one sequence, one receiver and five start perturbations, not five independent tests. Deep-Urban-1, the
  planned unseen check, has not been fetched or run.
- The reference inside the outage is an inertial estimate of unknown error.
- The start attitude needs the rotation between the NovAtel and Xsens units, which is not in the files.
- The F9P height is biased differently on the two sides of the outage, so a run would use the horizontal axes or declare
  a large vertical noise. That is a modelling choice and belongs in the decision.
- The noise of a real fix is metres and heavy-tailed. The filter's default for the simulated GNSS is far smaller.
- One sequence, one receiver, one day.

## Added for issue 131: the INSPVAX question and a sequence without an outage

This section is context and options. It does not change the Decision section above.

### Context: what INSPVAX is here

The publisher's README lists `/novatel_data/inspvax` among the ROS topics of both sequences and describes it as the
SPAN-CPT solution after post-processing. That is the same description as the text reference file the Tunnel-1 run
reads. The README gives no rate for the topic and no field list. Whether the topic and the text file hold the same
values has not been checked here. From outside the repository: INSPVAX is the NovAtel extended INS message. It carries
position, velocity and attitude, and also standard deviations and an INS status flag. The standard deviations are the
one thing the text file does not offer, and they are what could replace the page's "its error there is unknown" for the
reference.

The Tunnel-1 run did not use INSPVAX. Its start pose, velocity and attitude, and its truth grid, come from the text
reference (position, body-frame velocity, roll, pitch and heading), with the identity rotation of the dataset's
`extrinsic.yaml` between the reference unit and the IMU. Reading a ROS bag needs a reader that constraint S1 does not
allow, and `navkit urbannav fetch` does not download bags.

### Options for the reference and the start state

A. **The text reference only**, exactly as for Tunnel-1. No new reader. Deep-Urban-1 is a second sequence on equal
   terms, and the caveat that the reference error is unknown stays. No Tunnel-1 number changes.
B. **A, and INSPVAX read once outside the repository.** The topic is exported with standard ROS tools to a local CSV,
   as the IMU was, and compared with the text file in a scratch script. Nothing from it can be a generated number on a
   page. At most it is evidence in a pull request. No Tunnel-1 number changes.
C. **A, and a reader for an exported INSPVAX CSV in `urbannav_data.py`**, as an extra check with the text file still
   the reference. This is the only option that can turn "unknown" into generated rows about the reference's own
   uncertainty and about the agreement of the two files, for both sequences. It does not break S1. CI covers it only
   through synthetic tests. No Tunnel-1 number changes if it only adds rows.
D. **INSPVAX as the reference and the start state.** The conventions differ from the text file (local-level velocity
   and azimuth, as far as known here), so the attitude and velocity checks of the Tunnel-1 package would be redone.
   Applied to Tunnel-1 it would change the start state, the truth grid and every Tunnel-1 number. Applied to
   Deep-Urban-1 only, the two sequences would no longer be comparable. This option is not recommended.
E. **Decide not to use INSPVAX**, and record why. The same as A for the runs.

The maintainer chose A for the Deep-Urban-1 run. That choice is recorded here as context for the run, and the
Decision section is not filled in by it.

### Context: Deep-Urban-1 has no outage by the rule

The maintainer read the Deep-Urban-1 receiver file with the repository's readers and found a valid quality flag on
every fix, so the outage rule of `outage_intervals` finds no outage. The rule is not changed or tuned to find one, as
issue 95 requires. The same reading found the fixes heavier-tailed than the receiver's own reported sigma. These are
the maintainer's observations. The data page carries them as generated rows once the sequence is measured there.

So this sequence is a case of GNSS that is always present and wrong in the way urban multipath makes it wrong, and
not an outage sequence. The run for it is the aided run over the whole sequence: the declared and per-fix variants,
no oracle diagnostics (they act only inside an outage and are reported as not applicable), and quantities that do not
need an outage: the normalised errors, the pooled 2-sigma coverage per axis, the gate's rejection rate and the fixes'
own errors against the reference. Outages imposed on this sequence would be a separate experiment, with its own record.
