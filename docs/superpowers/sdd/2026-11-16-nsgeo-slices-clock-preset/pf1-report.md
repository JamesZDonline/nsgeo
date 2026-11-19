# PF-1 report: the "lost Time zero" estimate reads each line's raw record

Status: DONE, with one deviation from the brief's test as written (the campus side of the
fairness test uses all ten lines, not the first four; see "Brief vs inspection").
Branch `nsgeo-slices-clock-preset`, from c2adcae. Not pushed.

## Commits

- `cc4acef` fix(slices): the lost-Time-zero shift reads each line's raw first break
- `7a526c2` docs(spec): the lost-Time-zero first break is picked on the raw record

## What changed

1. **`PreparedLine.first_break_ns: float | None = None`** (`packages/nsgeo-core/src/nsgeo/slices/binning.py`),
   after `zero_ns`, with the brief's doc comment. `from __future__ import annotations` was already
   there; `float | None` on a dataclass field has precedent in core (`Radargram.dx_m`,
   `GridPlacement.label`). Every existing positional or keyword construction still works.
2. **Engine worker** (`packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`, `_start_task`'s `work`):
   `first_break = _raw_first_break(radargram)` straight after `Radargram.from_profile(...)`, before
   the stack is built or run, and passed as `first_break_ns=`. The helper is a new module-level
   `_raw_first_break(record) -> float | None`: `build_step("time_zero").apply(record).zero_ns`, and
   None on `ValueError` (no first arrival). It runs on the worker thread, so the main thread does no
   extra work. It never sees `result`.
3. **`SliceEngine.median_first_break(self) -> float | None`**: the median of the prepared lines'
   non-None `first_break_ns`, or None. The `amp_square` square-root branch, its docstring paragraph
   and the `threshold` parameter are gone. The docstring says the pick is the raw record's, where
   Time zero runs in an ordinary preset, so neither the other steps nor the transform move it. The one
   production caller (`slices_dock._shift_z_to_clock`) already called it with no arguments.
4. **Tests**
   - `test_plugin_slices_engine.py`:
     - `_banded_engine` adds a second preset without Time zero, `"gained"`: `gain_agc` (defaults),
       then a `gain_curve` climbing from −20 dB at raw row 39 to 0 dB at row 40. The points come from
       the raw header, through the new helpers `_raw_record` and `_row_ns`.
     - The two old transform tests (`..._is_where_the_amplitude_breaks_under_the_transform` and
       `..._finds_the_break_under_every_registered_transform`) are replaced by one test,
       `test_median_first_break_is_the_raw_records_break_whatever_the_preparation`. It is
       parametrized over preset (`radar`, `gained`) × transform (none plus every registered
       transform; ids now read `none` instead of an empty string). It asserts that the estimate is
       the raw record's row 38 time, exactly (abs 1e-6 samples). The square-root and envelope
       tolerances are gone.
     - New guard `test_gained_pick_lands_late`, which holds today: under `gained`, Time zero's pick
       on the prepared lines is rows [40, 40, 40], and on the raw records [38, 38, 39]. It keeps the
       test above from quietly checking a preset that moves nothing.
     - `..._is_the_median_band_row` and `..._leaves_out_a_line_with_no_signal` are unchanged and pass.
   - `test_plugin_slices_dock.py`:
     - The fairness test `test_the_first_break_estimate_matches_time_zero_on_real_lines` now runs the
       brief's presets: campus `[dewow 4.0, background_mean, gain_agc 20/1/1e-12, gain_curve(...)]`
       and GPS `[time_cutoff 45, dewow, background_mean, gain_agc, gain_curve(...)]`, with Time zero
       in front for the median-zero side. They live in `_CAMPUS_STEPS` and `_GPS_STEPS`, built with a
       small `_step` helper.
     - It is parametrized by a new `_REAL_PROCESSING` list. Campus uses **all ten** lines and GPS
       the first four.
     - It now also asserts that every line prepared under both presets (`line_count == len(paths)`).
     - The tolerance is still one sample (dt).
     - **The `assert transform == "amp_square"` is removed, replaced by nothing.** The docstring
       says why: the pick is the raw record's, so the transform cannot move it.
     - `time_cutoff` stays in the GPS radar-side preset: preparation on the radar clock succeeds on
       all four lines, and 45 ns is well after the first arrival.
     - `_real_docked`'s grid is now `max(3.0, 0.5 * (n + 1))` m wide, so ten lines half a metre
       apart fit. Four lines keep the old 3.0 m, so the other real-data test is unchanged.
     - The no-break note test's monkeypatch is now `lambda: None` (it named the removed
       `threshold`). The Task 3 "lost" restore test is untouched and passes.
