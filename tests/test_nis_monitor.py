"""Tests for the NIS window monitor and adaptive covariance inflation.

The three cases below are the ones that made the mechanism necessary and the
ones that could have made it dangerous, so they are tested at the filter level
rather than against the gate in isolation: a gate can be correct in isolation
and produce a filter that follows a spoof, and only the assembled filter says
which happened. The numbers asserted here are measured values from this
repository, not targets -- they are what the code does, and a change to them is
a change to be explained rather than an expectation to be met.

ADR-0006 carries the reasoning. In short: an isolated impulse is evidence about
a sensor, a run of failures on a channel that was not silent is evidence about
the filter, and only the second is allowed to buy covariance.
"""

from __future__ import annotations

import numpy as np
import numpy.linalg as la
import pytest

from navkit.degrade.config import Outage
from navkit.degrade.inject import apply_gnss_outage
from navkit.estimators.eskf import (
    _FDIR_INFLATION_BLOCK,
    ErrorStateKalmanFilter,
    EskfConfig,
)
from navkit.fdir import (
    STATUS_ACCEPTED,
    STATUS_REACCEPTED_WITH_INFLATION,
    STATUS_REJECTED_PERSISTENT,
    STATUS_REJECTED_SPOOF,
    STATUS_SENSOR_FAULT,
    FdirConfig,
    FdirManager,
    NisConfig,
    NisWindowMonitor,
)
from navkit.fdir.gating import chi2_threshold
from navkit.io.imu import ImuNoiseModel
from navkit.sensors.models import (
    GnssConfig,
    VisionConfig,
    gnss_fixes,
    visual_updates,
)
from navkit.synthetic import SyntheticConfig, synthetic_imu, synthetic_trajectory
from navkit.types import GnssFix, VisionUpdate, interpolate_trajectory

_DURATION_S = 20.0


# --- fixtures ---------------------------------------------------------------


def _platform(sigma_m: float = 0.1, seed: int = 3):
    """A platform with known motion, so the filter is correct to begin with.

    The inertial stream is noise-free. Noise widens the gate, which is the honest
    behaviour but makes "was this rejected?" depend on the noise draw. The fault
    magnitudes here are metres against a 0.1 m fix sigma, so there is no need for
    that slack.
    """
    cfg = SyntheticConfig(duration_s=_DURATION_S, rate_hz=100.0)
    gt = synthetic_trajectory(cfg)
    gt = gt.transformed(la.inv(gt.poses[0]))
    imu = synthetic_imu(cfg, rate_hz=200.0)
    fixes = gnss_fixes(gt, GnssConfig(sigma_m=sigma_m, rate_hz=5.0, seed=seed))
    return gt, imu, fixes.valid()


def _offset_fixes(fixes, offset, start, count):
    """`fixes` with `offset` metres added to `count` fixes beginning at `start`."""
    positions = fixes.positions.copy()
    positions[start : start + count] += np.asarray(offset, dtype=float)
    return GnssFix(
        t=fixes.t.copy(),
        positions=positions,
        cov=None if fixes.cov is None else fixes.cov.copy(),
        name=fixes.name + "_offset",
    )


def _filter(**kwargs) -> ErrorStateKalmanFilter:
    return ErrorStateKalmanFilter(EskfConfig(imu_noise=ImuNoiseModel(), **kwargs))


def _final_position_error(gt, result) -> float:
    reference = interpolate_trajectory(gt, result.trajectory.t)
    return float(np.linalg.norm(result.trajectory.positions[-1] - reference.positions[-1]))


def _grants(result) -> list[dict]:
    return [
        e
        for e in result.trajectory.metadata["fdir_events"]
        if e["status"] == STATUS_REACCEPTED_WITH_INFLATION
    ]


# --- the monitor itself -----------------------------------------------------


class TestPersistenceDecision:
    """`is_persistent_divergence` reads a trailing run, not a count."""

    def test_fewer_than_k_rejections_is_not_persistent(self):
        m = NisWindowMonitor()
        m.add_sample("gnss", 100.0, False)
        m.add_sample("gnss", 100.0, False)
        assert not m.is_persistent_divergence("gnss")

    def test_k_rejections_is_persistent(self):
        m = NisWindowMonitor()
        for _ in range(3):
            m.add_sample("gnss", 100.0, False)
        assert m.is_persistent_divergence("gnss")

    def test_one_accept_breaks_the_run(self):
        m = NisWindowMonitor()
        for _ in range(5):
            m.add_sample("gnss", 100.0, False)
        m.add_sample("gnss", 1.0, True)
        assert not m.is_persistent_divergence("gnss")

    def test_channels_do_not_share_history(self):
        """A rejected camera says nothing about a rejected GNSS.

        The point of the monitor is that a run of failures is evidence about one
        channel. Letting the visual blocks vouch for GNSS is the same mistake as
        gating them as one channel, which ADR-0001 already paid for.
        """
        m = NisWindowMonitor()
        for _ in range(3):
            m.add_sample("gnss", 100.0, False)
        assert not m.is_persistent_divergence("vision_rot")

    def test_reset_channel_forgets_a_stale_run(self):
        m = NisWindowMonitor()
        for _ in range(3):
            m.add_sample("gnss", 100.0, False)
        m.reset_channel("gnss")
        assert not m.is_persistent_divergence("gnss")
        assert m.history("gnss") == ()

    def test_window_is_bounded_and_drops_the_oldest(self):
        m = NisWindowMonitor(NisConfig(window_size=4))
        for i in range(10):
            m.add_sample("gnss", float(i), False)
        assert len(m.history("gnss")) == 4
        assert m.history("gnss")[0][0] == 6.0

    def test_mean_nis_reports_the_window_and_an_empty_channel(self):
        m = NisWindowMonitor()
        assert m.mean_nis("gnss") == 0.0
        m.add_sample("gnss", 4.0, False)
        m.add_sample("gnss", 8.0, False)
        assert m.mean_nis("gnss") == pytest.approx(6.0)


