# Task 2 report (W1 Show slice band checkbox)
Changed: profile_dock.py (QCheckBox import; slice_band_button is QCheckBox("Show slice band"), created before and added right after colormap_combo; no Fit-group change); test_plugin_profile_dock.py (new test: isinstance QCheckBox, text, x left of fit_button and one_to_one_button); docs/guide/getting-started.md wording.
RED: new test failed on c71fa74: isinstance(QToolButton, QCheckBox) False.
Tests: profile_dock 180 passed; profile_view 137 passed; time_cutoff 13 passed; pure 434 passed, 4 skipped. ruff check and format clean.
Commit: a388df3, pushed.
Concerns: test_picking_a_fit_does_not_move_the_buttons_after_it still lists slice_band_button.x(), now trivially stable (left of Fit); left unedited.
