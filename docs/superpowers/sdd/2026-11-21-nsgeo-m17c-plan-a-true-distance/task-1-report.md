# Task 1 report: gap rule and Gap over

Implemented spacing.py (GAP_FACTOR, usual_step, gap_threshold, gap_steps, left_out), TrackPlacement.gap_m (last field, validated None or finite > 0), project save ("gap_m" only when set) / load (_opt_float(doc.get("gap_m"))). Schema stays 4.

Tests: test_spacing.py (14 incl. parametrized), test_project round-trip, test_spacing_real_files.py (FILE__028 step 841->842 gap; FILE__016 traces 355-362 left out, 354/363 not; lines with a gap pinned).
Measured lines with at least one gap over both surveys (120 lines): **19** (matches §17).

TDD: tests and implementation were written together in one pass; RED was shown after the fact by moving spacing.py aside:
`pytest packages/nsgeo-core/tests/test_spacing.py` -> "ERROR packages/nsgeo-core/tests/test_spacing.py ... 1 error in 0.24s" (ImportError, expected). GREEN: 17 passed (spacing + real), then core+pure full: 2191 passed, 9 skipped, 19 xfailed (263 s). ruff check/format and mypy clean.

Existing tests unchanged. No coordinates or site names committed.
Self-review: fine. Note a median step of 0 (more than half the steps zero) gives inf threshold, no gaps (per brief).

## Fix report (review minors 1-5)
1. Strict `>` pinned: `gap_steps([0, 0.5], gap_m=0.5)` is not a gap, in the threshold test.
2. `filterwarnings("error")` on the no-spacing test.
3. `left_out` now validates `gap_m` first for every n; case added to the validity test.
4. One helper `check_gap_m` in spacing.py, used by `gap_threshold`, `left_out` and `TrackPlacement.__post_init__`.
5. Median wrapped in `np.errstate`.
Tests: spacing + project + real 140 passed; core+pure 2191 passed, 9 skipped, 19 xfailed; ruff and mypy clean.