class TestInflationBudget:
    """The bounds are the security argument, so they are tested as one."""

    def test_factor_is_capped(self):
        m = NisWindowMonitor()
        threshold = chi2_threshold(3, 0.001)
        assert m.inflation_factor(1e9, threshold) == 100.0
        assert m.inflation_factor(2.0 * threshold, threshold) == pytest.approx(2.0)

    def test_a_non_finite_distance_still_gets_the_cap_not_an_infinity(self):
        """An infinite distance is the case where the cap is least likely to be
        a problem, and it must not be a way to obtain unbounded covariance."""
        m = NisWindowMonitor()
        variance = m.inflation_variance(float("inf"), chi2_threshold(3, 0.001))
        assert variance == pytest.approx(900.0)

    def test_drift_bound_binds_when_the_filter_was_actually_blind(self):
        """More silence buys more room, and the growth is linear in sigma."""
        m = NisWindowMonitor()
        threshold = chi2_threshold(3, 0.001)
        a = m.inflation_variance(1e9, threshold, blind_s=4.0)
        b = m.inflation_variance(1e9, threshold, blind_s=8.0)
        assert np.sqrt(b) == pytest.approx(2.0 * np.sqrt(a))
        assert np.sqrt(b) == pytest.approx(0.5 * 8.0)

    def test_drift_bound_binds_hard_when_the_channel_was_not_silent(self):
        """A channel streaming a fix every 200 ms has had 200 ms of silence, so
        the budget is tiny no matter how long the spoof runs.

        This is the property that separates a sustained spoof from a genuine
        outage, and it is the reason the bound is measured from the longest single
        gap rather than from elapsed time.
        """
        m = NisWindowMonitor()
        variance = m.inflation_variance(1e9, chi2_threshold(3, 0.001), blind_s=0.2)
        assert np.sqrt(variance) == pytest.approx(0.1)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"window_size": 0},
            {"consecutive_rejection_threshold": 0},
            {"max_inflation_factor": 0.5},
            {"reacq_pos_sigma_m": 0.0},
            {"max_drift_sigma_mps": 0.0},
            {"reaccept_margin": 0.0},
            {"reaccept_margin": 1.5},
        ],
    )
    def test_nonsensical_configuration_is_refused(self, kwargs):
        with pytest.raises(ValueError):
            NisConfig(**kwargs)


# --- the three cases the mechanism exists for ------------------------------


class TestSingleImpulseIsNotRelieved:
    """One 20 m step is a sensor event. The covariance must not move."""

    def test_a_single_impulse_is_rejected_without_inflation(self):
        gt, imu, fixes = _platform()
        result = _filter(gnss_position_sigma_m=0.1).run(
            imu, gnss=_offset_fixes(fixes, [20.0, 0.0, 0.0], start=40, count=1)
        )
        stats = result.stats
        assert stats["fdir_gnss_rejected"] == 1.0
        assert stats["fdir_inflations"] == 0.0
        assert stats["fdir_gnss_reaccepted"] == 0.0
        # Not a fault, and not a persistent rejection either: nothing about a
        # single bad sample says the sensor is broken.
        assert stats["fdir_gnss_faulted"] == 0.0
        assert _grants(result) == []
        # And the estimate did not move toward it.
        assert _final_position_error(gt, result) < 0.5

    def test_the_status_names_the_policy_and_not_a_diagnosis(self):
        """`REJECTED_SPOOF` states what the filter did, not what happened.

        The gate cannot distinguish multipath from a spoof from a miscalibrated
        filter -- ADR-0005 says so -- and a status string claiming to know would
        be the overclaim moved out of prose and into an API. The name documents
        the policy: an unproven channel gets no relief.
        """
        assert STATUS_REJECTED_SPOOF == "REJECTED_SPOOF"
        assert "TRANSIENT" not in STATUS_REJECTED_SPOOF

    def test_a_run_of_impulses_on_a_live_channel_gets_no_relief(self):
        """Six bad epochs in a row is a persistent divergence, and it still buys
        nothing, because the channel never went silent.

        This is the same platform as the single-impulse case above, streaming at
        5 Hz without a gap. Its drift budget is 0.5 m/s of a 0.2 s silence, so
        0.1 m of sigma against a 20 m innovation. The relief mechanism is
        available and correctly declines: the only thing that unlocks it is
        evidence that the filter went blind, and there is none here.
        """
        gt, imu, fixes = _platform()
        result = _filter(gnss_position_sigma_m=0.1).run(
            imu, gnss=_offset_fixes(fixes, [20.0, 0.0, 0.0], start=40, count=6)
        )
        assert result.stats["fdir_inflations"] == 0.0
        assert _grants(result) == []
        assert _final_position_error(gt, result) < 0.5


