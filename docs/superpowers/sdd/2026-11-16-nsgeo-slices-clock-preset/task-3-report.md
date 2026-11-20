# Task 3 report: a preset whose clock changed since the save (#162 item 1)

Status: **DONE_WITH_CONCERNS** (two deviations from the brief's literal interface, both forced by
the code or the real data; details under Concerns).

Base 1584a6b. Commits (not pushed):
- `1fcb491` fix(slices): a restored cube moves onto the clock its preset is on now
- `34f4cb6` fix(slices): the first-break estimate reads a squared line through its root
- `291768b` docs(guide): a cube whose preset gained or lost Time zero comes back moved

## What I implemented

- **`slices_dock.py`**
  - `OwedShift` (frozen dataclass, fields and docstring verbatim from the brief).
  - `_pending_z_shift: OwedShift | None`; `_drop_restore_pending()` sets it to `None`.
  - `restore_cube`: `saved = recipe.time_base or TIME_BASE_RADAR`,
    `now = time_base_of(self._live_preset_steps(preset))`, and
    `OwedShift(now, cube_id, preset, recipe.time_base is not None)` when they differ, else
    `None`. Replaces the `sets_time_zero` test (import dropped).
  - `_shift_z_to_clock(owed) -> bool` replaces `_shift_z_by_median_zero`.
    - To time zero: `median_zero()`, `retime_ns(t, 0.0, m)`.
    - To radar: `median_first_break()`, `retime_ns(t, m, 0.0)`.
    - The shift is `retime_ns(0.0, from, to)` (−m and +m respectively), one rule for both.
    - With prepared lines but no value: `no_break_note`, returns False. With nothing prepared:
      silent, as before.
    - Otherwise it remembers the shifted range, as before, and adds `old_cube_note(shift)`
      (unmarked) or `clock_change_note(...)` (marked).
  - `_settle_z` consumes the `OwedShift` (`pending, self._pending_z_shift = …, None`). It still
    returns "push" whether or not the shift moved anything, because the restore stopped its
    debounce for this settle (a comment says so). Docstrings and comments that said "radar's
    clock" for the owed range now say "the clock it was saved on".
- **`slices_engine.py`**: `median_first_break(threshold=0.2) -> float | None`, beside
  `median_zero`. See Concerns 1 and 2 for how it picks.
- **`slices_plan.py`**: `clock_change_note(cube_id, preset, to, shift_ns)` uses the spec §4 wording
  for gained and lost. `no_break_note(cube_id, preset)` says "No line has a first break to move it
  by, so its range was left as saved." Cube and preset are quoted with `!r`, as the "moved to
  another grid" note already is.
- **`docs/guide/getting-started.md`**: one sentence appended to the cubes-before-0.4.0 paragraph:
  "A cube whose preset has gained or lost Time zero since it was saved comes back the same way, and
  the Slices panel's Warnings says by how much."

## Tests

New, pure (`test_pure_slices_plan.py`):
- `test_clock_change_note_names_the_cube_the_preset_and_the_signed_shift`, parametrized on the
  sign (±0.52), both values of `to`: the id, the preset, `f"{shift:+.2f} ns"`, gained and lost
  phrasing, and full text.
- `test_no_break_note_names_the_cube_and_the_preset`.

New, engine (`test_plugin_slices_engine.py`, helper `_banded_engine` writes its own banded lines):
- `test_median_first_break_is_the_median_band_row`: rows 40, 40, 41 under a preset with no Time
  zero, NO_TRANSFORM. It is None before preparation and `t0 + 40·dt` after. I used an empty preset,
  not `[dewow]`: dewow's 4 ns running mean drags energy ahead of the band and moves the pick, so
  row 40 would not hold.
