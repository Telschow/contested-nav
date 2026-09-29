# Sources

Every external claim in this directory is anchored here. Each entry records what
it was used to support, so a reader can check the claim against the source
rather than trust the summary.

**Access date for all links: 2026-09-29**, unless a publication date is given
separately.

**Source types are distinguished, because they are not equally strong:**

| Type | Weight |
|---|---|
| `PEER-REVIEWED` | Strongest. Peer-reviewed journal or conference paper. |
| `GOVERNMENT` | Official government or agency publication. |
| `VENDOR` | Company press release or product page. Authoritative for what a company claims, not for performance. |
| `PREPRINT` | Not peer-reviewed at time of access. Treated as provisional. |
| `INSTITUTIONAL` | Standards body, professional society, or survey publisher. |

---

<a id="s1"></a>
## S1 — GNSS receiver autonomous integrity monitoring: research status and opportunities

*Review article, Frontiers in Physics, 25 June 2025. DOI `10.3389/fphy.2025.1567301`.*
Type: `PEER-REVIEWED`

Used to support: that receiver integrity monitoring is an established research
area with its own survey literature; and, as reported within that review, that
ship groundings were attributed to excessive positioning deviation in January
2024 and that up to roughly 1,500 flights per day were subjected to GPS
spoofing across the first three quarters of 2024.

https://doi.org/10.3389/fphy.2025.1567301

---

<a id="s2"></a>
## S2 — DARPA Adaptable Navigation Systems (ANS)

*DARPA. Program page. Marked "This program is now complete."*
Type: `GOVERNMENT`

Used to support: that GNSS denial, jamming, and blocked environments are
long-standing publicly funded research problems; that improved inertial
measurement units, signals of opportunity, and plug-and-play sensor
reconfiguration are established programme areas. Notes GPS access is "easily
blocked by methods such as jamming".

https://www.darpa.mil/research/programs/adaptable-navigation-systems

---

<a id="s3"></a>
## S3 — DARPA Subterranean Challenge

*DARPA. SubT program page and challenge final event page.*
Type: `GOVERNMENT`

Used to support: that GNSS-degraded autonomous navigation is an established
public research framing, and that DARPA identifies autonomy, perception,
networking and mobility as the four technical gaps.

https://www.darpa.mil/research/programs/darpa-subterranean-challenge
https://www.darpa.mil/research/challenges/subterranean

---

<a id="s4"></a>
## S4 — Hexagon completes acquisition of Septentrio

*Hexagon press release, 19 March 2025. Announced 7 January 2025.*
Type: `VENDOR`

Used to support: that "resilient, assured positioning" is an active commercial
category, and that robotics, UAVs and autonomy are named target segments.

https://hexagon.com/company/newsroom/press-releases/2025/hexagon-completes-acquisition-of-septentrio-expanding-the-reach-of-mission-critical-navigation-and-autonomy-applications

---

<a id="s5"></a>
## S5 — Septentrio company and product information

*Septentrio. About page, and mosaic-G5 P8 product announcement, 18 May 2026.*
Type: `VENDOR`

Used to support: that receiver-level anti-jamming and anti-spoofing capability is
a commercial product category, distinct from estimator-level fault detection.

https://www.septentrio.com/en/about-us
https://www.septentrio.com/en/company/news/septentrio-unveils-mosaic-g5-p8-ultra-resilient-gnss-module

---

<a id="s6"></a>
## S6 — NIST request for comment on PNT; Satelles response

*National Institute of Standards and Technology. Public comment record, July 2020.*
Type: `GOVERNMENT`

Used to support: that backup and complementary PNT capability is an active
public policy and standards workstream, with industry responses on record.

https://www.nist.gov/document/pnt-rfi-response-satelles-inc

---

<a id="s7"></a>
## S7 — Alternative Positioning, Navigation, and Timing challenge

*AFWERX / SpaceWERX. Challenge overview.*
Type: `GOVERNMENT`

Used to support: that over-reliance on GNSS is treated as a public
challenge-framed problem.

https://afwerxchallenge.com/spacewerx26/altpnt/overview

---