class TestPersistentOffsetIsRelieved:
    """The B5 case: a channel that was silent, and is now telling the truth."""

    def _denial(self, **fdir_kwargs):
        """`outage_visual`: 15 s GNSS denial with vision aiding.

        Values are copied from `configs/benchmark.yaml` rather than imported, so
        this test cannot silently follow a change to the published scenario. It
        is pinning a measured result, and a result measured against a scenario
        that has since moved is not the same number.
        """
        syn = SyntheticConfig(
            duration_s=30.0, rate_hz=100.0, radius_m=4.0, circles=1.5,
            sway_amplitude_m=0.6, sway_cycles=3.0, yaw_amplitude_deg=35.0,
            yaw_cycles=1.0, start_position=(1.0, 0.0, 1.6),
        )
        gt = synthetic_trajectory(syn)
        gt = gt.transformed(la.inv(gt.poses[0]))
        imu = synthetic_imu(syn)
        gnss = apply_gnss_outage(
            gnss_fixes(gt, GnssConfig(rate_hz=5.0, sigma_m=0.8, seed=0)),
            [Outage(start_s=5.0, duration_s=15.0)],
            True,
        )
        vision = visual_updates(
            gt, VisionConfig(rate_hz=20.0, rot_sigma_deg=0.35, trans_sigma_m=0.05, seed=0)
        )
        cfg = EskfConfig(
            imu_noise=ImuNoiseModel(2e-4, 2e-3, 2e-6, 1e-4, 1e-5, 2e-3),
            gnss_position_sigma_m=0.8,
            vision_enabled=True,
            vision_rot_sigma_deg=0.35,
            vision_trans_sigma_m=0.05,
            vision_keyframe_interval=1,
            fdir_config=FdirConfig(**fdir_kwargs),
        )
        return gt, ErrorStateKalmanFilter(cfg).run(imu, gnss=gnss, vision=vision)

    def test_reacquisition_fixes_are_reaccepted_and_pull_position_back(self):
        gt, result = self._denial()
        stats = result.stats
        assert stats["fdir_inflations"] == 1.0
        assert stats["fdir_gnss_reaccepted"] == 1.0
        # Against the plain gate, which is what the fix was for.
        _, plain = self._denial(reacq_consecutive_rejections=999)
        assert plain.stats["fdir_gnss_rejected"] > 40.0
        assert stats["fdir_gnss_rejected"] < 20.0
        assert _final_position_error(gt, result) < 0.5 * _final_position_error(gt, plain)

    def test_the_grant_is_logged_with_what_it_bought(self):
        _, result = self._denial()
        grant = _grants(result)[0]
        assert grant["sensor"] == "gnss"
        # The distance collapses: that is the whole mechanism, and a log line
        # that recorded only "an inflation happened" would not show it.
        assert grant["mahalanobis_sq"] > grant["threshold"]
        assert grant["mahalanobis_sq_inflated"] < grant["threshold"]
        assert grant["inflation_variance"] > 0.0

    def test_the_position_block_is_inflated_and_nothing_else(self):
        """Inflating all 21 states on a position innovation would still be a
        valid covariance, and would be a filter suddenly unsure of its own gyro
        bias."""
        _, result = self._denial()
        sigma = np.sqrt(np.diagonal(result.position_cov, axis1=1, axis2=2))
        assert np.all(np.isfinite(sigma))
        # A 1-sigma of tens of metres would be a filter that has given up. The
        # bound is 0.5 m/s of drift, and this run is blind for 15 s.
        assert float(np.max(sigma)) < 20.0

    def test_disabling_adaptation_restores_the_old_behaviour(self):
        """The switch has to be a real off, not a wider gate."""
        gt, off = self._denial(reacq_consecutive_rejections=999)
        assert off.stats["fdir_inflations"] == 0.0
        assert off.stats["fdir_gnss_rejected"] > 40.0
        assert _final_position_error(gt, off) > 9.0


class TestInflationLimits:
    """The cap, and what a sustained attack can get out of the mechanism."""

    def test_a_large_sustained_offset_is_not_followed(self):
        """The security property, measured.

        A spoof delivered continuously is not a silence, so it earns no drift
        budget, so the innovation never becomes plausible and the estimate never
        moves toward it. 40 m and 100 m are the two that matter: an order of
        magnitude past anything the platform claims, and one past the scale of a
        plausible attack.
        """
        gt, imu, fixes = _platform()
        for offset in (40.0, 100.0):
            result = _filter(gnss_position_sigma_m=0.1).run(
                imu, gnss=_offset_fixes(fixes, [offset, 0.0, 0.0], start=40, count=30)
            )
            assert result.stats["fdir_inflations"] == 0.0, f"{offset} m got a grant"
            assert result.stats["fdir_gnss_rejected"] > 20.0
            assert _final_position_error(gt, result) < 0.5, f"followed a {offset} m spoof"

    def test_a_spoof_small_enough_to_drift_toward_is_still_isolated(self):
        """The regression this whole `outlier` distinction exists for.

        A 1 m offset does not stay a 1 m innovation. The filter is pulled toward
        it, the residual shrinks, and after a few epochs the innovation is
        *inside* the threshold -- the gate is entirely happy. The channel is
        still held out, but now for a different reason: a declared fault, not an
        outlier.

        The first version of this code could not tell those two exclusions apart.
        It treated the fault hold as an outlier, spent the drift budget on it,
        and the re-gate passed -- so a 1 m sustained spoof got a grant and moved
        the estimate 2.1 m, while a 3 m spoof was correctly refused. The
        mechanism was inverted over exactly the range an attacker would pick.

        Both halves are asserted, because only the pair distinguishes them: a
        test on 40 m alone passes against the broken code.
        """
        _gt, imu, fixes = _platform()
        for offset in (1.0, 2.0, 3.0):
            result = _filter(
                gnss_position_sigma_m=0.1,
                fdir_config=FdirConfig(max_consecutive_rejections=5),
            ).run(
                imu, gnss=_offset_fixes(fixes, [offset, 0.0, 0.0], start=40, count=30)
            )
            assert result.stats["fdir_inflations"] == 0.0, f"{offset} m got a grant"
            assert _grants(result) == []
            # Small enough that the filter drifts toward it and the innovation
            # falls back inside the threshold: the channel is then excluded by a
            # fault, and that exclusion is what the grant must not undo.
            if offset <= 2.0:
                assert result.stats["fdir_gnss_faulted"] == 1.0, offset

    def test_a_consistent_sample_under_a_fault_is_not_eligible_for_relief(self):
        """The unit-level statement of the same rule.

        Here the exclusion and the innovation are set up by hand, with no filter
        in the way: the sample is comfortably inside the threshold and the
        channel is faulted, so the decision is a refusal on the strength of the
        fault alone.
        """
        m = FdirManager(FdirConfig(max_consecutive_rejections=1))
        S = np.eye(3) * 0.01
        m.check("gnss", np.array([50.0, 0.0, 0.0]), S, t_s=0.0)
        assert m.is_faulted("gnss")
        P = np.eye(21) * 0.01
        H = np.zeros((3, 21))
        H[0, 3] = 1.0
        d = m.evaluate_and_adapt(
            "gnss", np.zeros(3), S, t_s=0.2, P=P, H=H, block=(3, 4, 5)
        )
        assert not d.accepted
        assert d.status == STATUS_REJECTED_PERSISTENT
        assert not d.outlier, "a consistent sample is not an outlier"
        assert not d.inflated

    def test_a_genuine_outlier_is_still_eligible(self):
        """The rule has to exclude fault holds without excluding real outliers,
        or the fix for B5 would be a fix that does not fix anything."""
        m = FdirManager(FdirConfig(max_consecutive_rejections=1))
        S = np.eye(3) * 0.01
        P = np.eye(21) * 0.01
        H = np.zeros((3, 21))
        H[0, 3] = 1.0
        for i in range(3):
            d = m.evaluate_and_adapt(
                "gnss", np.array([0.6, 0.0, 0.0]), S, t_s=i * 0.2,
                P=P, H=H, block=(3, 4, 5),
            )
        assert d.outlier
        assert d.mahalanobis_sq > d.threshold

    def test_a_sustained_offset_still_escalates_to_a_fault(self):
        """Relief is one grant, and the channel is still isolated after it."""
        _, imu, fixes = _platform()
        result = _filter(
            gnss_position_sigma_m=0.1, fdir_config=FdirConfig(max_consecutive_rejections=5)
        ).run(imu, gnss=_offset_fixes(fixes, [60.0, 0.0, 0.0], start=40, count=30))
        statuses = {e["status"] for e in result.trajectory.metadata["fdir_events"]}
        assert STATUS_SENSOR_FAULT in statuses

    def test_the_variance_handed_over_is_bounded(self):
        """A single grant may not exceed the cap, whatever the innovation is.

        100x3 m of variance is a 30 m 1-sigma. The mechanism is allowed to admit
        that much and no more, which is what makes it safe to enable at all.
        """
        m = NisWindowMonitor()
        threshold = chi2_threshold(3, 0.001)
        for distance in (1e3, 1e6, 1e12, float("inf")):
            variance = m.inflation_variance(distance, threshold, blind_s=1e6)
            assert np.sqrt(variance) <= 30.0 + 1e-9

    def test_a_growing_drift_budget_never_exceeds_the_factor_cap(self):
        m = NisWindowMonitor()
        threshold = chi2_threshold(3, 0.001)
        for blind_s in (1.0, 10.0, 100.0, 1000.0):
            variance = m.inflation_variance(1e9, threshold, blind_s=blind_s)
            assert variance <= 900.0 + 1e-9

    def test_inflation_is_not_available_to_the_visual_channels(self):
        """The anchor blocks are pose offsets, and `reacq_sigma_m` is metres.

        A metre-derived variance added to a radian block is a dimensional mistake
        that still yields a valid covariance, so nothing downstream would object.
        The estimator therefore names only GNSS, and this pins that.
        """
        assert set(_FDIR_INFLATION_BLOCK) == {"gnss"}

    def test_a_visual_step_still_faults_the_channel(self):
        """The ADR-0001 protections are not relaxed by any of this."""
        cfg = SyntheticConfig(duration_s=_DURATION_S, rate_hz=100.0)
        gt = synthetic_trajectory(cfg)
        gt = gt.transformed(la.inv(gt.poses[0]))
        imu = synthetic_imu(cfg, rate_hz=200.0)
        vision = visual_updates(
            gt, VisionConfig(rate_hz=20.0, rot_sigma_deg=0.35, trans_sigma_m=0.05, seed=0)
        )
        R_rel, t_rel = vision.R_rel.copy(), vision.t_rel.copy()
        t_rel[200:220] += np.array([0.0, 0.0, 10.0])
        stepped = VisionUpdate(
            t=vision.t.copy(),
            R_rel=R_rel,
            t_rel=t_rel,
            rot_cov=None if vision.rot_cov is None else vision.rot_cov.copy(),
            trans_cov=None if vision.trans_cov is None else vision.trans_cov.copy(),
        )
        result = _filter(
            vision_enabled=True, vision_keyframe_interval=1, fdir_config=FdirConfig()
        ).run(imu, vision=stepped)
        stats = result.stats
        assert stats["fdir_vision_trans_rejected"] > 0.0
        assert stats["fdir_inflations"] == 0.0
        statuses = {e["status"] for e in result.trajectory.metadata["fdir_events"]}
        assert STATUS_SENSOR_FAULT in statuses
        assert STATUS_REJECTED_PERSISTENT in statuses


