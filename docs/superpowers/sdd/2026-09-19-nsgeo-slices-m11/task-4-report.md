# Task 4 report: Live navigation — Position, Resolution and Display, and the slice on the map

## Summary

Implemented `slice_layer.py` (the live preview raster), the three remaining `SlicesDock` groups
(Position, Resolution, Display) and their navigation methods, and wired the layer into
`plugin.py`. Both tiers are green. Two genuine defects were found in the brief's own draft tests
and fixed (documented below), and one implementation bug of my own was caught only by actually
timing `refresh_slice()` against the synthetic fixture, per Step 10's instruction — not by
inspection.

## Test counts

| Tier | Before | After |
|---|---|---|
| core + pure (`./.venv`) | 541 passed, 2 skipped | 541 passed, 2 skipped (unchanged) |
| QGIS (`./.venv-qgis`) | 533 passed | 551 passed (+8 `SliceLayer`, +10 dock navigation) |

`ruff check .` and `ruff format --check .` are clean. The mypy command CI actually runs
(`nsgeo-core/src/nsgeo`, `lookup.py`, `view_transform.py`, `slices_plan.py`) is unaffected by this
task's files and still reports `Success: no issues found in 33 source files`.

## `refresh_slice()` timing at the default resolution

Measured directly on the `docked`-style synthetic fixture (3 lines, 60 traces, 512 samples,
range_ns=110.864), using the dock's own **seeded default** resolution (not a test override):
`cell=0.25 m, dz=0.2165 ns, z0=-11.086 ns, z1=99.561 ns` → `ZAxis(nz=512)`,
`CubeFrame(nx=24, ny=24)`, streaming mode.

50 calls after one warm-up call: **min 0.425 ms, median 0.436 ms, max 0.485 ms** — comfortably
single-digit milliseconds, as Step 10 asks.

## The four mutation checks

1. **Readout rebuilt from the request instead of `(k0, k1)`.** I implemented this two ways and
   report both, because the first (more literal) version produced a false pass against the
   test the brief names, and that gap is worth recording plainly rather than hiding it behind a
   "confirmed" checkbox:
   - **1a** — format the ns range directly from `slice_slider.value()`/`thickness_spin.value()`
     (`f"{top_ns:.1f}-{top_ns + thickness_spin.value():.1f} ns"`). Run against
     `test_the_readout_shrinks_with_the_window_at_the_end_of_the_axis` (the test Step 10 names):
     **PASSED** (false negative) — at the axis's last slice the real, clamped window collapses to
     one level, so its `lo == hi == 30.0`, which happens to equal the mutant's own `lo`
     (`top_ns = 30.0`) at that exact position; the substring check `f"{hi:.1f}" in text` then
     matches by coincidence. Run against `test_the_readout_states_the_window_that_was_actually_averaged`
     (not the named test, but the other readout test in the file): **FAILED** as expected —
     `AssertionError: assert ('7.0' in 'slice 3 / 10 · 7.0-11.0 ns' and '10.5' in 'slice 3 / 10 ·
     7.0-11.0 ns')`. So the mutant is caught by the suite as a whole, just not by the specific test
     Step 10 names, for this specific fixture and slider position.
   - **1b** — reconstruct `(k0, k1)` via `level_range`'s own ns→level formula but *without* its
     clamp (`SliceWindow(slider.value(), slider.value() + round(thickness/dz))`), then still call
     the real `window_label`. This is the more faithful rendering of "rebuilt from the request,
     not from what `level_range` returned": in the interior it reproduces the unclamped answer
     exactly (so it does *not* false-fail test 1), and at the axis end the reconstructed `k1`
     exceeds `nz`, so `window_label`/`window_times_ns` raise, `refresh_slice()`'s outer `except`
     catches it, and the readout is simply never updated for that tick. Run against the named
     test: **FAILED** as expected —
     `AssertionError: assert '30.0' in 'slice 1 / 9 · 2.0-9.5 ns'` (stale text from the previous,
     unclamped tick). Reverted; real code passes both tests (29/29).

