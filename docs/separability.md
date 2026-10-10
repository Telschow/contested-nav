# Honest returns and spoofs at the first GNSS gate

Can the GNSS gate tell an honest fix after an outage from a spoofed one? This page measures that on real
recorded IMU data (EuRoC, TUM VI) with simulated GNSS. It is the open problem of
[ADR-0007](adr/0007-spoof-permanence-hysteresis.md) and the exit-test gap on Track A.

## Method

Until the first fix after an outage, the filter state is the same whether that fix is honest or spoofed. A spoof of
size `delta` shifts the first innovation by `delta` and changes nothing else. One run per honest case therefore gives
the statistic for every spoof size. The honest population is the first fix after a 20 s outage, for each sequence,
outage start, seed and setting. The spoof population is the same fixes shifted by 5 to 500 m in 64 directions.
No spoof is injected into a running filter, so this covers the first gate only. It does not cover a campaign that
ramps up slowly. The GNSS is simulated from ground truth.

## Honest returns

<!-- separability-honest:start -->

| Dataset | Setting | Honest returns | Median d² | 95th percentile d² | Rejected by the shipped gate (16.3) | Median claimed σ at return (m) |
|---|---|---:|---:|---:|---:|---:|
| euroc | default | 108 | 19.64 | 150.0 | 56% | 4.7 |
| euroc | walk10 | 108 | 0.99 | 3.5 | 0% | 30.0 |
| tumvi | file | 69 | 4.23 | 18.6 | 7% | 4.3 |
| tumvi | allan | 69 | 10.61 | 51.9 | 30% | 4.5 |
| tumvi | file-walk10 | 69 | 1.36 | 7.5 | 1% | 10.9 |

<!-- separability-honest:end -->

Under the default textbook noise on EuRoC the filter is too sure of itself after an outage. The shipped gate
rejects many honest returns. This is the lockout of the [attribution](attribution.md) page seen from the gate.

## Spoof detection at the shipped gate

<!-- separability-detection:start -->

| Dataset | Setting | 5 m | 10 m | 20 m | 50 m | 100 m | 200 m | 500 m |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| euroc | default | 56% | 61% | 85% | 100% | 100% | 100% | 100% |
| euroc | walk10 | 0% | 0% | 0% | 1% | 48% | 98% | 100% |
| tumvi | file | 18% | 55% | 79% | 93% | 98% | 100% | 100% |
| tumvi | allan | 48% | 68% | 80% | 93% | 98% | 100% | 100% |
| tumvi | file-walk10 | 1% | 2% | 18% | 79% | 95% | 100% | 100% |

<!-- separability-detection:end -->

## Gate set on one dataset, tested on the other

<!-- separability-heldout:start -->

| Setting pair (EuRoC gate -> TUM VI) | Gate | EuRoC honest rejected | TUM VI honest rejected | Spoof size detected 90% (TUM VI) |
|---|---:|---:|---:|---:|
| walk10 -> file-walk10 | 3.5 | 6% | 16% | 50 m |

<!-- separability-heldout:end -->

## What it shows

1. **With the default noise, honest and spoofed returns overlap.** On EuRoC the shipped gate rejects 56% of honest returns. No gate level fixes that, because the honest returns are the problem.
2. **With a calibrated bias walk the two separate.** The shipped gate rejects 0% of honest EuRoC returns and 1% of honest TUM VI returns.
3. **Separation costs sensitivity.** After 20 s the claimed uncertainty is tens of metres on EuRoC, so spoofs under 50 m pass. A spoof of 100 m is caught about half the time and 200 m almost always.
4. **A gate fitted on EuRoC transfers imperfectly.** At 5% false alarms on EuRoC it rejects 16% of honest TUM VI returns.

## What follows

The fix for the lockout is the calibrated covariance, not a looser or tighter gate. A spoof smaller than the
honest uncertainty cannot be told from an honest return by the first fix. That is a limit of the measurement,
not of the tuning. The shipped configuration is unchanged. The decision is recorded in
[ADR-0018](adr/0018-honest-return-separability.md).
