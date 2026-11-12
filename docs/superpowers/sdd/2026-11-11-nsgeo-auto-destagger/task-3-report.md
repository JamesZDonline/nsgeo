# Task 3 report: Measure in Edit lines (#159)

## Implemented
- `nsgeo_qgis/destagger_job.py` (no Qt): `JobLine`, `MeasureJob` (reads only unprepared lines, first channel, per-line OSError/DztError/ValueError into `unreadable`, stop checked before each read, MeasureStopped -> `stopped`), `box_value`, `measure_summary` (P12 cap of 6 per group, then "and {n} more"). Imports core only via `nsgeo.io` / `nsgeo.destagger` / `nsgeo.geometry` (the boundary test rejects `nsgeo.io.dzt`).
- Dialog: `measure_button` after Set, `MEASURE_TIP`, `Refiner` created before the first `_refresh`, 200 ms progress QTimer, `_bins` cache, `measure()` start/stop, landing check (site identity, then snapshot), fill (rounded to 0.001) of selected on-grid rows plus the box, `_update_panel` enables the panel while busy and sets the button text, `done()` shuts the worker down. Every slot/callback guards with `except Exception -> _failed`.
- ci.yml mypy list, guide paragraph, README bullet.

## Tests
- Pure: 8 tests in `test_pure_destagger_job.py`. QGIS: 14 tests in `test_plugin_edit_lines_measure.py`, including the real survey (Grid 1, 29.98 m; box within 0.02 of +0.15, not skipped).
- RED: pure file with the module absent: `ModuleNotFoundError: No module named 'nsgeo_qgis.destagger_job'`; QGIS file with the dialog at HEAD: collection ImportError (MEASURE_* names missing). Honest note: I wrote destagger_job.py before running the pure tests, then removed it to record the RED.
- GREEN: measure + dialog files: 62 passed (25 s). Pure tier + core: 256 passed 1 skipped for qgis-pure (full core+pure earlier: 1297 passed, 5 skipped, after fixing the one boundary failure it caused). ruff check/format clean. mypy clean (50 files).

## Decisions / notes
- Tests of Stop must wait until the worker is inside the measure: a stop before it starts ends the job at the read check, which is correct.
- Tests with the real `measure_destagger` use a shared-field synthetic DZT (same field over the grid, reversed for backward lines, 8 m long); the 1 m `synthetic_dzt` lines are all TOO_SHORT. These measure clearly, so unreadable/twice/one-way run the real code.
- Constraint: when every axis fails, the summary is only the failure sentence, so an unreadable file is not named then (as specified).
- A stopped/discarded run still keeps its newly read bins in `_bins` once landed; a cancelled run (Stop, close) drops them (Refiner never delivers).
- Summary group formatting for "{n} more": own values join with ", " (", and 3 more"), the other groups with "; " ("; and 3 more"). The constraints did not fix this.
- Full QGIS tier not run (controller).

## Fix round 1
All in the QGIS measure file unless noted; the covering tests pass (measure + dialog files: 68 passed).
- Important 1: `test_results_land_in_the_rows_selected_when_measure_was_pressed`. Mutation proof (a temporary local edit, reverted before commit): `_land` using `self.selected_keys()` instead of `run.targets` fails it ("At index 0 diff: None != 0.12").
- Spec 2: guide Measure paragraph now follows "Fit a grid's lines before you destagger them".
- Minor 1: `JobLine.label` from `_label_of(key)` (dialog `_measure`). 2: `test_values_are_rounded_to_the_boxs_precision` (0.12345 -> 0.123 row and box). 3: error copy test (`Could not measure: RuntimeError: boom. Nothing was changed.`), no-targets test, progress test (gated read shows `read 2 of 6 lines`, then `comparing lines`). 4: `test_a_site_replaced_while_measuring_is_not_written_to`. 5: noise seed is the line index; shared-field lines carry a 9-trace (0.15 m) injected stagger; the twice test asserts |box| within 0.04 of 0.15. 6: `measure_summary` says `Could not measure: no line could be read. Nothing was changed.` when axes are empty (+ pure test). 7: close test uses a canned function that loops until `should_stop()` and asserts `stopped_by_request` plus the thread count. 8: two-axes test uses `_open(axes=...)`, no unused fixture, plain `spin_until` import, `box_value` assertion moved to the pure file. 9: pure test for the "; " group cap. 10: `_drop_note` and `fit_to_edges` use `_label_of`.
- Verification: ruff clean, mypy clean (50 files), core + pure: `1301 passed, 5 skipped`.

## Fix round 2
- Minor 4: `test_the_same_site_reopened_while_measuring_is_still_a_new_site` (save, close, `open_site` of the same json mid-run; Site-changed copy, nothing written).
- Minor 5: the twice test asserts `box == approx(-0.142, abs=0.02)` and every row equal to it; the fixture docstring now says the value to find is about -0.15.
- Progress race: the test waits for `canned.seen` before the "comparing lines" status.
- Ruling 11: `_measure` returns with the No-targets copy when no selected row is on this grid (edit_lines_dialog.py, after the P6 filter); `test_measure_with_every_selected_row_on_another_grid_starts_nothing`.
- Verification: measure + dialog files 70 passed; pure destagger file 11 passed; ruff and mypy clean.

## Final fix wave
- Important 1 (Ruling 12): core `measure.py` `NO_LINES` constant, used when no line survives the exclusions (before the neighbour stage); ONE_WAY/TOO_FEW unchanged. Plugin `destagger_job.py` `measure_summary`: when every axis failed, the failure sentence(s) are followed by the not-measured group, leaving out NO_NEIGHBOUR and AXIS_FAILED lines (the axis reason covers both; AXIS_FAILED added by me so UNCLEAR grids do not list every line). Unreadable files are named. Both constants are exported from `nsgeo.destagger` (README table updated) so the plugin imports only the public API. Tests: core `test_when_every_line_is_too_short_the_axis_says_none_could_be_measured`; pure `test_when_every_axis_failed_the_excluded_lines_are_still_named`, `test_a_one_way_summary_is_only_the_failure_sentence`. Plan amended (summary rule, NO_LINES).
- Minor 1: `_measure_axis` sorts its lines by (offset, key); `test_the_input_order_does_not_change_the_result` (real Grid 1 reversed: identical axes incl. spread_m, identical lines).
- Minor 3 (Ruling 15): `measure_summary(..., limit=6)` (`None` = uncapped); dialog `_say(text, tooltip="")` now sets every status text and clears the tooltip; `_land` sets the full text as tooltip when it differs. Tests: pure `test_no_limit_names_every_line`, QGIS `test_the_tooltip_names_every_line_the_status_caps` (8 own values).
- Minor 4: `_site_problem()` shared by `_accept` and `_measure` (same messages); `_bins` keyed by resolved file path (`_MeasureRun.paths`). Test `test_a_dialog_for_a_closed_site_does_not_measure_another`.
- Minor 7 (Ruling 14): `box_value` takes the largest axis among those that measured; pure test updated.
- Minor 8: mirror test also compares OWN values (0.02) and allows at most 2 status flips.
- Minor 9: guide paragraph says unusable lines are named with the reason, and the button reads Stop.
- Verification: core test_destagger_grid.py 31 passed; Measure + dialog QGIS files 72 passed; core+pure run 1359 passed, 5 skipped, 1 failed (`__all__` sort order of the new exports), fixed and test_public_api + qgis pure re-run: 279 passed, 1 skipped; ruff and mypy clean.
