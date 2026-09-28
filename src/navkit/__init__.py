"""navkit: replay, evaluation and uncertainty calibration for GNSS-denied navigation.

The package is organised by role rather than by sensor, so that adding a sensor
does not mean restructuring the library:

``navkit.geometry``
    Rigid-body algebra, quaternions and trajectory alignment.
``navkit.types``
    Shared containers: trajectories, inertial samples, fix streams, measurements.
``navkit.io``
    Readers and writers for the on-disk formats used by public datasets.
``navkit.sensors``
    Measurement models and the generation of synthetic observations.
``navkit.estimators``
    Dead reckoning and the error-state Kalman filter.
``navkit.degrade``
    Outage, noise and degradation injection for scenario replay.
``navkit.eval``
    Accuracy metrics, threshold logic and uncertainty calibration.
``navkit.analysis``
    Typed claims and report rendering.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
