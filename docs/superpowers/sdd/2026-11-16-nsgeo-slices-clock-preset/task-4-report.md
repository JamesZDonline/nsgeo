# Task 4 report

Commit: ce5ec49 fix(processing): a time field behind Time zero has no clock until the samples load

## Implemented
- ProcessingDock.input_axis returns None when stack.source is None and an enabled time_zero is above the row; _show_form then passes no time_range/time_step. time_axis returns (0.0, header.dt_ns, header.n_samples) in that case.
- ProcessingDock._on_line_loaded (guarded slot, connected to session.line_loaded): for the shown line, resets self._shown and re-runs _show_form for the current row. plugin.py comment updated.
- SliceEngine.prepared_steps property; grid_time_bases(session, source, site_engine) now requires site_engine, uses prepared_steps; SiteScope.warnings docstring says queued/preparing grids count from presets. grid_time_bases had one production caller (SiteScope.warnings), already passing the engine.

## TDD evidence
- RED: test_a_time_field_behind_time_zero_is_unbounded_until_the_samples_load failed (spin maximum equalled header radar-clock end, 512*dt); test_a_cutoff_added_behind_time_zero_before_the_samples_load_crops_nothing failed (461 != 507 samples: seed was at the radar-clock end, so it cropped). Both then GREEN.
- test_a_saved_curve_is_drawn_on_the_shown_clock: guard (docstring says so), passes before change. Mutation (retime_ns call replaced by its first argument, PYTHONDONTWRITEBYTECODE=1) FAILS: "Obtained: 22.3606797749979, Expected: 21.3606797749979 +- 1e-9". File restored; git status shows profile_dock.py clean.
- test_grid_time_bases_reads_each_grids_preset rewritten to pass dock.site_engine (passes).
- test_a_grid_with_no_lines_has_no_clock is also a gap-filling guard (passes on the existing code once the engine is given the source). It needs `site_engine.set_source(source)` so Z's state is "no lines"; without that state_text returns "waiting" for a grid the engine never heard of, and the grid is counted from its preset.

## Results
- test_plugin_processing_dock.py + test_plugin_velocity_fit.py: 111 passed
- test_plugin_param_form.py + test_plugin_time_cutoff.py: 68 passed
- test_plugin_site_scope.py: 174 passed
- test_plugin_slices_dock.py: 243 passed
- pure tier (incl. test_no_orphan_signals, test_plugin_boundary): 308 passed, 1 skipped; pure+core: 1685 passed, 5 skipped
- ruff check and format --check clean (ruff format reformatted one test file before commit).

## Files
packages/nsgeo-qgis/nsgeo_qgis/{plugin.py, slices_engine.py, ui/processing_dock.py, ui/site_scope.py}; tests test_plugin_processing_dock.py, test_plugin_velocity_fit.py, test_plugin_site_scope.py.

## Concerns
- QGuiApplication::font() "no instance" lines print at teardown of the processing-dock/velocity run; not new from this change (appear at interpreter exit).
- _on_line_loaded re-shows the form for any row (not only time fields); cheap, and uncommitted edits in a form on that row are discarded when its line loads, which only happens at load.

## Fix round 1
- Changed: ProcessingDock keeps `_form_axis_unknown` ((key, row) or None), set in `_show_form` only when a time-field form is built with `input_axis` None and cleared on every other build or clear. `_on_line_loaded` re-shows only when it equals (key, current row); guard kept.
- New test test_a_line_loading_again_leaves_a_bounded_form_alone: RED on ce5ec49 (the end_ns editor was rebuilt: new TimeSpinBox object); GREEN after. The two earlier processing tests stay green (open-then-bounded still re-shows).
- Commands: pytest test_plugin_processing_dock.py test_plugin_param_form.py test_plugin_time_cutoff.py with .venv-qgis: 102 passed; pure tier: 308 passed, 1 skipped; ruff check and format --check clean.

## Fix round 2 (docs only)
plugin.py initGui comment rewritten to read as an argument; _resync_gain_strip docstring now says ProcessingDock reacts to line_loaded only to re-show a form built before the samples loaded.
Commands: ruff check + format --check on plugin.py, pure tier.
All checks passed!
1 file already formatted
308 passed, 1 skipped in 15.18s
