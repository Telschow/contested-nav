"""Outages imposed on the real GNSS fixes of Deep-Urban-1 (issue #245, code slice of #185).

This is one sequence, one receiver. The outages here are cut into that receiver's fixes by this code. They are
imposed and are not the receiver's own: the receiver reports none on Deep-Urban-1 by the rule of
:func:`urbannav_data.outage_intervals`, and that rule is not changed (issue #95). What this measures is the filter's
behaviour through a denial of known position and length on real fixes and a real IMU. It says nothing about how
often or how long a receiver loses its fix in a city.

The positions and lengths are declared in :data:`IMPOSED` before any run on this data. The reasons do not depend on
how the filter does, and the settings are not changed after a run. Starts are in seconds from the first IMU sample.
Lengths are 10, 30 and 60 s, the short, middle and long outage of the synthetic outage study, so that the rows can be
read against it. The starts are one per fifth of an assumed 20 minute run (240, 480 and 720 s), apart enough that the
filter has re-converged on real fixes between two outages. Each outage is run alone, on its own rows.

Everything else is the run of :mod:`urbannav_run`: the same declared settings, the same variants ``declared`` and
``per_fix``, the same gate and the same five seeds. The oracle variants are not run. They replace the start attitude
with the reference's inside an outage, which was a diagnostic of the receiver's own outage on Tunnel-1 and has no
question to answer here.

Results are rows in the format of :func:`urbannav_run.rows_for`, under a sequence name of their own
(``deepurban1_imposed_<start>s_<duration>s``). This module writes no page. With ``--csv`` it merges its rows
into that file under those names; rows of other sequences in the file are not touched.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any

import numpy as np

from . import urbannav_run as ur
from .recorded import EurocSequence, SequenceError
from .types import GnssFix

VARIANTS = ur.VARIANTS
ORACLE_VARIANTS = ur.ORACLE_VARIANTS


@dataclass(frozen=True)
class Outage:
    """One imposed outage: fixes with ``start_s <= t < start_s + duration_s`` are removed."""

    start_s: float
    duration_s: float
    reason: str


IMPOSED: dict[str, tuple[Outage, ...]] = {
    "deepurban1": (
        Outage(240.0, 10.0, "short outage of the synthetic study, one fifth into an assumed 20 minute run"),
        Outage(480.0, 30.0, "middle outage of the synthetic study, two fifths in"),
        Outage(720.0, 60.0, "long outage of the synthetic study, three fifths in"),
    ),
}


def row_sequence(seq_name: str, outage: Outage) -> str:
    """The sequence name of the rows of one outage, apart from the receiver's own rows of ``seq_name``."""
    return f"{seq_name}_imposed_{outage.start_s:g}s_{outage.duration_s:g}s"


def impose(gnss: GnssFix, info: dict[str, Any], spans: list[tuple[float, float]]) -> tuple[GnssFix, dict[str, Any]]:
    """Remove the fixes inside ``spans`` (``start <= t < end``) and the per-fix facts of the same fixes."""
    drop = np.zeros(len(gnss.t), dtype=bool)
    for a, b in spans:
        hit = (gnss.t >= a) & (gnss.t < b)
        if not hit.any():
            raise SequenceError(f"the imposed outage [{a:g}, {b:g}) s removes no fix: it is outside the fixes")
        drop |= hit
    keep = ~drop
    cov = None if gnss.cov is None else gnss.cov[keep]
    out = GnssFix(t=gnss.t[keep], positions=gnss.positions[keep], cov=cov, name=gnss.name)
    out_info = dict(info)
    for key in ("fix_t", "fix_difference_m", "fix_sigma_h_m"):
        out_info[key] = np.asarray(info[key])[keep]
    return out, out_info


def rows_for_outage(
    seq_name: str,
    outage: Outage,
    seq: EurocSequence,
    gnss: GnssFix,
    own_spans: list[tuple[float, float]],
    info: dict[str, Any],
    seeds: tuple[int, ...] = ur.SEEDS,
) -> list[dict[str, Any]]:
    """Run the declared variants through one imposed outage and return rows under the imposed name.

    ``own_spans`` are the receiver's own outages, kept as they are. Times are on the clock of ``gnss``, which starts
    at the first IMU sample on the real data.
    """
    t0 = float(seq.imu.t[0])
    span = (t0 + outage.start_s, t0 + outage.start_s + outage.duration_s)
    cut, cut_info = impose(gnss, info, [span])
    spans = sorted([*own_spans, span])
    results = [ur.run_once(seq, cut, spans, cut_info, seed, v) for v in VARIANTS for seed in seeds]
    return ur.rows_for(row_sequence(seq_name, outage), results)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="navkit urbannav imposed", description="Run the declared imposed outages on an aided UrbanNav sequence."
    )
    p.add_argument("--root", default="data/raw/urbannav")
    p.add_argument("--sequence", "-s", default="deepurban1")
    p.add_argument("--csv", default=None, help="write one row per seed and quantity to this file")
    args = p.parse_args(argv)
    try:
        if args.sequence not in IMPOSED:
            raise SequenceError(f"no imposed outages are declared for {args.sequence}")
        seq, gnss, spans, info = ur.build(args.root, args.sequence)
        if spans:
            raise SequenceError(f"{args.sequence} has an outage of its own: imposed outages are for an aided sequence")
        rows: list[dict[str, Any]] = []
        for outage in IMPOSED[args.sequence]:
            rows += rows_for_outage(args.sequence, outage, seq, gnss, spans, info)
            print(f"{row_sequence(args.sequence, outage)} done", file=sys.stderr)
    except SequenceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.csv:
        try:
            ur.TABLE.merge(args.csv, rows)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {args.csv}", file=sys.stderr)
    else:
        print("\n".join(f"{r['sequence']},{r['variant']},{r['seed']},{r['quantity']},{r['value']}" for r in rows))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
