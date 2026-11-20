# Task 2 report (#157 items 1 and 3)

## Inherited diff vs the brief
Checked point by point: the reach formula and docstring, `Taps.lean`/`take`, the exact `sample_counts` path, the
two-slot OrderedDict LRU behind a Lock, `north_up_plans_nbytes`, `clear_north_up_plans`, `lean()` stored by
`_build_north_up_plan`, the "4 bytes a point" comment, `format_status(extra_bytes=)`, `status_text` passing it, and
every test in the brief. All present and correct. Changes I made:
1. `slices/__init__.py`: `north_up_plans_nbytes` moved to its alphabetical place in `__all__` (it sat after
   `surface_volume`).
2. `test_this_grids_status_counts_the_cached_north_up_plans` was a test that dodged the hazard: its 30x30 plan is
   under 1 MB, so the status string was identical with or without `extra_bytes`, and it PASSED with the engine
   change reverted. Rebuilt it: clears the cache, uses a rotated 600x600 frame (plan > 5 MB), asserts the status
   text changes after `to_north_up`, then asserts equality with `format_status(..., extra_bytes=...)`.

## Sweep misses before the fix (reach = ceil(r/sqrt 2) only)
- 8x: 8 of 64 phases (k = 28, 29, 30, 31, 33, 34, 35, 36), each losing all four edge lines (col 0, col 399, row 0, row 399).
- 16x: 20 of 64 phases (k = 22-31, 33-42), each losing all four edge lines.
Matches #157 (8 and 20 of 64).

## Fail-first evidence (production file temporarily reverted to HEAD, then restored)
- site.py reverted: `pytest packages/nsgeo-core/tests/test_slices_site.py -k edge_line` -> 2 failed:
  `AssertionError: assert [(28, 'col', ...w', 399), ...] == []` (8x) and `assert [(22, 'col', ...w', 399), ...] == []` (16x).
- resample.py reverted: `-k lean` -> 2 failed: `AttributeError: 'Taps' object has no attribute 'lean'`.
- display.py reverted: test module `ImportError: cannot import name 'clear_north_up_plans'`.
- display.py with only `taps.lean()` removed from `_build_north_up_plan`: `-k north_up` -> 2 failed,
  `assert 4000 == 0` (ids.size) and `assert (True and 3200000 == 0)`.
- slices_plan.py reverted: pure `-k extra_bytes` -> `TypeError: format_status() got an unexpected keyword argument 'extra_bytes'`.
- slices_engine.py reverted: strengthened QGIS test fails
  `assert '4 lines held in memory, 1 MB ...' != '4 lines held in memory, 1 MB ...'`; passes with the change.

## Final runs
- core: 1666 passed, 5 skipped, 19 xfailed, 2 failed (32 min, machine at load ~18):
  - `test_public_api.py::test_the_readme_names_every_public_name` -- mine: the two new public names were not in
    packages/nsgeo-core/README.md. Fixed (two rows added, `sample_counts` row notes the exact path); now 17 passed.
  - `test_hyperbola_trace_hand_fits.py::test_the_largest_box_traces_within_a_second` -- 1.48 s vs 1.0 s; a timing test in
    an untouched module, also fails alone under this load (1 failed rerun alone). Not from this change.
- pure: 385 passed, 4 skipped.
- QGIS test_plugin_slices_engine.py: 88 passed. QGIS `-m real_data`: 46 passed.
- ruff check and format --check clean.
- Extra file touched: packages/nsgeo-core/README.md (public-API doc test).

## Deviations
None from the brief beyond the strengthened engine test above (the brief's test text would have passed without the fix).

Push pending (GitHub auth down).
