# Product management and systems engineering

Three documents in `docs/product_management/`, written against the measured
state of this repository rather than an aspiration. Every number in them is
tagged **[M]** measured, **[D]** derived, **[C]** configured, **[E]** estimate
or **[P]** proposed, and the two that are not verifiable today are marked
**NOT VERIFIED** rather than omitted.

| Document | ID | What it settles |
|---|---|---|
| [System Requirements Specification](product_management/01_system_requirements_spec.md) | PM-SRS-001 | The three operational user needs, 32 technical requirements, and a per-requirement verdict. **Only one OUN passes in full.** |
| [SWaP-C and Sensor Selection Trade-off](product_management/02_swapc_tradeoff_matrix.md) | PM-SWAPC-002 | Three platform profiles, IMU grades, cost and power bands, and the rule for when to move off pure ESKF dead reckoning. |
| [FDIR and Adversarial Spoofing Strategy](product_management/03_fdir_and_spoofing_strategy.md) | PM-FDIR-003 | Threat taxonomy, the two-stage defence architecture, and what the operator is actually shown. |

Start with the SRS if you want one number: **AC-03 and AC-04 fail**, so the
filter is not yet trustworthy under GNSS denial, and the cause is a model error
rather than a tuning error.
