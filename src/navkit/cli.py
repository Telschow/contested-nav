"""The ``navkit`` command line.

``navkit run`` runs the reproducible benchmark; ``navkit --version`` prints the
package version. The implementation of each subcommand lives in its own module, so
this file only routes arguments.

    navkit run --markdown
    navkit run --only gnss_only outage_visual --out results/two_cases.json
    python -m navkit run --list
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from . import __version__, benchmark

#: Subcommand name to ``main(argv) -> int``, with a one-line summary for ``--help``.
_COMMANDS: dict[str, tuple[Callable[[list[str] | None], int], str]] = {
    "run": (benchmark.main, "run the seeded benchmark scenarios and write a result JSON"),
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