2. **`radius_cells()` → `int(self.radius_spin.value())` (metres read as cells).** Ran the named
   test, `test_the_fill_radius_is_metres_and_survives_a_cell_size_change`: **PASSED** (false
   negative) against the brief's own draft. Root cause: this fixture's `GRID.default_spacing` is
   0.5, so the seeded default radius is `1.5 * 0.5 = 0.75` m — under one cell wide even before any
   conversion — so `int(0.75) == 0` both before and after the cell-size change, and the relative
   check `radius_cells() == approx(before * 2, abs=1)` reduces to `0 == approx(0, abs=1)`, which is
   trivially true. I re-ran the **entire** `test_plugin_slices_dock.py` and
   `test_plugin_slice_layer.py` (37 tests) with this exact mutant applied: **all 37 still passed**
   — no test in either file discriminates this literal mutant against this fixture.
   I strengthened the test with one added absolute assertion,
   `assert before == round(1.5 * GRID.default_spacing / 0.25)`, pinned to the exact conversion the
   fixture's own known constants (`radius=0.75`, `cell=0.25`) predict. Re-run against the mutant:
   **FAILED** — `AssertionError: assert 0 == 3`. Reverted the mutant; the strengthened test passes
   against real code (29/29).

3. **`display_limit()` → always `clip.limit(self._values)` (ignores the stretch combo).** Ran
   `test_a_shared_stretch_holds_one_limit_across_depth_and_per_slice_does_not`: **FAILED** as
   expected — `AssertionError: assert 70426.5859375 == 81738.3828125 ± 0.0817384`. Reverted;
   passes against real code.

4. **`build_shader` → `lo = -limit` unconditionally.** Ran
   `test_the_shader_spans_zero_to_limit_for_unipolar_data`: **FAILED** as expected —
   `AssertionError: assert -4.0 == 0.0 ± 1.0e-12`. This is spec §8's wasted-half-table defect, the
   reason the whole unipolar shader path exists. Reverted; passes against real code (8/8 in
   `test_plugin_slice_layer.py`).

All four mutants were reverted before committing; the working tree matches the description below.

## Bugs found and fixed (not in the brief, or wrong in the brief)

### 1. `test_nodata_renders_transparent`'s row assertions were reversed (brief's own test)

The brief's draft asserted `qAlpha(block.color(0, 0)) == 0` (row 0 transparent) and
`qAlpha(block.color(FRAME.ny - 1, 0)) == 255`. `_values()` sets grid-local row 0 (the frame's
*southern* edge) to NaN. Task 1's `to_north_up` — already shipped, already tested by its own
`test_north_up_puts_frame_row_zero_at_the_BOTTOM_of_the_raster`, whose docstring calls this "the
single most likely defect in this function" — reverses rows so a raster's row 0 is north: the
NaN row therefore lands at the raster's **last** row, not its first. The brief's assertions would
only pass if that north-up flip were silently undone. I fixed the test (swapped which row is
checked for which alpha) rather than touch `to_north_up`, which is correct and already covered
elsewhere. See `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_layer.py`.

### 2. `test_the_palette_offers_unipolar_tables_for_a_transformed_source` never selected a transform (brief's own test)

The brief's draft called `_ready(dock)` and immediately asserted the palette offered *unipolar*
tables — but `docked`'s preset ("p") is a plain `dewow` with no transform, and `transform_combo`
starts on its own first item, `"none"`. Without an explicit transform selection,
`engine.output_unipolar` is `False` right after `_ready()`, so the very first assertion failed
against **correct** code (`grey_black_high`/`grey_white_high`/`seismic` were offered, not the
unipolar set). Fixed by adding `dock.transform_combo.setCurrentText("amp_abs")` (the transform
this test file already uses elsewhere for exactly this purpose) and waiting for the re-preparation
it triggers, before the first assertion.

### 3. My own bug: `_seed_resolution_defaults` assumed a DZT's recorded window starts at `t0 = 0`

