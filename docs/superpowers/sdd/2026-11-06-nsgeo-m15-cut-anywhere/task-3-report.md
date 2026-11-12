# Task 3 report: seeing a cut

Status: DONE_WITH_CONCERNS. #97 items deferred per task-3-deferrals.md (no time_base in provenance, no layers.py/line_zero guards, band test in #97-free form).

## Implemented
- session.py: cut keys in open_line/set_preview/set_trace (clamped only below)/set_selection/resolved_velocity; remove_cut and remove_grid clear a working/previewed cut (line_opened("") then preview_changed("", -1)).
- slices_engine.SliceEngine.section_fills (wraps _fill_for on cube.coverage()).
- cut_sections.py: CutSource, CutSection, CutSections (source per call 10, fingerprint cache, redraw on slice_changed/cuts/grids/site_closed, wait cursor, kriging stand-in, provenance JSON without time_base, column_at, dispose).
- render/qimage.rgba_to_qimage; ProfileView.set_message; ProfileDock cut path (_show_cut, _draw_cut, chrome, title, no ruler, guards in cutoff/velocity helpers); loader, processing dock (PROCESSING_ON_CUT_TEXT), survey dock ("Open" on a cut; target_grid_id fallback uses the cut's grid), plugin (builds/disposes CutSections, Velocity disabled with VELOCITY_ON_CUT_TIP).
- Tests: test_plugin_cut_sections.py, test_plugin_profile_cut.py, additions in session_cuts, loader, processing_dock, slices_engine, survey_dock (one existing menu assertion updated for "Open").

## TDD evidence
Session tests, section_fills and CutSections tests were seen failing first (4 failed KeyError; TypeError; missing plugin attribute). The loader and processing-dock tests were written then implemented in one step without a separate RED run (concern).
GREEN: cut_sections + profile_cut 20 passed; survey_dock cut 12 passed.

## Suites
core+pure 1291 passed, 5 skipped; QGIS full 1720 passed (15:45); ruff check and format clean; mypy CI list clean.

## Concerns
- Cuts open from the Survey panel menu only (no click-to-open); Task 4 adds map selection.
- add_pick on a cut key currently reports an error on the message bar (Task 5).
- min_curvature stand-in builds the whole-frame curvature plan via _fill_for (Task 6 solves).
- _refresh_picks draws nothing for a cut until Task 5.

# Fix round 1
1. Waiting cuts: CutSections._waiting ("source"/"cube"); _on_inputs_changed announces once when the source returns or a held cube appears. Tests: test_a_waiting_cut_is_announced_once_its_source_returns, test_a_preview_waiting_for_a_cube_is_announced_when_one_is_held, profile tests (a) other grid shown, (b) shrunk grid, (c) switch away and back; tightened shrunk-edge and engine-goes-away tests.
2. remove_grid: _reset_cuts resets fields, one _announce_dropped for both kinds. Test: parametrized both orders with message_log.
3. source_for logs Critical on exceptions (preconditions guarded so closed-site is silent); cut lookups catch KeyError only (_cut helper). Test: test_a_source_that_cannot_be_read_is_logged_critical.
4. nsgeo.slices.column_distances (exported, README row, core test); section_columns and column_at use it.
5. SliceEngine.cube_generation (bumped by the _cube setter); fingerprint uses it, no cube reference held. Tests: engine generation test, test_a_rebuilt_cube_redraws_the_cut_though_nothing_else_moved.
6. Profile: no transform carry-over when old or new key is a cut. Test: test_a_second_cut_of_equal_length_opens_fitted.
7. section_fills raises RuntimeError without a held cube. Test in test_plugin_slices_engine.
Results: core+pure 1292 passed, 5 skipped; QGIS full 1731 passed (15:45); ruff check/format clean; mypy CI list clean.
