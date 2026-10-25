"""Write, read, merge and compare a study's results CSV (ADR-0038).

A study declares its columns once. Values are written with plain ``str()``, a missing value as an empty cell,
and read back as the declared type.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

Row = dict[str, Any]


@dataclass(frozen=True)
class Column:
    name: str
    kind: type = str
    optional: bool = False

    def parse(self, cell: str) -> Any:
        if cell == "":
            if self.optional:
                return None
            if self.kind is str:
                return ""
            raise ValueError(f"column {self.name}: an empty cell in a required {self.kind.__name__} column")
        return self.kind(cell)

    def format(self, value: Any) -> str:
        if value is None:
            if not self.optional:
                raise ValueError(f"column {self.name}: a missing value in a required column")
            return ""
        return str(value)


@dataclass(frozen=True)
class Table:
    columns: tuple[Column, ...]
    key: str

    @property
    def header(self) -> list[str]:
        return [c.name for c in self.columns]

    def write(self, path: str | Path, rows: list[Row]) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        cells = [[c.format(r.get(c.name)) for c in self.columns] for r in rows]
        with target.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(self.header)
            writer.writerows(cells)

    def read(self, path: str | Path) -> list[Row]:
        target = Path(path)
        with target.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if list(reader.fieldnames or []) != self.header:
                raise ValueError(f"{target}: the header is {list(reader.fieldnames or [])}, expected {self.header}")
            return [{c.name: c.parse(r[c.name]) for c in self.columns} for r in reader]

    def merge(self, path: str | Path, rows: list[Row]) -> None:
        """Write ``rows`` to ``path``, replacing the rows of those keys and keeping the rows of any other.

        A replaced key keeps its place in the file. A new key goes at the end. A file with another header is
        refused with a ``ValueError`` and is not touched.
        """
        target = Path(path)
        existing = self.read(target) if target.exists() and target.stat().st_size > 0 else []
        groups: dict[Any, list[Row]] = {}
        for r in existing:
            groups.setdefault(r[self.key], []).append(r)
        fresh: dict[Any, list[Row]] = {}
        for r in rows:
            fresh.setdefault(r[self.key], []).append(r)
        groups.update(fresh)
        self.write(target, [r for group in groups.values() for r in group])

    def is_current(self, path: str | Path, rows: list[Row]) -> bool:
        """True if the file at ``path`` holds exactly ``rows`` once written."""
        target = Path(path)
        expected = [[c.format(r.get(c.name)) for c in self.columns] for r in rows]
        with target.open(newline="", encoding="utf-8") as fh:
            found = list(csv.reader(fh))
        return found == [self.header, *expected]
