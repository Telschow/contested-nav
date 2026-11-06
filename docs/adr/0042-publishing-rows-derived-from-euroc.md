# ADR-0042: Publishing rows derived from EuRoC

- Status: proposed
- Date: 2026-11
- Related: [ADR-0010](0010-determinism-and-seeding.md), S2 in `CONSTRAINTS.md`, [#278](https://github.com/Telschow/contested-nav/issues/278), [#250](https://github.com/Telschow/contested-nav/issues/250)

## Context

Many files in `docs/data/` hold measurements computed from the EuRoC recordings. The largest is `docs/data/vo_errors.csv`, with one row per frame. The README names the others. Tables and figures in the docs are built from them.

The rights statement on the dataset's [ETH Research Collection record](https://www.research-collection.ethz.ch/handle/20.500.11850/690084) is "In Copyright - Non-Commercial Use Permitted". It links to [rightsstatements.org InC-NC 1.0](http://rightsstatements.org/page/InC-NC/1.0/). Read on 2026-11-06:

- Non-commercial uses need no permission from the rights-holder. Other uses need it.
- The statement says it is not a licence.
- It does not mention derivative works, and it does not name the rights-holder.
- The record states no citation requirement. The ASL page states no licence and points to the record.

The code is MIT. The README already tells readers to use the derived files for non-commercial purposes only. S2 says no third-party data is vendored. The rows are results of running the estimator, not the recordings, but they are computed from the recordings.

This ADR does not give a legal opinion. Whether a derived row is an adaptation of the dataset is not answered by the statement.

## Options

(a) Keep the rows and the current README notice. Cost: none. Risk: the public MIT repository carries rows whose status is unclear, and the notice is a reader warning, not a permission.

(b) Keep the rows, and ask the dataset's authors (ETH ASL, contact on the record) whether publishing derived measurements is permitted. Record the answer here. Until it arrives, (a) applies. Cost: a wait, and the answer may be no reply.

(c) Replace per-frame rows with aggregates. Keep the per-frame code path, so a reader regenerates the rows from fetched data. Cost: pages, tables and tests that read `vo_errors.csv` change, and the rows can no longer be checked byte for byte in CI. Follow-up ticket, not an in-place edit.

(d) Remove the EuRoC-derived files and the pages built from them. Cost: the largest loss of recorded-data evidence. Not proposed.

## Decision

To be written by the maintainer.

## Consequences

To be completed with the decision. Whichever option is chosen:

- The EuRoC notice in the README states the decision, where a reader looks for the licence.
- Committed rows change only through a follow-up ticket.
- Claims on the recorded-data pages stay scoped as they are now.