Not prescribed by the brief (z0/z1 defaults were left unspecified — see "Decisions" below), but
worth recording as a real implementation bug, caught only by Step 10's own instruction to
*measure* `refresh_slice()` rather than trust it by inspection: my first cut seeded
`z0_spin = 0.0` and `z1_spin = (n_samples - 1) * dt_ns`. The synthetic fixture's DZT header has
`position_ns = -11.086` (GSSI's own `rh_position` field — real SIR-4000 files commonly start
before time zero; `nsgeo.velocity`'s own module docstring gives exactly this example), and
`Radargram.from_profile` sets `t0_ns = header.position_ns`, not 0. Seeding `z0 = 0.0` therefore
asked for two-way-time levels before the line's own recording actually starts, which
`nsgeo.slices.binning.plan_line` correctly refuses with `CoverageError` the moment anything tries
to slice it. None of Step 5's given tests caught this, because every one of them runs through
`_ready()`, which explicitly overrides `z0_spin`/`z1_spin` to `2.0`/`30.0` — values that happen to
sit inside the fixture's real recording window regardless of what the *seeded* default was. It
surfaced only when I did exactly what Step 10 asks and measured `refresh_slice()` at the
**default** (unoverridden) resolution: every call raised `CoverageError`, which
`refresh_slice()`'s own guard correctly turned into a silent early return (`self._values = None`),
so the *symptom* was a suspiciously-fast, do-nothing timing loop rather than a visible crash —
exactly the kind of thing "run it, don't just inspect it" is for. Fixed by seeding
`z0_spin = header.position_ns` and `z1_spin = header.position_ns + (n_samples - 1) * dt_ns`.

## Decisions made where the brief was ambiguous (prose-only sections)

The brief gives Position/Resolution/Display in prose and leaves several concrete choices open.
Here is every call I made and why:

- **z0/z1 seeded defaults.** Not specified at all. I seed them from the first included line's own
  header (`position_ns` and `position_ns + (n_samples-1)*dt_ns` — the line's genuine native
  recording window), the same source `dz_spin`'s prescribed default already reads from. Seeding
  happens once, only when the selected grid actually changes (see below), not on every session
  signal.
- **When resolution defaults are (re-)seeded.** The brief prescribes the formulas but not the
  trigger. I seed `cell_spin`/`radius_spin`/`dz_spin`/`z0_spin`/`z1_spin` from inside
  `_sync_included()`'s existing "the selected grid actually changed" branch — the same moment (and
  same reasoning) `_included_is_default` already exists for: reseeding on every unrelated
  `presets_changed`/`lines_changed` would silently clobber a value the user picked for the grid
  that is still selected. One consequence, accepted rather than engineered around: if a dock is
  constructed before a grid has any lines yet, `dz_spin`/`z0_spin`/`z1_spin` are never re-seeded
  once lines later arrive under that same grid (unlike `_included`'s own re-seed-while-default
  behaviour) — untested by any given test, and a user can simply edit the three spin boxes by
  hand regardless.
- **Fallback constructor defaults, before any site is open.** `cell=0.5 m`, `dz=1.0 ns`,
  `z0=0.0 ns`, `z1=100.0 ns`, `radius=0.0 m` — never observed by any test (every fixture opens a
  site with a grid before constructing the dock), chosen only so the widgets are in a valid,
  non-crashing state (`Resolution.__post_init__` requires `cell>0`, `dz>0`, `t1>t0`) before any
  seeding can happen.
- **Spin box ranges/decimals.** Not specified. `cell_spin`/`radius_spin`: 0.01–5.0 m / 0.0–50.0 m,
  3 decimals. `dz_spin`: 0.001–100.0 ns, 4 decimals (needs sub-ns precision for a real header's
  native `dt_ns`). `z0_spin`/`z1_spin`: -1000.0–100000.0 ns, 3 decimals (negative allowed — see the
  `position_ns` bug above). `thickness_spin`/`step_spin`: 0.01–100000.0 ns, 2 decimals.
