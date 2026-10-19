"""Relative visual measurements must not create information about global position.

Global position is unobservable from relative pose. A consistent filter that has no absolute sensor must therefore
not become more certain about its absolute position than its initial prior says. This is the textbook consistency
test for visual-inertial filters. ``docs/results.md`` and the module docstring of ``navkit.estimators.eskf`` explain
the B1 blocker in prose (the Schur complement of the anchor blocks); these tests pin the property itself, for both
visual-update models:

* the stochastic clone (``vision_only_clone``) satisfies it;
* the anchor model (``vision_only``) violates it, which is why that row is a control row that must stay visible;
* a GNSS-aided run (``gnss_only``) shrinks below the prior, which is correct, because GNSS is an absolute sensor.
  That third case shows the check can tell information from an absolute sensor from information from relative poses.

The cases are run through ``navkit.benchmark.run_case``, the code path the benchmark uses, and the estimator's own
result is kept to read the per-epoch position covariance. Nothing is copied from a page: the prior is read from
the run's recorded filter config, and every ratio is computed from the covariance the run returned.

The attitude block is not tested. ``EstimatorResult`` exposes the position covariance only, and exposing the attitude
block would need a change in ``src/``, which this package does not make.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pytest
import yaml

from navkit import benchmark as bm
from navkit.estimators.eskf import ErrorStateKalmanFilter

#: Relative tolerance on "not below the prior". The covariance is symmetrised and its eigenvalues are taken, so the
#: noise is floating-point rounding: measured below 1e-12 relative (the largest asymmetry in the clone run is about
#: 1e-15 absolute). 1e-6 sits about six orders of magnitude above that and about five below the smallest real
#: violation (the anchor model's smallest variance is a small fraction of the prior). It is also tighter than the
#: growth of the clone's covariance in its first step, which the run measures as a few parts per million.
PRIOR_TOLERANCE = 1e-6


def _case_config() -> tuple[dict[str, Any], dict[str, Any]]:
    loaded = yaml.safe_load(bm.default_config_path().read_text(encoding="utf-8"))
    return loaded["defaults"], loaded["cases"]


def run_with_covariance(name: str, estimator: dict[str, Any] | None = None) -> tuple[dict[str, Any], Any]:
    """Run one benchmark case through ``run_case`` and keep the estimator result, which the record does not hold."""
    defaults, cases = _case_config()
    case = copy.deepcopy(cases[name])
    case.setdefault("estimator", {}).update(estimator or {})
    kept: dict[str, Any] = {}
    original = ErrorStateKalmanFilter.run

    def keep(self: ErrorStateKalmanFilter, *args: Any, **kwargs: Any) -> Any:
        result = original(self, *args, **kwargs)
        kept["result"] = result
        return result

    ErrorStateKalmanFilter.run = keep  # type: ignore[method-assign]
    try:
        record = bm.run_case(name, case, defaults)
    finally:
        ErrorStateKalmanFilter.run = original  # type: ignore[method-assign]
    return record, kept["result"]


def prior_sigma_m(record: dict[str, Any]) -> float:
    """The initial position 1-sigma the filter was given, from the recorded filter config."""
    return float(record["estimator"]["initial_pos_sigma_m"])


def eigenvalue_ratio(cov: np.ndarray, sigma0: float) -> np.ndarray:
    """Smallest eigenvalue of the position covariance at each epoch, over the prior variance."""
    sym = 0.5 * (cov + cov.transpose(0, 2, 1))
    return np.asarray(np.linalg.eigvalsh(sym).min(axis=1) / sigma0**2)


def trace_ratio(cov: np.ndarray, sigma0: float) -> np.ndarray:
    """Trace of the position covariance at each epoch, over the trace of the isotropic prior."""
    return np.asarray(np.trace(cov, axis1=1, axis2=2) / (3.0 * sigma0**2))


def becomes_more_certain_than_the_prior(cov: np.ndarray, sigma0: float) -> bool:
    """True if some direction of position is claimed more precisely than the prior at some epoch."""
    return bool(eigenvalue_ratio(cov, sigma0).min() < 1.0 - PRIOR_TOLERANCE)


@pytest.fixture(scope="module")
def clone() -> tuple[dict[str, Any], Any]:
    return run_with_covariance("vision_only_clone")


@pytest.fixture(scope="module")
def anchor() -> tuple[dict[str, Any], Any]:
    return run_with_covariance("vision_only")


@pytest.fixture(scope="module")
def gnss() -> tuple[dict[str, Any], Any]:
    return run_with_covariance("gnss_only")


def test_the_clone_never_becomes_more_certain_about_absolute_position_than_its_prior(clone):
    """No absolute sensor and relative poses only: the claimed position variance must not fall below the prior.

    Growth is allowed and expected, because the inertial integration adds process noise and a relative measurement
    cannot remove absolute uncertainty. Shrinkage below the prior is not allowed, in any direction (smallest
    eigenvalue) or in total (trace). The tolerance is ``PRIOR_TOLERANCE``, with its reason.

    The run must have fused visual measurements and no GNSS, or the test would hold for the wrong reason.
    """
    record, result = clone
    sigma0 = prior_sigma_m(record)
    assert result.stats["vision_updates_used"] > 0
    assert result.stats["gnss_updates_used"] == 0
    cov = result.position_cov
    assert eigenvalue_ratio(cov, sigma0).min() >= 1.0 - PRIOR_TOLERANCE, "a direction of position became more certain"
    assert trace_ratio(cov, sigma0).min() >= 1.0 - PRIOR_TOLERANCE, "the total position variance fell below the prior"
    assert not becomes_more_certain_than_the_prior(cov, sigma0)


def test_the_anchor_model_still_becomes_more_certain_about_absolute_position_and_that_is_pinned(anchor):
    """The control row: the known defect, asserted so that it stays visible.

    With the anchor model the Schur complement of the relative-pose measurement gives the filter information about
    absolute position that no sensor supplied, so the smallest position standard deviation falls far below the
    prior. Measured on this run it is about a tenth of the prior. The band below keeps a margin of more than a
    factor of two on both sides: the upper bound (a quarter of the prior) fails the test if the defect is fixed or
    the control row is changed so that it no longer violates the property; the lower bound fails it if the defect
    gets much worse. Fixing it is good news, and the fix then belongs in this docstring and in ``docs/results.md``,
    not in a quiet loss of the control row.
    """
    record, result = anchor
    sigma0 = prior_sigma_m(record)
    assert result.stats["vision_updates_used"] > 0
    assert result.stats["gnss_updates_used"] == 0
    cov = result.position_cov
    ratio = float(np.sqrt(eigenvalue_ratio(cov, sigma0).min()))  # smallest position std over the prior std
    assert becomes_more_certain_than_the_prior(cov, sigma0), "the control row no longer violates the property"
    assert 0.05 < ratio < 0.25, f"smallest position std is {ratio:.3g} of the prior, outside the pinned band"


def test_an_absolute_sensor_shrinks_the_position_covariance_below_the_prior(gnss):
    """GNSS is an absolute sensor, so shrinking below the prior is correct there and the check must say so.

    With the same anchor model and no vision, the position covariance falls below the prior. The check that passes
    the clone and flags the anchor control is therefore telling absolute information from relative information, and
    not just flagging every run that has a position fix of some kind.
    """
    record, result = gnss
    sigma0 = prior_sigma_m(record)
    assert result.stats["gnss_updates_used"] > 0
    cov = result.position_cov
    assert becomes_more_certain_than_the_prior(cov, sigma0)
    assert float(np.sqrt(eigenvalue_ratio(cov, sigma0).min())) < 0.5
