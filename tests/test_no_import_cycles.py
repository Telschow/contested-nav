"""The package has no import cycles, lazy imports included.

CodeQL reports a module that begins a cycle (``py/cyclic-import``) even when the import is inside a function, so
the check reads every import statement in the tree, not only the top-level ones.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "navkit"


def _modules() -> dict[str, Path]:
    mods = {}
    for path in SRC.rglob("*.py"):
        name = ".".join(path.relative_to(SRC.parent).with_suffix("").parts)
        mods[name.removesuffix(".__init__")] = path
    return mods


def _graph(mods: dict[str, Path]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    for name, path in mods.items():
        package = name if path.name == "__init__.py" else name.rsplit(".", 1)[0]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            targets: list[str] = []
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                    mod = ".".join([*base, *([node.module] if node.module else [])])
                else:
                    mod = node.module or ""
                if mod.startswith("navkit"):
                    targets += [mod, *(f"{mod}.{a.name}" for a in node.names)]
            elif isinstance(node, ast.Import):
                targets += [a.name for a in node.names if a.name.startswith("navkit")]
            graph[name].update(t for t in targets if t in mods and t != name)
    return graph


def _cycles(graph: dict[str, set[str]], mods: dict[str, Path]) -> list[list[str]]:
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on: set[str] = set()
    found: list[list[str]] = []
    counter = [0]

    def visit(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in graph[v]:
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                found.append(sorted(comp))

    for v in mods:
        if v not in index:
            visit(v)
    return found


def test_there_are_no_import_cycles() -> None:
    mods = _modules()
    assert _cycles(_graph(mods), mods) == []


def test_the_check_would_see_a_cycle() -> None:
    graph = {"a": {"b"}, "b": {"c"}, "c": {"a"}, "d": set()}
    assert _cycles(graph, dict.fromkeys(graph, Path("."))) == [["a", "b", "c"]]
