# Final fix report

## I1 guide
Added a bullet after the Gain curve bullet in docs/guide/getting-started.md:

"Select a **Time cutoff** step, or a **Time zero** step set to **sample**, and a line on the profile marks it. Drag the line or type the value, and the two always agree. While Time zero is selected the profile shows the record it receives, with the rows it crops dimmed above the line, which reads 0 ns. Switching its **Mode** to **sample** starts the row at the automatic first break, so nothing moves until you drag."

Pure suite (incl. release-docs test) green: 434 passed, 4 skipped.

## M1
Test: test_a_hidden_field_out_of_bounds_does_not_block_a_mode_switch (test_plugin_param_form.py).
RED: `qgis_tests.sh .../test_plugin_param_form.py -q -k hidden_field_out` ->
`assert got and got[-1]["mode"] == "sample"` / `assert ([])`; 1 failed, 62 deselected.
Fix: ParamForm.values() now also falls back (shown value, else default) for a hidden field whose parsed value has param_problem(...) not None. Visible fields still raise. To do this `param_problem` is exported from nsgeo.processing (one line + __all__), since the boundary test forbids importing nsgeo.processing.base from the plugin.
GREEN: same file, 63 passed (both existing cleared-field tests green).

## M3
Docstrings fixed: profile_view.py module docstring, cutoff_dragged comment, profile_dock._handle_row.

## Checks
param_form 63, processing_dock 75, profile_view 137, profile_dock 173 passed; pure 434 passed; ruff check and format clean.
Note: `pytest packages/nsgeo-core -x` shows a collection error under this venv (not investigated; core not in the required list).

## Follow-up: core README
Added the `param_problem` line to packages/nsgeo-core/README.md (public-API test). Whole core suite with PYTHONPATH set to this worktree's core src: 1739 passed, 5 skipped, 19 xfailed. ruff check and format clean. The earlier collection error was the environment (core venv imports nsgeo from the main checkout).
