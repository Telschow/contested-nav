# A structural fix for visual overconfidence

This project does not plan a structural fix (multi-anchor or sliding-window visual fusion) that makes the filter's
claimed uncertainty match its error under GNSS denial with vision on.

## Why this is out of scope

B1 is closed as characterised, not solved ([ADR-0036](../docs/adr/0036-b1-is-closed-as-characterised-not-solved.md)).
The question was asked with a pre-registered gate ([ADR-0028](../docs/adr/0028-the-b1-gate.md)), the candidates were
tried by their pre-registered procedures ([ADR-0030](../docs/adr/0030-the-gate-for-the-next-visual-update-candidate.md)),
and what they show is recorded. Work towards a default-on visual configuration has stopped, and the tools stay in the
repository. A structural fix, and a comparison against an established consistent estimator that exists to choose which
alternative formulation to build, would reopen that work.

Two further limits:

- The formulation is undecided, and the gate may not be reachable with a NumPy-only filter (constraint S1).
- A comparison needs an external reference implementation and a scene export, which strains the zero-dependency rule.

`vision_enabled` stays False. A new candidate is still allowed through the gate of ADR-0030, but that is a new proposal
with its own ADR, not these issues.

## Prior requests

- #44: "P5-03: Fix visual overconfidence structurally (multi-anchor or sliding window)"
- #52: "P5-11: Comparison against an established consistent estimator"
