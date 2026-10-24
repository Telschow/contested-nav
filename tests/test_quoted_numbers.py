"""The first-read pages carry no unmarked measured number, and every timing says it was measured once.

``README.md``, ``docs/index.md``, ``docs/getting-started.md``, ``docs/results.md`` and ``docs/status.md`` are the pages
a reader opens first. A number there that states a result must be one of:

* inside a generated table that ``scripts/check_doc_tables.py`` verifies (the "Scenario" and "Configuration" tables),
* inside a ``<!-- metric:key -->`` marker, which ``scripts/metrics.py`` checks against ``docs/data/metrics.json``,
* in a paragraph that carries the one-off label (:data:`LABEL`) or ``measured at <sha or date>``, or
* gone.

What counts as a measured result is decided by :func:`measured_numbers`: a number with a decimal point and a unit
(m, s, %, x), any percentage or ratio that is not a threshold, an integer after NEES, ATE, RMSE, ratio or range, and an
integer count of seconds in a sentence about how long something took. Counts of runs, seeds and windows, scenario
parameters (30 s, 5 Hz), versions, and thresholds written as "above 90%" are not results and are not flagged.

Known limits of the rule, kept visible here:

* A paragraph, or one list item, that carries the label exempts every number in it. That is wider than a line, and it
  is the price of Markdown wrapping a sentence over several lines.
* A threshold word (above, below, at least, nominal, expected, ...) directly before a number, or "expected" or
  "nominal" directly after it, exempts it, so a result written as "coverage above 20.5%" would pass. The words are
  listed in :data:`_THRESHOLD`.
* A result written as words ("about three quarters") is not a number and is not checked.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: The pages, as paths, so that ``tests/test_ci_docs_tests.py`` sees that this file reads them and requires it to run
#: in a documentation-only pull request.
PAGE_PATHS = {
    "README.md": ROOT / "README.md",
    "docs/index.md": ROOT / "docs" / "index.md",
    "docs/getting-started.md": ROOT / "docs" / "getting-started.md",
    "docs/results.md": ROOT / "docs" / "results.md",
    "docs/status.md": ROOT / "docs" / "status.md",
}
FIRST_READ_PAGES = tuple(PAGE_PATHS)

#: The one phrase every one-off timing carries, so that it can be found with a grep.
LABEL = "measured once on one machine, not checked by CI"
#: The other accepted label: a figure pinned to the commit or date it was taken at.
MEASURED_AT = re.compile(r"\bmeasured at (?:[0-9a-f]{7,40}|\d{4}-\d{2}-\d{2})\b")

#: Files whose timing statements must carry :data:`LABEL`.
TIMING_FILES = ("README.md", "docs/index.md", "docs/getting-started.md", "CONTRIBUTING.md", "Makefile")

#: Words before a number that make it a threshold or a definition, not a result.
_THRESHOLD = (
    r"(?:above|below|at least|at most|than|exceed\w*|nominal|expected|require\w*|target|threshold|first|bar|floor)"
)
#: The multiplication sign, built from its code point so that the file stays plain ASCII.
_TIMES = chr(0xD7)
#: A threshold word directly before the number ("below 10", "at least 90%"), or directly after it ("99.3% expected").
THRESHOLD_BEFORE = re.compile(rf"\b{_THRESHOLD}\s+(?:(?:of|about|only|a|an|the|is|are|be)\s+)*$")
THRESHOLD_AFTER = re.compile(rf"^\s*(?:%|{_TIMES}|x|m|s)?\s*(?:expected|nominal|required|threshold|target|floor)\b")
#: A statistic word directly before a number ("mean NEES 656", "NEES of 4.2", "ATE ratio 0.14").
STAT_BEFORE = re.compile(r"\b(?:nees|ate|rmse|ratio|range)\s+(?:(?:of|is|was|about)\s+)?$")
TIMING_WORDS = re.compile(r"\b(took|measured|end to end|timed|fresh clone|from scratch)\b", re.IGNORECASE)

FENCE = re.compile(r"^\s*(```|~~~)")
MARKER = re.compile(r"<!--\s*metric:\w+\s*-->.*?<!--\s*/metric\s*-->")
INLINE_CODE = re.compile(r"`[^`\n]*`")
HTML_TAG = re.compile(r"<[^>\n]*>")
LINK_TARGET = re.compile(r"\]\([^)]*\)")
NUMBER = re.compile(
    rf"(?<![\w.\-/#])(\d[\d,]*(?:\.\d+)?)(\s?(?:%|{_TIMES}|x\b|m/s\b|ms\b|m\b|s\b)|\s(?:seconds?|minutes?)\b)?"
)
HEADING = re.compile(r"^\s*#{1,6}\s")
CHECKED_TABLE_HEADERS = ("scenario", "configuration")
#: A table between these lines is generated from a committed CSV, and ``tests/test_start_draw_page.py`` checks every
#: cell against it. Only its table rows are exempt; the sentences around it are scanned like any other.
GENERATED_BLOCK = ("<!-- start-draw:start -->", "<!-- start-draw:end -->")


def _blank_checked_blocks(text: str) -> list[str]:
    """The lines of ``text`` with code fences and the verified tables blanked, so line numbers survive."""
    lines = text.splitlines()
    out = list(lines)
    fenced = False
    generated = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == GENERATED_BLOCK[0]:
            generated = True
        elif line.strip() == GENERATED_BLOCK[1]:
            generated = False
        if generated and line.lstrip().startswith("|"):
            out[i] = ""
        elif FENCE.match(line):
            fenced = not fenced
            out[i] = ""
        elif fenced:
            out[i] = ""
        elif line.lstrip().startswith("|"):
            first_cell = line.strip().strip("|").split("|")[0].strip().lower()
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            if first_cell in CHECKED_TABLE_HEADERS:
                for k in range(i, j):
                    out[k] = ""
            i = j - 1
        i += 1
    return out


def _clean(line: str) -> str:
    if HEADING.match(line):
        return ""  # a section title such as "In 60 seconds" is an idiom, not a measurement
    line = MARKER.sub("", line)
    line = INLINE_CODE.sub("", line)
    line = HTML_TAG.sub("", line)
    return LINK_TARGET.sub("]", line)


LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def _paragraphs(lines: list[str]) -> list[list[int]]:
    """Groups of consecutive non-blank line indices. A list item starts a new group, so a label covers one item."""
    groups: list[list[int]] = []
    current: list[int] = []
    for i, line in enumerate(lines):
        if line.strip():
            if current and LIST_ITEM.match(line):
                groups.append(current)
                current = []
            current.append(i)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _is_result(paragraph: str, match: re.Match[str]) -> bool:
    """Whether ``match`` in the (joined) paragraph states a measured result."""
    number, unit = match.group(1), (match.group(2) or "").strip()
    start = match.start()
    before = re.split(r"[.;:()]\s", paragraph[:start])[-1].lower()
    if THRESHOLD_BEFORE.search(before) or THRESHOLD_AFTER.search(paragraph[match.end() :].lower()):
        return False
    if paragraph[match.end() : match.end() + 1] in ("σ", "°"):
        return False
    decimal = "." in number
    if unit in ("%", _TIMES, "x"):
        return True
    if unit in ("m", "ms", "m/s") and decimal:
        return True
    if unit in ("second", "seconds", "minute", "minutes"):
        return True  # a duration written out is a timing, whatever the sentence says
    if unit == "s":
        return decimal or bool(TIMING_WORDS.search(paragraph[max(0, start - 80) : match.end() + 80]))
    # A figure with no unit directly after a statistic word: "mean NEES 656", "ATE ratio 0.14".
    return bool(STAT_BEFORE.search(before))


def measured_numbers(text: str) -> list[tuple[int, str, str]]:
    """``(line number, number as written, the line)`` for each unmarked measured number in ``text``.

    Each paragraph (or list item) is read as one text, so a sentence that wraps over two lines is not split in
    the middle of "requires 95%".
    """
    blanked = _blank_checked_blocks(text)
    cleaned = [_clean(line) for line in blanked]
    hits = []
    for group in _paragraphs(cleaned):
        pieces = [cleaned[i] for i in group]
        paragraph = " ".join(pieces)
        if LABEL in paragraph or MEASURED_AT.search(paragraph):
            continue
        starts, position = [], 0
        for i, piece in zip(group, pieces, strict=True):
            starts.append((position, i))
            position += len(piece) + 1
        last_end = None
        for match in NUMBER.finditer(paragraph):
            # The second end of a range whose first end is a result: "0.14 to 0.89" after "ATE ratio".
            in_range = last_end is not None and paragraph[last_end : match.start()].strip() == "to"
            if _is_result(paragraph, match) or in_range:
                last_end = match.end()
                line_index = max(i for s, i in starts if s <= match.start())
                hits.append((line_index + 1, match.group(0).strip(), cleaned[line_index].strip()))
            else:
                last_end = None
    return hits


# -- the rule itself ---------------------------------------------------------------------------------------------


def test_the_scanner_flags_an_unmarked_result_and_accepts_the_same_text_marked() -> None:
    assert measured_numbers("The error is 2.5 m after the outage.\n")
    marked = "The error is <!-- metric:tests_collected -->2.5<!-- /metric --> m after the outage.\n"
    assert measured_numbers(marked) == []


@pytest.mark.parametrize(
    "text",
    [
        "Coverage was 35.2% in the worst run.",
        "The ratio was 4.4x between cases.",
        "Mean NEES 656 over ten seeds.",
        "ATE ratio 0.14 to 0.89 against the control.",
        "From a fresh clone this took 321 s end to end.",
        "Install and run the headline case in 19 seconds.",
        "The whole thing regenerates in about 5 minutes.",
        "The sweep varies the path over a 4.65x length range.",
    ],
)
def test_the_scanner_flags_each_kind_of_result(text: str) -> None:
    assert measured_numbers(text + "\n"), text


@pytest.mark.parametrize(
    "text",
    [
        "The bar is a mean NEES below 10 and a coverage above 90% with GNSS denied.",
        "A 30 s run at 5 Hz, seed 0, with the outage from 5 s to 20 s.",
        "Python 3.11 to 3.13 are supported.",
        "Over 10 noise seeds and 40 outage runs the verdicts held.",
        "## In 60 seconds",
        "Coverage against 99.3% expected.",
        "The SRS requires 95% and the bar is a NEES below 10.",
        "See [the run](docs/results-3.77.md) and `0.162 m` in code.",
    ],
)
def test_the_scanner_ignores_parameters_thresholds_versions_and_counts(text: str) -> None:
    assert measured_numbers(text + "\n") == [], text


def test_the_scanner_accepts_the_label_and_a_pinned_measurement() -> None:
    assert measured_numbers(f"It took 18.7 s ({LABEL}).\n") == []
    assert measured_numbers("The error was 2.5 m, measured at 2026-10-18.\n") == []
    assert measured_numbers("The error was 2.5 m, measured at 4038fef.\n") == []


def test_the_scanner_skips_code_fences_and_the_verified_tables() -> None:
    fenced = "```text\nerror 2.5 m coverage 35.2%\n```\n"
    table = "| Configuration | ATE RMSE |\n|---|---:|\n| GNSS denied | 3.768 m |\n"
    scenario = "| Scenario | ATE RMSE (m) |\n| --- | ---: |\n| a | 0.528 |\n"
    other = "| Name | Error |\n|---|---|\n| a | 2.5 m |\n"
    assert measured_numbers(fenced) == []
    assert measured_numbers(table) == []
    assert measured_numbers(scenario) == []
    assert measured_numbers(other), "a table that is not verified must be scanned"


def test_a_label_exempts_its_own_paragraph_and_no_other() -> None:
    text = f"It took 18.7 s.\n{LABEL}.\n\nThe error is 2.5 m.\n"
    hits = measured_numbers(text)
    assert [h[1] for h in hits] == ["2.5 m"]


def test_a_label_exempts_one_list_item_and_not_its_neighbours() -> None:
    text = f"- The error was 2.5 m ({LABEL}).\n- The error was 3.5 m.\n"
    assert [h[1] for h in measured_numbers(text)] == ["3.5 m"]


# -- the pages ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", FIRST_READ_PAGES)
def test_no_unmarked_measured_numbers_in_first_read_pages(name: str) -> None:
    hits = measured_numbers(PAGE_PATHS[name].read_text(encoding="utf-8"))
    shown = "\n".join(f"  {name}:{n}: {num}   {line[:110]}" for n, num, line in hits)
    assert hits == [], (
        "measured numbers with no marker, generated table or one-off label; "
        f"quote them with a metric marker, point to the generated table, or label them:\n{shown}"
    )


# -- timings -----------------------------------------------------------------------------------------------------

_DURATION = re.compile(r"\b\d+(?:\.\d+)?\s?(?:s|seconds|minutes?|min)\b")


def _timing_blocks(text: str) -> list[tuple[int, str]]:
    """``(first line number, block text)`` of each paragraph, or comment block in a Makefile, that states a duration."""
    lines = [re.sub(r"^\s*#\s?", "", line) for line in text.splitlines()]
    blocks = []
    for group in _paragraphs(lines):
        block = " ".join(lines[i] for i in group)
        if (_DURATION.search(block) and TIMING_WORDS.search(block)) or re.search(r"\babout \d+ minutes?\b", block):
            blocks.append((group[0] + 1, block))
    return blocks


@pytest.mark.parametrize("name", TIMING_FILES)
def test_one_off_label_is_uniform(name: str) -> None:
    text = (ROOT / name).read_text(encoding="utf-8")
    blocks = _timing_blocks(text)
    assert blocks, f"{name}: expected at least one timing statement"
    unlabelled = [f"{name}:{n}: {block[:100]}" for n, block in blocks if LABEL not in block]
    assert unlabelled == [], f"timings must say '{LABEL}' (the exact phrase):\n" + "\n".join(unlabelled)


def test_the_generated_block_exempts_its_table_rows_and_nothing_else():
    text = "\n".join(
        [
            "<!-- start-draw:start -->",
            "| Case | Full |",
            "| `x` | 25.44 m |",
            "The median was 25.44 m here.",
            "<!-- start-draw:end -->",
            "| Case | Full |",
            "| `x` | 25.44 m |",
        ]
    )
    lines = _blank_checked_blocks(text)
    assert lines[1] == lines[2] == ""
    assert lines[3] != ""
    assert lines[5] != "" and lines[6] != ""
