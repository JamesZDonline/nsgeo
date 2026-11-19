# Task 2 report: TrackPlacement (commit 54073d9)

Status: DONE. Rulings R1 (trace 38, shift 0.24, expect (3.0, 0.04)) and R2 (29.5-31.0 m) applied.

## Implemented
`nsgeo/geometry/track.py`: TrackFix, Bridge, TrackPlacement (frozen, tuple fields; validation in __post_init__ in the Copy's wording), track_from_log, ToXY, END_LIMIT_M, HEADING_BASE_M. Exports added to `nsgeo.geometry` (sorted), README table rows.
- P3 anchors = quality 4 with finite x/y. P4 bridges = consecutive anchors with a non-anchor fix between. P5 ends run on by wheel (1/tpm, else end segment's m/trace) along heading from the end anchor towards the nearest anchor >= 1 m away, else the farthest. P6 shift by arc length with straight extension past both ends, searchsorted so coincident positions never divide by zero. P7 injected to_xy; track_from_log refuses before projecting.

## Tests
test_track.py (24 tests), test_track_real_files.py (3, all RUN, none skipped). Core+pure: 1606 passed, 5 skipped (baseline 1579/5; +27). ruff check/format clean, mypy (core) clean.

## TDD
RED: with a NotImplementedError skeleton (after an initial ModuleNotFoundError), `pytest tests/test_track.py tests/test_track_real_files.py` gave `25 failed, 2 passed` (every behavioural test failed with NotImplementedError; the 2 passes were the constants test and the hashable-compare test, which do not need behaviour). Then implemented. One test I wrote had wrong arithmetic (time-triggered end spacing); fixed the test, not the code.
GREEN: `27 passed`; full core+pure 1606 passed, 5 skipped.
Mutation probes on a scratch copy (deleted afterward; not the worktree): 19 mutants (heading base, farthest fallback, anchor quality/finite, bridge gap, time-trigger spacing, shift in distance/coords, rising check, 1-anchor, one-point, finite shift, end_runs off-by-one, extension past end/start, last-end heading direction, track_from_log one-fixed and NaN filtering), all killed.

## Files
packages/nsgeo-core/src/nsgeo/geometry/track.py (new), geometry/__init__.py, README.md, tests/test_track.py, tests/test_track_real_files.py.

## Privacy
No coordinate, altitude or sentence from real files in any file or this report. Real tests assert lengths, counts, traces and bridge metres; projection is about each file's first RTK fix read at run time. (pytest failure output during RED echoed a real log repr to the terminal only.)

## Concerns
- A quality-4 fix with NaN position is treated as a non-anchor (a bridge marker). Not in the brief.
- The post-format full-suite rerun was not repeated (ruff format only re-wrapped one call); the 42-test targeted rerun incl. test_public_api passed after it.

# Fix round 1 (items 1-3, R6 / R7a / R7b)

## What changed
1. `TrackFix` is `@dataclass(frozen=True, eq=False)` with `__eq__`/`__hash__` over a key tuple that maps every float NaN to one sentinel (None stays distinct). `TrackPlacement`'s generated eq/hash work through its fixes tuple. Tests: `test_no_position_fixes_compare_and_hash_by_value` (float('nan'), math.nan, np.nan, np.float64 NaN; differing alt value unequal; None != NaN; non-fix unequal), `test_two_placements_from_the_same_log_are_equal`.
2. New tests with coincident positions at the end (shift 0.0 and 0.3) and start (shift 0.0 and -0.3), warnings as errors, all finite and exact.
3. New tests where the track turns back (start and end), asserting first-in-track-order heading. Docstring and comment at `_heading` corrected.

## RED
Items 2 and 3 pass on the unchanged code (they pin existing behaviour; their value is in the mutants). Item 1 RED before the fix: `2 failed, 30 passed` (test_no_position_fixes_compare_and_hash_by_value, test_two_placements_from_the_same_log_are_equal).

## Mutants killed (scratch copy outside the worktree, deleted; none committed)
- `safe = length` (no zero-length guard): FAILED end-coincident [0.0], [0.3], start-coincident [-0.3] (3 failed).
- `_tail_dir` literal first/last segment (`k = -1 if last else 0`): FAILED end-coincident [0.3], start-coincident [-0.3], plus 2 older shift tests (4 failed).
- candidates sorted by distance in `_heading`: FAILED both heading-order tests (2 failed).
- `_key` returns value unchanged: 2 failed (the two equality tests). `_key` NaN -> None: 1 failed (None-vs-NaN pin). `__hash__` -> id(self): 3 failed.

## Verification
- `pytest test_track.py test_track_real_files.py test_public_api.py`: 50 passed.
- Full core+pure: 1614 passed, 5 skipped (skip count unchanged).
- ruff check and format --check clean; mypy types command (without gps_import.py, per the pre-Task-4 rule) clean on 56 files.
- Commit pushed to origin nsgeo-m17-gps.