# --- the wiring -------------------------------------------------------------


class TestFdirManagerWiring:
    def test_adaptation_needs_a_covariance_to_inflate(self):
        """Without P and H there is nothing to do, so the second pass declines."""
        m = FdirManager()
        for _ in range(3):
            m.check("gnss", np.array([20.0, 0.0, 0.0]), np.eye(3) * 0.01, t_s=0.0)
        d = m.evaluate_and_adapt("gnss", np.array([20.0, 0.0, 0.0]), np.eye(3) * 0.01)
        assert not d.accepted
        assert not d.inflated
        assert d.status == STATUS_REJECTED_PERSISTENT

    def test_a_block_of_no_indices_disables_the_second_pass(self):
        m = FdirManager()
        for _ in range(3):
            m.evaluate_and_adapt(
                "gnss", np.array([20.0, 0.0, 0.0]), np.eye(3) * 0.01,
                P=np.eye(21) * 0.01, H=np.zeros((3, 21)), block=(),
            )
        d = m.evaluate_and_adapt(
            "gnss", np.array([20.0, 0.0, 0.0]), np.eye(3) * 0.01,
            P=np.eye(21) * 0.01, H=np.zeros((3, 21)), block=(),
        )
        assert not d.inflated
        assert d.inflation_block == ()

    def test_a_fault_declared_by_the_plain_gate_is_not_relabelled(self):
        """Pass 2 must not overwrite SENSOR_FAULT with a softer label.

        Measurement caught this: the relabel ran unconditionally, so a channel
        that had genuinely been declared faulty was recorded in the event log as
        an ordinary persistent rejection and no fault ever appeared.
        """
        m = FdirManager(FdirConfig(max_consecutive_rejections=2))
        P = np.eye(21) * 0.01
        H = np.zeros((3, 21))
        H[0, 3] = 1.0
        far = np.array([40.0, 0.0, 0.0])
        for i in range(2):
            d = m.evaluate_and_adapt(
                "gnss", far, H @ P @ H.T + np.eye(3) * 0.01, t_s=i * 0.2,
                P=P, H=H, block=(3, 4, 5),
            )
        assert d.status == STATUS_SENSOR_FAULT
        assert d.sensor_fault
        assert STATUS_SENSOR_FAULT in {e.status for e in m.events}

    def test_the_decision_tells_the_estimator_what_to_inflate(self):
        """`inflation_variance` and `inflation_block` are a contract, not advice.

        The estimator applies exactly this to P and recomputes S before forming
        the gain, so the fused update is the one the re-gate cleared.
        """
        m = FdirManager()
        P = np.eye(21) * 1e-3
        H = np.zeros((3, 21))
        H[0, 3] = 1.0
        S = H @ P @ H.T + np.eye(3) * 0.01
        # A long silence earns a large budget; a 3 m innovation then passes.
        for i in range(3):
            m.evaluate_and_adapt(
                "gnss", np.array([3.0, 0.0, 0.0]), S, t_s=100.0 + i * 0.2,
                P=P, H=H, block=(3, 4, 5),
            )
        assert m.state("gnss").longest_silence_s == pytest.approx(0.2)
        d = m.evaluate_and_adapt(
            "gnss", np.array([3.0, 0.0, 0.0]), S, t_s=100.6,
            P=P, H=H, block=(3, 4, 5),
        )
        # A 0.2 s silence earns 0.1 m of sigma, which cannot explain 3 m, so the
        # mechanism correctly declines even though the divergence is persistent.
        assert not d.inflated
        assert d.status == STATUS_REJECTED_PERSISTENT

    def test_a_clean_accept_closes_the_episode(self):
        m = FdirManager()
        S = np.eye(3) * 0.01
        d = m.check("gnss", np.zeros(3), S, t_s=0.0)
        assert d.status == STATUS_ACCEPTED
        assert not d.recovered
        assert m.state("gnss").consecutive_rejections == 0
        assert not m.nis.is_persistent_divergence("gnss")

    def test_recovery_after_a_fault_is_flagged_on_the_decision(self):
        m = FdirManager(FdirConfig(max_consecutive_rejections=2, auto_recovery_count=3))
        S = np.eye(3) * 0.01
        for i in range(2):
            m.check("gnss", np.array([50.0, 0.0, 0.0]), S, t_s=i * 0.2)
        assert m.is_faulted("gnss")
        # Hysteresis: the first good samples are credited but the channel stays
        # excluded, because one healthy epoch after a fault is not a recovery.
        # The cadence is uninterrupted on purpose -- a gap wider than twice the
        # channel's own period is a material silence, and that wipes the
        # recovery credit along with everything else.
        for i in range(2):
            d = m.check("gnss", np.zeros(3), S, t_s=0.4 + i * 0.2)
            assert not d.accepted
            assert not d.recovered
            assert m.is_faulted("gnss")
        d = m.check("gnss", np.zeros(3), S, t_s=0.8)
        assert d.recovered
        assert not m.is_faulted("gnss")

    def test_stats_expose_the_new_counters(self):
        m = FdirManager()
        S = np.eye(3) * 0.01
        for i in range(3):
            m.check("gnss", np.array([50.0, 0.0, 0.0]), S, t_s=i * 0.2)
        stats = m.stats()
        for key in (
            "fdir_gnss_rejected",
            "fdir_gnss_reaccepted",
            "fdir_gnss_inflation_variance",
            "fdir_gnss_mean_nis",
        ):
            assert key in stats

    def test_reset_channel_drops_isolation_state_and_history(self):
        m = FdirManager()
        S = np.eye(3) * 0.01
        for i in range(3):
            m.check("gnss", np.array([50.0, 0.0, 0.0]), S, t_s=i * 0.2)
        assert m.nis.is_persistent_divergence("gnss")
        m.reset_channel("gnss")
        assert not m.nis.is_persistent_divergence("gnss")
        assert m.state("gnss").rejected_total == 0

    def test_disabled_fdir_touches_nothing(self):
        m = FdirManager(FdirConfig(enabled=False))
        d = m.evaluate_and_adapt(
            "gnss", np.array([50.0, 0.0, 0.0]), np.eye(3) * 0.01, t_s=0.0,
        )
        assert d.accepted
        assert d.status == STATUS_ACCEPTED
        assert m.stats()["fdir_channels"] == 0
        assert m.nis.channels() == ()

    def test_the_fault_config_survives_a_round_trip(self):
        cfg = FdirConfig(reacq_consecutive_rejections=4, max_drift_sigma_mps=0.75)
        again = FdirConfig(**cfg.as_dict())
        assert again.nis_config() == cfg.nis_config()

    @pytest.mark.parametrize("field", ["reacq_consecutive_rejections", "reacq_window",
                                       "max_inflation_factor", "reacq_sigma_m",
                                       "max_drift_sigma_mps", "reaccept_margin"])
    def test_nonsense_fault_configuration_is_refused(self, field):
        with pytest.raises(ValueError):
            FdirConfig(**{field: -1.0})