- `test_median_first_break_leaves_out_a_line_with_no_signal` (extra; pins the interface's "skips a
  line with no signal / None when no line has a break" on real code, not a monkeypatch). Rows 40,
  41 and a silent line give `t0 + 40.5·dt`, and all three silent give None.
- `test_median_first_break_is_where_the_amplitude_breaks_under_the_transform[none|amp_abs|amp_square]`
  (commit 34f4cb6): the band rises to 0.3 of itself two rows early, so the break is row 38 under
  every transform.

New and changed, dock (`test_plugin_slices_dock.py`):
- Fixture `docked_banded_radar` = `_docked_with(tmp_path, PRESET, band_rows=(40, 40, 41))`.
- `test_a_radar_record_whose_preset_gained_time_zero_restores_moved_by_the_median_zero`
  (docked_zeroed, `time_base="radar"`): moved by −median as `_assert_shifted_once`, with note
  `clock_change_note("A__old", "p", TIME_BASE_TIME_ZERO, -median)`.
- `test_a_time_zero_record_whose_preset_lost_it_restores_moved_by_the_median_first_break`
  (docked_banded_radar):
  - `fb` is read first, and `abs(fb) > dt` holds: fb is about −2.42 ns, so this range moves
    earlier;
  - the record's z is chosen inside the prepared bounds with `|fb| + 1` ns margin each side;
  - after the restore, the spins and `engine.z.t0_ns` sit at `t0 + fb` (abs 1e-3), and
    `_notes == [clock_change_note(..., TIME_BASE_RADAR, fb)]`.
- `test_a_lost_time_zero_with_no_first_break_says_the_range_was_left` (Review Focus 5,
  monkeypatched `median_first_break → None`): the range is unchanged (spins and engine), and
  `_notes == [no_break_note("A__old", "p")]`.
- Ruling P1: `test_a_marked_record_is_not_shifted` and
  `test_an_old_recipe_without_time_zero_restores_unchanged` each gain `assert _notes(dock) == []`.
  No new test of that name.
- Real data, parametrized `campus` (`CAMPUS_LINES[:4]`, 12 m grid) and `gps` (`GPS_LINES[:4]`,
  31 m grid), each with `skipif(not <list>)`. A `_real_docked` context manager builds the dock as
  the existing real-data test does.
  - `test_a_real_data_old_record_restores_moved_by_the_median_zero`: a guard, which holds today
    (its docstring says so). It checks `_assert_shifted_once` and that `|median_zero|` is inside
    the author's band.
  - `test_the_first_break_estimate_matches_time_zero_on_real_lines`: through This grid, under its
    default transform, as a restore reads the lines. It takes the `median_first_break()` under
    "radar" `[dewow]` and the `median_zero()` under "zeroed" `[time_zero, dewow]`, and needs them
    to agree within `dt` (commit 34f4cb6).
- `_assert_shifted_once(dock, errors, note=None)` takes the expected note, defaulting to the
  unmarked one, and now also asserts `abs(median) > 1e-3`, so it cannot pass vacuously.
- Existing tests that read `_pending_z_shift` (10 places) all use truthiness (`assert x` /
  `assert not x`). They hold unchanged for `OwedShift | None`; no test set it to True or False.

## TDD evidence

RED, recorded in the order run:
- Pure: collection error `ImportError: cannot import name 'clock_change_note'`.
- Engine: `AttributeError: 'SliceEngine' object has no attribute 'median_first_break'`, both tests.
- Dock, run with the pure and engine parts in place so each failed on behaviour:
  - gained: `assert 5.0 == 7.4248 ± 0.001`. The marked radar record was not shifted.
  - lost: `assert -7.661 == -10.0858 ± 0.001`. Not shifted.
  - no-break: `assert [] == ["Cube 'A__old' … left as saved."]`. Nothing was said.
  - estimate check, campus: `-0.0433 == -0.4764 ± 0.2165`; gps: `-1.1260 == -1.5590 ± 0.2165`
    (see Concern 2).
  - The two extended guards and the real-data median guard passed, as expected.
- Squared-line engine test with the square root removed: only `[amp_square]` fails
  (`-2.4248 == -2.8578`, two rows late). `none` and `amp_abs` pass.
- Mutation checks, run by hand and reverted: making the engine read a silent line as row 0 fails
  `…leaves_out_a_line_with_no_signal` (`-2.4248 == -2.3165`). I checked it against both
  implementations, before and after the boundary change.

GREEN after each fix: the targeted runs pass (pure 4, engine 5, dock 8 including real data).

Whole files at HEAD 291768b:
- `test_plugin_slices_dock.py`: `243 passed in 85.05s`
- `test_plugin_slices_engine.py`: `81 passed in 6.81s`
- `test_plugin_site_scope.py`: `173 passed in 436.44s`
- pure + core tier: `1685 passed, 5 skipped in 196.42s`

Before the boundary fix, the same run at the first-commit state was dock 241 passed, engine 78,
site scope 173, and pure 1 failed (`test_plugin_imports_only_the_named_core_api`, Concern 1), 1684
passed, 5 skipped.

Lint: `ruff check .` and `ruff format --check .` clean. mypy, as CI runs it (it covers
`slices_plan.py`): no issues in 55 files. Test output: no warning lines in any log.

## Real-data measurements (four lines each, dt = 0.21653 ns)

| Survey | median line zero (time zero preset) | estimate as the brief read it (on the prepared, squared lines) | estimate after 34f4cb6 |
|---|---|---|---|
| campus | −0.4764 ns (in the 0.3–0.7 band) | −0.0433 ns: gap **+0.4331 ns = +2.00 samples** | −0.4764 ns: gap **0.0000 ns = 0 samples** |
| gps | −1.5590 ns (in the 1.2–1.7 band) | −1.1260 ns: gap **+0.4331 ns = +2.00 samples** | −1.5590 ns: gap **0.0000 ns = 0 samples** |

Both medians lie inside the author's bands, so no band was touched. For context, I measured the
other transforms with a core-only script over the same lines, reading `[dewow]` and the transform
as prepared:
- none and `amp_abs`: gap 0 on both surveys;
- `amp_envelope`: −1.00 sample on campus, 0 on GPS.

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`
- `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`
- `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`
- `docs/guide/getting-started.md`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`
- `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py`

## Self-review

- **Brief completeness:** every Produces item, the Step 1 tests, the Step 3 steps, the guide and
  the commits are done. The "Leave alone" items are untouched: the Save cube… / Export row,
  `param_form.py`, `first_break_row`. I added no Qt slot or override, so there is no new guard to
  write. No toast: every message here goes through `_add_grid_note`.
- **Names** are as briefed. One extra, for the reviewer to keep or drop: the engine test for
  silent lines. It costs about a second and is the only place Review Focus 5's None is produced by
  real code rather than a monkeypatch.
- `_shift_z_to_clock`'s bool return is unused by its one caller (`_settle_z` pushes regardless,
  with a comment explaining why). It is kept because the brief's signature names it.
