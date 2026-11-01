"""The seed ranges of the project, in one place.

Seeds 0 to 99 are development seeds. Seeds 100 to 124 are the held-out set of ADR-0028, spent. From 125 the seeds are
held-out blocks of 25 (ADR-0030), run one at a time through :mod:`navkit.candidate_gate`. Every sweep and study that is
not one of those two procedures calls :func:`require_development` before it runs a case.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable

#: The first seed that is not a development seed.
HELD_OUT_FROM = 100
#: Seeds 0 to 99.
DEVELOPMENT_SEEDS = range(0, HELD_OUT_FROM)
#: The held-out set of ADR-0028, single use and spent.
B1_HELD_OUT_SEEDS = range(HELD_OUT_FROM, 125)
#: Later held-out blocks (ADR-0030) start here.
FIRST_BLOCK_SEED = B1_HELD_OUT_SEEDS.stop

MESSAGE = (
    "seeds from {first} are held-out seeds (ADR-0028, ADR-0030); this command takes development seeds 0 to {last} only"
)


def require_development(seeds: Iterable[int]) -> None:
    """Raise ``ValueError`` if any seed is negative or from the held-out range. Runs no case."""
    for s in seeds:
        if s < 0:
            raise ValueError(f"seed {s} is negative")
        if s >= HELD_OUT_FROM:
            raise ValueError(MESSAGE.format(first=HELD_OUT_FROM, last=HELD_OUT_FROM - 1) + f" (got {s})")


def require_development_or_exit(count: int) -> None:
    """For a command line: seeds ``range(count)`` must be development seeds, else print the reason and exit 2."""
    try:
        require_development(range(count))
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(2) from None
