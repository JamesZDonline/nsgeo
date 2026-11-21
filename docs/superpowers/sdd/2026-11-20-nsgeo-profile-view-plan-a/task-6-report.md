# Task 6 report

Implemented carry_time_window (view_transform.py) and the clock rule in ProfileDock._set_axes_holding (new zero_ns param, _axes_zero set at end of each call and reset in _clear_view_only; _render passes rg.zero_ns, the other two callers use the 0.0 default). Docstring describes the rule between rules 1 and 2.
Rule 1 also now requires zero_ns == _axes_zero, so a zero-only change reaches the new rule instead of being swallowed by the identity rule.

## RED
- pure: stub raising NotImplementedError -> 3 failed (the three carry_time_window tests), 37 passed.
- dock (implementation removed): 4 failed (unruled, ruled, campus, gps survive tests), e.g. obtained (-6.75, 99.78) vs expected (39.35, 49.35); the top test passed on the ruled line pre-fix, so it was changed to an unruled line, where it failed: (0.0, 106.5) vs (0.0, 10.0).
## GREEN
profile_dock 154 passed; time_cutoff 13; profile_cut 19; velocity_fit 78; processing_dock 64; difference_presets 18; real_data 54 passed; pure 421 passed 4 skipped; ruff check and format clean.

## Re-pins
None needed: no older test failed.

Files: ui/view_transform.py, ui/profile_dock.py, tests/pure/test_pure_view_transform.py, tests/qgis/test_plugin_profile_dock.py (adds import of CAMPUS_LINES, GPS_LINES).
Self-review: no concerns; the work was done implementation-first once before tests, then the implementation was reverted to show RED and reapplied.

## Fix round 1
- Added `_axes_from_header` (set True after `_take_down_picture`'s `_set_axes_holding` call, which also covers the `_show_steps_refused` path via :957; False at the end of every other call and in `_clear_view_only`). The clock rule is skipped when the previous axes were header-only, so rule 2 holds the window. Docstring updated. Signatures unchanged.
- R13: `_render` passes `rg.zero_ns`.
- New test `test_a_held_zoom_does_not_move_when_an_unloaded_lines_samples_arrive` (asserts `_shown_radargram is None` and zero 0.0 between open and load). RED before fix: obtained 37.44 vs expected 39.346 (shift 1.906).
- GREEN: profile_dock 155, time_cutoff 13, profile_cut 19, pure 421 (4 skipped), real_data 54 passed; ruff check/format clean.
