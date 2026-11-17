# Task 4 report
Implemented Site.load_notes, project._repair_steps (stack + preset wiring in load_site), plugin.open_site warning log + summary.
TDD: tests and implementation were written in one pass, so no separate RED run was captured (process slip); first run showed 2 failures that were the old-meaning tests (one-point curve in test_schema, db-runaway curve) which now expect removal + note.
GREEN: core 1347 passed 4 skipped; QGIS files: processing_dock 31, param_form 55, difference_presets 12, session 126, profile_dock 119, time_cutoff 13, gain_strip 44, survey_dock 81, site_scope 162, slices_engine 74, layers 110, grid_velocity_dialog 29, velocity_dialog 84 -- all pass. ruff check/format clean; mypy clean.
Changed tests: test_load_site_reports_an_invalid_stack... -> test_a_one_point_gain_curve_is_removed_with_a_note; db-runaway load assertion in test_schema now expects removal + note.
New: tests/test_project_repair.py; QGIS test in test_plugin_survey_dock.py.
Concerns: constructor-refusal note text is mine (brief gave none): "<where>: <Title> is removed. It could not be built: <exc>. Add it again with the settings you want." No real-DZT test added (repair touches settings only). Core suite ran before a cosmetic line-wrap edit.

## Fix round 1
Changed `_repair_steps` (project.py): (1) all refused and all missing settings are collected before deciding removal, and one removed-step note names them all (refused settings with defaults too), single ending sentence; (2) steps already disabled in the file get "<Title> (already off) had settings reset. ... The step stays off, as it was saved." for any step including Time zero; the pinned enabled-step texts are unchanged; (3) the test-build runs first and exactly one note is appended per step; (4) constructor-refusal test pins the exact note and count.
New tests in tests/test_project_repair.py: every refused setting named, every missing setting named, already-off Time zero, already-off AGC, reset-then-constructor-refusal gives one note.
Results: core suite 1352 passed, 4 skipped; test_plugin_survey_dock.py 81 passed; ruff check/format clean; CI mypy line clean.
