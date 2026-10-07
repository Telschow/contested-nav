"""Compute the RICE table for the roadmap and keep docs/prioritisation.md in step with it.

RICE score = reach * impact * confidence / effort. The inputs live in
docs/product_management/rice.csv and are judgements, not measurements; the arithmetic and
the sensitivity analysis are computed here so that nobody has to trust a typed number.

    python scripts/rice_table.py            # print the table and the sensitivity result
    python scripts/rice_table.py --write    # rewrite the generated block in the doc
    python scripts/rice_table.py --check    # exit 1 if the doc block is out of date
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "docs" / "product_management" / "rice.csv"
DOC_PATH = ROOT / "docs" / "prioritisation.md"
START, END = "<!-- rice:start -->", "<!-- rice:end -->"

IMPACT_SCALE = (0.25, 0.5, 1.0, 2.0, 3.0)
CONFIDENCE_SCALE = (50, 80, 100)
TOP_N = 3


@dataclass(frozen=True)
class Item:
    id: str
    title: str
    reach: float
    impact: float
    confidence: float
    effort_days: float
    source: str
    depends_on: str
    rationale: str

    @property
    def score(self) -> float:
        return self.reach * self.impact * (self.confidence / 100.0) / self.effort_days


def load(path: Path = CSV_PATH) -> list[Item]:
    items: list[Item] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            items.append(
                Item(
                    id=row["id"],
                    title=row["title"],
                    reach=float(row["reach"]),
                    impact=float(row["impact"]),
                    confidence=float(row["confidence"]),
                    effort_days=float(row["effort_days"]),
                    source=row["source"],
                    depends_on=row["depends_on"],
                    rationale=row["rationale"],
                )
            )
    return items


def ranked(items: list[Item]) -> list[Item]:
    """Highest score first; the cheaper item wins a tie, then the id, so the order is stable."""
    return sorted(items, key=lambda i: (-round(i.score, 9), i.effort_days, i.id))


def _step(scale: tuple[float, ...], value: float, direction: int) -> float | None:
    idx = scale.index(value)
    new = idx + direction
    return scale[new] if 0 <= new < len(scale) else None


def sensitivity(items: list[Item]) -> dict[str, object]:
    """Perturb one input of one item at a time and see whether the top-N set changes.

    Effort is doubled and halved, impact and confidence move one step on their scales. This
    answers "would a plausible estimation error change what we build first".
    """
    base = {i.id for i in ranked(items)[:TOP_N]}
    total = 0
    changed: list[str] = []
    for pos, item in enumerate(items):
        variants: list[tuple[str, Item]] = []
        for factor in (0.5, 2.0):
            variants.append((f"effort x{factor:g}", _replace(item, effort_days=item.effort_days * factor)))
        for direction in (-1, 1):
            for field, scale in (("impact", IMPACT_SCALE), ("confidence", CONFIDENCE_SCALE)):
                new = _step(scale, getattr(item, field), direction)
                if new is not None:
                    variants.append((f"{field} {new:g}", _replace(item, **{field: new})))
        for label, variant in variants:
            total += 1
            trial = [*items[:pos], variant, *items[pos + 1 :]]
            top = {i.id for i in ranked(trial)[:TOP_N]}
            if top != base:
                changed.append(f"{item.id} {label}")
    return {"base": sorted(base), "total": total, "changed": changed}


def _replace(item: Item, **kw: float) -> Item:
    data = {f: getattr(item, f) for f in item.__dataclass_fields__}
    data.update(kw)
    return Item(**data)  # type: ignore[arg-type]


def table_markdown(items: list[Item]) -> str:
    lines = [
        "| Rank | ID | Item | Reach | Impact | Confidence | Effort (days) | Score | Depends on |",
        "|---:|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for rank, i in enumerate(ranked(items), 1):
        lines.append(
            f"| {rank} | {i.id} | {i.title} | {i.reach:g} | {i.impact:g} | {i.confidence:g}% "
            f"| {i.effort_days:g} | {i.score:.2f} | {i.depends_on or 'none'} |"
        )
    return "\n".join(lines)


def rationale_markdown(items: list[Item]) -> str:
    lines = []
    for i in ranked(items):
        lines.append(f"- **{i.id}, {i.title}.** Source: {i.source}. {i.rationale}")
    return "\n".join(lines)


def sensitivity_markdown(items: list[Item]) -> str:
    s = sensitivity(items)
    changed = s["changed"]
    assert isinstance(changed, list)
    out = [
        f"Top {TOP_N} by score: {', '.join(s['base'])}.",  # type: ignore[arg-type]
        "",
        f"I perturbed one input of one item at a time ({s['total']} perturbations: effort doubled "
        f"or halved, impact and confidence moved one step). The top {TOP_N} set changed in "
        f"{len(changed)} of them.",
    ]
    if changed:
        out += ["", "Perturbations that change the set:", ""] + [f"- {c}" for c in changed]
    return "\n".join(out)


def generated_block(items: list[Item]) -> str:
    return (
        f"{START}\n\n{table_markdown(items)}\n\n### Why each item scored as it did\n\n"
        f"{rationale_markdown(items)}\n\n### How stable the ranking is\n\n"
        f"{sensitivity_markdown(items)}\n\n{END}"
    )


def splice(doc: str, block: str) -> str:
    if START not in doc or END not in doc:
        raise ValueError(f"{DOC_PATH} has no {START} ... {END} markers")
    head, rest = doc.split(START, 1)
    _, tail = rest.split(END, 1)
    return head + block + tail


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="rewrite the generated block in the doc")
    mode.add_argument("--check", action="store_true", help="fail if the doc block is out of date")
    args = ap.parse_args(argv)
    items = load()
    block = generated_block(items)
    if args.write:
        DOC_PATH.write_text(splice(DOC_PATH.read_text(encoding="utf-8"), block), encoding="utf-8")
        print(f"wrote {DOC_PATH.relative_to(ROOT)}")
        return 0
    if args.check:
        current = DOC_PATH.read_text(encoding="utf-8")
        if splice(current, block) != current:
            print(f"{DOC_PATH.relative_to(ROOT)} is out of date; run: python scripts/rice_table.py --write")
            return 1
        print("prioritisation table is up to date")
        return 0
    print(table_markdown(items))
    print()
    print(sensitivity_markdown(items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
