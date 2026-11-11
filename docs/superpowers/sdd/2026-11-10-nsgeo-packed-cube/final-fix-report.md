# Final fix report (#113)

F1: slices_dock.py `prepare()` now calls `_update_resident_check_label()` right after `engine.set_source(choice)`; `_included_estimate` docstring corrected. Test `test_the_checkbox_does_not_show_the_old_line_sets_figure_while_re_preparing` (prepare, set_included with one fewer line, engine held unprepared; asserts last cube-bytes figure shown equals the packed figure of the new set, and differs from the old). Confirmed it fails with the new call removed.
F2: docstrings reworded in slices_plan.py (MemoryEstimate, format_status), slices/cube.py (slice_levels, one-ulp clause), render.py, slices/display.py, tests/test_real_files.py (cube.mean removed); upper-bound comment in test_pure_slices_plan.py.
F3: `test_a_line_whose_position_cannot_be_computed_is_left_out_of_the_count` (Line is frozen, so the test patches the class method and raises ValueError only for one instance; spy checks n_covered equals covered_cells of the other lines). Confirmed it fails when the try/except is narrowed to ZeroDivisionError.
F4: test_slices_store.py: dead setup removed; missing-array test docstring reworded plus a version 1 case; `_damage_float_counts` added to the damaged-file parametrization (not mutation-checked).
Mutations were applied in place and restored from a backup before commit (git diff confirmed).

Verification (tail): core+pure 1115 passed, 5 skipped; dock file 149 passed; ruff check clean; ruff format 178 files already formatted; mypy no issues in 42 files.
Concerns: none. The F1 test holds the engine empty by wrapping `engine.set_source`, so it does not exercise the async task.
