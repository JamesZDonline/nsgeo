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

## Suggested layout

```
local/
├── single-channel/
├── multi-channel/
└── with-dzg/
```
