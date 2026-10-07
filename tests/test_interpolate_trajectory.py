"""``interpolate_trajectory`` against the scalar implementation it replaced.

The function used to loop over every query in Python, doing one SLERP and one
quaternion-to-matrix conversion per sample, and that loop was the largest single cost of
a benchmark case (see ``docs/PERFORMANCE.md``). It is now vectorised. This test keeps the
old per-sample code as an oracle and requires the two to agree on trajectories built to
exercise every branch: the short-way-round flip, the nearly-parallel fallback and the
ordinary SLERP, plus queries at the knots, at the ends and outside the span.
"""

from __future__ import annotations

import numpy as np
import pytest

from navkit.geometry.rigid import quat_to_matrix, rot_exp
from navkit.types import Trajectory, interpolate_trajectory


def _slerp_scalar(q0: np.ndarray, q1: np.ndarray, a: float) -> np.ndarray:
    """The original per-sample implementation, kept verbatim as the oracle."""
    q0 = np.asarray(q0, float)
    q1 = np.asarray(q1, float)
    d = float(q0 @ q1)
    if d < 0.0:
        q1 = -q1
        d = -d
    if d > 0.9995:
        q = q0 + a * (q1 - q0)
        return q / np.linalg.norm(q)
    th0 = np.arccos(np.clip(d, -1.0, 1.0))
    s = np.sin(th0)
    return (np.sin((1.0 - a) * th0) / s) * q0 + (np.sin(a * th0) / s) * q1


def _interpolate_scalar(traj: Trajectory, t_query: np.ndarray) -> np.ndarray:
    t_query = np.asarray(t_query, dtype=float).reshape(-1)
    lo, hi = float(traj.t[0]), float(traj.t[-1])
    tq = np.clip(t_query, lo, hi)
    idx = np.clip(np.searchsorted(traj.t, tq, side="right") - 1, 0, len(traj) - 2)
    t0, t1 = traj.t[idx], traj.t[idx + 1]
    alpha = np.clip((tq - t0) / np.maximum(t1 - t0, 1e-12), 0.0, 1.0)
    q = traj.quaternions
    return np.array([quat_to_matrix(_slerp_scalar(q[idx[i]], q[idx[i] + 1], float(alpha[i]))) for i in range(len(tq))])


def _random_trajectory(seed: int, n: int = 60) -> Trajectory:
    """A trajectory whose consecutive rotations span tiny, ordinary and near-half-turn steps."""
    rng = np.random.default_rng(seed)
    step_scale = rng.choice([1e-4, 0.05, 0.6, 2.5], size=n)
    R = np.eye(3)
    poses = np.tile(np.eye(4), (n, 1, 1))
    pos = np.zeros(3)
    for i in range(n):
        R = R @ rot_exp(rng.normal(size=3) * step_scale[i])
        pos = pos + rng.normal(size=3)
        poses[i, :3, :3] = R
        poses[i, :3, 3] = pos
    return Trajectory(t=np.cumsum(rng.uniform(0.01, 0.2, size=n)), poses=poses, name="random")


def _branches_hit(traj: Trajectory) -> tuple[bool, bool, bool]:
    q = traj.quaternions
    d = np.einsum("ij,ij->i", q[:-1], q[1:])
    return bool((d < 0.0).any()), bool((np.abs(d) > 0.9995).any()), bool((np.abs(d) <= 0.9995).any())


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5])
def test_matches_the_scalar_implementation(seed: int) -> None:
    traj = _random_trajectory(seed)
    rng = np.random.default_rng(100 + seed)
    knots = traj.t
    mids = 0.5 * (knots[:-1] + knots[1:])
    outside = np.array([knots[0] - 1.0, knots[-1] + 1.0])
    query = np.concatenate([knots, mids, rng.uniform(knots[0], knots[-1], 200), outside])
    query = np.sort(query)  # a Trajectory requires non-decreasing times, so queries must be sorted

    got = interpolate_trajectory(traj, query)
    want = _interpolate_scalar(traj, query)

    np.testing.assert_allclose(got.poses[:, :3, :3], want, rtol=0.0, atol=1e-12)
    # translation and the homogeneous row are untouched by the change
    np.testing.assert_array_equal(got.poses[:, 3, :], np.tile([0.0, 0.0, 0.0, 1.0], (len(query), 1)))
    np.testing.assert_array_equal(got.t, np.clip(query, knots[0], knots[-1]))


def test_the_random_trajectories_exercise_every_branch() -> None:
    """Guard against the comparison above passing because no branch was reached."""
    flipped = parallel = ordinary = False
    for seed in range(6):
        f, p, o = _branches_hit(_random_trajectory(seed))
        flipped, parallel, ordinary = flipped or f, parallel or p, ordinary or o
    assert flipped, "no consecutive pair needed the short-way-round flip"
    assert parallel, "no consecutive pair took the nearly-parallel fallback"
    assert ordinary, "no consecutive pair took the ordinary SLERP"


def test_the_outside_mask_and_clamping_are_unchanged() -> None:
    traj = _random_trajectory(7)
    query = np.array([traj.t[0] - 5.0, traj.t[3], traj.t[-1] + 5.0])
    out = interpolate_trajectory(traj, query)
    assert out.metadata["inside"].tolist() == [False, True, False]
    np.testing.assert_array_equal(out.t, [traj.t[0], traj.t[3], traj.t[-1]])


def test_an_empty_query_returns_an_empty_trajectory_or_raises_as_before() -> None:
    traj = _random_trajectory(8)
    try:
        out = interpolate_trajectory(traj, np.array([]))
    except ValueError:
        return  # Trajectory refuses an empty pose list; that was true before the change
    assert len(out) == 0


def test_no_runtime_warning_for_nearly_parallel_pairs() -> None:
    """A vanishing sine must never be divided by; pytest turns RuntimeWarning into an error."""
    poses = np.tile(np.eye(4), (3, 1, 1))
    poses[1, :3, :3] = rot_exp(np.array([0.0, 0.0, 1e-9]))
    poses[2, :3, :3] = rot_exp(np.array([0.0, 0.0, 2e-9]))
    traj = Trajectory(t=np.array([0.0, 1.0, 2.0]), poses=poses)
    out = interpolate_trajectory(traj, np.array([0.25, 0.75, 1.5]))
    assert np.isfinite(out.poses).all()