5. **Spec** (`docs/superpowers/specs/2026-11-16-nsgeo-slices-clock-preset-design.md`):
   - §4, the "Time zero → radar" bullet: each line's break is picked during preparation on its raw
     record, before any step, by Time zero's own rule at its default threshold, where Time zero runs
     in an ordinary preset.
   - The accepted catch now reads: "A cube whose saved preset ran other steps before Time zero, or
     used Sample mode or another threshold, can be a few samples off."
   - New sub-bullet "Corrected in the build (PF-1)": the prepared-line pick ran two samples late on
     the author's real preset because of its gain steps.
   - **Also §12** (not asked for, one line): "building a `Radargram` from a prepared line for
     `first_break_ns`" contradicted the new §4. It now reads "where each line's raw-record pick is
     kept until it is read (PF-1: on its `PreparedLine`)".

## RED / GREEN

### Engine, synthetic (on c2adcae's implementation, new tests only)

`5 failed, 6 passed, 76 deselected` (`-k "median_first_break or gained_pick"`):

| case | late on c2adcae (samples) | after |
|---|---|---|
| gained, none | +2.0 | 0 |
| gained, amp_abs | +2.0 | 0 |
| gained, amp_square (sqrt branch) | +2.0 | 0 |
| gained, amp_envelope | −1.0 | 0 |
| radar, amp_envelope | −3.0 (the old tolerance allowed it) | 0 |
| radar, none / amp_abs / amp_square | 0 (passed) | 0 |

The gain-step case fails for the stated reason: picked on the prepared data, the gain curve holds the
rise down, and the pick lands on the band two rows late, as on the campus lines. In probes on these
synthetic lines, `gain_agc` alone and the author's own campus `gain_curve` move nothing: its points
start at 0.478 ns, after the synthetic arrival at about −2.4 ns. So the test's curve is placed across
the synthetic arrival.

### Dock, real data: measured gaps (`median_first_break − median_zero`, dt = 0.21653 ns)

| survey | lines | c2adcae | after |
|---|---|---|---|
| campus | all 10 | −0.0433 vs −0.4764: **+0.4331 ns = +2.00 samples → FAIL** | −0.4764 vs −0.4764: **0.0 ns, 0 samples** |
| campus | first 4 (the test as it stood) | −0.4764 vs −0.4764: 0.0 → passes | 0.0 |
| GPS | first 4 | −1.3425 vs −1.5590: **+0.2165 ns = +1.00 sample → passes at the boundary** | −1.5590 vs −1.5590: **0.0 ns, 0 samples** |
| GPS | all 60 (probe only) | 0.0 (medians of both sides are −1.3425) | n/a |

RED run with the new presets: `1 failed, 1 passed` (campus failed with
`AssertionError: ('amp_square', -0.0433056503534317, -0.47636787593364716, 0.21653111279010773)`;
GPS passed). GREEN: both pass with an exact match.

Per line on campus (old prepared-line pick under amp_square through its root, versus raw):
- Lines 1–4 and 6 are unmoved (−0.4764).
- Lines 5, 7, 8, 9 and 10 read +0.3898, **four samples late each**.
- The median of ten is the mean of −0.4764 and +0.3898: −0.0433, two samples late, as the brief
  measured.

## Brief vs inspection

- **The brief's measurement is right, but not for `CAMPUS_LINES[:4]`.** The real-data test used the
  first four campus lines, and those four are exactly the ones the gain steps leave alone. With the
  brief's presets on four lines, the test passed on c2adcae (gap 0.0). I did not stop: the fix to
  the test is to measure the population the brief measured. The campus side now uses all ten lines,
  so it fails on c2adcae by the brief's measured +2 samples. A comment on `_REAL_PROCESSING` says
  why.
- **GPS does not fail on c2adcae at one-sample tolerance.** It sits at exactly +1.00 sample on its
  first four lines, and at 0 on all sixty. Tightening to dt/2 would make it fail too, and the new
  rule makes both sides identical, so there is room. But the brief and spec §9 say "within one
  sample", so I kept dt. Controller's call.

## Commands and summary lines (worktree root)