# --- ADR-0007: spoof permanence -------------------------------------------


def _denial_then_spoof(offset_m: float, **fdir_kwargs):
    """`outage_visual`, then a constant x-offset on every fix that returns.

    This builds audit finding H5: a 15 s denial leaves the filter displaced, the
    drift budget buys an inflation grant, that grant is large enough to pull the
    mean most of the way to the offset, and every later spoofed fix is then small
    relative to the corrupted mean. Measured in this repository: 22 m of
    post-outage offset is admitted with exactly one grant.

    ``available`` has to survive the rebuild below, or the outage window stops
    being silent and the drift budget never engages -- which silently turns this
    into a different scenario that passes for the wrong reason.

    The first keyword arguments are routed to ``EskfConfig`` and the rest to
    ``FdirConfig``, so a caller can vary either side of the loss.
    """
    eskf_extra: dict = {}
    fdir_extra: dict = {}
    for k, v in fdir_kwargs.items():
        if k in ("vision_keyframe_interval",) or k.startswith("vision_"):
            eskf_extra[k] = v
        else:
            fdir_extra[k] = v
    syn = SyntheticConfig(
        duration_s=30.0, rate_hz=100.0, radius_m=4.0, circles=1.5,
        sway_amplitude_m=0.6, sway_cycles=3.0, yaw_amplitude_deg=35.0,
        yaw_cycles=1.0, start_position=(1.0, 0.0, 1.6),
    )
    gt = synthetic_trajectory(syn)
    gt = gt.transformed(la.inv(gt.poses[0]))
    imu = synthetic_imu(syn)
    gnss = apply_gnss_outage(
        gnss_fixes(gt, GnssConfig(rate_hz=5.0, sigma_m=0.8, seed=0)),
        [Outage(start_s=5.0, duration_s=15.0)],
        True,
    )
    spoofed = GnssFix(
        t=gnss.t.copy(),
        positions=gnss.positions.copy(),
        cov=None if gnss.cov is None else gnss.cov.copy(),
        available=gnss.available.copy(),
    )
    returning = spoofed.t >= 20.0
    spoofed.positions[returning, 0] += offset_m
    vision = visual_updates(
        gt, VisionConfig(rate_hz=20.0, rot_sigma_deg=0.35, trans_sigma_m=0.05, seed=0)
    )
    base_eskf = {
        "imu_noise": ImuNoiseModel(2e-4, 2e-3, 2e-6, 1e-4, 1e-5, 2e-3),
        "gnss_position_sigma_m": 0.8,
        "vision_enabled": True,
        "vision_rot_sigma_deg": 0.35,
        "vision_trans_sigma_m": 0.05,
        "vision_keyframe_interval": 1,
    }
    if "vision_keyframe_interval" in eskf_extra:
        base_eskf["vision_keyframe_interval"] = eskf_extra.pop("vision_keyframe_interval")
    cfg = EskfConfig(
        **base_eskf,
        **eskf_extra,
        fdir_config=FdirConfig(**fdir_extra),
    )
    return gt, ErrorStateKalmanFilter(cfg).run(imu, gnss=spoofed, vision=vision)


