# Scope and responsible use

`contested-nav` is a research and evaluation library in a publicly studied field. It measures
whether a navigation filter is right about how wrong it is. It is not a navigation product,
it is not field-validated, it is not novel, and it is not qualified for any platform.

## What it contains

- A 21-state error-state Kalman filter, an inertial dead-reckoning baseline, and a
  chi-square fault detection layer.
- A synthetic known-answer fixture: an analytic trajectory with generated sensor streams.
- Calibration and accuracy metrics, sweeps over noise, trajectory and outage timing, and the
  figures and tables built from them.

## What it does not contain

- No real sensor data, drivers or capture tooling, and no live front end.
- No radio-frequency model. A GNSS outage is a gap in a stream, and the spoofing tests in the
  suite are measurement offsets injected into the filter. There is no code that generates,
  transmits or simulates a signal.
- No guidance, targeting, weapons or platform-integration code.

## Responsible use

Everything here is built from public sources and synthetic data, and the documents under
`docs/defense/` cite them. To the maintainer's knowledge nothing in the repository is classified
or restricted, but that is not a legal determination; if you intend to use any of it in a
regulated or operational setting, check your own obligations first.

The failure this project documents, that a filter can become more accurate while becoming far
more overconfident, is a reason to be careful with visual aiding under GNSS denial. It is not a
recipe for exploiting a navigation system. The [dual-use analysis](defense/DUAL_USE_ANALYSIS.md)
and the [limitations](defense/LIMITATIONS.md) say more, and a vulnerability in the code itself
goes through the process in the [security policy](security.md).

## Where it sits

The most important line of the [defense assessment](defense/README.md): the failure documented
here is a known failure mode with established remedies, and this repository implements none of
them. What it adds is a harness that measures the failure and refuses to ship the broken
configuration.
