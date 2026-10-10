# ADR-0020: A second source against a slow-ramp spoof

- Status: accepted
- Date: 2026-10
- Related: [ADR-0017](0017-stochastic-clone-for-the-visual-update.md), [ADR-0019](0019-slow-ramp-spoofing.md), [vision ramp](../vision_ramp.md)

## Context

ADR-0019 found that an IMU and GNSS alone follow a slow GNSS ramp. A simulated visual source with independent
errors catches and refuses a 2 m/s ramp, sees a 1 m/s ramp without stopping it, and sees nothing at 0.2 m/s and
below. With the correlated-error setting that keeps the clone calibrated, it catches none of them.

## Options

1. **Record the floor.** State a detection floor of about 2 m/s, conditional on independent visual errors, and
   leave the shipped configuration unchanged.
2. **Measure a real front end's error correlation first.** The result decides whether the floor holds, and is the
   open item of ADR-0017. It needs a front end the dependency rules allow.
3. **Test a different second source.** A barometer or a map constrains a different axis, and may catch ramps the
   visual source cannot.

## Decision

Option 1 now, then option 2, then option 3.

The floor is recorded: about 2 m/s, and only if a front end's errors are independent. It is stated wherever the
slow-ramp limit is stated. The shipped configuration is unchanged and `vision_enabled` stays False.

Next, a real front end's error correlation is measured (work package WB-3), because the floor holds only for
independent errors and no data here says which a real front end has. Until then the floor is a conditional claim.

After that, a different second source (a barometer or a map) is tested in the same experiment. That is not started,
and it is not blocked on the front end.

## Consequences

Whatever is chosen, the claim stays limited to simulated GNSS, a surrogate camera, one direction and two datasets.