def _blind_gnss_manager(offset_m: float, n_updates: int = 24, **fdir_kwargs):
    """A manager-level channel that goes silent and then returns spoofed.

    Units are metres on a position block and the covariance is unit, so this is
    the gate in isolation rather than the assembled filter. It is here because
    the two-grant escalation is a property of the monitor's state machine, and
    the filter-level case never reaches it.
    """
    m = FdirManager(FdirConfig(**fdir_kwargs))
    P, H, S = np.eye(3), np.eye(3), np.eye(3)
    t = 0.0
    for _ in range(5):
        m.evaluate_and_adapt("gnss", np.zeros(3), S, t_s=t, P=P, H=H, block=(0, 1, 2))
        t += 0.2
    t = 20.0  # 15 s of silence: what earns the drift budget in the first place
    for _ in range(n_updates):
        m.evaluate_and_adapt(
            "gnss", np.array([offset_m, 0.0, 0.0]), S, t_s=t, P=P, H=H, block=(0, 1, 2)
        )
        t += 0.2
    return m


class TestSpoofLockoutEscalates:
    """ADR-0007 option 2: escalation, cooldown, and the re-expansion it owes."""

    def test_a_second_grant_in_one_episode_escalates_to_a_spoof_lockout(self):
        m = _blind_gnss_manager(15.0)
        st = m.state("gnss")
        assert st.grants_this_episode >= 2
        assert m.is_locked_out("gnss")
        assert m.is_faulted("gnss")

    def test_the_lockout_carries_a_re_expansion_variance(self):
        m = _blind_gnss_manager(15.0)
        st = m.state("gnss")
        assert st.reexpansion_variance > 0.0, (
            "a lockout with no re-expansion leaves the filter coasting on a "
            "covariance that no longer describes a displaced mean"
        )
        d = st.as_dict()
        assert d["reexpansion_variance"] > 0.0
        assert d["locked_out"] is True
        assert np.isfinite(d["lockout_until_s"])

    def test_the_lockout_is_reported_separately_from_a_fault(self):
        """The two expire on different clocks, so an operator needs both flags.

        A fault clears on `auto_recovery_count` clean updates; a lockout clears
        only on elapsed time. Collapsing them would report a channel as usable
        the moment it produces a few clean fixes, which is exactly what a
        spoofed channel does.
        """
        m = _blind_gnss_manager(15.0)
        assert m.is_locked_out("gnss") and m.is_faulted("gnss")
        assert "locked_out" in m.state("gnss").as_dict()

    def test_a_locked_out_channel_cannot_buy_more_inflation(self):
        """Inside the cooldown, covariance is exactly what must not be on offer."""
        m = _blind_gnss_manager(15.0)
        before = m.state("gnss").grants_this_episode
        m = _blind_gnss_manager(15.0, n_updates=48)
        assert m.state("gnss").grants_this_episode == before, (
            "grants kept accruing after escalation, so the cooldown bounds "
            "nothing"
        )

    def test_the_lockout_expires_but_the_fault_does_not(self):
        """60 s cooldown, then ordinary recovery hysteresis -- not instant trust."""
        m = _blind_gnss_manager(15.0, spoof_lockout_s=60.0)
        assert m.is_locked_out("gnss")
        P, H, S = np.eye(3), np.eye(3), np.eye(3)
        d = m.evaluate_and_adapt(
            "gnss", np.zeros(3), S, t_s=30.0, P=P, H=H, block=(0, 1, 2)
        )
        assert m.is_locked_out("gnss"), "lockout released early"
        assert not d.accepted, "a locked-out channel accepted a measurement"
        m.evaluate_and_adapt(
            "gnss", np.zeros(3), S, t_s=100.0, P=P, H=H, block=(0, 1, 2)
        )
        assert not m.is_locked_out("gnss"), "lockout outlived its cooldown"
        assert m.is_faulted("gnss"), (
            "the lockout expiry granted trust outright instead of leaving the "
            "fault to the normal recovery hysteresis"
        )

    def test_a_genuine_post_outage_recovery_is_not_locked_out(self):
        """The threshold of two must not punish an honest re-acquisition.

        `outage_visual` grants exactly once on a truthful return, which is why
        `spoof_grant_threshold` is 2 and not 1. A threshold of 1 would lock out
        every working receiver coming back from a real outage.
        """
        _, result = _denial_then_spoof(0.0)
        lockouts = [
            e
            for e in result.trajectory.metadata["fdir_events"]
            if e["status"] == STATUS_REJECTED_SPOOF
        ]
        assert not lockouts, "a truthful return from a denial was judged a spoof"
        assert result.stats["fdir_gnss_reaccepted"] == 1.0

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"spoof_grant_threshold": 0},
            {"spoof_lockout_s": 0.0},
            {"spoof_reexpansion_factor": 0.5},
        ],
    )
    def test_nonsense_lockout_configuration_is_refused(self, kwargs):
        with pytest.raises(ValueError):
            FdirConfig(**kwargs)


