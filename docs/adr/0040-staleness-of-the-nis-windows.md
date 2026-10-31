# ADR-0040: Staleness of the NIS windows

- Status: proposed
- Date: 2026-10
- Related: [ADR-0006](0006-nis-window-monitor.md), [ADR-0035](0035-the-integrity-status-record.md), [issue #181](https://github.com/Telschow/contested-nav/issues/181)

## Context

The NIS window monitor keeps the last outcomes of each channel and never ages them. If GNSS runs and then goes out, as in `outage_control` (5 s to 20 s), the `gnss` window keeps its last outcomes. `monitored` stays true and `nis_state` can stay `ok` on history that is seconds old, through the whole outage.

ADR-0035 (schema version 1) allows this and says so. It points consumers to `seconds_since_absolute_fix`, read together with `monitored`.

A staleness rule needs a threshold, the age after which a sample no longer counts. Nothing in the repository supports a value yet. The `outage_control` run is the first evidence to look at: it shows how long the stale `ok` lasts, and how often it hides a diverging filter.

## Options

(a) Leave schema version 1 as it is. The consumer reads `seconds_since_absolute_fix`. No change and no threshold. The record still says `ok` on old history.

(b) Age the windows. A sample older than a staleness window no longer counts, per channel. A channel with no counted samples is unmonitored. The staleness window is a new threshold and needs its own evidence.

(c) Expire a window after a number of epochs with no update on its channel. The same threshold in a different unit, and it ties the rule to the update rate.

(d) Add the age of the newest sample per channel as new fields, and no rule. The consumer decides. Adds fields without a threshold, but moves the judgment out of the record, which ADR-0035 rejected for the covariance and the windows.

## Decision

To be written by the maintainer.

## Consequences

To be confirmed with the decision. If (b), (c) or (d) is chosen:

- The record changes meaning or fields, so it is schema version 2 (ADR-0035 requires a new version and a new ADR for that).
- Tests come first: a known-answer case where GNSS stops and the channel is no longer reported as monitored after the window.
- For (b) and (c), the threshold comes from a generated table over the outage scenarios, labelled synthetic, checked in CI.
- No runtime dependency changes.
