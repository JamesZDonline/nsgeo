# Task 1 report: one rule for pending values, and the fallback preset

Status: DONE_WITH_CONCERNS. The concerns are about scope, not correctness. See "Concerns".
Commit: `9c48217 fix(slices): one rule for a restore's pending values, and the fallback preset` (not pushed).

## What I implemented (`packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`)

- **`_drop_restore_pending(self) -> None`**: sets `_pending_z_shift = False` and `_pending_palette = None`.
  It replaces the paired clears in `_on_source_changed`, `set_included` and `_switch_resumed_grid`.
- **`rebuild_source`**:
  - The unconditional `_pending_z_shift = False` at its top is gone.
  - `new_site = self.session.site is not self._site_seen` is computed first. If the site is new,
    `_drop_restore_pending()` runs before anything else.
  - The tail branch beside `self._site.forget()` now tests `new_site`, so there is one check per
    call, as spec §2 says. It also sets `_pending_top_ns = None` and `_resolution_owed = False`.
  - **Beyond the brief:** that same branch also puts `slice_slider` back to 0, with signals blocked.
    See Concern 1.
- **`_sync_included(self, *, by_hand: bool = False)`**: in the grid-changed branch, when the change
  is not by hand:
  1. `_drop_restore_pending()`;
  2. select `site_scope.default_preset(self.session, grid_id)` inside the `_updating` guard. This is
     skipped when the result is `None`, when the preset is not offered, or when no grid is selected
     or no site is open.

  Then the branch goes on as before. `_on_source_changed` passes `by_hand=True`.
- **Docstrings:**
  - `_pending_palette` and `_pending_z_shift` now say when they are dropped: a new site, or a source
    change (by hand, from the site list, or a fallback grid). Their own `_on_prepared` still consumes
    them, and a refresh that keeps the source never drops them.
  - `_sync_included`'s docstring gains a #152 paragraph.

## Tests

`test_plugin_slices_dock.py`:
- `test_an_edit_while_a_restore_prepares_keeps_its_shift_and_note[lines_changed|grids_changed|presets_changed]`
- `test_rebuilding_the_source_keeps_what_a_restore_owes_on_the_same_site` replaces
  `test_rebuilding_the_source_drops_an_owed_shift`.
- `test_a_restored_palette_does_not_carry_into_the_next_survey`
- `test_a_survey_opened_after_closing_one_in_this_grid_starts_at_its_first_slice`. This one is
  **extra, not in the brief.** See Concern 1.
- `test_a_grid_the_combo_falls_back_to_opens_on_the_preset_whole_site_draws_it_with`
- `test_a_grid_picked_by_hand_still_carries_the_preset_over` (guard; says so in its docstring)
- `test_opening_a_survey_does_not_carry_a_same_named_preset_over` (guard; says so in its docstring,
  see below)
- `test_removing_the_grid_while_its_restore_prepares_drops_the_restore` (Review Focus 1). I made it
  stronger than the brief: A is on a time-zero preset `z` and the record has no clock marked, so a
  shift really is owed. The test asserts that both values are pending before the removal. It keeps
  every assertion the brief lists, and adds one: no old-cube note lands on B.

Helpers:
- `_another_palette(dock)`
- `_second_survey(tmp_path, presets=("p",))`: a saved survey under `tmp_path / "second"`, with grid
  A, three synthetic lines and the named presets.
- `_owed_record` gained a `palette=` keyword (default unchanged).
- The import line now reads `from nsgeo_qgis.ui import folds, site_scope`.

`test_plugin_site_scope.py`:
- `test_a_survey_opened_after_closing_one_in_whole_site_starts_at_its_first_slice(plugin, site3_factory)`

New tests test `_pending_z_shift` by truthiness only. `_assert_shifted_once` still has
`is False`; Task 3 owns that.

## TDD evidence

### RED (before any production change)

Command:
`PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py -q -p no:xonsh -p no:cacheprovider -rA -k "<the new tests>"`

Result: 7 failed, 2 passed.

| Test | How it failed | Why that was expected |
|---|---|---|
| `edit_while_a_restore_prepares` ×3 | `assert 5.0 == 7.4247… ± 0.001` (z0 not shifted), the same for every signal | `rebuild_source` dropped the owed shift on every signal, so `_on_prepared` never shifted the range |
| `keeps_what_a_restore_owes_on_the_same_site` | `assert dock._pending_z_shift` → `False` | the same blanket clear |
| `restored_palette_does_not_carry_into_the_next_survey` | `assert 'amp_white_high' is None` (`_pending_palette` after `close_site`) | a close never dropped the palette |
| `falls_back_to_opens_on_the_preset_whole_site_draws_it_with` | `assert 'q' == 'p'` | the fallback grid B kept A's preset |
| `removing_the_grid_while_its_restore_prepares` | `assert 'amp_white_high' == 'amp_black_high'` | A's restored palette was applied to B |
| `picked_by_hand_still_carries_the_preset_over` | PASSED | guard |
| `opening_a_survey_does_not_carry_a_same_named_preset_over` | PASSED | guard; see "A test that passed before the fix" |

