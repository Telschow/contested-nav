"""Status codes and channel names shared by the FDIR modules.

These are plain strings so that a log line or a JSON result can be read back to a
verdict without importing anything. They live apart from the policy in
:mod:`navkit.fdir.fdir_manager` so that the configuration and the records that
carry them can name them without importing the manager.
"""

from __future__ import annotations

__all__ = [
    "SENSOR_CHANNELS",
    "STATUS_ACCEPTED",
    "STATUS_REACCEPTED_WITH_INFLATION",
    "STATUS_REJECTED_PERSISTENT",
    "STATUS_REJECTED_SPOOF",
    "STATUS_SENSOR_FAULT",
]

STATUS_ACCEPTED = "ACCEPTED"
#: An isolated gate failure, with no run of failures behind it. The name states
#: the *policy* -- an unproven channel gets no covariance relief and is treated as
#: untrusted -- and deliberately does not assert a cause. A lone large residual
#: is what multipath looks like and what a spoof looks like, and ADR-0005 records
#: that the gate cannot tell them apart; calling this "spoof" would be the same
#: over-claim in a string literal that the ADR refuses to make in prose.
STATUS_REJECTED_SPOOF = "REJECTED_SPOOF"
#: A run of failures too long to be attributed to a single bad epoch, and too
#: long to be relieved by the inflation in :mod:`navkit.fdir.nis_monitor`. Still a
#: sensor, not the filter.
STATUS_REJECTED_PERSISTENT = "REJECTED_PERSISTENT"
#: A channel that has been failing for long enough to look like the filter's own
#: overconfidence, and whose innovation became plausible once a bounded amount of
#: covariance was admitted. This is the one verdict that *loosens* the filter, so
#: it is always an event and never just a counter.
STATUS_REACCEPTED_WITH_INFLATION = "REACCEPTED_WITH_INFLATION"
STATUS_SENSOR_FAULT = "SENSOR_FAULT"

#: Channels the tracker understands. The names match the ``sensor=`` argument the
#: measurement models in :mod:`navkit.estimators.eskf` actually pass, so a log
#: line can be read back to a source.
#:
#: ``vision`` is deliberately absent. A relative-pose fix arrives as two
#: independent blocks -- rotation and translation -- with different dimensions,
#: different noise, and different failure modes, so gating them under one channel
#: would let a bad rotation mask a good translation. They are tracked separately
#: and share nothing but the run.
SENSOR_CHANNELS = ("gnss", "vision_rot", "vision_trans", "altimeter")
