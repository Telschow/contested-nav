"""The ``navkit euroc`` command: ``fetch``, ``run``, ``compare`` and ``selftest``.

It lives apart from :mod:`navkit.euroc_eval` and :mod:`navkit.euroc_compare` because it needs both, and
``euroc_compare`` already imports ``euroc_eval``; routing from either one would make them import each other.
"""

from __future__ import annotations

import sys

from .euroc_compare import main as compare_main
from .euroc_eval import run_command, selftest_command
from .io.euroc_fetch import main as fetch_main
from .timing_check import main as timing_main


def main(argv: list[str] | None = None) -> int:
    """Route ``navkit euroc fetch|run|compare|selftest``."""
    args = list(sys.argv[1:] if argv is None else argv)
    commands = {
        "fetch": fetch_main,
        "run": run_command,
        "compare": compare_main,
        "timing": timing_main,
        "selftest": selftest_command,
    }
    if not args or args[0] in ("-h", "--help") or args[0] not in commands:
        usage = "usage: navkit euroc {fetch,run,compare,timing,selftest} [options]"
        kinds = (
            "  fetch     download the IMU and ground-truth files of a sequence (needs network)",
            "  run       run the filter on a fetched sequence, GNSS simulated from its ground truth",
            "  compare   run several filter settings over the fetched sequences and count lost runs",
            "  timing    timestamp regularity and the ground-truth-to-IMU time offset of fetched sequences",
            "  selftest  run the whole pipeline on a synthetic sequence in the EuRoC layout",
        )
        print("\n".join((usage, *kinds)), file=sys.stderr)
        return 0 if args and args[0] in ("-h", "--help") else 2
    return commands[args[0]](args[1:])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