The `removing_the_grid` row is from the strengthened version, rerun against `git show HEAD:` of
`slices_dock.py`.

Site-scope command (the same flags, `-k survey_opened_after_closing_one_in_whole_site`): 1 failed,
with `assert dock._pending_top_ns is None` → `61.053`. The switch back to This grid on close carried
the site's time over. A probe of step 5 alone on the old code showed the slider at 282 of 459.

### A test that passed before the fix

`test_opening_a_survey_does_not_carry_a_same_named_preset_over` passed on the old code. I stopped and
investigated before changing anything. A probe connected after the dock's slots logged
`[('closed', '', 0, None), ('opened', 'p', 2, 'A')]`. Here is what happens:
1. `SiteSession.open_site` → `_install` → `close_site()` whenever a survey is open.
2. That `site_closed` runs `rebuild_source`, which refills `preset_combo` with nothing, so it is
   empty and `_last_grid_id` becomes `None`.
3. The new survey's refill then lets Qt select its first preset.

`new_site` takes the same route. So no path today opens a survey on a same-named preset carried over,
although spec §5 says one does. I kept the test, unweakened, as the brief's second guard ("both guard
tests pass"). Its docstring says it is a guard and gives the reason. With the fix, the site open now
goes through the fallback rule explicitly, and the result is the same.

### GREEN

- After the brief's production changes, the 9 new dock tests passed (9 passed).
- The #102 site-scope test **still failed** at step 5: `assert 282 == 0`. See Concern 1.
- After adding the slider reset: that test passed, and so did the extra This-grid test.

Proof that the slider reset is what fixes them: I took the reset out and kept the rest of the fix.
Both #102 tests then failed: This grid with `306 == 0`, Whole site with `282 == 0`. Restored after.

Two mutants of the Review Focus 1 test (each restored after, `cmp` checked):
- **No `_drop_restore_pending()` in `_sync_included`:** it fails on the palette.
- **The palette dropped but not the shift:** it fails on the new note assertion, with "…moved by
  +2.42 ns" on B. So the shift part of the test checks something.

### Whole files and lint (final code)

- `test_plugin_slices_dock.py`: **222 passed** (85 s, rerun after the last test edit and formatting).
- `test_plugin_site_scope.py`: **173 passed** (564 s).
- Pure and core (`packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests`): **1682 passed,
  5 skipped**, the same as the ledger's baseline.
- `ruff check .`: all checks passed. `ruff format --check .`: 233 files already formatted (I ran
  `ruff format` on the test file once).

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`

## Self-review

- **Completeness against the brief:** every listed change is made, and every listed test is written
  (two of them stronger or with an extra twin; see above). The interfaces match the brief:
  `_drop_restore_pending(self) -> None` and `_sync_included(self, *, by_hand: bool = False) -> None`.
- **Patterns:**
  - The fallback preset is set inside an `_updating += 1 / try / finally -= 1` block.
  - The slider write is blocked like every other placement of it.
  - The new branches sit inside `rebuild_source`'s existing slot guard. `_sync_included` is not a
    slot; its callers guard it.
  - Docstrings follow the file's style.
- **Untouched:** the Save cube… / Export row, `param_form.py` and `first_break_row`.
- **`restore_cube`:** it still sets `_last_grid_id` before it moves the combo, so a restore never
  reads as a fallback.
- **Redundancy left in place on purpose:** `_switch_resumed_grid` still selects `default_preset`
  itself, and its later `_sync_included()` now does the same thing again (and drops again). The
  repeat is idempotent. The brief scoped that method to swapping the paired clears, so I left it.
  A reviewer may want it simplified.

## Concerns

1. **Beyond the brief: the slider reset on a new site (#102).**
   - **What happened:** the brief's fix (clear `_pending_top_ns` and `_resolution_owed` beside
     `forget()`) does make step 3 of its own #102 test pass. Step 5 (`slice_slider.value() == 0`)
     still failed, with 282.
   - **Root cause:** the slider's own index also outlives the survey. The engine is cleared on
     `site_closed`, so the new survey's first `_apply_resolution` has no old axis and no previous
     time. `setRange` only clamps the index, so the next survey opens at the old one's slice.
   - **The same happens without Whole site:** a probe in This grid went from 275 to 275 across a
     close and an open.
   - **What I added:** the same new-site branch puts the slider back to 0 (blocked), plus a twin
     test for the This-grid path. Both fail without it.
   - **For the reviewer:** this changes the visible behaviour of a plain close-then-open in This grid
     too: it now starts at the first slice. That matches #102's "starts at its own first slice", but
     it was not asked for in so many words.
2. **The second guard test is my reading.** `test_opening_a_survey_does_not_carry_a_same_named_preset_over`
   holds on today's code, for the reason above. The brief's "both guard tests" fits it, but the
   brief did not name it as a guard. Spec §5's claim that opening carries a same-named preset over
   does not hold under today's `SiteSession` (`_install` always closes first).
