# Task 3 — what is deferred, and why (controller ruling, 2026-11-11)

The time-zero branch (#97, `nsgeo-time-zero`) is NOT on main yet. None of its names exist on this branch: `Pick.zero_ns`, `SiteSession.line_zero`, `SiteLayers._follow_key`/`follow_zero`, `nsgeo.processing.timezero.time_base_of`, `ProfileDock.set_cube_zero_lookup`/`shown_zero_ns`, `retime_ns`. So the #97 items in the Task 3 brief move to a later "Task 5b: time-zero hand-off", which runs once #97 merges. Do NOT build them now, and do not stub or anticipate them.

Skip these items of the Task 3 brief:
1. **Provenance.** The `"time_base"` key in `provenance_json`. Build the JSON with every other key; Task 5b adds it.
2. **Step 1.** `test_line_zero_of_a_cut_is_none_and_logs_nothing` (in test_plugin_session_cuts.py).
3. **Step 1.** `test_opening_a_cut_runs_no_time_zero_follow` (in test_plugin_layers.py). Task 3 therefore makes no change to layers.py or test_plugin_layers.py.
4. **Step 9, `test_the_slice_band_shows_on_a_cut`.** Keep the test, but in its #97-free form. `window_changed(12.0, 14.0)` while a cut is shown draws the band at exactly 12.0-14.0 ns. Leave out the "preset sets a time zero / cube-zero lookup / a line is still converted" parts.
5. **Step 9.** `test_a_cut_on_a_time_zero_preset_starts_its_axis_at_the_cubes_t0`.
6. **Step 11.** The bullet about skipping #97's conversions in the dock, and the bullet adding plan call 13's guards in session.py and layers.py.

Everything else in the brief stands.