<a id="s8"></a>
## S8 — Physical consequences of GNSS interference, as reported publicly

*Reported figures are cited within S1, drawn from OPSGROUP civil-aviation
spoofing statistics and news reporting on port groundings.*
Type: `INSTITUTIONAL` (secondary — see S1 for the review that compiles them)

Used to support: that GNSS interference has documented operational
consequences, not only theoretical ones.

Note: the underlying statistics are third-party and were not independently
verified here. They are cited only as reported in a peer-reviewed review.

---

<a id="s9"></a>
## S9 — BlackNaute resilient PNT

*Safran. Press release, June 2025. See also the company's resilient-PNT explainer.*
Type: `VENDOR`

Used to support: that resilient PNT is a marketed commercial product category.

https://www.safran-group.com/pressroom/blacknaute-resilient-pnt-revolution-against-threats-global-navigation-satellite-systems-gnss-2025-06-16
https://safran-navigation-timing.com/how-resilient-pnt-works-in-gps-denied-environments

---

<a id="s10"></a>
## S10 — Consistency analysis and improvement of vision-aided inertial navigation

*Hesch, J. A., Kottas, D. G., Bowman, S. L., Roumeliotis, S. I. *IEEE Transactions
on Robotics* 30(1), pp. 158–176, 2014. DOI `10.1177/0278364913509675`.*
Type: `PEER-REVIEWED`

Used to support: **the central claim of this directory** — that inconsistency and
overconfidence in vision-aided inertial navigation is a characterised, published
problem traceable to a mismatch between the observability of the linearised
estimator and that of the true system.

https://doi.org/10.1177/0278364913509675

---

<a id="s11"></a>
## S11 — Observability-based rules for designing consistent EKF SLAM estimators

