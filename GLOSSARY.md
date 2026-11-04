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

## Experimental governance

- **Development seed**: A seed from 0 to 99. Studies and tuning runs use these, and only these.
- **Held-out seed**: A seed from 100 up. Seeds 100 to 124 are the spent B1 block. Later blocks start at 125 and run one at a time through the candidate gate. Never used for development.
- **Gate**: A pre-registered pass or fail procedure with fixed seeds and conditions. Passing it does not change a default by itself.
- **Candidate**: A configuration under evaluation by a gate. It stays opt-in until the maintainer changes the default.
- **B1**: The question whether visual fusion can be enabled under GNSS denial without becoming overconfident. Closed as characterised, not solved. The research work is stopped and `vision_enabled` stays False. Do not use B1 for the blocker alone.
- **Stream**: One independent random generator and the draws it produces.
- **Shared seed**: Equal integer seeds given to two sensor streams. Each stream has its own generator, but their standard-normal draws are correlated. Say shared seed, not shared stream.
