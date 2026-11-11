# Task 5 report
Done. site_note (ElidedLabel, hidden outside Whole site) in slices_dock.py; ElidedLabel.set_hint gained `whole=` so the tooltip (note + export refusal) survives elision. site_scope.py: `problem`, `show_note`, stale comments reworded. plugin.py: both export messages carry "(cell m cell, pixel m pixels)"; site export checks export_refusal before the dialog (Warning, no dialog).
RED: 8 new tests in test_plugin_site_scope.py failed first. GREEN: all pass; 5 QGIS files (site_scope, slices_dock, export_dialogs, site_engine, site_export) pass, 1 skip. ruff clean.
Mutants: plain QLabel (width test fails), no scope hide (clear-on-switch fails), no refusal check (dialog test fails).
Concern: "Not drawn" only shows when nothing is drawn (no lattice); a failure after a good lattice keeps the old drawing with the toast only.
