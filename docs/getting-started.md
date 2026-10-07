# Getting started

## Quickstart

```bash
git clone https://github.com/Telschow/contested-nav.git
cd contested-nav
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/navkit run --only gnss_only outage_control outage_visual --markdown
```

The last command prints the three rows that carry the headline result:

```text
| Scenario | ATE RMSE (m) | Claimed 1-sigma (m) | Mean NEES (exp. 3) | Coverage at 2 sigma | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| gnss_only | 0.509 | 0.252 | 4.0 | 100.0% | mixed(bulk=overconfident, tail=underconfident) |
| outage_control | 3.782 | 0.567 | 4.1 | 100.0% | mixed(bulk=overconfident, tail=underconfident) |
| outage_visual | 2.541 | 0.161 | 419.4 | 20.0% | overconfident |
```

**Timed from a fresh clone** on the machine that wrote this page (Python 3.13, a fast
connection): clone 1.2 s, virtual environment 2.7 s, `pip install -e .` 9.6 s, the three-case
run 5.2 s, **18.7 s in total**. Your numbers will differ with your network and CPU; the
printed results will not (see [determinism](adr/0010-determinism-and-seeding.md)).

Runtime dependencies are NumPy, Matplotlib and PyYAML. There is no SciPy, no GTSAM, no factor
graph library and no compiled extension: the incomplete gamma function, the chi-square
quantiles, the covariance propagation and the metric definitions are implemented in this
repository from the published definitions.

## The command line

`pip install -e .` installs a `navkit` command. It works from any directory, because the
default scenario file ships inside the package; output paths such as `results/` and
`docs/figures/` are relative to where you run it.

| Command | What it does |
|---|---|
| `navkit run [--only CASE ...] [--markdown] [--out PATH]` | Run the seeded benchmark scenarios and write a result JSON |
| `navkit sweep seeds --seeds N` | Repeat the benchmark over N noise seeds |
| `navkit sweep scenes --seeds N` | Repeat it over N synthetic trajectories |
| `navkit sweep outages [--starts ...] [--durations ...]` | Sweep the GNSS outage start and length, with a CSV and a figure |
| `navkit sweep mismatch [--scales ...] [--channel ...]` | Tell the filter the wrong sensor noise, with a CSV, a figure and a table |
| `navkit sweep faults [--faults ...] [--list]` | Inject each fault mode and compare with a clean control, with a CSV and a table |
| `navkit figures [--animate]` | Render the committed figures (and the hero GIF) from a result JSON |
| `navkit --version` | Print the package version |

The scripts under `scripts/` are thin wrappers around the same code, so a source checkout
works without installing.

## Reproduce every number

```bash
pip install -e ".[dev]"
make repro
```

`make repro` runs the benchmark, the three sweeps and the figures, then checks that every
table in the documentation still matches the result. It took **321 s** end to end, in a clean
worktree, on the machine that wrote this page. `make help` lists the other targets
(`check` runs the three local gates; `docker` builds the container image).

The benchmark is bit-reproducible: two runs give byte-identical output once wall-clock timings
are stripped, and CI enforces that for the benchmark and the sweeps.

## Development

| Task | Command |
|---|---|
| Editable install with the pinned dev tools | `make install` |
| Lint, tests and the coverage ratchet | `make check` |
| Install the pre-commit hooks | `make hooks` |
| Scan for credentials | `make secrets` |

The full contributor guide, including the branch-protection settings, is
[CONTRIBUTING](contributing.md).
