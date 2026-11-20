# Final-review fix wave: report

Branch `nsgeo-slices-clock-preset`, from d87c927. Four commits, not pushed:

| SHA | Subject | Items |
|---|---|---|
| 9557a9b | fix(slices): saving a cube takes the last restore's notes down | 1 |
| dfcb1df | test(slices): a deferred restore owing a shift, and two tighter pins | 2, 5, 6 |
| f53106d | test(slices): the first-break estimate holds under every registered transform | 4 |
| c2adcae | docs(plugin): the clock warning, time_axis and line_loaded say what they do | 3 |

## Item 1: F-I1, Save cube… leaves the restore's notes standing (behaviour change)

**Change.** `SlicesDock.refresh_cube_combo` (`ui/slices_dock.py`): when `select` is given, it now
clears `_grid_notes` and calls `show_warnings()` (only if there were notes). It does this whether or
not `select` is among the items, because a save always writes a record that matches the screen, even
one that overwrites the restored cube's own id. A refill with no `select` (`rebuild_source`) is
unchanged. The docstring says so. `plugin.save_cube` is unchanged (it already passes `select=cube_id`).
The Save cube… and Export row widgets are untouched.

**Test.** `test_saving_a_cube_takes_the_last_restore_s_notes_down` (`test_plugin_slices_dock.py`).
A shifted restore of an unmarked record on `docked_zeroed`, picked through the combo, shows
`[old_cube_note(...)]`. Then `_save_cube(..., "A__saved", dock.view_settings(), time_base=TIME_BASE_TIME_ZERO)`
records the cube as `save_cube` does and refills with no `select`: the combo stays on `A__old` and the
note stands. Then `refresh_cube_combo(select="A__saved")`: the combo reads `A__saved` and `_notes == []`.

- **RED** (before the fix), failing for the reason it names:
  `assert ['This cube w...by +2.42 ns.'] == []`, with the old-cube note still in Warnings beside the
  saved cube. 1 failed.
- **GREEN** after the fix: 1 passed.

## Item 2: M2-3, a deferred restore that also owes a shift (guard)

`test_a_restore_that_waits_for_a_site_task_and_owes_a_shift_pushes_it_shifted`. Setup:
`_prepared_with_owed_record` (engine cleared), `_site_task_live`, `_record_pushes`. After
`restore_cube`, it asserts the restore is pending, its resolution is owed and the shift is owed. With
the site task gone, `_run_pending_grid_prepare()` dispatches (`engine.is_running`) with `pushed == []`.
After the preparation lands, `_assert_shifted_once` (one note) and `_assert_pushed_shifted` (every push
is the shifted range).

- **Guard: passes on today's code.** Docstring line: *"A guard: it pins today's code."*
- Bite check (temporary, reverted in the same command, tree verified clean): I dropped
  `not self._pending_z_shift and` from `_run_pending_grid_prepare`'s running branch, and the test
  failed with `AssertionError: pushed before the shift / assert [5.0] == []`.

## Item 3: docstrings and comments (no behaviour change)

- **M4-5** `SiteScope.warnings` (`ui/site_scope.py`): one description throughout. The warning counts
  the grids the site draws or will draw (`grid_time_bases`): a ready grid by its prepared steps, a
  queued or preparing one by its preset. A grid with no lines or a failed preparation is left out. The
  docstring no longer says "the drawn grids".
