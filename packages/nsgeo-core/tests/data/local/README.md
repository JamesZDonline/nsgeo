# Local survey data (not committed)

Drop real `.DZT` / `.DZG` files here for development and manual testing.

Everything in this directory is gitignored except this README.

Survey data is *also* ignored by extension anywhere in the repository
(`.DZT`, `.DZG`, `.DZX`, and the MALA and Sensors & Software equivalents), so a
file dropped in the wrong place is still caught. Committing a scrubbed fixture
requires `git add -f` — deliberately.

## Why

DZT headers can contain GPS information, and DZG files contain per-trace
coordinates. Committing real survey files to a public repository can permanently
disclose site locations. That is not reversible, and it is not a decision to
make casually.

## What gets committed instead

Fixtures under `packages/nsgeo-core/tests/data/fixtures/` are either:

- **synthetic** — written by the test-only DZT writer, with known headers and
  known sample values, or
- **derived from real files** — truncated to a handful of traces and scrubbed of
  coordinates, only after the header contents have been inspected and the
  provenance is known to be safe to publish.

## Layout: one folder per survey

```
local/
├── FILE__001.DZT … FILE__010.DZT   the ten campus lines (and their .DZX)
├── sunnyside.nsgeo.json            optional saved project for the line-edit tests
├── with-dzg/                       the sixty GPS-recorded lines for M17 (.DZT + .DZG + .DZX); Nashville Grid 1
├── grid2/                          Nashville Grid 2, sixty lines for #159 (links to the raw files)
└── mag-data/                       magnetometer examples for M19 (no tests read them yet)
```

The tests pick a survey by its folder, through the named lists in
`packages/nsgeo-core/tests/real_data.py` (`CAMPUS_LINES`, `GPS_LINES`, `GRID2_LINES`; the
plugin tests' `REAL_DZT` is `CAMPUS_LINES`). Each list reads only its own
folder, never `local/` recursively, because the surveys reuse file names:
`with-dzg/FILE__001.DZT` is a different line from `FILE__001.DZT` (#141).

A new survey goes in a folder of its own, with its own list in `real_data.py`.
Keep the top level for the campus lines: everything with a `.DZT` suffix there
counts as one of them.
