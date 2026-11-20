# Task 1 report
Status DONE. Commit: see git log (feat(slices): fill and curvature plans can stop and report progress (#193)).

Changes: slices/stopping.py (new, SolveStopped); curvature.py (re-imports it; plan_curvature, _grow, _stencil take should_stop/progress); interpolate.py (plan_fill, reach_mask, _reach, _neighbourhoods, _kriging_weights, plan chunk loop); multigrid.py build_hierarchy (check once per level); slices/__init__ imports SolveStopped from stopping.
Progress split: plan_fill idw/kriging: reach 0..0.1, neighbour search 0.1..0.6 (reported every 32 offsets), weights 0.6..1.0 per plan chunk, 1.0 at end. min_curvature: reach 0.1, grow 0.15, stencil 0.4, hierarchy+plan 1.0.
Fail first: new tests failed with "TypeError: plan_fill() got an unexpected keyword argument 'should_stop'", "TypeError: reach_mask() got an unexpected keyword argument 'should_stop'", and "ImportError: cannot import name 'stopping' from 'nsgeo.slices'" (10 failed).
Final: core 1678 passed, 5 skipped, 19 xfailed; pure 396 passed, 4 skipped; ruff check/format clean; CI mypy clean.
Deviations: none. test_a_plan_stops_inside_the_neighbour_search is parametrized idw+kriging only (min_curvature's reach stage ends at 0.1 too but the brief's weight-stage split does not apply). No public-API row needed.

## Fix round 1

Finding 1 (stop gap in the search): `interpolate.py` `_reach` and `_neighbourhoods` now ask `should_stop` before EVERY offset; `_neighbourhoods` still reports progress every 32 (`_PRUNE_EVERY`). Tests: `test_the_neighbour_search_asks_before_every_offset` (new: 32 asks between reports), `test_a_reach_mask_stops_at_the_very_next_offset` (new), `test_a_plan_stops_inside_the_neighbour_search` (rewritten, see 3).
Finding 2 (`_coarsen`): `multigrid.py` `_coarsen(level, should_stop, progress)` asks before each of the 25 probes and reports probe share; `build_hierarchy(..., progress=)` reports fractions in [0,1) (level n weighted 0.25^n of the first: done = 1-0.25^n, share 0.75*0.25^n); `curvature.py` `plan_curvature` maps it onto 0.4..1.0 (1.0 still exact at the end). Arithmetic untouched.
Finding 3 (tests): `test_a_plan_stops_inside_the_neighbour_search` flips only at/after the search's second report (0.1+0.5*32/total) and asserts a stop on the very next ask, last progress in [second report, 0.6). New in test_slices_curvature.py: `test_a_plan_stops_mid_stencil` (third term stops, last progress == 0.15), `test_a_plan_stops_mid_coarsening` (stop after first probe, last progress < 0.85), `test_the_hierarchy_progress_never_falls_and_stays_below_one`.

Mutants (scratch worktree under scratchpad/fix-b1/wt, removed after):
- first-check-only (`i == 0 and should_stop()` on all 4 interpolate.py checks): 7 failed (neighbour_search idw+kriging, reach_mask very_next_offset, stops_when_asked idw+kriging, 2 bit-identical).
- every-32 in `_neighbourhoods`: `test_the_neighbour_search_asks_before_every_offset` fails (`{1,32} == {32}` before the dedupe fix; after it, AssertionError); the neighbour_search test alone does not catch this one, the new asks-before-every test does.
- no check in `_stencil`: `test_a_plan_stops_mid_stencil` fails.
- no probe checks in `_coarsen`: `test_a_plan_stops_mid_coarsening` fails.
- all pass at the fix.

Gap between `should_stop` calls, 1000x800, cell 0.05, max 0.375, radius 1.0 (includes start to first call and last call to return):
- before: idw 1.261 s, kriging 1.239 s, min_curvature 0.877 s (load avg 4.8-5.2)
- after: idw 0.043 s, kriging 0.046 s, min_curvature 0.295 s (load avg 3.3-3.6). min_curvature's remaining 0.3 s is the unstoppable `eigh`/one probe pass.

Suites: test_slices_interpolate + test_slices_curvature + multigrid: green; core 1683 passed, 5 skipped, 19 xfailed (490 s); pure 396 passed, 4 skipped; ruff check + format --check clean; CI mypy clean (66 files).