- `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py -q -p no:xonsh -p no:cacheprovider`
  → `506 passed in 534.52s (0:08:54)` (no #166 flake)
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q -p no:xonsh -p no:cacheprovider`
  → `1685 passed, 5 skipped in 228.10s (0:03:48)`
- `.venv/bin/ruff check . && .venv/bin/ruff format --check .` → `All checks passed!`, `233 files already formatted`
- mypy as CI runs it (`.venv/bin/python -m mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo …lookup.py …view_transform.py …ruler.py …slices_plan.py …line_edit.py …export_pipeline.py …destagger_job.py`)
  → `Success: no issues found in 55 source files` (local mypy 2.4.1; CI pins 2.4.0)
- No Python 3.9 interpreter on this machine. The new annotation follows existing 3.9-safe core
  dataclass fields under `from __future__ import annotations`.

## Files changed

- /home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-slices-clock-preset/packages/nsgeo-core/src/nsgeo/slices/binning.py
- /home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-slices-clock-preset/packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py
- /home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-slices-clock-preset/packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py
- /home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-slices-clock-preset/packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py
- /home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-slices-clock-preset/docs/superpowers/specs/2026-11-16-nsgeo-slices-clock-preset-design.md

## Concerns

1. The GPS side of the fairness test passed on c2adcae, at exactly one sample. Only the campus side
   is the RED pin. A tighter tolerance would also pin GPS, but it goes against the one-sample rule
   in the brief and spec.
2. The campus fairness case now prepares ten lines twice instead of four. In the run it stayed fast
   (the two real-data cases together took about 4 s).
3. The synthetic "gained" curve is placed by hand across the synthetic arrival: the author's real
   campus curve starts after it and moves nothing on these lines. The guard
   `test_gained_pick_lands_late` pins that the preset really moves a prepared-line pick.
4. Every line now runs Time zero's pick once more on its raw record during preparation: one
   `|x|` row mean and one cropped copy per line, on the worker thread. No main-thread cost.
5. The spec §12 line was edited beyond the brief's §4 scope, to keep the spec self-consistent.

## Follow-up: the fairness tolerance is half a sample (coordinator, after review)

The coordinator accepted these calls: all ten campus lines, the hand-placed synthetic curve with its
guard, the §12 correction, and nothing in place of the `amp_square` assert. They asked for the
fairness tolerance to go from one sample to dt/2, so that GPS pins the fix too. Concern 1 above is
resolved by this change.

**Commit:** `4a7964c` test(slices): the first-break fairness check holds to half a sample

**What changed**
- `test_the_first_break_estimate_matches_time_zero_on_real_lines`:
  - The assertion is now `pytest.approx(zero, abs=dt / 2)`.
  - The docstring says why: both sides are the same pick on the same raw records, so they match
    exactly, and a pick a whole sample off is a different row.
  - It also says that the old prepared-line pick was one sample late on the four GPS lines, which
    the one-sample tolerance let through.
- Spec §9, the real-lines bullet: "within half a sample", with a line on why (a pick a whole sample
  off must fail; PF-1's prepared-line pick was one sample late on GPS).

**RED on c2adcae's engine.** I temporarily replaced `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`
with `git show c2adcae:…`, which brings back the old `median_first_break` with the square-root
branch. I ran with `PYTHONDONTWRITEBYTECODE=1`, then restored the file with `git checkout HEAD -- …`.
Result: `2 failed, 243 deselected`.

| survey | median first break | median line zero | gap |
|---|---|---|---|
| campus (10 lines) | −0.0433 | −0.4764 | +0.4331 ns = +2.00 samples |
| GPS (4 lines) | −1.3425 | −1.5590 | +0.2165 ns = +1.00 sample |

Each failure message is the tuple `(transform, first_break, zero, dt)`, for example GPS:
`AssertionError: ('amp_square', -1.342492327094078, -1.5590234398841858, 0.21653111279010773)`.
Both gaps exceed the dt/2 tolerance (0.1083 ns).

After the restore, `git status` showed only the test file modified, and
`git diff HEAD --quiet -- slices_engine.py packages/nsgeo-core/src` was clean. The experiment left
nothing behind.

**GREEN:** fairness test `2 passed, 243 deselected`. Both gaps are 0.0 ns, 0 samples.

**Runs**
- `test_plugin_slices_dock.py` in full: `245 passed in 82.62s`.
- `.venv/bin/ruff check . && .venv/bin/ruff format --check .`: `All checks passed!`,
  `233 files already formatted`.

**Files:**
- /home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-slices-clock-preset/packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py
- /home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-slices-clock-preset/docs/superpowers/specs/2026-11-16-nsgeo-slices-clock-preset-design.md

**Concerns:** none new.