*Huang, G. P., Mourikis, A. I., Roumeliotis, S. I. *International Journal of
Robotics Research`.*
Type: `PEER-REVIEWED`

Used to support: the origin of the observability-mismatch framing, and that
filter design rules for consistency were published years before this repository.

Cited within [S14](SOURCES.md#s14) and the survey literature.

---

<a id="s12"></a>
## S12 — High-precision, consistent EKF-based visual-inertial odometry

*Li, M., Mourikis, A. I. *International Journal of Robotics Research* 32(6),
pp. 690–711, 2013.*
Type: `PEER-REVIEWED`

Used to support: that consistency-first filter design for visual-inertial
odometry is established prior work.

---

<a id="s13"></a>
## S13 — Towards Consistent Visual-Inertial Navigation (STOC-VINS)

*Huang, G. MIT Computer Science and Artificial Intelligence Laboratory.*
Type: `PREPRINT` (technical report, not peer-reviewed at time of access)

Used to support: that state-transition-constrained and observability-constrained
formulations are an active remedy family.

https://people.csail.mit.edu/ghuang/paper/tr/stocvins.pdf

---

<a id="s14"></a>
## S14 — FEJ2: A consistent visual-inertial state estimator design

*Chen, C., Yang, Y., Geneva, P., Huang, G. IEEE ICRA 2022. NSF Public Access
record.*
Type: `PEER-REVIEWED`

Used to support: that first-estimate-Jacobian methods, and their refinements,
are established; and to source the S11 and S12 citations.

https://par.nsf.gov/servlets/purl/10376064

---

<a id="s15"></a>
## S15 — OpenVINS: a research platform for visual-inertial estimation

*Geneva, K., Eckenhoff, K., Lee, W., Yang, Y., Huang, G. IEEE ICRA 2020,
pp. 4666–4672.*
Type: `PEER-REVIEWED`

Used to support: that an open, established visual-inertial reference
implementation exists and is the natural comparison baseline for this
repository — which does not currently use it.

Cited within [S16](SOURCES.md#s16).

---

<a id="s16"></a>
## S16 — Unobservable Subspace Evolution and Alignment for Consistent Visual-Inertial Navigation

*Tian, C., He, F., Hao, N. arXiv:2511.17992.*
Type: `PREPRINT`

Used to support: that the consistency problem in visual-inertial navigation was
still being actively re-analysed, and is not a closed problem.

https://arxiv.org/abs/2511.17992

---

<a id="s17"></a>
## S17 — Ensuring PNT resilience in a time of navigation uncertainty

*Critchley-Marrows, J. J. R., Verspieren, Q. *Space Policy* 72, 101665, May 2025.
DOI `10.1016/j.spacepol.2024.101665`. Open access, CC BY.*
Type: `PEER-REVIEWED`

Used to support: the policy framing of PNT resilience as a matter of national
concern.

https://doi.org/10.1016/j.spacepol.2024.101665

---

<a id="s18"></a>
## S18 — Resilience of A-PNT systems compared with traditional PNT systems

*Diachenko, A. / Oscilloquartz, ADTRAN. WSTS presentation, May 2024.*
Type: `VENDOR`

Used to support: a vendor-side taxonomy of alternative PNT sources, including
LEO satellite PNT, signals of opportunity, and ground-based systems.

Explicitly **not** used to support any technical or performance claim; vendor
decks are treated as marketing for that purpose.

https://wsts.atis.org/wp-content/uploads/2024/05/07_Resilience-of-APNT-systems-compared-ADiachenko-1.pdf

---

<a id="s19"></a>
## S19 — Autoware vision_pilot

*Autoware Foundation. Open-source repository.*
Type: `INSTITUTIONAL`

Used to support: that a public, productionizable, safety-certifiable L2 ADAS
software stack exists, as a concrete example of where an estimator of this type
would be integrated.

https://github.com/autowarefoundation/vision_pilot

---

<a id="s20"></a>
## S20 — DARPA non-GPS PNT programme overview

*DARPA PNT programmes briefing, presented 2019. DoD Distribution Statement A:
approved for public release; distribution unlimited. Archived by the National
Geospatial-Intelligence Agency.*
Type: `GOVERNMENT`

Used to support: that alternative PNT, ultrastable clocks, cold-atom inertial
sensing, and signals of opportunity are long-running research areas.

Supporting commentary: *Physics Today*, "DARPA looks beyond GPS for
positioning, navigating, and timing", 9 October 2025.
https://physicstoday.aip.org/news/darpa-looks-beyond-gps-for-positioning-navigating-and-timing

https://archive.gps.gov/governance/advisory/meetings/2019-06/burke.pdf

---

<a id="s21"></a>
## S21 — Survey on opportunistic PNT with signals from LEO communication satellites

*Stock, W., Schwarz, R. T., Hofmann, C. A., Knopp, A. *IEEE Communications
Surveys & Tutorials* 27(1), pp. 77–107, February 2025.
DOI `10.1109/COMST.2024.3406990`.*
Type: `PEER-REVIEWED`

Used to support: that opportunistic PNT is an active research area with survey-
level treatment.

https://doi.org/10.1109/COMST.2024.3406990

---

<a id="s22"></a>
## S22 — Septentrio and Xona Space Systems memorandum of understanding

*Septentrio, 7 October 2025.*
Type: `VENDOR`

Used to support: that LEO PNT receiver development is an active commercial
activity, and is an example of an alternative signal source this repository does
not implement.

https://www.septentrio.com/en/company/news/septentrio-and-xona-sign-mou-accelerate-adoption-next-era-navigation-technology

---

<a id="s23"></a>
## S23 — Navigation safety assurance of a KF-based GNSS/IMU system

*Proceedings of the International Technical Meeting of the Satellite Division of
the Institute of Navigation. DOI `10.33012/navi.612`, 2023.*
Type: `INSTITUTIONAL` (peer-reviewed conference proceedings)

Used to support: that navigation *safety assurance* for GNSS/IMU Kalman filters
is an active, published topic — and that this repository does not engage it.

https://doi.org/10.33012/navi.612

---

## Sources deliberately not used

- **Vendor or aggregator company profiles** (for example business-data platforms)
  were not used as sources. They were not needed: every organisation in the
  mapping is anchored to a first-party public page.
- **Secondary news coverage** was not used where a primary or peer-reviewed
  source was available.
- **Any non-public, internal, or classified material** was not used, and none is
  required to read this directory.
