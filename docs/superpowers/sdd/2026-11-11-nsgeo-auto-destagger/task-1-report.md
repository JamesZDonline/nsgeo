# Task 1 report: grid value in nsgeo-core

Commit: see `git log -1` on nsgeo-auto-destagger ("feat(core): measure a grid's destagger from its lines (#159)").

## Implemented
- `nsgeo/destagger/` package: `prepare.py` (EnvelopeBins, envelope_bins), `profiles.py` (vectorised steps 3-5, peak, clearness, bootstrap; take bin subsets and an along range for Task 2), `measure.py` (types, reason constants, measure_destagger), `__init__.py`.
- Per axis: no distance, then P2, then P3, then neighbours (rulings applied); AXIS_FAILED only for otherwise-measured lines.
- Vectorisation: moving means by cumsum; the FFT product is summed over bins before one irfft per line (linear); neighbour mean taken in the FFT domain.
- Tests: `tests/destagger_data.py` (lines_for with all parameters, per-path envelope cache, needs_grid1/2), `tests/test_destagger_grid.py` (19 tests), GRID2_LINES, real-files test for Grid 2, README layout, public API, core README.

## TDD
RED: `pytest packages/nsgeo-core/tests/test_destagger_grid.py` -> `ImportError: cannot import name 'DestaggerResult' from 'nsgeo.destagger' (unknown location)`; collection error.
First GREEN attempt: 17 passed, 2 failed: (a) my own test expected lines_used 58 when flipping line 0, but line 2 still has line 3 as a neighbour, so it is 59 (test corrected); (b) the alternating Grid 1/Grid 2 pairing gave a "clear" peak (see concerns), fixed by a strength test.
GREEN: `19 passed in 24.50s` (first run includes reading 120 files, about 10 s per grid; one 60-line measure about 0.4 s).
Full core+pure: 1249 passed, 5 skipped (baseline 1228/5; no new skips). Lint and types clean.

## Measured values (spread_m = half-width of 95% bootstrap, in destagger metres; lines_used 60 each)
| | spike | here | spread_m |
|---|---|---|---|
| Grid 1 unfitted | +0.152 | +0.1617 | 0.0127 |
| Grid 1 fitted | -0.065 | -0.0657 | 0.0078 |
| Grid 2 unfitted | +0.165 | +0.1622 | 0.0188 |
| Grid 2 fitted | -0.059 | -0.0611 | 0.0103 |
Grid 1 unfitted is +0.010 from the spike, inside the 0.02 tolerance but the farthest (common axis starts at the smallest along value, not 0; window end rule differs from the spike's 70 ns).

## Files
packages/nsgeo-core/src/nsgeo/destagger/{__init__,prepare,profiles,measure}.py; tests/{destagger_data,test_destagger_grid}.py; modified README.md (core), tests/real_data.py, test_public_api.py, test_real_files.py, tests/data/local/README.md.

## Concerns
- Time-window end rule (spec section 11): window = bins after 4 ns up to the last bin whose median envelope (over all lines) exceeds 1.25 x the noise floor (median of the last 8 bins); fewer than 8 bins falls back to everything after 4 ns. Gives 5.3-69.4 ns (38 bins) on Grid 1 and 5.3-55.5 ns (30 bins) on Grid 2, both inside the tolerances. Not tuned beyond 1.25; the end differs per grid.
- Added a strength test to "clear" that the brief did not list: peak >= 0.08 correlation per bin (`MIN_CORRELATION`). Reason: alternating real Grid 1 and Grid 2 lines (and Grid 1 with odd lines reversed) produce a faint hump at the same lag as the real grids (peak about 1.1 vs 12.3 and 6.8, i.e. about 0.02 per bin vs 0.14-0.25) with no rival maximum, so the shape test alone calls it clear. Real grids sit well above 0.08, unrelated lines well below. Task 2 may want its own per-line value; `is_clear(curve, n_bins, min_correlation)` takes it as a parameter. Interesting for the author: unrelated lines peaking at the same lag suggests something common to the lines (a travel-dependent effect) feeds the grid value a little.
- Peak-clearance margin: `CLEAR_RATIO = 0.8` (highest other local maximum more than 0.12 m from the peak must be at most 80% of it). The real grids have no rival maximum at all, so the margin is not exercised by the data; it is untuned. 
- `test_unrelated_lines_have_no_clear_match` uses the alternating Grid 1 / Grid 2 pairing, which does reach UNCLEAR with the strength test (docstring says so).

## Fix round 1
Correction: concern 4 gave the wrong cause for the Grid 1 unfitted gap. It came from the grid length (30.0 vs the saved survey's 29.98), not the axis start or window rule.
Changes:
- `tests/destagger_data.py`: GRID1_LENGTH = 29.98. Grid 1 now: unfitted +0.1517 (spike +0.152), fitted -0.0657, spread 0.0127 / 0.0078. Grid 2 unchanged.
- `should_stop`: `lag_curves` takes a `check` callable called once per line; `measure_destagger` passes it. The no-distance, time-settings and neighbour loops now check per line too (the too-short and profile loops already did).
- Test `test_should_stop_is_honoured_in_every_per_line_stage[0..5]`: stops at call 30+60*stage, i.e. in each of the six per-line loops (360 calls for 60 lines), asserts MeasureStopped and that the call count equals the stop point. Before the time-settings check was added, stage 5 did not raise (the test caught the missing check).
- Removed `test_the_result_types_are_importable` and its two imports; removed the unused fixture argument; `failed(...)` returned plainly.
Verification: `test_destagger_grid.py` 23 passed; full core+pure `1253 passed, 5 skipped`; ruff check/format clean; mypy "no issues found in 48 source files".
