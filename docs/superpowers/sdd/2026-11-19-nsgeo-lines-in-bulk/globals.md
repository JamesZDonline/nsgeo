# Global constraints (every task)

Spec (binding; read the sections your brief cites): docs/superpowers/specs/2026-11-19-nsgeo-lines-in-bulk-design.md


- Paths are under `packages/nsgeo-qgis/nsgeo_qgis/` unless they start with `packages/`.
- User-facing strings are copied verbatim from the spec (§2.1, §4.1, §4.2, §5); the tests quote
  them through module constants, as `survey_dock.py` already does for its cut prompts.
- Every slot (menu action, signal handler, `itemSelectionChanged`, `selectionChanged`) guards its
  own body and logs through `QgsMessageLog` (`_log`), per each module's docstring: an exception in
  a slot never reaches the emitter, and in CI's container it aborts the run.
- New re-entrancy guards are depth counters (`+= 1` / `-= 1` in `try/finally`, read as truthy),
  never set/clear booleans.
- No modal runs in a test without `answer_modal` / `drive_dialog`; never `QMenu.exec()` in a
  test (build the menu, then find and trigger its action, as `test_plugin_survey_dock.py` does).
- Other sessions' files: no edit to `ui/processing_dock.py`. In `ui/slices_dock.py` only the one
  new slot and its `connect` line (Task 3). In `map_link.py` new methods plus a few lines in
  `_on_selection` (Task 2). In `survey_dock.py` and `plugin.py`, new functions; existing
  functions get one-line calls into them.
- Magnetometer files (M19a, unmerged) are not lines: nothing here may assume a selected key is a
  line without checking it is a "line" row (`SurveyDock.key_of`).
- Real data first: real-data tests use `tests.real_data.GRID2_LINES` and `GPS_LINES` and skip with
  a reason naming `tests/data/local` (that names them `real_data`; an unmarked data skip fails).
  Never put a survey or site name in code, tests, commits or the PR.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; push the branch
  after each task.
- **Local test recipe** (do not run the whole QGIS tier locally; CI does, on 3.44 and 4.2):
  - core + pure: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh`
  - touched QGIS files: `packages/nsgeo-qgis/scripts/qgis_tests.sh <files> -q`
  - real data: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis -m real_data -q`
  - then `gh run list --branch nsgeo-lines-in-bulk` until the pushed commit's run passes,
    **including the `qgis/qgis:4.2` job** (Qt 6: enums are not ints).


## Controller rulings that bind tasks
- R1: Task 1's mag test is cut-only: `test_the_bulk_items_never_offer_a_cut_key` (main has no mag rows).
- R2: assert dirtiness by saving first and checking `session.dirty` afterwards, not by counting `dirty_changed` (it only fires on a transition).
- R3: Task 4's module is `nsgeo_qgis/decimal_input.py` (not numbers.py, which would shadow stdlib `numbers`); its pure test is `tests/pure/test_pure_decimal_input.py`.
- The machine is shared and heavily loaded (load ~25 on 4 cores): run focused test files, never the whole QGIS tier; long runs are expected, give them generous timeouts.