class TestPermanenceIsStillUndetected:
    """The gap ADR-0007 was written to close, and does not yet close.

    Each of these is a measurement, not an expectation. They are the reason
    `spoof_grant_threshold` cannot be the whole mitigation: on the scenario
    that motivated the ADR, the channel grants inflation once, the inflated
    update pulls the mean onto the spoofed offset, and every later fix is then
    small relative to that corrupted mean. Nothing is ever rejected a second
    time, so the second-grant trigger has nothing to fire on.

    `xfail(strict=False)` is deliberate. Turning these green requires a second
    modality to cross-check GNSS against, not more hysteresis on one channel --
    see the open question in ADR-0007.
    """

    @pytest.mark.xfail(
        strict=False, reason="one grant, then permanent adoption; no second grant to count"
    )
    def test_a_permanently_adopted_offset_is_locked_out(self):
        _, result = _denial_then_spoof(22.0)
        lockouts = [
            e
            for e in result.trajectory.metadata["fdir_events"]
            if e["status"] == STATUS_REJECTED_SPOOF
        ]
        assert lockouts, "audit finding H5: 22 m admitted with no escalation"

    @pytest.mark.xfail(strict=False, reason="same cause as the lockout test above")
    def test_the_admitted_offset_exceeds_what_the_drift_budget_can_explain(self):
        """The measurable form of the gap.

        A truthful return consumes about 1.1 drift-sigma of the grant; a spoof
        consumes 1.4 to 2.0. The bands overlap below ~1.4, so a threshold on
        this ratio cannot separate an honest re-acquisition from a modest spoof
        -- it only separates large offsets from small ones.
        """
        from navkit.fdir import FdirManager

        orig = FdirManager._reaccept_with_inflation

        def spy(self, sensor, innovation, S, P, H, block, decision, t_s):
            d = orig(self, sensor, innovation, S, P, H, block, decision, t_s)
            spy.ratio = (
                float(np.linalg.norm(innovation)) / np.sqrt(d.inflation_variance)
                if d.accepted and d.inflated and d.inflation_variance > 0
                else None
            )
            return d

        FdirManager._reaccept_with_inflation = spy
        try:
            for offset in (0.0, 22.0):
                spy.ratio = None
                _denial_then_spoof(offset)
                assert spy.ratio is not None
                if offset == 22.0:
                    spoofed_ratio = spy.ratio
        finally:
            FdirManager._reaccept_with_inflation = orig
        assert spy.ratio is not None
        assert spoofed_ratio < 2.2, (
            "ratio fell under the honest-recovery band; the discriminator may "
            "now be separable and the ADR's open question can be answered"
        )


