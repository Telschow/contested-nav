# Technology mapping

**Question.** What technical areas does this repository touch, how mature are
those areas, and who works in them publicly?

**Scope note.** Organisations are listed only where a public product or programme
is verifiable from a cited source. **Inclusion is not a claim of relationship,
interest, or hiring intent, and none is implied.** No organisation is scored,
ranked, or assessed.

---

## 1. Technical areas, by maturity

| Area | Maturity | Public evidence of activity |
|---|---|---|
| GNSS positioning and interference | Long-established, commercial | Receiver-level anti-jam/anti-spoof products are mainstream; see [S4](SOURCES.md#s4), [S5](SOURCES.md#s5) |
| Strapdown / dead-reckoning inertial navigation | Textbook | Standard |
| Extended Kalman filtering | Textbook | Standard |
| Error-state and invariant filter formulations | Mature research, two decades of publication | [S10](SOURCES.md#s10)–[S16](SOURCES.md#s16) |
| Visual-inertial odometry | Mature research and shipped software | OpenVINS, VINS-Mono, and derivatives are publicly available; [S15](SOURCES.md#s15) |
| Consistency of visual-inertial filters | **Active research problem, explicitly not closed** | Re-analysis published as recently as 2025; [S16](SOURCES.md#s16) |
| Navigation integrity monitoring (RAIM) | Mature survey literature | [S1](SOURCES.md#s1) |
| Resilient / assured PNT as a product category | Active commercial and policy market | [S5](SOURCES.md#s5), [S17](SOURCES.md#s17), [S18](SOURCES.md#s18) |
| Autonomous driving stacks | Active, with public open-source L2 reference implementations | [S19](SOURCES.md#s19) |
| GNSS-denied autonomous navigation as a research programme | Long-running government programme | [S2](SOURCES.md#s2), [S3](SOURCES.md#s3) |
| Cold-atom inertial measurement | Active research, pre-availability | [S2](SOURCES.md#s2), [S20](SOURCES.md#s20) |
| Signals of opportunity for PNT | Active research, survey stage | [S21](SOURCES.md#s21) |
| Formal safety assurance for autonomous systems | Established discipline, separate field | Not engaged by this repository |

**VERIFIED BY EXTERNAL SOURCE** for the activity column.

**AUTHOR-STATED** for the maturity assessments, which are the author's reading
of that evidence rather than a bibliometric claim.

### Where this repository sits in that picture

**INFERENCE.** The repository sits on the *measurement* side of a mature
research area. It implements one well-known filter formulation, and its
substantive output is an evaluation result plus a refusal to ship a broken
default. It is not on the algorithmic frontier, and it does not claim to be.

---

## 2. Ecosystem by category

Organised by what an organisation publicly does, not by size or preference.
Every entry is anchored to a source.

### Receivers and interference resilience

| Organisation | Public evidence | Relevance to this repository |
|---|---|---|
| **Hexagon** | Completed acquisition of Septentrio, 19 March 2025, to expand "resilient, assured positioning"; target segments include robotics, UAVs, autonomy. [S4](SOURCES.md#s4) | Owns the receiver and correction-service layer this repository's FDIR sits above |
| **Septentrio** (Hexagon) | Designs multi-frequency multi-constellation GNSS receivers with anti-jam/anti-spoof capability; IMO-derived research lineage. [S5](SOURCES.md#s5) | Interference *detection* is receiver-level, not estimator-level; this repository does not duplicate it |
| **Safran** | Markets a resilient-PNT product line positioned against GNSS threats since June 2025. [S9](SOURCES.md#s9) | Commercial resilient-PNT integrator |
| **Xona Space Systems** | LEO PNT satellite operator; publicly announced a receiver-development partnership with Septentrio, October 2025. [S22](SOURCES.md#s22) | Alternative PNT signal source; not implemented here |
| **Satelles** | LEO PNT service; submitted a public response to the NIST PNT request for comment. [S6](SOURCES.md#s6) | Alternative PNT signal source; not implemented here |

### Government and public-sector research

| Organisation | Public evidence | Relevance |
|---|---|---|
| **DARPA** | Adaptable Navigation Systems: PINS and All-Source Positioning and Navigation. Archived as complete. [S2](SOURCES.md#s2) | Direct public precedent for the problem this repository addresses |
| **DARPA** | Subterranean Challenge: autonomous mapping, navigation and search in GPS-degraded environments. [S3](SOURCES.md#s3) | Public benchmark framing for GNSS-denied autonomy |
| **DARPA** | STOIC and Micro-PNT technology areas; non-GPS PNT programme set. [S20](SOURCES.md#s20) | Longer-horizon sensing direction |
| **NIST** | Request for comment on PNT backup and complementary capabilities; public responses on record. [S6](SOURCES.md#s6) | Standards-adjacent policy work |
| **AFWERX / SpaceWERX** | Alternative PNT challenge focused on over-reliance on GNSS. [S7](SOURCES.md#s7) | Challenge-driven innovation framing |
| **Institute of Navigation** | Publishes conference proceedings including resilience, integrity and spoof-detection work; e.g. a 2025 paper on safety assurance of a KF-based GNSS/IMU system. [S23](SOURCES.md#s23) | Where this kind of work is peer-reviewed and presented |

### Academic and open research

| Source | Public evidence | Relevance |
|---|---|---|
| **Hesch, Kottas, Bowman, Roumeliotis (2014)** | Consistency analysis of vision-aided inertial navigation, *IEEE T-RO* 30(1). [S10](SOURCES.md#s10) | **The closest prior work to this repository's central finding** |
| **Huang, Mourikis, Roumeliotis** | Observability-based rules for consistent EKF SLAM estimators. [S11](SOURCES.md#s11) | Origin of the observability-mismatch framing |
| **Li & Mourikis (2013)** | High-precision, consistent EKF-based visual-inertial odometry, *IJRR*. [S12](SOURCES.md#s12) | Consistency-first filter design |
| **Huang (MIT CSAIL)** | STOC-VINS: state-transition and observability-constrained formulations. [S13](SOURCES.md#s13) | Remedy family not implemented here |
| **Chen, Yang, Geneva, Huang (2022)** | FEJ2: a consistent visual-inertial state estimator design. [S14](SOURCES.md#s14) | Remedy family not implemented here |
| **Geneva, Eckenoff, Lee, Yang, Huang (2020)** | OpenVINS: an open research platform for visual-inertial estimation. [S15](SOURCES.md#s15) | The comparison baseline this repository should be using, and does not |
| **Tian, He, Hao (2025)** | Re-analysis of the unobservable subspace in visual-inertial navigation. [S16](SOURCES.md#s16) | Evidence the problem is still open, not settled |

### Autonomous systems and automotive

| Organisation | Public evidence | Relevance |
|---|---|---|
| **Autoware Foundation** | Publishes an open, productionizable, safety-certifiable L2 ADAS software stack. [S19](SOURCES.md#s19) | Where an estimator of this type would be integrated; this repository is not integrated into anything |

### Policy and analysis

| Source | Public evidence | Relevance |
|---|---|---|
| **Critchley-Marrows & Verspieren (2025)**, *Space Policy* | Viewpoint on national approaches to assuring PNT resilience. [S17](SOURCES.md#s17) | Policy framing for the resilience category |
| **Stock, Schwarz, Hofmann, Knopp (2025)**, *IEEE COMST* 27(1) | Survey on opportunistic PNT with LEO communication satellites. [S21](SOURCES.md#s21) | Academic survey of the alternative-PNT landscape |

---

## 3. Claims this document does not make

- That any organisation listed is a customer, partner, employer, or target of
  the author.
- That any organisation has an interest in this repository or in its author.
- That the organisations listed are exhaustive, or that the list reflects
  quality, priority, or preference.
- That the public activity described above is stable, current beyond the access
  dates in [Sources](SOURCES.md), or indicative of any procurement cycle.

**AUTHOR-STATED** — recorded explicitly so that a reader can distinguish a
technical claim from a market observation.

---

## 4. How to extend this document

The correct way to add an organisation is to cite a public page that describes
its product or programme, record the access date, and describe the
technological adjacency to this repository. The incorrect way is to add a name
that is merely plausible. Every entry above meets the first standard; if an entry
ever stopped doing so, it should be deleted rather than kept for reach.