- **Main-thread cost:** `median_first_break` runs in `_on_prepared` only for a "lost" restore.
  Per prepared line it takes a square root (only when the transform is `amp_square`) and a Time
  zero `apply`, which copies the rows from the break down. That is one pass and one copy of about
  3.6 MB on a GPS line, once per such restore. Fine for the grids in hand, but on a very large grid
  it is a noticeable one-off.

## Concerns

1. **The private import the brief allowed fails an existing test.**
   `tests/pure/test_plugin_boundary.py::test_plugin_imports_only_the_named_core_api` forbids
   importing anything outside `nsgeo.processing.__all__`, and `_first_break_or_none` is not in it.
   - `median_first_break` therefore picks with the public Time zero step instead:
     `build_step("time_zero", threshold=…).apply(rg).zero_ns`. The step refuses a line with no
     first arrival (`ValueError`), and that line is skipped.
   - On a line whose zero is 0.0, that value equals `first_break_ns` (`0 + t0 + row·dt`). It is
     literally "Time zero's own rule", with no core API change.
   - Values are unchanged from the brief's formulation. Only the means differ.
2. **The brief's estimate, read straight off `line.data`, fails spec §9's fairness check under
   This grid's default transform.**
   - Under `amp_square` it is 2 samples (0.43 ns) late on both surveys. On campus that is nearly
     the whole shift (−0.04 against −0.48 ns), so a "lost" restore would barely move.
   - Cause: Time zero averages |x|, and a square reaches 0.2 of its peak only where |x| reaches
     0.45 of its own.
   - The spec (§12) leaves the engine read to the builder, so commit 34f4cb6 reads a squared line
     through `np.sqrt`, which gives |x| back exactly. The gap is then 0 on both surveys.
   - I kept it as its own commit so it can be ruled on and reverted alone. Reverting it would also
     revert the real-data fairness test, which then fails 2 samples out under the old read.
   - Alternative if the literal `"amp_square"` check in the engine is unwelcome: record each line's
     break before the transform during preparation (exact for every transform, envelope included).
     That changes the preparation worker's result, which is a larger and riskier edit.
   - Left as is: an envelope reads within one sample (−1.00 on campus), which is at the edge of
     the check if the default transform ever became the envelope.
3. The brief's bands and every other value fit the measurements. No test was weakened, and none
   passed before its fix except the guards, which say so.
