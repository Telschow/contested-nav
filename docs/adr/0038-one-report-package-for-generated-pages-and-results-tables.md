# ADR-0038: One report package for generated pages and results tables

- Status: accepted
- Date: 2026-10
- Related: [ADR-0010](0010-determinism-and-seeding.md), [ADR-0035](0035-the-integrity-status-record.md)

## Context

Each study under `src/navkit` writes a CSV, builds a block of Markdown from it, and splices the block into a documentation page between a pair of marker lines. Each study also has its own command. Nothing shared exists for any of the three steps, so each study carries its own copy.

At commit 3fbef21 (grep, not retyped into a page):

- **Page splice.** Twenty modules define a function that puts a block between markers. Nine of the ten file-writing copies are the same code; `timing_check` swaps the argument order. Six of the ten text-returning copies check that both markers are present and in order and share one error message; two delegate to a private strict helper; `fault_matrix` and `mismatch_sweep` check presence only.
- **Results tables.** Fifteen modules define `write_csv` or `read_csv`. All write with plain `str()` except `integrity.py`, which uses fixed formats by design (ADR-0035). Only four read. Two of those return typed rows and two return every value as a string. `vo_error.read_clone_csv` only calls `read_csv`. `urbannav_data.write_merged_csv` merges rows by sequence for three studies.
- **Commands.** `cli.py` routes thirteen sweeps to each module's `main`. The flags `--csv`, `--page`, `--markdown`, `--seeds`, `--from-csv` and `--compare` are declared again in each module. Compare is done three ways: through a temporary CSV, by parsing text, and by comparing rows in memory.

The cost is locality. A change to the marker rule or to how a value round-trips through a CSV has to be made in many places, and the copies have already drifted (the presence-only check, the argument order, the string-only readers). The per-page tests re-test the same splice behaviour for each page.

## Options

(a) Leave the copies. Rejected in the candidate review: the drift is the evidence that the copies do not stay equal.

(b) One package, `navkit.report`, with three modules, in this order: a page-splice module, a results-table module, then a study-runner module that uses both. Each is migrated by expand-contract: the new module is added beside the old code, studies move over in small batches, and the old copies are deleted last.

(c) One module for all three. Rejected in the candidate review: the study-runner depends on the other two, and a single module would make the first migration batch as large as the last.

## Decision

One package, `navkit.report`, with three modules, in this order: a page-splice module, a results-table module, then a study-runner module that uses both. Each is migrated by expand-contract: the new module is added beside the old code, studies move over in small batches, and the old copies are deleted last.

## Consequences

To be confirmed with the decision. The intended consequences, if (b) is chosen:

- Every committed page block and CSV stays byte-identical in every batch. A batch that needs a golden to change stops and goes to the maintainer.
- The command names and flags of every `navkit sweep` entry stay as they are.
- The one behaviour change is the error raised for reversed markers in the two presence-only copies.
- `integrity.py` stays outside the results-table module.
- The sweeps that write only JSON (`seeds`, `scenes`, `outages`) keep their own commands.
- The per-page tests keep running until the contract step, so a migration batch is checked against the old behaviour.
