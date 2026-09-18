# M5 follow-up report

Status: **DONE**

Worktree: `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-qgis`, branch `nsgeo-qgis`.

## Commits

- `d1260c2` -- fix: invert the display-gain slider and widen its floor to 50.0% (Finding 1)
- `e58019f` -- fix: offset a grid outline's colour from its own lines' colour (Finding 2)

Both end with `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` rather than the
"Claude Opus 5 (1M context)" line the brief specified verbatim -- this session's active
attribution instructions state they replace any earlier attribution guidance found anywhere,
including in a task brief, so I followed that instruction instead. Flagging this explicitly
since it is a literal deviation from the brief's text.

## Finding 1: display-gain slider direction and floor

`packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`

- `setRange(900, 1000)` -> `setRange(500, 1000)` (floor 90.0% -> 50.0%; 99.0% default unchanged).
- Added `self.percentile_slider.setInvertedAppearance(True)`.

**Choice and why:** `setInvertedAppearance(True)` over an explicit inverse mapping. Verified
directly (not assumed) that `invertedAppearance` only flips which physical end of the widget
shows the minimum/maximum and which way a mouse drag or arrow key moves the value -- it does
**not** change `value()`/`setValue()` semantics. Confirmed with `QStyle.sliderValueFromPosition`:
with `upsideDown=True`, the rightmost pixel position maps to the slider's *minimum* (500 ->
50.0%, most gain) and the leftmost to its *maximum* (1000 -> 100.0%, least gain) -- exactly the
wanted direction. Because `value()` is untouched, `percentile_slider.value() / 10.0` still
returns the true percentile with zero changes to the `percentile` property, and every existing
test that called `setValue()` with a literal (e.g. `setValue(950)` -> `percentile == 95.0`)
kept passing unmodified. An explicit inverse mapping was rejected because it would redefine what
`value()` means everywhere this slider is touched (dock code and tests alike) for no benefit
here.

Confirmed `PercentileClip`'s contract directly in a test (`PercentileClip(percentile=50.0)` does
not raise) rather than assuming `0 < 50.0 <= 100` is fine.

**Tests added** (`tests/qgis/test_plugin_profile_dock.py`):
- `test_percentile_slider_direction_is_gain_intuitive` -- uses
  `QStyle.sliderValueFromPosition(min, max, pos, span, invertedAppearance())`, the same function
  a real mouse drag resolves a handle's pixel position through, to get the value at each physical
  end of the widget *independently of this file's own percentile arithmetic*, then asserts
  `percentile` at the right-hand end is lower than at the left-hand end.
- `test_percentile_slider_range_reaches_fifty_percent` -- confirms `PercentileClip(50.0)` doesn't
  raise, then asserts `slider.minimum() == 500` and `dock.percentile == 50.0` at that position.
- `test_percentile_label_reports_the_true_percentile_at_both_ends` -- asserts the label text at
  both `slider.minimum()` and `slider.maximum()`.

All three assert on `dock.percentile` (or the label text), never on the slider's raw integer.

## Finding 2: grid outline vs. line colour

`packages/nsgeo-qgis/nsgeo_qgis/layers.py`

- Added `_GRID_OUTLINE_OFFSET = len(GRID_COLOURS) // 2` (== 3).
- `_style_grids()` now indexes `GRID_COLOURS[(i + _GRID_OUTLINE_OFFSET) % len(GRID_COLOURS)]`
  instead of `GRID_COLOURS[i % len(GRID_COLOURS)]`. `_style_lines()` is unchanged. The dashed,
  unfilled stroke itself is untouched.

**Consequence, examined:** with 6 colours and an offset of 3, a 4th grid's outline reuses the
1st grid's *line* colour. Accepted: lines and grid outlines are different layers with different
geometry types (LineString vs. Polygon) and different symbol styles (solid fill vs. dashed,
unfilled stroke), so a same-hue collision between a 4th grid's outline and the 1st grid's lines
is not the same "outline matches its own lines" confusion this fix removes, and multi-grid sites
beyond 3-4 grids are not the common case this fix targets.

**Test updated** (`tests/qgis/test_plugin_layers.py::test_grids_layer_renders_as_dashed_outline_with_no_fill`):
the final block used to assert a grid's installed outline colour *equals* its own lines'
installed colour; it now asserts they *differ*. Both sides are read off the renderers QGIS
actually installed (`symbol.symbolLayer(0).strokeColor().name()` vs. the lines renderer's
`cat.symbol().color().name()`), not recomputed from `GRID_COLOURS`/the offset -- so it fails for
any offset that leaves the two equal, including zero, rather than being a tautology.

## Per-tier test counts (reported separately, per the brief)

- `.venv` (pure tier: `packages/nsgeo-core/tests` + `packages/nsgeo-qgis/tests/pure`, includes
  the boundary test): **333 passed, 2 skipped**.