- **`velocity_label`'s content and styling.** The brief says only "smaller, dimmer font" and
  "provenance, not state." I reused `profile_dock.velocity_source()` and its exact wording
  (`f"v = {model.surface_velocity:.3f} m/ns ({source})"`) rather than invent a second format, keyed
  to the first line in `engine.provenance().line_keys` (the same line the engine's own recorded
  provenance actually resolved velocity against). Styling: 85% of the base point size,
  `color: palette(mid)` (theme-aware dim, rather than a hardcoded grey).
- **`legend_label`'s exact text.** The brief gives the two numeric halves
  (`"0 – {limit:.3g}"` / `"−{limit:.3g} – {limit:.3g}"`, using the literal en dash and minus sign
  characters shown) and says only "with the transform's name." I append
  `f"{base} ({transform_label})"`, where `transform_label` is `transform_combo.currentText() or
  "none"` — the same word already shown in the Source group's own combo, rather than introduce a
  second vocabulary for "no transform."
- **How Display-group changes reach the map.** `stretch_combo`, `palette_combo` and
  `coverage_check` don't change the values `refresh_slice()` fetches from the engine in every
  case (palette never does; stretch and coverage do), but all three are wired to call
  `refresh_slice()` (the one path, per the brief's own framing) rather than a narrower
  `slice_changed.emit()`, for uniformity — the extra `engine.slice_at()` call this causes for a
  palette-only change is a few hundred microseconds, not a per-tick cost.
- **`_on_prepared()` calls `refresh_slice()` and refills the palette combo.** Neither is stated
  in the brief. Without the `refresh_slice()` call, a source that finishes preparing while the
  Resolution controls have already applied a seeded default (the ordinary case: the ~120 ms
  debounce fires well before the ~0.9 s preparation completes) would leave the map and
  `current_values()` at `None` until the user happened to touch a control — visibly incomplete
  against "Task 4 is done when: dragging the depth slider redraws the map layer." The palette
  refill is required by the brief's own prose ("whenever the source is prepared"); `_on_prepared`
  is the one callback that actually fires at that moment.
- **`build_shader`'s deprecated `QgsMapLayer.setAbstract()` call.** The brief prescribes calling
  it explicitly; QGIS 3.44 reports it deprecated in favour of
  `serverProperties().setAbstract()`. I left it as prescribed rather than swap to the newer API,
  since I could not confirm `serverProperties()` exists on every QGIS version this plugin actually
  supports, and a cosmetic deprecation warning is a smaller risk than an `AttributeError` on an
  older build. Noted here rather than silently worked around.

## Files touched

- Created: `packages/nsgeo-qgis/nsgeo_qgis/slice_layer.py`
- Created: `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_layer.py`
- Modified: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (Position/Resolution/Display groups
  and their navigation methods; `slice_changed` signal)
- Modified: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (owns `SliceLayer`, connects
  `slice_changed`, disposes it in `unload()` outside-in before `layers.detach()`)
- Modified: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py` (ten new navigation tests,
  two of them corrected from the brief's draft as described above)

## Verification performed

- `./.venv/bin/python -m pytest packages/nsgeo-core packages/nsgeo-qgis/tests/pure -q -p no:xonsh`
  → 541 passed, 2 skipped (both before and after this task's changes).
- `QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p
  no:xonsh` → 533 passed (before) → 551 passed (after).
- `./.venv/bin/ruff check .` and `./.venv/bin/ruff format --check .` → clean.
- `./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`
  → `Success: no issues found in 33 source files` (this task's files are outside CI's mypy list
  and untouched by any of the files that are in it).
- Four mutants built, run against their named tests, confirmed to discriminate (with the two
  documented exceptions/strengthenings above), reverted, and the full suite re-confirmed green
  after every revert.
- `refresh_slice()` timed directly against the synthetic fixture at its seeded default resolution:
  0.425–0.485 ms over 50 calls.

---

## Fix round 1

Six Importants (no Criticals) and four promoted Minors from review. All addressed. Test counts
after this round: core+pure 541 passed/2 skipped (unchanged), QGIS 533 → 558 passed, **0
warnings** confirmed with `-W error::DeprecationWarning -W error::FutureWarning`.

### Important 1 — the readout had no metres

`_update_readout` called `window_label(z, window)` with no velocity, so the readout never showed
depth, only two-way time. Fixed by resolving the same `(key, velocity)` pair `velocity_label`
already needed (`_resolved_velocity()`, now shared by both) and passing it to `window_label`,
which already supports the ns-and-m format when given one. Extended
`test_the_readout_states_the_window_that_was_actually_averaged` to assert both units are present.
**Verified**: reverting to the two-argument call makes the strengthened assertion fail
(`AssertionError: assert ('0.28' in 'slice 3 / 10 · 7.0-10.5 ns')`); restored, passes.

### Important 2 — the coverage view was rendered against an amplitude limit (Ruling AB)

`display_limit()` ignored `coverage_check` and returned the shared (amplitude) limit even when
`_values` held trace counts. Fixed: `display_limit()` now measures its own limit from
`current_values()` (the greatest count on screen, floored at 1) whenever coverage is checked,
regardless of the stretch combo. `_update_legend_label()` states "N traces" instead of an
amplitude range with a transform name in that case. Also extended `display_unipolar()` (new
method) so the coverage view is drawn on a unipolar ramp even for a bipolar source, since a count
is never negative — `plugin.py`'s `_on_slice_changed` now calls `dock.display_unipolar()` instead
of reading `engine.output_unipolar` directly. Extended
`test_the_coverage_toggle_shows_trace_counts_not_amplitudes` to pin the limit itself. **Verified**:
reverting `display_limit()`'s coverage branch reproduces the reviewer's own cited magnitude exactly
(`assert 99634.7... == 15.0`); restored, passes.

### Important 3 — the preview stopped appearing after a site switch, or after external removal

Two related hazards in `SliceLayer.update()`'s create-vs-reuse check (`if self.layer is None`):
(a) `SiteLayers.detach()` (every "Open site...") removes the site's group *node* without deleting
the layer itself, so an already-live layer had no node anywhere to rejoin; (b)
`project.removeMapLayer(...)` on the layer (or any code path that deletes it) leaves
`sip.isdeleted(self.layer)` true while `self.layer` itself is still non-`None`, so `update()` kept
writing into and trying to use a dead wrapper forever. Fixed with two new helpers: `_layer_gone()`
(`None`, `sip.isdeleted`, or absent from `project.mapLayer(...)`) decides whether to rebuild, and
`_ensure_group_membership()` rejoins `layers.group` whenever the layer is alive/registered but has
no node in the *current* group — called both from the reuse branch and from `_create_layer()`
itself (so there is one implementation of "does this layer have a node," not two). Also hardened
`clear()`, which had the identical "leaves a dead reference behind" shape on its own exception
path — reset in a `finally` now, not only on the happy path. Two new tests:
`test_the_layer_rejoins_a_new_group_after_a_site_switch` and
`test_the_layer_is_recreated_after_being_removed_from_the_project`. **Verified**: reverting to the
brief's original `if self.layer is None` check fails both
(`assert None is not None` on `findLayer`, and `RuntimeError: wrapped C/C++ object ... has been
deleted` on the second); restored, both pass, and the full 10-test file is green.

### Important 4 — a stale slice stayed on the map, and `layer.clear()` was unreachable

`refresh_slice()`'s early return (source not prepared) set `_values = None` without emitting
`slice_changed`, the only signal `plugin._on_slice_changed` uses to `clear()` the map. Since
`set_source` empties the engine's lines synchronously (before any re-preparation starts), the map
kept showing the *previous* source's slice from the moment a combo changed, indefinitely if the
new source never prepares (e.g. a grid with no lines). One-line fix: emit `slice_changed` there
too. Added a genuine plugin-level test,
`test_a_source_change_clears_the_stale_slice_from_the_map` (`test_plugin_loads.py`), that builds a
real `NsgeoPlugin`, renders a slice, switches to an empty grid, and asserts
`plugin.slice_layer.layer is None`. **Verified**: reverting the emit fails exactly there
(`AssertionError: the stale slice from grid A must not still be on the map ...`); restored, passes.

Writing this test surfaced a **second, more consequential bug** than the one I'd already disclosed
in the original report (the accepted limitation that dz/z0/z1 defaults don't reseed once lines
arrive after the grid): the plugin-realistic construction order — dock built before any site
exists, then *new site → add grid → import lines* — is not a rare edge case, it is the ordinary
flow, and it left `dz_spin`/`z0_spin`/`z1_spin` stuck at their generic fallback values
(`dz=1.0, z0=0.0, z1=100.0`) forever, which is wrong on its face and also raises `CoverageError`
under exactly the same mechanism Important 6 already names. I closed this rather than route around
it in the test: `_seed_resolution_defaults` now only re-seeds `cell_spin`/`radius_spin` (grid-only);
a new `_seed_dz_z_defaults(grid_id)`, tracked by `_dz_z_seeded_for` so it runs at most once per
grid, is retried both on a genuine grid change and from `_sync_included`'s existing "still default"
branch — the same branch that already retries `_included` itself for the identical reason. This
was required for the Important-4 test to pass at all with a realistic construction order, not an
optional extra.

### Important 5 — 9 warnings in a tier that had 0 (Ruling AA)

`setAbstract()`: swapped to `serverProperties().setAbstract(...)` as instructed — confirmed
available since QGIS 3.22, well under this plugin's `qgisMinimumVersion=3.40`. All 8
`DeprecationWarning` occurrences gone.

The GDAL `FutureWarning`: wrapped `_write`'s body in `with gdal.ExceptionMgr(useExceptions=True):`
as instructed, and independently verified the other two claims hold — `gdal.GetUseExceptions()`
is `0` both before and after the block, and a failing `Create()` now raises `RuntimeError` into the
existing guard (confirmed directly: an impossible path raises `RuntimeError: Attempt to create new
tiff file ... failed`, state restored to `0` after).

**The third claim — that this wrap also silences the warning — does not hold in this environment.**
Checked directly, three ways: (1) a bare repro with `-W error::FutureWarning` still raises out of
`Create()` from inside the `with gdal.ExceptionMgr(useExceptions=True):` block; (2) the same repro
with `useExceptions=True` and the driver's `Create()` called explicitly, same result; (3)
`gdal._UserHasSpecifiedIfUsingExceptions()` reads `0` even *while inside* the block. Reading
`gdal.py`'s own source explains why: `ExceptionMgr.__enter__` calls the *local*
`_SetExceptionsLocal`, a different, thread/call-scoped flag from the one
`_WarnIfUserHasNotSpecifiedIfUsingExceptions()` actually checks — only the real, process-global
`gdal.UseExceptions()`/`DontUseExceptions()` (called via `_UseExceptions()`, a distinct C-level
function) sets that one. So `ExceptionMgr` genuinely cannot silence this warning without the
process-global call Ruling AA explicitly forbids.

Closed instead with a second, narrower scope: `with warnings.catch_warnings():
warnings.simplefilter("ignore", FutureWarning)` around the same block. This never touches any GDAL
exception-mode flag, local or global — it only affects Python's own `warnings` filter for the
duration of this one call — so it does not reintroduce the "changes the mode for the whole QGIS
process" problem Ruling AA is about; if anything it is *more* narrowly scoped than the instructed
fix, since it does not even touch GDAL's state. Verified with both
`-W error::DeprecationWarning` and `-W error::FutureWarning` together: 0 warnings, 37/37 (later
49/49, later the full 558) still pass.

### Important 6 — the bug found by timing had no regression test

Added `test_the_seeded_default_resolution_actually_slices`: prepares, `flush_debounce()` with no
`_ready()`-style overrides, asserts `z0_spin.value() == header.position_ns` and
`current_values() is not None`. **Verified**: reverting the seed back to `z0_spin.setValue(0.0)`
fails exactly as the original bug did
(`assert 0.0 == -11.086000442504883 ± 1.1e-05`); restored, passes. (This test also depends on the
Important-4 fallout fix above — without it, this fixture's own construction order, grid-then-lines
via signals fired inside the `docked` fixture, still happens to seed correctly because the fixture
adds grid *and* lines to the session before constructing the dock, so both signals are not what
exercises the gap; the plugin-level Important-4 test is what does.)

### Four promoted Minors (Ruling AC)

- **M1**: `test_the_readout_shrinks_with_the_window_at_the_end_of_the_axis` gained a second,
  parallel assertion (`f"{lo:.1f}-{hi:.1f} ns" in text`) alongside the original `f"{hi:.1f}" in
  text`. **Verified**: applying the naive "rebuild from slider + thickness" mutant, the *original*
  assertion still passes (the clamped window's `lo == hi == 30.0` coincides with the mutant's own
  `top_ns`), but the new one correctly fails
  (`assert '30.0-30.0 ns' in 'slice 12 / 12 · 30.0-38.0 ns'`); restored, both pass.
- **M2**: `_refill_palette_combo` now blocks `palette_combo`'s signals around `clear()`/
  `addItems()`/`setCurrentText()`. New test
  `test_a_preparation_triggers_exactly_one_rebuild_not_several` asserts exactly one
  `slice_changed` per preparation and no logged "colormap" error. **Verified**: unblocked, the test
  fails with `assert 3 == 1`; restored, passes.
- **M3**: `_apply_resolution` now blocks `slice_slider`'s signals around `setRange()`/`setValue()`,
  calling `refresh_slice()` explicitly exactly once afterward. New test
  `test_a_resolution_change_touching_dz_is_still_one_rebuild` (varies `dz`/`z0`/`z1`, which moves
  the slider's own clamped value, unlike the existing cell-only debounce test). **Verified**:
  unblocked, fails with `assert 2 == 1`; restored, passes, and the existing cell-only test still
  passes throughout (confirming it really was blind to this specific mutant, as M3 diagnosed).
- **M4**: `refresh_slice`'s exception handler now resets `_values`/`_window`, sets
  `readout` to `f"error: {exc}"`, and emits `slice_changed` before reporting through `error`. New
  test `test_an_error_during_refresh_clears_the_stale_slice_and_readout` forces a real
  `CoverageError` via an out-of-range `z1`. **Verified**: reverted to report-only, the test fails
  with `current_values()` still holding the previous tick's full array; restored, passes.

### Files touched in this round

- `packages/nsgeo-qgis/nsgeo_qgis/slice_layer.py` — Important 3, Important 5
- `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` — Important 1, 2, 4 (+ the dz/z0/z1 seeding
  fix it required), 6, M1–M4
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` — Important 2 (`display_unipolar()` wiring)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_layer.py` — Important 3 (2 new tests)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py` — Important 1, 2, 6, M1–M4 (2
  strengthened, 5 new tests)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py` — Important 4 (1 new plugin-level test)

### Verification performed

- `QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p
  no:xonsh -W error::DeprecationWarning -W error::FutureWarning` → **558 passed, 0 warnings**.
- `./.venv/bin/python -m pytest packages/nsgeo-core packages/nsgeo-qgis/tests/pure -q -p no:xonsh`
  → 541 passed, 2 skipped (unchanged).
- `./.venv/bin/ruff check .` and `./.venv/bin/ruff format --check .` → clean.
- The extended mypy command → `Success: no issues found in 33 source files` (unaffected; none of
  this round's files are in CI's mypy list).
- Every fix above independently built as a mutant, run against its named/new test, confirmed to
  fail with the exact numbers recorded above, reverted, and re-confirmed green.
