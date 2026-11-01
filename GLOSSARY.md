# Glossary

Terms that tickets, tests and ADRs use for the generated pages. Short on purpose.

- **Marker**: a pair of lines such as `<!-- name:start -->` and `<!-- name:end -->` in a documentation page. The name identifies the page block.
- **Page block**: the text between one pair of markers. A study generates it and the page holds a copy.
- **Results table**: the typed rows of one study, and the CSV that stores them.
- **Committed copy**: the CSV or page block that is checked in. A change to it is a change to a published result.
- **Regenerate and compare**: run the study again and diff the output against the committed copy. A difference is a failure with exit code 1.
- **Ellipsoid coverage**: the share of epochs where the 3-D position error lies inside the claimed 2σ ellipsoid, `e^T P^-1 e <= 4 * dof`. Expected value 99.3% (`src/navkit/eval/calibration.py`). The README, the calibration report and the SRS acceptance criterion AC-04 use it.
- **Per-axis coverage**: the share of single-axis errors inside twice their own claimed sigma. Expected value 95.4% (`src/navkit/eval/candidate_gate.py`). The B1 gate and ADR-0030 use it.
- **"2σ coverage"**: never used bare. Say ellipsoid coverage or per-axis coverage.
