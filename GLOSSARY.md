# Glossary

Terms that tickets, tests and ADRs use for the generated pages. Short on purpose.

- **Marker**: a pair of lines such as `<!-- name:start -->` and `<!-- name:end -->` in a documentation page. The name identifies the page block.
- **Page block**: the text between one pair of markers. A study generates it and the page holds a copy.
- **Results table**: the typed rows of one study, and the CSV that stores them.
- **Committed copy**: the CSV or page block that is checked in. A change to it is a change to a published result.
- **Regenerate and compare**: run the study again and diff the output against the committed copy. A difference is a failure with exit code 1.