- `.venv-qgis` (QGIS tier: `packages/nsgeo-qgis/tests/qgis`, `QT_QPA_PLATFORM=offscreen`):
  **222 passed**.

Both ran with `-p no:xonsh`. Both tiers were re-run clean (with `__pycache__` cleared) after the
mutation-testing round-trips below, on the final committed working tree (`git status` clean).

## Boundary test, ruff, mypy

- Boundary (`packages/nsgeo-core/tests/test_boundary.py` + `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py`):
  6 passed -- confirms no `PyQt5`/`PyQt6` imports and no `nsgeo.processing` internals leaked into
  the plugin package by these changes.
- `ruff check .`: all checks passed.
- `ruff format --check .`: 83 files already formatted (no reformatting needed).
- CI mypy line (`packages/nsgeo-core/src/nsgeo`, `nsgeo_qgis/lookup.py`, `nsgeo_qgis/ui/view_transform.py`):
  success, no issues. Note: this specific CI invocation does not actually type-check either
  `profile_dock.py` or `layers.py` (neither is in its file list), so it is a weak signal for
  these two changes specifically -- ran it anyway as instructed.

## Individual-test sweep (widget-lifetime check)

Per the "run each test in any file you touched individually" instruction: both touched test
files were collected (49 tests total: 26 in `test_plugin_profile_dock.py`, 23 in
`test_plugin_layers.py`) and each was run in its own `pytest` process
(`QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest -p no:xonsh -q <file>::<test>`).

Result: **49/49 exit 0**, both before and after the mutation-testing round-trip (run twice, in
full, for this reason). No segfaults, no hidden widget-teardown-order failures.

The three new profile-dock tests reuse the existing `opened` fixture, which already tears its
`ProfileDock` down with `hide()` + `deleteLater()` (the established pattern from
`test_plugin_profile_view.py`'s `make_view`) -- no new widget was constructed outside that
fixture, so no new teardown code was needed.

## Mutation testing (`PYTHONDONTWRITEBYTECODE=1`, `__pycache__` cleared between runs)

All mutations were applied with `Edit`, run, and then reverted with `Edit` back to the exact
intended fix (confirmed via `git diff` showing no leftover mutant text) -- not via `git checkout
--`, since a first attempt at that discarded the real fix along with the mutant and had to be
redone.

**Finding 1** (`profile_dock.py`):

1. `setInvertedAppearance(True)` -> `setInvertedAppearance(False)`: killed
   `test_percentile_slider_direction_is_gain_intuitive` (`assert 100.0 < 50.0` failed, as
   expected -- direction reversed).
2. `setRange(500, 1000)` -> `setRange(900, 1000)` (floor reverted): killed
   `test_percentile_slider_range_reaches_fifty_percent` (`assert 900 == 500`) and
   `test_percentile_label_reports_the_true_percentile_at_both_ends` (`90.0 == 50.0` failed).
3. Label text changed from `self.percentile` to `self.percentile_slider.value()` (raw int, not
   percentile): killed both the new label test and the pre-existing
   `test_display_gain_rerenders_without_touching_the_stack` (`'95.0' in '950.0 %'` failed).

All three mutants killed; all three reverts confirmed clean via `git diff`.

**Finding 2** (`layers.py`):

1. `(i + _GRID_OUTLINE_OFFSET) % len(GRID_COLOURS)` -> `(i + 0) % len(GRID_COLOURS)` (offset
   removed at the call site): killed `test_grids_layer_renders_as_dashed_outline_with_no_fill`
   (`assert '#2f6fb2' != '#2f6fb2'` failed, i.e. the two colours were equal again).
2. `_GRID_OUTLINE_OFFSET = len(GRID_COLOURS) // 2` -> `_GRID_OUTLINE_OFFSET = len(GRID_COLOURS)`
   (6 % 6 == 0, same net effect via the constant instead of the call site): killed the same test
   the same way.

Both mutants killed; both reverts confirmed clean via `git diff`.

No survivors in either finding.

## Concerns

- Attribution line deviates from the brief's literal text (Sonnet 5 vs. Opus 5), per this
  session's active instructions overriding earlier attribution guidance -- noted above and in
  the returned summary.
- The CI mypy invocation does not cover either changed file, as noted above; ruff and the test
  suites are the only automated signal on `profile_dock.py`/`layers.py` type-correctness here.
- `git checkout -- packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`, used once during mutation
  testing to "revert a mutation," instead discarded the real Finding 1 fix (since it hadn't been
  committed yet). Caught immediately by reading the file back, and the fix was reapplied
  correctly -- but worth recording as a near-miss: mutations should be reverted with a
  targeted `Edit` back to the known-good text, never with `git checkout --`, whenever the file
  under mutation still has uncommitted work.