class TestFrozenAnchorCrossCheck:
    """The anchor cross-check in `_update`, measured rather than assumed.

    A visual anchor is frozen at the start of a GNSS outage and every later grant
    is checked against it: a fix that disagrees with the anchor by more than
    `15^2` in Mahalanobis distance is refused. On paper that is a second modality
    for the case ADR-0007 could not close, and `TestPermanenceIsStillUndetected`
    above is the standing evidence that one channel cannot detect permanence by
    itself.

    Measured here, the branch does what it says at the arithmetic level and is
    then never reached. The guard needs `gnss_grants_since_verified > 0` *and*
    `decision.inflated` on the same epoch, and the grant counter cannot be
    positive on a grant: the counter is incremented by the grant itself, and the
    epoch after a grant is a clean accept, which resets it to zero (the
    `decision.accepted and not decision.inflated` branch in `_update`). So
    `grants == 0` on every inflation epoch, and the cross-check never runs on
    the scenario it was written for.

    Both halves are pinned. The first says the refusal arithmetic is correct, so
    a later fix to the guard is a one-line change rather than a rewrite. The
    second says the guard is currently unreachable, so the mitigation is not
    counted as working anywhere.
    """

    #: The threshold the branch compares against, read from the source rather
    #: than restated, so retuning the code does not silently invalidate the test.
    THRESHOLD_SQ = 225.0

    def _granted_state(self, **cfg_kwargs):
        """A state mid-episode with one grant already spent.

        Built by hand rather than by running a filter, because no filter run
        produces this state: the grant counter is reset before the next grant
        can occur. That is the finding, so the test has to construct it directly.
        """
        # `gate_sigma` is the legacy per-update residual test that runs
        # independently, after FDIR, at `eskf.py:577`. Left at its default it
        # rejects a 60 m fix on its own, which would let the test below pass
        # with the cross-check deleted -- the outcome would be identical and the
        # cause would be wrong. It is disabled so the cross-check is the only
        # thing in the file that can refuse, and the test measures it.
        eskf = _filter(vision_enabled=True, gate_sigma=0.0, **cfg_kwargs)
        x = {
            "R": np.eye(3), "p": np.zeros(3), "v": np.zeros(3),
            "b_a": np.zeros(3), "b_g": np.zeros(3), "P": np.eye(21) * 0.01,
            "R_vk": np.eye(3), "p_vk": np.zeros(3),
            "P_theta_vk": np.eye(3) * 0.01, "P_p_vk": np.eye(3) * 0.01,
            "c_p": np.zeros(3), "c_t": np.zeros(3),
            "vision_keyframe_set": True, "vision_updates": 0,
            "gnss_grants_since_verified": 1,  # the state a run cannot reach
            "anchor_snapshot": {
                "R_vk": np.eye(3), "p_vk": np.zeros(3),
                "c_p": np.zeros(3), "c_t": np.zeros(3),
                "P_p_vk": np.eye(3) * 0.01, "P_cp": np.eye(3) * 0.01,
            },
        }
        return eskf, x

    def _forced_grant_update(self, eskf, x, offset_m, t_s=20.0):
        """One GNSS update with FDIR's verdict forced to an inflated grant.

        `evaluate_and_adapt` is stubbed rather than driven, because reaching an
        inflated verdict requires a run of rejections that the state above will
        not produce. The point under test is the estimator's response to the
        verdict, so the verdict is the input.
        """
        from navkit.fdir import GatingDecision

        decision = GatingDecision(
            accepted=True,
            mahalanobis_sq=float("inf"),
            threshold=float("inf"),
            dof=3,
            status=STATUS_REACCEPTED_WITH_INFLATION,
            inflation_variance=1.0,
            inflation_block=(3, 4, 5),
            outlier=True,
        )
        eskf.fdir.evaluate_and_adapt = lambda *a, **k: decision
        try:
            return eskf._gnss_update(
                x, np.array([offset_m, 0.0, 0.0]), 0.8, t_s=t_s
            )
        finally:
            del eskf.fdir.evaluate_and_adapt

    def test_a_fix_that_contradicts_the_frozen_anchor_is_refused(self):
        """The arithmetic. A 60 m disagreement is ~5.4e3 and is refused."""
        eskf, x = self._granted_state()
        accepted, d2 = self._forced_grant_update(eskf, x, 60.0)
        assert not accepted, "a fix 5.4e3 from the frozen anchor was fused"
        assert d2 > self.THRESHOLD_SQ

    def test_a_fix_that_agrees_with_the_frozen_anchor_is_accepted(self):
        """The other half, without which the test above passes a filter that
        refuses everything.

        The offset is 5 m, not zero. A fix exactly at the anchor sits at
        d2 = 0.0, so a cross-check whose threshold had been broken down to
        "refuse anything non-zero" would still pass it; 5 m is d2 = 15.2, an
        order of magnitude inside the threshold, and separates the two failure
        directions. Measured in this state: 5 m is accepted, 20 m is not.
        """
        eskf, x = self._granted_state()
        accepted, d2 = self._forced_grant_update(eskf, x, 5.0)
        assert accepted, f"a fix 5 m from the anchor was refused (d2={d2:.1f})"
        assert d2 < self.THRESHOLD_SQ

    def test_the_threshold_separates_a_honest_return_from_a_spoof(self):
        """What the number is worth: 15^2 against the two populations.

        Measured in this state, where the anchor covariance is 0.66 m^2 per axis.
        5 m of honest disagreement is d2 = 15.2 and 60 m is d2 = 5454.5, so the
        threshold has a wide margin on both sides. What it does not have is
        reach: a spoof under about 20 m stays inside it, which is the same
        limitation the drift budget has and the reason this cannot be the whole
        answer to ADR-0007.
        """
        honest = self._forced_grant_update(*self._granted_state(), 5.0)[1]
        spoofed = self._forced_grant_update(*self._granted_state(), 60.0)[1]
        assert spoofed > 15.0 * honest, (honest, spoofed)
        modest = self._forced_grant_update(*self._granted_state(), 10.0)[1]
        assert modest < self.THRESHOLD_SQ, (
            f"a 10 m spoof now clears the threshold (d2={modest:.1f}); the "
            "measured reach of this check has changed"
        )

    def test_the_threshold_sits_between_the_honest_and_spoof_bands(self):
        """Pin where 15^2 actually falls, not just that both ends clear it.

        The two tests either side of this one would both pass with the threshold
        at 100 or at 225, because no other point in the suite lands between
        them. This is that point: 12 m is d2 = 87.3 and must be accepted, 12.5 m
        is d2 = 236.7 and must be refused. The 0.5 m gap between them is the
        entire resolution of the check, and it is why the threshold being
        "about 15 sigma" is not the same as it being 15 sigma.
        """
        accepted, d2_low = self._forced_grant_update(*self._granted_state(), 12.0)
        assert accepted, f"12 m (d2={d2_low:.1f}) was refused"
        assert 50.0 < d2_low < self.THRESHOLD_SQ

        refused, d2_high = self._forced_grant_update(*self._granted_state(), 12.5)
        assert not refused, f"12.5 m (d2={d2_high:.1f}) was fused"
        assert self.THRESHOLD_SQ < d2_high < 400.0

    def test_the_guard_is_never_satisfied_during_a_sustained_offset_spoof(self):
        """The measurement that matters: on the real scenario the branch is dead.

        Every epoch of `_denial_then_spoof` is inspected for the two conditions
        the cross-check needs. Across a truthful return and 5 m to 100 m of
        offset, no epoch satisfies both, so the refusal above protects nothing
        in this scenario. The second-grant trigger ADR-0007 relies on has nothing
        to fire on for the same reason: one grant, then permanent adoption.

        This is `strict=True` on purpose. It asserts the gap is still open, so
        it fails loudly the moment the guard is fixed -- at which point the xfail
        tests above and the roadmap's B1 discussion need revisiting, and that
        should be a deliberate change rather than a surprise.
        """
        from navkit.estimators import eskf as eskf_mod

        observed: list[tuple[int, bool, bool]] = []
        by_time: dict[tuple[float, str], object] = {}
        orig_eea = FdirManager.evaluate_and_adapt
        orig_update = eskf_mod.ErrorStateKalmanFilter._update

        def spy_eea(self, sensor, innovation, S, t_s=0.0, P=None, H=None, block=None):
            d = orig_eea(
                self, sensor, innovation, S, t_s=t_s, P=P, H=H, block=block
            )
            by_time[(round(float(t_s), 4), sensor)] = d
            return d

        def spy_update(self, x, residual, H, Rcov, sensor="unknown", t_s=0.0):
            grants = int(x.get("gnss_grants_since_verified", 0))
            snap = x.get("anchor_snapshot")
            out = orig_update(self, x, residual, H, Rcov, sensor=sensor, t_s=t_s)
            d = by_time.get((round(float(t_s), 4), sensor))
            if sensor == "gnss" and d is not None and d.inflated:
                observed.append((grants, snap is not None, True))
            return out

        FdirManager.evaluate_and_adapt = spy_eea
        eskf_mod.ErrorStateKalmanFilter._update = spy_update
        try:
            for offset in (0.0, 5.0, 12.0, 20.0, 22.0, 40.0, 100.0):
                _denial_then_spoof(offset)
        finally:
            FdirManager.evaluate_and_adapt = orig_eea
            eskf_mod.ErrorStateKalmanFilter._update = orig_update

        reachable = [o for o in observed if o[0] > 0 and o[1] and o[2]]
        assert observed, "no inflation grant observed; the probe is not measuring"
        assert reachable == [], (
            f"the frozen-anchor cross-check is now reachable at {reachable}; the "
            "gap it was written for may be closed -- revisit the ADR-0007 xfails, "
            "audit doc 06 item N1, and whether B1 is still open"
        )
        assert all(grants == 0 for grants, _, _ in observed), (
            "a grant happened with the counter already positive, so the guard "
            "condition changed and the comment in _update is no longer accurate"
        )
