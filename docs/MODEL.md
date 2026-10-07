# Model assumptions and interface contract

What the simulator and the filter assume, in the units they use. Everything here is
synthetic: the reference is an analytic trajectory, so ground truth is exact, and no
number in this repository is a field measurement. The configuration and result tables
below are checked against the code by `tests/test_model_doc.py`, so a field added
without a row, or a default that changed, fails the build.

Contents: [conventions](#conventions) | [time stepping](#time-stepping-and-data-flow) |
[state vector](#state-vector) | [seeding](#seeding-and-determinism) |
[configuration](#configuration-reference) | [result contract](#result-json-contract) |
[as implemented](#as-implemented-things-a-reader-should-know) | [FMEA-lite](#fmea-lite)

## Conventions

| Item | Convention |
|---|---|
| Units | SI inside the code: metres, seconds, radians. Config keys that end in `_deg` are degrees, `_hz` hertz, `_s` seconds. |
| World frame | Gravity is the constant `(0, 0, +9.80665)` m/s^2 in the world frame (`navkit.types.GRAVITY`). Specific force is `f = R^T (a_world - g)`, and the filter integrates `a_world = R (f - b_a) + g`. |
| Poses | `T_world_body`, a 4x4 matrix. `R` maps body to world. |
| Quaternions | `(w, x, y, z)`, Hamilton product, canonical hemisphere `w >= 0` ([ADR-0004](adr/0004-quaternion-order.md)). At a half turn (`w = 0`) either sign is canonical. |
| Attitude error | `R_true = R Exp(dtheta)`: a perturbation on the body side. Position, velocity and biases are additive errors. |
| Visual measurement | The relative pose `T_prev_cur`: rotation `R_{i-1}^T R_i` and translation `R_{i-1}^T (p_i - p_{i-1})`. "Previous" means the previous visual update, not the previous inertial tick. |
| Time | Seconds as float64. Streams must be non-decreasing in time. |

## Time stepping and data flow

- The filter takes one step per IMU sample. The benchmark generates the IMU at 200 Hz
  (a 5 ms step) from the analytic motion; the reference trajectory itself is sampled at
  `synthetic.rate_hz` (100 Hz).
- Within one IMU tick the order is fixed: propagate with the previous sample's
  measurement, then apply every GNSS fix whose timestamp is at or before the tick, then
  every visual update likewise.
- **There is no latency compensation.** A measurement is applied at the first tick at or
  after its timestamp, with the state as it is at that tick. The lag is reported as
  `max_measurement_latency_s` and nothing corrects for it.
- A gap in the IMU stream is bridged by holding the previous sample's accelerometer and
  gyro readings over the whole gap.
- GNSS runs at 5 Hz and vision at 20 Hz in the benchmark. Both are generated from the
  reference trajectory plus noise; neither is a sensor model of a real device.
- At the first IMU sample inside a GNSS outage the filter snapshots the visual anchor
  (used by the frozen-anchor cross-check, [ADR-0008](adr/0008-frozen-anchor-cross-check.md),
  which is implemented but never runs).

## State vector

The filter carries a 21-element error state. The nominal state is `(R, p, v, b_a, b_g)`.

| Index | Symbol | Meaning | Unit |
|---|---|---|---|
| 0:3 | `dtheta` | attitude error | rad |
| 3:6 | `dp` | position error | m |
| 6:9 | `dv` | velocity error | m/s |
| 9:12 | `db_g` | gyro bias error | rad/s |
| 12:15 | `db_a` | accelerometer bias error | m/s^2 |
| 15:18 | `c_p` | error of the stored visual anchor position | m |
| 18:21 | `c_t` | error of the stored visual anchor attitude | rad |

The anchor states are nuisance parameters. Their corrections are computed and
deliberately not applied (CN-003, see the comment in `_inject_correction`), which is
part of why visual aiding stays overconfident ([ADR-0001](adr/0001-anchor-as-filter-state.md),
[ADR-0003](adr/0003-ship-visual-disabled.md)).

## Seeding and determinism

- Every stochastic stream has its own seed: `gnss.seed`, `vision.seed`,
  `camera_drop.seed`. The IMU noise seed is derived from the scenario name, the string
  `imu` and the GNSS and vision seeds, so overriding the seeds also changes the IMU
  noise realisation.
- `navkit sweep seeds` overrides all three streams with the same integer. `navkit sweep
  scenes` varies the trajectory parameters instead (`seeded_scene`, ranges in
  `synthetic._SCENE_RANGES`) and leaves the noise seeds alone. The two axes are
  independent.
- The motion is built from `1 - cos(w t)` terms, so position, velocity and angular rate
  are exactly zero at `t = 0`. A filter initialised at the identity pose is exactly
  right at the first sample, which is what makes the fixture a known-answer test.
- The same code on the same machine gives byte-identical output once timing fields are
  stripped, and CI enforces that for the benchmark and the sweeps. Across platforms the
  benchmark is compared with the golden snapshot at a relative tolerance of 1e-9 plus an
  absolute floor of 1e-9, on Linux (Python 3.11, 3.12, 3.13), macOS and Windows (3.13). The
  first macOS and Windows runs differed by about 1e-7 because the synthetic IMU was a finite
  difference that amplified one-ulp differences in `cos`; it is now derived analytically
  ([ADR-0009](adr/0009-cross-platform-numerics.md)).

## Configuration reference

Defaults and types are the dataclass defaults. "Unit" is the unit the code uses, which
in a few places is not what the key's name suggests; those are called out in the table
and in [as implemented](#as-implemented-things-a-reader-should-know).

### Filter: `EskfConfig`

<!-- table:EskfConfig -->
| Key | Unit | Default | Meaning |
|---|---|---|---|
| `imu_noise` | see ImuNoiseModel | `required` | Inertial noise model the filter assumes. |
| `gnss_position_sigma_m` | m | `0.8` | 1-sigma GNSS position noise declared to the filter. |
| `gnss_enabled` | flag | `True` | Fuse GNSS fixes. |
| `vision_enabled` | flag | `False` | Fuse visual relative-pose updates. Off by default (ADR-0003, constraint S3). |
| `vision_rot_sigma_deg` | deg | `0.35` | 1-sigma of the measured relative rotation. |
| `vision_trans_sigma_m` | m | `0.05` | 1-sigma of the measured relative translation. |
| `vision_keyframe_interval` | accepted updates | `1` | Accepted visual updates between anchor re-commits; None holds one anchor for the run. |
| `vision_anchor_modelled` | flag | `True` | Carry the anchor error as filter state (true) or fold it into measurement noise (false, kept to reproduce the failure). |
| `anchor_pos_sigma_m` | m | `1.0` | Declared 1-sigma of a stored anchor position. |
| `anchor_rot_sigma_deg` | deg | `5.0` | Declared 1-sigma of a stored anchor attitude. |
| `anchor_pos_drift_sigma_m_s` | m per sqrt(s) | `0.0` | Random-walk strength on the anchor position. Named m/s; it enters Q as sigma^2 dt, so the unit is m/sqrt(s). |
| `anchor_rot_drift_sigma_deg_s` | deg per sqrt(s) | `0.0` | Random-walk strength on the anchor attitude. Same convention as the position term. |
| `gate_sigma` | multiples of predicted sigma | `5.0` | Per-component residual gate. |
| `fdir_config` | see FdirConfig | `factory` | Chi-square fault detection, isolation and recovery policy. |
| `gravity` | m/s^2, world frame | `None` | Gravity vector; None uses (0, 0, 9.80665). |
| `initial_pos_sigma_m` | m | `1.0` | 1-sigma of the initial position error. |
| `initial_vel_sigma_m_s` | m/s | `0.5` | 1-sigma of the initial velocity error. |
| `initial_rot_sigma_deg` | deg | `2.0` | 1-sigma of the initial attitude error. |
| `initial_bias_sigma` | rad/s and m/s^2 | `0.0` | One value used for both the gyro-bias and accel-bias states, so its unit differs between them. |

### Fault detection: `FdirConfig`

<!-- table:FdirConfig -->
| Key | Unit | Default | Meaning |
|---|---|---|---|
| `enabled` | flag | `True` | Run the chi-square FDIR layer. |
| `confidence_level` | probability | `0.999` | One minus the false-rejection probability on a healthy sensor. |
| `max_consecutive_rejections` | updates | `5` | Consecutive rejections before a channel is declared faulty. |
| `auto_recovery_count` | updates | `10` | Consecutive accepts needed to clear a declared fault. |
| `reacq_consecutive_rejections` | updates | `3` | Consecutive gate failures that make a channel eligible for adaptive inflation. |
| `reacq_window` | updates | `5` | Gate outcomes retained per channel (reporting only). |
| `max_inflation_factor` | ratio | `100.0` | Ceiling on variance an adaptation may add, as a multiple of the named variance. |
| `reacq_sigma_m` | m | `3.0` | 1-sigma of position uncertainty admitted to a re-acquiring channel. |
| `max_drift_sigma_mps` | m/s | `0.5` | 1-sigma per second by which a dead-reckoned position may be wrong. |
| `reaccept_margin` | fraction | `0.25` | How far inside the gate a re-accepted innovation must sit; valid range (0, 1]. |
| `spoof_grant_threshold` | grants | `2` | Inflation grants in one episode before the channel is treated as spoofed (ADR-0007). |
| `spoof_lockout_s` | s | `60.0` | Time a channel stays locked out once treated as spoofed. |
| `spoof_reexpansion_factor` | granted sigma | `2.0` | Extra covariance forced onto the block when a channel is locked out. |

### Inertial noise: `ImuNoiseModel`

Used twice: by the filter (inside `EskfConfig.imu_noise`) to size its process noise, and
by the scenario to corrupt the synthetic IMU.

The dataclass defaults below are all zero, meaning noise off. A `Scenario` does not use
them: it starts from `navkit.io.imu.DEFAULT_NOISE`, an order-of-magnitude set for an
industrial MEMS unit (gyro noise 2e-4, accelerometer noise 2e-3, gyro bias walk 2e-6,
accelerometer bias walk 1e-4, in the units below).

<!-- table:ImuNoiseModel -->
| Key | Unit | Default | Meaning |
|---|---|---|---|
| `gyro_noise_density` | rad/s/sqrt(Hz) | `0.0` | Gyro white noise. |
| `accel_noise_density` | m/s^2/sqrt(Hz) | `0.0` | Accelerometer white noise. |
| `gyro_bias_rw` | rad/s per sqrt(s) | `0.0` | Gyro bias random walk. Q adds rw^2 dt per step. |
| `accel_bias_rw` | m/s^2 per sqrt(s) | `0.0` | Accelerometer bias random walk. Q adds rw^2 dt per step. |
| `gyro_bias_sigma` | rad/s | `0.0` | Accepted, scaled and hashed, but read by nothing: no code draws an initial bias from it. The realised bias starts at zero. |
| `accel_bias_sigma` | m/s^2 | `0.0` | Same as gyro_bias_sigma: accepted but unused. |

### Synthetic motion: `SyntheticConfig`

Every amplitude is a peak-to-trough excursion of a `1 - cos` term.

<!-- table:SyntheticConfig -->
| Key | Unit | Default | Meaning |
|---|---|---|---|
| `duration_s` | s | `30.0` | Length of the generated motion. |
| `rate_hz` | Hz | `100.0` | Sample rate of the reference trajectory. |
| `radius_m` | m | `4.0` | Peak-to-trough excursion of the dominant x oscillation (y uses 0.6 of it at 1.5x the frequency). |
| `circles` | cycles | `1.5` | Cycles of the dominant x oscillation over the run. |
| `sway_amplitude_m` | m | `0.6` | Peak-to-trough sway. |
| `sway_cycles` | cycles | `3.0` | Sway cycles over the run. |
| `yaw_amplitude_deg` | deg | `35.0` | Peak-to-trough yaw. |
| `yaw_cycles` | cycles | `1.0` | Yaw cycles over the run. |
| `roll_amplitude_deg` | deg | `4.0` | Peak-to-trough roll. |
| `roll_cycles` | cycles | `6.0` | Roll cycles over the run. |
| `height_amplitude_m` | m | `0.15` | Peak-to-trough height change. |
| `start_position` | m, world frame | `(1.0, 0.0, 1.6)` | Position at t = 0. |

### Scenario: `Scenario`

<!-- table:Scenario -->
| Key | Unit | Default | Meaning |
|---|---|---|---|
| `name` | text | `required` | Case name. |
| `description` | text | `''` | Free text. |
| `gnss` | see GnssConfig | `factory` | GNSS model. |
| `vision` | see VisionConfig | `factory` | Vision model. |
| `imu_noise` | see ImuNoiseModel | `factory` | Noise the IMU stream is corrupted with. |
| `imu_noise_scale` | ratio | `1.0` | Multiplies every IMU noise term. |
| `imu_outages` | list of Outage | `factory` | Windows with no IMU samples. |
| `gnss_outages` | list of Outage | `factory` | Windows with no GNSS fixes. |
| `vision_outages` | list of Outage | `factory` | Windows with no visual updates. |
| `camera_drop` | see CameraDropConfig | `None` | Bursty frame loss; None means none. |
| `vision_time_offset_s` | s | `0.0` | Added to the visual timestamps. |
| `imu_time_offset_s` | s | `0.0` | Added to the IMU timestamps. |
| `gnss_time_offset_s` | s | `0.0` | Added to the GNSS timestamps. |
| `notes` | text | `''` | Free text. |

### GNSS: `GnssConfig`

<!-- table:GnssConfig -->
| Key | Unit | Default | Meaning |
|---|---|---|---|
| `enabled` | flag | `True` | Produce GNSS fixes at all. |
| `rate_hz` | Hz | `5.0` | Fix rate. |
| `sigma_m` | m | `0.8` | 1-sigma white position noise per axis. |
| `multipath_sigma_m` | m | `0.0` | Stationary 1-sigma of a slow common-mode bias (Gauss-Markov). Zero disables it. A surrogate, not a multipath model. |
| `multipath_tau_s` | s | `30.0` | Correlation time of that bias. |
| `seed` | integer | `0` | Seed of the GNSS noise stream. |

### Vision: `VisionConfig`

<!-- table:VisionConfig -->
| Key | Unit | Default | Meaning |
|---|---|---|---|
| `enabled` | flag | `True` | Produce visual relative-pose updates at all. |
| `rate_hz` | Hz | `20.0` | Update rate. |
| `rot_sigma_deg` | deg | `0.35` | 1-sigma noise on the relative rotation. |
| `trans_sigma_m` | m | `0.05` | 1-sigma noise on the relative translation. |
| `noise_multiplier` | ratio | `1.0` | Scale applied to both visual noise terms. |
| `seed` | integer | `0` | Seed of the vision noise stream. |

### Camera drops: `CameraDropConfig`

<!-- table:CameraDropConfig -->
| Key | Unit | Default | Meaning |
|---|---|---|---|
| `drop_fraction` | fraction | `0.2` | Fraction of frames dropped. |
| `burst_period_s` | s | `2.0` | Period of the drop bursts. |
| `seed` | integer | `0` | Seed of the drop pattern. |

### Outage window: `Outage`

<!-- table:Outage -->
| Key | Unit | Default | Meaning |
|---|---|---|---|
| `start_s` | s | `required` | Start of the window. |
| `duration_s` | s | `required` | Length of the window; it is half-open, [start, start + duration). |

### What `configs/benchmark.yaml` can set

`defaults.synthetic` and `cases.<name>.synthetic` merge into `SyntheticConfig`.
`cases.<name>.scenario` is parsed into `Scenario` (unknown keys are rejected).
`defaults.estimator` and `cases.<name>.estimator` accept only these keys; everything
else in `EskfConfig` (the gate, FDIR policy, initial uncertainty, gravity) keeps its
default in the benchmark:

| Key | Effect |
|---|---|
| `class` | `ErrorStateKalmanFilter` (default) or `DeadReckoning` |
| `vision_fuse` | fuse visual updates; the scenario's `vision.enabled` alone is not enough |
| `vision_keyframe_interval`, `vision_anchor_modelled` | as in `EskfConfig` |
| `anchor_pos_sigma_m`, `anchor_rot_sigma_deg` | as in `EskfConfig` |
| `anchor_pos_drift_sigma_m_s`, `anchor_rot_drift_sigma_deg_s` | as in `EskfConfig` |
| `rpe_delta_s` | spacing of the relative-pose-error metric, s |

The filter's GNSS and vision noise are taken from the scenario's sensor model, so the
filter is told the true noise level; there is no mismatch case in the benchmark.

## Result JSON contract

`navkit run` writes one JSON document (`schema: navkit-benchmark/1`).

<!-- keys:top -->
| Key | Meaning |
|---|---|
| `schema` | Format name and version. |
| `claim_type` | Always `MEASUREMENT` here; see `navkit.analysis.findings`. |
| `data_class` | Always `synthetic`. |
| `disclaimer` | Standing statement that these are not field measurements. |
| `environment` | Python, NumPy and platform of the run. Not part of any comparison. |
| `config_file` | Label of the scenario file used. |
| `config_sha256` | Hash of the scenario file bytes. |
| `cases` | List of per-case records, below. |

Each case record:

<!-- keys:case -->
| Key | Meaning |
|---|---|
| `name`, `description` | Case name and text. |
| `claim_type`, `data_class` | As above. |
| `config_hash` | Hash of the scenario and the estimator configuration. |
| `seed`, `scene_seed` | Noise seed and trajectory seed (`null` when not overridden). |
| `synthetic` | The `SyntheticConfig` used. |
| `scenario` | The `Scenario` used, as a dictionary. |
| `estimator` | The estimator class and its full configuration. |
| `manifest` | What the injection layer applied, measured rather than declared. |
| `outages` | Per-outage error at the start, peak, end and growth. Present when the estimator reports a covariance and the scenario has GNSS outages. |
| `runtime_s` | Wall-clock time of the estimator. Excluded from every comparison. |
| `stats`, `summary` | Counters: fixes used and rejected, FDIR state, final and maximum position sigma, latency. |
| `ate` | Absolute trajectory error under four alignments (`none`, `rigid`, `rigid_start`, `similarity`). |
| `headline` | The numbers the README quotes: ATE (`alignment: none`), rotation error, mean NEES, expected NEES, coverage at 1, 2 and 3 sigma, claimed sigma, verdicts. Covariance fields are absent for dead reckoning. |
| `calibration` | Full calibration report: coverage points with intervals, conformal radius, inflation to reach 95%, verdicts. Absent for dead reckoning. |
| `drift` | Drift as a percentage of path length and of time, with a fitted growth rate. |
| `rpe_1s` | Relative pose error over 1 s windows, translation and rotation. |
| `error_time_series` | Position error and the filter's claimed per-axis sigma against time (`t`, `position_error_m`, `claimed_sigma_p_m`). Present when the estimator reports a covariance. |

The golden snapshot (`tests/golden/benchmark.json`) is the executable form of this
contract for the seeded benchmark.

## As implemented: things a reader should know

These are observations of the code as it stands, recorded so that nobody has to
rediscover them. None is changed here, because changing any of them moves the golden
snapshot.

1. **`gyro_bias_sigma` and `accel_bias_sigma` do nothing.** `ImuNoiseModel` accepts,
   scales, serialises and hashes them; no code reads them. The injected bias is a random
   walk that starts at zero, and the benchmark filter's initial bias covariance is also
   zero, because `initial_bias_sigma` keeps its default of 0.
2. **Two drift keys are named per second and are per square-root second.**
   `anchor_pos_drift_sigma_m_s` and `anchor_rot_drift_sigma_deg_s` enter the process
   noise as `sigma^2 dt`, so a value of 0.01 means a variance that grows by 1e-4 per
   second, and the dimensionally correct unit is m/sqrt(s) and deg/sqrt(s).
3. **`initial_bias_sigma` is one number for two units.** It sets the initial standard
   deviation of the gyro bias (rad/s) and of the accelerometer bias (m/s^2).
4. **No process noise on velocity.** `_process_noise` adds the rate-noise terms to the
   attitude and position blocks only, in a `dt^3/3` form, and the bias random walks as
   `sigma^2 dt`. The velocity block receives none. In Phase 1 the golden snapshot was found insensitive to
   the accelerometer and gyro terms at the 5 ms step, so benchmark results do not depend
   on them; a different IMU or step could.
5. **The filter is told the true sensor noise.** The scenario's GNSS and vision sigmas
   feed both the generator and the filter. Mismatched noise is not exercised by any case.
6. **The reference frame is the filter's frame.** The filter starts at the identity pose
   and the fixture starts there too, so ATE with `alignment: none` is the headline and
   there is no alignment error to absorb.

## FMEA-lite

One row per fault mode the simulator can inject, with what the filter does about it
and where the evidence is. "Benchmarked" means a case in `configs/benchmark.yaml`
exercises it; "unit-tested" means only the code path is tested, not the effect on
accuracy or calibration. This is a map of what is known, not a safety analysis.

| Fault mode | Injected by | Detection and mitigation | Evidence | Status and residual gap |
|---|---|---|---|---|
| GNSS denial | `gnss_outages` | The filter dead-reckons; covariance grows. Re-acquisition after the outage can use bounded adaptive inflation ([ADR-0006](adr/0006-nis-window-monitor.md)). | Benchmark `outage_control` (README table); `navkit sweep outages`; `tests/test_nis_monitor.py` | Benchmarked, and swept over 8 outage windows: stays calibrated (coverage 97.3% to 100.0% in all 40 runs). |
| GNSS denial with visual aiding | `gnss_outages` with `vision_fuse` | Visual relative pose with an anchor modelled as state ([ADR-0001](adr/0001-anchor-as-filter-state.md)). | Benchmark `outage_visual`; `navkit sweep outages` | Benchmarked and swept. Overconfident in all 40 sweep runs (coverage 10.4% to 39.2%), including 5 s outages. More accurate than the control only when the outage starts early. Structural, not a fault: shipped disabled ([ADR-0003](adr/0003-ship-visual-disabled.md)). |
| Camera frame loss | `camera_drop`, `vision_outages` | Missed frames are simply absent; the relative pose then spans a longer baseline. | Benchmark `outage_visual_degraded_camera`; `test_camera_drop_*` in `tests/test_thresholds_and_injection.py` | Benchmarked for one bursty pattern (30% of frames, 1 s bursts). Vision outages are injectable; no test or case covers them. |
| IMU sample loss | `imu_outages` | The previous reading is held over the gap. An outage that removes almost every sample is refused. | `test_imu_outage_*` in `tests/test_thresholds_and_injection.py` | Unit-tested only. Effect on accuracy not measured. |
| Timestamp offset (IMU, GNSS, vision) | `*_time_offset_s` | None: no latency compensation. | `test_inject_applies_a_vision_time_offset` (injection only) | Unit-tested only. Effect on the filter not measured. |
| IMU noise and bias | `imu_noise`, `imu_noise_scale` | Filter carries gyro and accelerometer bias states and a matching process noise. | Every benchmark case uses the default noise at scale 1 | Only scale 1 is run. Bias sigma fields are inert (see above). |
| GNSS multipath, single spike | measurement outlier | Chi-square gate rejects it once, with a stated false-alarm rate ([ADR-0005](adr/0005-chi-square-fdir-gating.md)); recovers on the next good fix. | `test_a_single_multipath_spike_is_rejected_once_and_recovers_immediately` in `tests/test_fdir.py` | Unit-tested only. |
| GNSS slow bias | `gnss.multipath_sigma_m`, `multipath_tau_s` | None specific. A Gauss-Markov surrogate, not a multipath model. | The model is in `sensors/models.py` | No benchmark case sets it. Effect not measured. |
| GNSS spoofing, large sustained offset | measurement offset (unit tests inject it directly) | Gate rejects; after `max_consecutive_rejections` the channel is isolated as faulty ([ADR-0005](adr/0005-chi-square-fdir-gating.md)). Inflation is capped and not available to visual channels. | `test_a_persistent_spoofed_signal_isolates_the_channel` (`tests/test_fdir.py`); `test_a_large_sustained_offset_is_not_followed`, `test_inflation_is_not_available_to_the_visual_channels` (`tests/test_nis_monitor.py`) | Unit-tested only. No spoofing scenario in the benchmark. |
| GNSS spoofing, modest offset after an outage | measurement offset after denial | Escalation to a 60 s lockout exists ([ADR-0007](adr/0007-spoof-permanence-hysteresis.md)) but its trigger does not fire on the measured case; the frozen-anchor cross-check is implemented and unreachable ([ADR-0008](adr/0008-frozen-anchor-cross-check.md)). | `TestPermanenceIsStillUndetected` is `xfail` on purpose (`tests/test_nis_monitor.py`) | **Open.** A modest offset after an outage is admitted by one inflation grant and is not detected. |
| Covariance corruption (loss of symmetry or positive semi-definiteness) | numerical | Joseph-form update ([ADR-0002](adr/0002-joseph-covariance-form.md)); NEES scorer floors small eigenvalues. | `tests/test_estimators.py`, `tests/test_calibration.py` | Property tests (`tests/test_properties.py`) check symmetry, positive semi-definiteness and orthonormality after every update on random inputs; they cannot distinguish the Joseph form from the textbook update. |
