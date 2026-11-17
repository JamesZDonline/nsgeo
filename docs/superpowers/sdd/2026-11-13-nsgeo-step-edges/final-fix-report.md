# Final fix wave report

1. Removed-step note lists held settings: `_held` helper in project.py; "It also held ..." for missing/refused removal, "It held ..." for constructor refusal; reset sentences kept in constructor-refusal note. Tests in test_project_repair.py: bandpass nan/600/0.3 exact note, constructor refusal with settings, reset-then-constructor exact note, no-default exact note.
2. Line notes: "Line {name} (grid {grid_id})" when placement has grid_id. Tests updated: test_project_repair.py, test_schema.py, QGIS survey-dock test (now pins "FILE__001.DZT (grid A): ...").
3. Already-off note: "a setting" / "settings" (asserted in the AGC already-off test).
4. Dewow help text reworded (wrapped for E501).
5. running_mean reference caps window at n; cases (8,0), (70,0), (4,1) added.
6. One-sample tests: dewow 0.3 ns and AGC 0.1 ns on FILE__007.
7. trace_stack test parametrized over FILE7 and GRID2.
8. real_radargram skip names path relative to DATA.
9. #125 margins commented in test_steps_migration.py.
10. Docs: guide Step 5 menu + refusal sentence, #40 known issue removed, README trace stacking, spec section 5 wording.

Commands: core suite 1370 passed, 4 skipped; QGIS survey_dock 81, processing_dock 31, param_form 55 passed; ruff check + format clean; mypy (CI line) no issues in 52 files.
Concerns: constructor-refusal note lists original saved values, so a reset setting appears twice (reset sentence and "It held"); per the brief's literal wording.