- **M4-6** `ProcessingDock.time_axis` (`ui/processing_dock.py`): a new paragraph describes the
  `(0.0, dt, n_samples)` branch. With no samples and an enabled `time_zero` in the stack, the header is
  the wrong clock. On the time-zero clock the record starts at 0 and has at most the header's samples,
  so a seeded end time crops nothing (#163 item 3). The header fallback moved out of the
  ValueError sentence into this paragraph. I also corrected the docstring's "only used to seed a curve's
  identity default": `add_step_with_dialog` also seeds a time parameter at the record's end.
- **M4-8** `plugin.py`: the initGui comment by the `line_loaded` connection and `_resync_gain_strip`'s
  docstring now say that ProcessingDock re-shows only a form with a time field and an enabled Time zero
  above its row, built before the samples loaded.
- **M4-3** `test_a_grid_with_no_lines_has_no_clock` (`test_plugin_site_scope.py`) docstring:
  *"A guard: it holds on today's code (#163 item 6 asked for the test)."*

## Item 4: M3-1, tripwire over the transform registry

`test_median_first_break_finds_the_break_under_every_registered_transform`
(`test_plugin_slices_engine.py`). It is parametrized over `[NO_TRANSFORM, *transform_names()]`,
read at collection from the registry (`slices_plan.transform_names`, newly imported in the test file).
Today that is `''`, `amp_abs`, `amp_envelope`, `amp_square`.

**One deviation from the brief's wording, made on purpose.** The brief says "within one sample of the
band row". I used `_banded_engine`'s lines with `rise=0.3`, so the break is the rise at row 38, two
rows before the band, and the test asserts within one sample of that. On flat bands with no rise, any
pure power such as |x|³, read as prepared, still picks the band row exactly. I measured this: an
un-rooted square picks row 40 on those lines. So a no-rise tripwire would not catch a power
transform. With the rise it does.

**Envelope tolerance:** up to three samples early (still at most one late). These synthetic bands are
flat DC steps, not wavelets, and the envelope of a step spreads ahead of it along the Hilbert
transform's 1/t tail. It reaches 0.2 of the peak three rows out: measured row 35 against a break at
38, and row 37 against a band at 40 with no rise. On real lines the envelope picks within a sample. I
measured this with the fairness test's method under each transform, with a probe that is now deleted:

| Survey | none | amp_abs | amp_envelope | amp_square |
|---|---|---|---|---|
| campus | 0 | 0 | −1 sample | 0 |
| GPS | 0 | 0 | 0 | 0 |

So `median_first_break`'s docstring claim ("an envelope picks within a sample") holds on real data,
and I left it unchanged. The test docstring gives this reason.

- **Guard: passes on today's code.** Docstring: *"A tripwire (final review M3-1), passing on today's code…"*
  4 passed; the full `-k median_first_break` set is 9 passed.
- Bite check (temporary probe file, deleted): I registered a fifth transform through
  `monkeypatch.setitem(base._REGISTRY, ...)` and ran the test body. **|x|³** failed with
  `('amp_cube_probe', 2.0)` (2 samples late), and **log1p|x|** failed with `('amp_log_probe', -36.0)`.

## Item 5: M3-2, the real-data fairness test pins `amp_square`

`test_the_first_break_estimate_matches_time_zero_on_real_lines` now has
`assert transform == "amp_square", transform` before the comparison, with a comment saying why.
Both surveys (campus, GPS) ran on this machine with no skip: 2 passed.

## Item 6: M2-6, the close drops the owed resolution

In `test_closing_the_site_while_a_restore_waits_for_a_site_task_is_quiet`, the assertion
`assert not dock._resolution_owed, "the close dropped the owed resolution"` now sits just after
`session.close_site()`, before the retry. I removed it from after `_run_pending_grid_prepare()`, where
the retry consumes the flag anyway. I also added `assert dock._resolution_owed` before the close, to
show the flag was set beforehand. 1 passed.

## Verification (from the worktree root, after all four commits)

- `test_plugin_slices_dock.py test_plugin_slices_engine.py test_plugin_site_scope.py test_plugin_processing_dock.py`
  (one run): **538 passed in 537.95s**. No failures, and the #166 Whole site flake did not appear.
- `test_plugin_slice_export_dialogs.py` (the only file that drives `plugin.save_cube`, the caller of
  the changed path): **45 passed**.
- Pure and core: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q -p no:xonsh -p no:cacheprovider`:
  **1685 passed, 5 skipped**.
- `.venv/bin/ruff check . && .venv/bin/ruff format --check .`: **All checks passed! 233 files already formatted**.
- I did not run the full QGIS tier, as the constraints say.

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`: `refresh_cube_combo` (code and docstring)
- `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`: `SiteScope.warnings` docstring
- `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`: `time_axis` docstring
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: initGui comment and `_resync_gain_strip` docstring
- `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`: 2 new tests; 2 tests tightened
- `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`: 1 new parametrized test; `transform_names` import
- `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`: one docstring

## Concerns

- None that block. Item 4 measures against the rise row rather than the literal "band row". The
  reason is given above; it makes the tripwire catch power transforms.
- `refresh_cube_combo(select=...)` clears the notes even when `select` is not among the items, which
  `save_cube` never produces. I chose this because a save always replaces what the notes describe.
  Say if you want it limited to `select in items`.
