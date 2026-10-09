"""The ``navkit`` command line.

``navkit run`` runs the reproducible benchmark, ``navkit sweep`` repeats it over
seeds or scenes, ``navkit figures`` renders the committed plots from a result file,
``navkit euroc`` fetches and runs recorded sequences, and ``navkit --version`` prints the
package version. The implementation of each subcommand lives in its own module, so this file
only routes arguments.

    navkit run --markdown
    navkit run --only gnss_only outage_visual --out results/two_cases.json
    navkit sweep seeds --seeds 10 --markdown
    navkit sweep scenes --seeds 8
    navkit sweep outages --markdown
    navkit sweep mismatch --markdown
    navkit sweep faults --markdown
    navkit figures --results results/benchmark.json
    navkit euroc fetch --sequence MH_01_easy
    navkit tumvi fetch --sequence room1
    navkit euroc run --sequence MH_01_easy --outage 60:20 --markdown
    python -m navkit run --list
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from . import (
    __version__,
    benchmark,
    euroc_cli,
    fault_matrix,
    figures,
    mismatch_sweep,
    outage_sweep,
    scene_sweep,
    seed_sweep,
)
from .io import tumvi_fetch

_SWEEPS: dict[str, Callable[[list[str] | None], int]] = {
    "seeds": seed_sweep.main,
    "scenes": scene_sweep.main,
    "outages": outage_sweep.main,
    "mismatch": mismatch_sweep.main,
    "faults": fault_matrix.main,
}


def _sweep(argv: list[str] | None) -> int:
    """Route ``navkit sweep seeds|scenes|outages|mismatch|faults`` to the matching sweep."""
    args = list(argv or [])
    if not args or args[0] in ("-h", "--help") or args[0] not in _SWEEPS:
        names = ", ".join(_SWEEPS)
        usage = f"usage: navkit sweep {{{names}}} [options]"
        kinds = (
            "  seeds    vary sensor noise on one scene",
            "  scenes   vary the trajectory",
            "  outages  vary the GNSS outage start and duration",
            "  mismatch vary how wrong the filter's assumed sensor noise is",
            "  faults   inject each fault mode and compare with a clean control",
        )
        print("\n".join((usage, *kinds)), file=sys.stderr)
        return 0 if args and args[0] in ("-h", "--help") else 2
    return _SWEEPS[args[0]](args[1:])


def _tumvi(argv: list[str] | None) -> int:
    """Route ``navkit tumvi fetch``. Running on TUM VI goes through ``navkit euroc run --dataset tumvi``."""
    args = list(argv or [])
    if not args or args[0] in ("-h", "--help") or args[0] != "fetch":
        usage = "usage: navkit tumvi fetch [options]"
        note = "  fetch  download TUM VI room sequences (CC BY 4.0) and keep the IMU, ground-truth and noise files"
        print("\n".join((usage, note)), file=sys.stderr)
        return 0 if args and args[0] in ("-h", "--help") else 2
    return tumvi_fetch.main(args[1:])


#: Subcommand name to ``main(argv) -> int``, with a one-line summary for ``--help``.
_COMMANDS: dict[str, tuple[Callable[[list[str] | None], int], str]] = {
    "run": (benchmark.main, "run the seeded benchmark scenarios and write a result JSON"),
    "sweep": (
        _sweep,
        "repeat the benchmark over noise seeds, trajectories, outage windows, a wrong noise model or injected faults",
    ),
    "figures": (figures.main, "render the benchmark figures from a result JSON"),
    "tumvi": (_tumvi, "fetch TUM VI room sequences (CC BY 4.0); run them with `navkit euroc run --dataset tumvi`"),
    "euroc": (euroc_cli.main, "fetch EuRoC sequences and run the filter on them (recorded IMU, simulated GNSS)"),
}


def _build_parser() -> argparse.ArgumentParser:
    lines = "\n".join(f"  {name:<8}{summary}" for name, (_, summary) in _COMMANDS.items())
    parser = argparse.ArgumentParser(
        prog="navkit",
        description="Replay, evaluation and uncertainty calibration for GNSS-denied navigation.",
        epilog=f"commands:\n{lines}\n\nRun `navkit <command> --help` for the options of a command.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"navkit {__version__}")
    parser.add_argument("command", nargs="?", choices=sorted(_COMMANDS), help="what to do")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="options passed to the command")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command line and return a process exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()
    ns = parser.parse_args(argv)
    if ns.command is None:
        parser.print_help()
        return 2
    handler, _ = _COMMANDS[ns.command]
    return handler(ns.args)
