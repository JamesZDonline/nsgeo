# Task 2 report: Migration at true spacing

## Implemented
- spacing.py: `resample_even`, `sample_back`. Margin is one usual step (R1): a column is zeroed only when its bracketing drawn pair spans more than Gap over AND it is >= one step (1e-9 tolerance) from both. One extra column past the last trace (ceil), extrapolated on the last pair's slope unless that pair straddles a gap, so the last trace round-trips exactly. Left-out traces never feed it; falling/non-monotone distance sorted (stable argsort); repeated distances safe (zero-span pairs take weight 0); ValueError when no usual step or <2 drawn traces.
- base.py: `Radargram.trace_x_m`, `gap_m`, length guard, `from_profile(profile, *, trace_x_m, gap_m)`.
- migration.py: `MigrateFk.apply` resamples only when `trace_x_m` is given, usual step finite > 0 and steps uneven (ptp > 1e-9 * usual); else today's call with `rg.dx_m` (R2).
- session.py: module `source_radargram(line, profile)`; `_attach_source` uses it (a key with no line, i.e. a cut, keeps `from_profile`); `edit_lines` re-attaches and emits `stack_changed` for each applied TrackPlacement edit that has a stack. slices_engine.py: the job calls `session_module.source_radargram(line, profiles[0])`.
- Not touched: session.py:1243 / paraview_export (time-zero probes), per ruling.

## Tests
New: test_spacing (5: gap invents nothing, left-out do not feed, round trip with gap + left-out + repeated distance, falling = reverse, no-step raises), test_steps_migration (5 incl. constant-distance fallback), 2 session, 1 slices engine.
Brief deviation: the even-axis test passes dx_m=0.02 to both records (the trace axis is exactly that even axis).
No existing test changed.

## TDD
RED core: `ImportError: cannot import name 'resample_even'` (test_spacing collection). RED plugin (src reverted): 3 failed (`module 'nsgeo_qgis.session' has no attribute 'source_radargram'`, two session tests). GREEN: core migration 42 passed; QGIS two files 104 passed. Core+pure full: see final line below.

## Lint/types
ruff check + format --check clean; mypy clean.

## Concerns
- `SiteSession.set_travel_shift` (bulk destagger) also changes placements but was out of the ruling, so it does NOT re-attach the source: a source attached before it keeps the old distances until the next attach. Suggest a one-line follow-up (same loop as edit_lines) in a later task.

Core+pure full: 2201 passed, 9 skipped, 19 xfailed.

## Fix round 1
- C1: add_step_dialog probe slices `trace_x_m` too. New test `test_the_add_step_dialog_opens_and_validates_on_a_gps_line` (processing dock tests): fails without the fix (ValueError base.py:53), passes with it.
- I1: end-extrapolation only when the last drawn pair is >= half a usual step apart, else holds the end trace. Tests: near-zero-step in test_spacing and test_steps_migration; both fail with the bound removed (checked, restored).
- I2a: uneven test now a ramp of steps 0.01 -> 0.03 m, apex at trace 180. Assertions: strongest column within one usual step of the apex, peak >= 0.8x the evenly sampled peak, and plain `migrate_fk(dx_m=usual_step)` peak < 0.7x (peak ratio ~0.47 at that apex). The strongest column cannot discriminate (plain keeps each trace's index), so the peak is the assertion.
- I2b: gap tests use off-grid edges (right block starts 2.011). I tried the half-step mutant (`nearest >= 0.5*step`): test_nothing_is_invented_inside_a_gap and the round-trip test both failed; reverted, no mutant in tree.
- I3: re-attach/emit moved after `_set_dirty`/`lines_changed` in edit_lines; destagger test asserts `dirty` is True when the slot runs.
- R7: `_reattach_gps_sources(keys)` helper shared by edit_lines and set_travel_shift (after dirty); new set_travel_shift test (source moves 0.2, one emit, dirty at emit).
- Minors: type-ignores gone (narrowed `x`, direct migrate_fk calls); `_with_gap` docstring fixed.
- Commands: ruff check/format --check clean, mypy clean; QGIS files gps_grids, slices_engine, processing_dock, param_form, session: 400 passed; core+pure 2202 passed, 9 skipped, 19 xfailed.
