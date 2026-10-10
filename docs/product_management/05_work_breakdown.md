# Work breakdown and the B4 estimate

What is left on the [roadmap](https://github.com/Telschow/contested-nav/blob/main/ROADMAP.md), split into work
packages with a deliverable, a dependency and an exit test each. It is the item listed as missing under Track C. This
is a solo project, so there are no owners and no teams. Sizes are judgements, not measurements.

## 1. How sizes are read

| Size | Meaning |
|---|---|
| S | One module or one data path, one generated page, tests that check the page against a committed CSV. |
| M | Several of those, or a new data path that has to be validated before anything is built on it. |
| L | A new capability with its own validation, or work that needs a tool outside the dependency rules. |

The sizes compare with work already done in the repository: the separability and slow-ramp studies are each S, the
TUM VI data path was M. No hours are quoted, because none were recorded.

## 2. Work packages

| ID | Package | Deliverable | Depends on | Size | Exit test |
|---|---|---|---|---|---|
| WB-1 | Second source against a slow ramp | Vision-ramp study and page, ADR | The slow-ramp and clone decisions | S | The smallest ramp a simulated visual source exposes, with a detection time, from a committed CSV. |
| WB-2 | Classify faults | A detector that separates multipath, spoofing and sensor degradation, with measured rates | WB-1 | M | Detection above 95% per fault type at zero false alarms on the control (Track A exit test). |
| WB-3 | Real front-end error correlation | A measured error correlation for a real visual front end | A front end that is allowed by the dependency rules | L | The clone is calibrated on that front end, or the opt-in stays. Decides `vision_enabled`. |
| WB-4 | Close B4 | One of the options in section 3 | None | S to L | The skipped tests either run on fetched data or are removed with the claim. |
| WB-5 | Comparison with an established consistent estimator | A reference filter run on the same recorded sequences | A decision on constraint S1 | L | NEES and coverage of both on identical data. Strains S1, so it needs a decision first. |
| WB-6 | Remaining P5-09 and P5-12 | Baseline records and the pull-request clean-up | None | S | Stated in the roadmap item. |
| WB-7 | UrbanNav | A licence answer, then a third dataset | Issue 94 | M | The licence permits the use, or the dataset is dropped. |

WB-1 is done: the [vision-ramp study](../vision_ramp.md) puts the floor at about 2 m/s for independent visual errors. WB-7 is on hold.

## 3. B4: the published TUM VI estimate

B4 is two skipped tests. They compare a published Basalt estimate of room1 with a subsampled ground truth, and neither
file is fetched. The repository cites 0.069 m for room1 at the 512 by 16 setting. The TUM VI paper's table of RMSE ATE
lists 0.09 m for Basalt on room1. The two figures may differ by configuration. Nobody has checked, so the first step of
any option is to find where the file the tests name came from.

| Option | What it takes | Size | Risk |
|---|---|---|---|
| 1. Fetch the published estimate | Find a stable source with a licence that allows use, add a fetch path in the style of `navkit tumvi fetch`, and run the two tests on it. | S, if a source exists | The source may not exist. The licence is unchecked. |
| 2. Run Basalt on the room1 sequence | Build an external C++ tool, run it, and read its output. | L | As an external tool it adds no Python dependency, so S1 holds, but it adds a C++ build the repository does not have. Its licence was seen only in packaging metadata (BSD-3-Clause), so read its LICENSE file before relying on that. The repository does not vendor third-party code or data (S2). |
| 3. Retire the claim | Remove the 0.069 m reproduction claim and the two skipped tests. Check the trajectory reader against the fetched motion-capture ground truth instead. | S | It gives up the check against a published number. |

Recommendation: option 3 now, and option 1 only if a stable source turns up. Option 2 is not worth its size for a
reader check.

Sources for the figures above: the [TUM VI benchmark paper](https://arxiv.org/pdf/1804.06120) for the 0.09 m
figure, and the [packaging metadata of a Basalt fork](https://gitlab.freedesktop.org/monado/utilities/basalt-build-scripts)
for the licence hint. Neither is a reproduction.

## 4. Order

1. WB-1, because it decides what WB-2 can build on.
2. WB-4, option 3, because it is small and removes a skipped-test blocker.
3. WB-2.
4. WB-5 and WB-3 only after a decision on S1 and on the front end.

WB-6 can be done in any gap. WB-7 waits for the licence.
