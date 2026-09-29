"""Tests for ``seeded_scene``: the trajectory-variation axis.

The seed sweep that already exists varies *sensor noise*. That answers "is this
filter overconfident under this noise", which is not the same question as "is
this filter overconfident in general". Every published number came from one
trajectory, so a result that was really an artefact of that trajectory -- a
particular excursion, a particular turn -- looked identical to a property of the
estimator. These tests pin the two invariants that make the new axis honest.
"""

from __future__ import annotations

import numpy as np
import pytest

from navkit.synthetic import SyntheticConfig, seeded_scene, synthetic_trajectory

BASE = SyntheticConfig()


class TestInvariants:
    def test_duration_and_rate_are_never_varied(self):
        """A swept result must stay comparable to the published one.

        Changing either would change the number of samples and the window the
        outage is scheduled into, so a swept NEES would no longer be measuring
        the same thing as the committed baseline.
        """
        for seed in range(20):
            c = seeded_scene(BASE, seed)
            assert c.duration_s == BASE.duration_s
            assert c.rate_hz == BASE.rate_hz

    def test_the_initial_state_is_exact_at_t_zero(self):
        """The known-answer property must survive scene variation.

        This is the property the whole fixture rests on: the motion is built
        from ``1 - cos(w t)`` terms, so position, velocity, and rotation are
        exactly zero at ``t = 0`` and an estimator initialised at the identity
        pose with zero velocity is *exactly* correct at the first sample. If a
        scene draw perturbed the start state, every subsequent error would be
        un-attributable to the estimator, and every known-answer test would
        quietly stop being one.
        """
        for seed in range(20):
            traj = synthetic_trajectory(seeded_scene(BASE, seed))
            assert np.allclose(traj.rotations[0], np.eye(3), atol=1e-12)
            assert np.allclose(traj.positions[0], np.array(BASE.start_position), atol=1e-12)
            # Velocity is zero in the limit; a forward difference over one 10 ms
            # step still picks up half the initial acceleration, so the check is
            # that the start is slow relative to the motion as a whole rather
            # than exactly still. Asserting exact zero here would be a test of
            # floating point, not of the invariant.
            v0 = (traj.positions[1] - traj.positions[0]) / (traj.t[1] - traj.t[0])
            v_all = np.diff(traj.positions, axis=0) / np.diff(traj.t)[:, None]
            peak = float(np.max(np.linalg.norm(v_all, axis=1)))
            assert peak > 0.0
            assert np.linalg.norm(v0) < 1e-2 * peak

    def test_the_same_seed_always_gives_the_same_scene(self):
        a = seeded_scene(BASE, 7).as_dict()
        b = seeded_scene(BASE, 7).as_dict()
        assert a == b

    def test_different_seeds_give_different_scenes(self):
        a = seeded_scene(BASE, 0).as_dict()
        b = seeded_scene(BASE, 1).as_dict()
        assert a != b


class TestVariation:
    def test_the_scene_actually_changes_the_trajectory(self):
        """Otherwise the axis would be a relabelled no-op.

        Measured on path length, which is the quantity a drift result depends
        on: if every seed produced the same distance travelled, a swept ATE
        would be ten copies of the baseline.
        """
        lengths = {round(synthetic_trajectory(seeded_scene(BASE, s)).path_length(), 6) for s in range(10)}
        assert len(lengths) >= 8, f"scene variation is too small to be meaningful: {lengths}"

    def test_path_length_stays_inside_the_declared_range(self):
        """The sweep must not wander into a regime the filter was not built for."""
        for seed in range(30):
            c = seeded_scene(BASE, seed)
            assert 0.6 * BASE.radius_m - 1e-9 <= c.radius_m <= 1.4 * BASE.radius_m + 1e-9
            assert 0.6 * BASE.circles - 1e-9 <= c.circles <= 1.4 * BASE.circles + 1e-9

    def test_the_ensemble_is_centred_on_the_baseline(self):
        """A log-uniform multiplier keeps the configured value at the centre.

        A sweep that is biased towards short paths would flatter the estimator,
        because drift has less distance to accumulate over. This is the check
        that stops that bias going unnoticed.
        """
        draws = np.array([seeded_scene(BASE, s).radius_m for s in range(200)])
        assert abs(np.log(draws).mean() - np.log(BASE.radius_m)) < 0.06
        # Roughly symmetric in log space, so no systematic direction of travel.
        assert draws.min() < BASE.radius_m < draws.max()

    def test_the_base_config_is_not_mutated(self):
        """A swept run must not leave the caller's config changed."""
        before = BASE.as_dict()
        seeded_scene(BASE, 3)
        assert BASE.as_dict() == before

    def test_explicit_config_values_are_respected_as_the_centre(self):
        """The multiplier is relative to the given config, not hard-coded values.

        A case that asks for a 10 m radius should sweep around 10 m. If the
        ranges were absolute, such a case would be swept outside its own
        regime and the result would mean nothing.
        """
        big = SyntheticConfig(radius_m=10.0)
        draws = [seeded_scene(big, s).radius_m for s in range(50)]
        assert min(draws) >= 6.0
        assert max(draws) <= 14.0


class TestNonRegression:
    def test_the_unseeded_scene_is_unchanged(self):
        """`seeded_scene` must not be on the default path."""
        traj = synthetic_trajectory(SyntheticConfig())
        assert traj.path_length() == pytest.approx(synthetic_trajectory(BASE).path_length())
        assert np.allclose(traj.positions[0], BASE.start_position)
