"""Baseline estimators.

Nothing in this package is copied from an existing VIO or SLAM implementation.
The two estimators here are the standard textbook baselines for an
inertially-aided pipeline, written from the published formulations:

* :class:`~navkit.estimators.dead_reckoning.DeadReckoning` -- pure inertial
  integration, no updates. The unaided lower bound.
* :class:`~navkit.estimators.eskf.ErrorStateKalmanFilter` -- error-state
  Kalman filter fusing inertial, GNSS position and relative visual-pose
  measurements, with the visual anchor error carried as six estimated states.

They are deliberately modest. A full VIO front end (feature tracking, optical
flow, keyframe selection, loop closure) is a different and much larger piece of
work; see ``docs/roadmap.md`` for how it would slot in and what it would take.
"""

from .dead_reckoning import DeadReckoning, EstimatorResult
from .eskf import ErrorStateKalmanFilter, EskfConfig, InitialState

__all__ = ["DeadReckoning", "ErrorStateKalmanFilter", "EstimatorResult", "EskfConfig", "InitialState"]
