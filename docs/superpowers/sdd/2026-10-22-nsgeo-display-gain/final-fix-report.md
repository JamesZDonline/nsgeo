# Final-fix report: display gain (#6, #10)

All six items done. Each behaviour fix was written test-first.

1. Stale band: `_push_headroom` now calls `gain_strip.set_headroom(None)` when `self.image is None`. The same call sits in `_show_line` (after `self.image = None`) and `_clear_view_only` (which `_clear` and `site_closed` go through). Tests: `test_a_line_without_profiles_does_not_inherit_the_previous_lines_band` and `test_closing_the_site_takes_the_strips_band_away`. RED before the fix (both failed with the old Headroom still present), GREEN after.
2. `test_the_cursor_trace_follows_the_session_cursor` now uses DEEP (replace_step then show_gain_strip(DEEP)) and asserts displayed != reference data. Sabotage: `_push_trace` reading `self.image.reference.data` made it FAIL; restored, it passes.
3. `test_leaving_a_preview_re_pushes_the_band_at_the_current_percentile`. Sabotage: deleting `_push_headroom()` in `_exit_preview` made it FAIL; restored, it passes.
4. `test_raising_only_the_deep_point_leaves_the_shallow_pixels_alone` (real data, REAL_DZT[0]) in test_plugin_profile_dock.py; passes, ran (not skipped). It adds no new red: it pins behaviour already in place.
5. Guide bullet now says "It works on its own, without `gain_agc` before it." (bullet re-wrapped).
6. `row_envelope` returns zeros for a zero-trace array (test `test_row_envelope_of_a_zero_trace_array_is_zeros`, RED confirmed by disabling the guard). Docstring now cites "§3, call 1" and puts call 4 with the difference view.

Verification: qgis tier 809 passed; core + pure 635 passed, 3 skipped (test_schema, by design); ruff check clean; ruff format clean (134 files); mypy no issues (33 files).

Files: docs/guide/getting-started.md, packages/nsgeo-core/src/nsgeo/render.py, packages/nsgeo-core/tests/test_render.py, packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py, packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py, packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py.

Concerns: item 1 was reproduced at dock level (not through the assembled plugin).
