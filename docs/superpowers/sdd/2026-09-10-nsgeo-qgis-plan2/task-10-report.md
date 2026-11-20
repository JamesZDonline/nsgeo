# Task 10 report: grid dialog with three georeferencing tabs and the digitise map tool

## What was implemented

- `packages/nsgeo-qgis/nsgeo_qgis/maptools/__init__.py` — docstring-only package marker, per the brief.
- `packages/nsgeo-qgis/nsgeo_qgis/maptools/digitise_tool.py` — `DigitiseGridTool(QgsMapToolEmitPoint)`: two canvas clicks (origin, then a point along +Y) emit `points_picked(QgsPointXY, QgsPointXY)`; a `QgsRubberBand` shows the first pick; `reset()`/`deactivate()` clear state. Implemented verbatim from the brief — no defects found in this file.
- `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py` — `GridDialog(QDialog)` with the three tabs (GNSS corners, digitise on map, from polygon) and the shared result fields, exactly the widget names/signals the brief specifies (`corner_table`, `fit_corners()`, `residual_label`, `layer_combo`, `feature_picker`, `origin_combo`, `plus_y_combo`, `use_polygon()`, `digitise_requested`, `set_digitised()`, `id_edit`, `crs_widget`, `origin_x/y`, `azimuth`, `size_x/y`, `spacing`, `velocity`, `ok_button`, `result_grid()`). Deviates from the brief's reference code in four places (all fixes, detailed below).
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` — `open_grid_dialog()` replaced (grid lookup, suggested velocity from header dielectric, dialog exec, add/replace), and a new `_start_digitise()` wiring the map tool to the dialog. Deviates from the brief's reference code in three places (all fixes, detailed below).
- `packages/nsgeo-qgis/tests/qgis/conftest.py` — extended the modal guard: `QDialog.exec()` is now forbidden by default (raises `AssertionError`) alongside the existing `QMessageBox`/`QFileDialog` entries, and a new `drive_dialog` fixture is the opt-in path (symmetric to `answer_modal`, but takes a driver callback since a dialog needs its fields set and buttons clicked, not a single fixed return value).
- `packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py` — the brief's six tests verbatim, plus 11 more covering the carry-forward defect, the failure-path audit, and the plugin wiring (17 total... see file; final count is 20 tests).

## Both tiers' results

```
.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q
→ 313 passed, 2 skipped   (unchanged from the pre-task baseline)

.venv/bin/ruff check .        → All checks passed!
.venv/bin/ruff format --check . → 70 files already formatted

.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
→ Success: no issues found in 23 source files

QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
→ 111 passed (91 pre-existing + 20 new), exit code 0
  (run twice for stability confidence; both times 111 passed, exit 0)
```

A benign, pre-existing-class stderr artifact appears only when the new digitise-tool tests run: `QBasicTimer::start: QBasicTimer can only be used with threads started with QThread`, printed by Qt's internal focus/timer machinery when a `QgsMapCanvas` that is never actually shown (no window manager under `offscreen`) receives focus-related calls. It does not affect the exit code or any assertion, and it is the same code path implicated in the segfault investigation below (see "the digitise dialogs' cleanup"), just the non-fatal half of it. I chose not to chase silencing it further — it is stderr noise, not a failure, and QGIS's own C++ internals are out of reach.

## TDD Evidence

**RED** — `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py -q`:
```
ImportError while importing test module '.../test_plugin_grid_dialog.py'.
...
E   ModuleNotFoundError: No module named 'nsgeo_qgis.maptools'
=========================== short test summary info ============================
ERROR packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py
```
Matches the brief's expected failure exactly (Step 2).

**GREEN** — after implementing `maptools/digitise_tool.py` and `ui/grid_dialog.py` and wiring `plugin.py`:
```
QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py -q -p no:xonsh
....................                                                     [100%]
20 passed in ~3s
```

Additional RED/GREEN cycles for the failure-path fixes (each was written failing against the brief's reference code first, confirmed, then fixed):
- `test_fit_corners_reports_bad_numeric_entry_without_crashing` — RED against the brief's `fit_corners()` (which calls `_corner_arrays()` *outside* its own try/except): the test raised `ValueError: could not convert string to float: 'not-a-number'` uncaught. GREEN after moving `_corner_arrays()` inside the try block.
- `test_set_digitised_rejects_coincident_points` — RED against the brief's `set_digitised()` (no `pytest.raises(ValueError)` was ever raised; `azimuth` silently became `0.0`). GREEN after adding the `math.hypot(dx, dy) == 0.0` guard.
- `test_use_polygon_reports_an_empty_geometry_without_crashing` — RED against the brief's `use_polygon()`: `IndexError: list index out of range` uncaught (confirmed via a standalone script that `QgsGeometry.fromPolygonXY([]).isNull()` is `False` while `.asPolygon()` is `[]`). GREEN after wrapping the ring-extraction in its own try/except.
- `test_corner_tab_residual_caption_distinguishes_mirrored_from_not_square` — RED against the brief's caption text (still said "nonzero = grid not square" even for a clearly mirrored/swapped correspondence, residual_rms ≈ 8.5 m in the constructed case). GREEN after rewording the caption to name both possibilities.
- `test_open_grid_dialog_reports_a_stale_grid_id_without_crashing` — RED against the brief's `open_grid_dialog()` (`self.session.grid(grid_id)` raised `KeyError` straight out of a signal-connected slot). GREEN after wrapping the lookup in try/except.
- `test_digitise_flow_recovers_from_coincident_points` — RED against the brief's `_start_digitise()`/`done()` (an uncaught `ValueError` from the now-guarded `set_digitised()` would leave the map tool stuck active and the dialog hidden, per the standing signal/slot hazard). GREEN after wrapping `done()`'s body in try/except/finally.

## Numeric geometry verification (all three tabs)

Ground truth throughout: `TRUE = Grid("A", (500.0, 700.0), 30.0, 5.0, 11.0, "EPSG:32616", 0.5)` — a **rotated** (30° azimuth, non-axis-aligned) 5×11 m grid — with `LOCAL = [[0,0],[5,0],[5,11],[0,11]]` and `TRUE.to_world(LOCAL)` for the world coordinates.

1. **GNSS corners tab** (`test_corner_fit_fills_origin_azimuth_and_sizes`): fills the four corner rows with `(local, world)` pairs from `TRUE`, calls `fit_corners()`, asserts `origin_x/y == 500.0/700.0`, `azimuth == 30.0`, `size_x/y == 5.0/11.0`, residual `"0.000"`. Passes.
2. **Digitise tab** (`test_digitised_points_set_origin_and_azimuth`): `set_digitised((500, 700), (500 + 5·sin(30°), 700 + 5·cos(30°)))` → asserts origin `(500, 700)` and `azimuth == 30.0`. Passes. (This is the rotated case for this tab.)
3. **Polygon tab, winding A** (`test_polygon_tab_reads_a_selected_feature`): ring built as `TRUE.to_world(LOCAL)` (vertex order origin, +X, +X+Y, +Y). With the brief's default `plus_y_combo` index 3, `use_polygon()` yields `azimuth == 30.0`, `size_y == 11.0`. Passes.
4. **Polygon tab, winding B — the carry-forward defect** (`test_polygon_tab_rejects_the_mirrored_default_pick_and_the_other_corner_fixes_it`): same rectangle, ring built as `TRUE.to_world(LOCAL[[0,3,2,1]])` (reversed winding). Verified by hand computation (`cross(pts[x]-pts[o], pts[y]-pts[o])`) that with the brief's default `plus_y_combo` index 3, the pick is mirrored for *this* winding (cross ≈ -54.99), so `corners_from_polygon` must raise; confirmed the dialog shows the "mirrored" message and leaves `azimuth`/`size_x`/`size_y` at their untouched defaults (0.0, 10.0, 10.0) — no silent wrong answer. Then `plus_y_combo.setCurrentIndex(1)` (the *other* corner adjacent to the origin) and `use_polygon()` again recovers the exact same true grid: `azimuth == 30.0`, `size_x == 5.0`, `size_y == 11.0`. This is the required "both digitising windings" coverage.
5. **Corner tab, mirrored-input residual** (`test_corner_tab_residual_caption_distinguishes_mirrored_from_not_square`): swapped world[1]/world[3] (a +X/+Y row-swap blunder) against the same true grid; confirmed numerically (standalone script) `fit_grid_from_corners` returns `residual_rms ≈ 8.544 m`, `azimuth ≈ 60.0°` — a large, structurally wrong residual, not the small imprecision-only case the brief's caption implied. Asserted the caption text is not `"0.000"` and mentions "mirror".

All five cases were independently verified by hand/script computation (not just by reading test assertions) before being encoded as pytest assertions, per the task's numeric-verification requirement.

## Failure-path audit (deliberate pass over every slot and new line)

| Site | What could fail | Who catches it | User-visible outcome |
|---|---|---|---|
| `GridDialog.fit_corners()` (`QPushButton.clicked`) | `_corner_arrays()`'s `float(v)` on a hand-typed non-numeric cell; `fit_grid_from_corners`'s `ValueError` (too few points, shape mismatch) | Own try/except (now covers both — the brief's reference left `_corner_arrays()` outside the guard) | `residual_label` shows the exception text; fields untouched |
| `GridDialog.use_polygon()` (`QPushButton.clicked`) | No layer/feature selected; empty (zero-ring) geometry → `IndexError`; `corners_from_polygon`/`fit_grid_from_corners` `ValueError` (mirrored pick, non-adjacent +Y, degenerate polygon) | Own try/except, in three stages (selection guard, ring-extraction guard, corners/fit guard) | `polygon_status` shows a specific message per failure mode; fields untouched on any failure |
| `GridDialog.set_digitised()` | Two coincident points → `atan2(0,0)` would silently give `azimuth = 0.0` | Raises `ValueError` instead of swallowing it | Caller (`plugin.py`'s `done()`) must catch it — see below |
| `GridDialog._validate()` (text/value-changed slots) | None identified — pure boolean logic over already-valid widget state | n/a | n/a |
| `GridDialog.result_grid()` | `Grid(...)` has no `__post_init__` validation; `crs_widget.crs().authid()` could theoretically be `""` if no CRS was ever set (not exercised by any test — project CRS or explicit selection covers the normal path) | Not guarded here; would surface later as a `ValueError`/refusal in `SiteLayers`'s CRS handling (Task 8) when `grids_changed` fires | Noted as a residual concern below, not fixed (out of this task's mandated scope) |
| `NsgeoPlugin.open_grid_dialog()` (`QAction.triggered` / dock signal) | `self.session.grid(grid_id)` `KeyError` for a stale id (grid removed between context-menu build and click) | New try/except around the lookup | `message()` (message bar + log), dialog never opens, no crash |
| `NsgeoPlugin.open_grid_dialog()` — velocity suggestion | `VelocityModel.from_dielectric(epsr)` `ValueError` for a corrupt/non-positive header `epsr` | New try/except; cosmetic-only, does not block the dialog | `message()` warning; dialog opens unseeded instead of never opening |
| `NsgeoPlugin.open_grid_dialog()` — commit | `session.add_grid`/`replace_grid` `ValueError`/`KeyError` (duplicate id, id vanished) | Existing try/except (from the brief, unchanged — already correct) | `message()` critical |
| `NsgeoPlugin._start_digitise().done()` (slot on `tool.points_picked`, a `pyqtSignal`) | Any exception from `set_digitised()` (now including the coincident-points case) or `crs_widget.setCrs(canvas.mapSettings().destinationCrs())` | New try/except/finally: exception is caught and reported; `finally` unconditionally releases the map tool and restores the dialog | `message()` critical; map tool is never left stuck active with the dialog hidden (this is exactly the standing architectural hazard the task calls out — verified with a dedicated test, `test_digitise_flow_recovers_from_coincident_points`) |
| `DigitiseGridTool._on_click()` (slot on `canvasClicked`) | None identified — pure coordinate bookkeeping, no exception-raising calls | n/a | n/a |

**Residual concern (not fixed, flagged only):** `result_grid()` does not gate `ok_button` on a valid CRS the way it gates on id/velocity/sizes; an all-invalid `QgsProjectionSelectionWidget` state would produce `crs=""`. In practice the widget always starts from the project CRS or an explicit user selection, so this was not reachable in any test and I judged it out of the brief's mandated scope to add new gating logic beyond what the brief specifies — flagging it for a future task rather than silently expanding scope.

## What was added to the modal guard

`tests/qgis/conftest.py`'s `_no_unhandled_modals` (autouse) now also forbids `QDialog.exec()` by default, raising `AssertionError` — same raise-by-default shape as the existing `QMessageBox`/`QFileDialog` entries, so a test that triggers a real dialog's modal loop by accident fails fast instead of hanging under `QT_QPA_PLATFORM=offscreen`.

A new `drive_dialog` fixture is the opt-in path, structurally parallel to `answer_modal` but shaped differently because `QDialog.exec()` is an *instance* method with no single fixed return value: `drive_dialog(QDialog, "exec", driver)` makes the next `QDialog.exec()` call run `driver(dialog_instance)` (set fields, click buttons, `accept()`/`reject()`) and then return `dialog_instance.result()`, appending each dialog instance to the returned list. Used throughout the new plugin-wiring tests to drive `GridDialog` exactly as a user would.

## A genuine segfault found and fixed (test infrastructure, not application-correctness)

While adding the plugin-wiring tests for the digitise flow, running two such tests in the same pytest session reproducibly **segfaulted during interpreter shutdown** (well after pytest reported all tests passing, so `pytest`'s own exit code came back 0 but the process then crashed with SIGSEGV — a real risk for CI, which checks the process exit code). I did not treat "pytest says passed" as sufficient and chased this down with `gdb`:

```
Thread 1 received signal SIGSEGV ... in libQt5Core.so.5
#1 QApplication::focusChanged(QWidget*, QWidget*)
#2 QWidget::clearFocus()
#3 QWidget::~QWidget()
... (nested QObjectPrivate::deleteChildren() / ~QWidget() frames) ...
#16 Py_FinalizeEx
```

Root cause: `GridDialog`'s own signal wiring (`self.digitise_button.clicked.connect(self.digitise_requested.emit)` inside the widget, and `dialog.digitise_requested.connect(lambda: self._start_digitise(dialog))` / `tool.points_picked.connect(done)` in `plugin.py`, where the lambda/closure captures the very object whose signal it is connected to) forms reference cycles that PyQt's `QObject` wrapper does not expose to Python's cyclic garbage collector — confirmed by instrumenting the `qgis_app` fixture teardown: an explicit `gc.collect()` right before `exitQgis()` did **not** free the dialogs (`gc.get_objects()` still showed them, with their full widget trees, immediately afterward). They only get destroyed by CPython's own shutdown-time cleanup, by which point `qgis_app`'s `exitQgis()` has already destroyed the `QApplication` — so their destructors touch a gone `QApplication` singleton and crash.

Two other hypotheses were tested and **ruled out** empirically (documented here so the next person doesn't re-chase them): `QgsFeaturePickerWidget`'s background gatherer thread (fixed by 20× `processEvents()`+`sleep` pumping in isolation, but the crash persisted through pytest regardless — this was a red herring, likely coincidental from the earlier experiment's changed timing); and `QgsMapCanvas`'s parallel rendering (`setParallelRenderingEnabled(False)` "fixed" a standalone script but made no difference once retested against the real crash reproduction through pytest — also a red herring). Neither is in the final diff.

The actual fix, applied only to the two tests that go through the digitise flow (the only ones that create a `DigitiseGridTool`/`QgsRubberBand`/`canvas.setMapTool()` — confirmed by bisection that plain corner/polygon-tab `GridDialog`s leak the same way but never crash): explicitly `dialog.deleteLater()` + `qgis_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)` before the test ends (helper `_dispose()` in the test file), destroying the C++ object — and hence releasing its connections — while the `QApplication` is still alive. Verified stable across many repeated runs (individually and as part of the full 111-test suite, twice).

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/maptools/__init__.py` (new)
- `packages/nsgeo-qgis/nsgeo_qgis/maptools/digitise_tool.py` (new)
- `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py` (new)
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (modified: `open_grid_dialog`, new `_start_digitise`, imports)
- `packages/nsgeo-qgis/tests/qgis/conftest.py` (modified: `_no_unhandled_modals` extended, new `drive_dialog` fixture)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py` (new, 20 tests)

## Self-review findings

- Re-read every new/changed line against "what happens if this fails" — this is what produced the four dialog-level fixes and three plugin-level fixes listed above; none were present in my first draft (transcribed from the brief), all were found on the audit pass.
- Checked test independence: every polygon-tab test cleans up its `QgsProject` layer registration in a `finally` block (pre-existing convention from Task 8/9's tests), and the two digitise-flow tests explicitly dispose their dialogs — no test depends on another's leftover project/session state.
- Checked for restating-implementation-as-test smells: each new test asserts an *outcome* (a value, a message, a state transition) never a call count or internal method invocation, except `len(calls) == 1` in the digitise-flow test, which is asserting the dialog was actually exercised once (an integration-test sanity check, not restating internals).
- Verified the boundary guard (`test_plugin_boundary.py`, unchanged) still passes: neither new file imports `nsgeo.processing`, `PyQt5`/`PyQt6` directly, or anything outside the allowed surface.
- Verified `nsgeo_qgis/maptools/__init__.py` is docstring-only, matching `ui/__init__.py`'s existing pattern.
- Test module basename (`test_plugin_grid_dialog.py`) is unique across the repo (grepped).
- No real DZT files are needed by any new test (none touch line data), so nothing new to skip.

## Concerns

- The `result_grid()` CRS-gating gap noted in the failure-path audit table (not fixed; flagged for a later task).
- The benign `QBasicTimer::start` stderr warning from Qt's internal focus machinery when the digitise tests run a real (never-shown) `QgsMapCanvas` under `offscreen` — does not affect any test result or exit code, left undiagnosed further per the time/value tradeoff.
- The segfault investigation cost significant time chasing two red herrings (`QgsFeaturePickerWidget` threading, `QgsMapCanvas` parallel rendering) before finding the actual cause with `gdb`. I would use `gdb`'s backtrace much earlier next time rather than bisecting by guesswork first.

## Deviations from the brief's reference code (with reasoning)

1. **`fit_corners()`'s residual caption** — brief said "(nonzero = grid not square)"; changed to name both causes (imprecise corners *or* a mirrored local/world correspondence), per the task's explicit carry-forward instruction that this caption "mis-explains that case."
2. **`fit_corners()` guards `_corner_arrays()`** — the brief's reference left this call outside the try/except; moved inside, since a non-numeric hand-typed cell raised uncaught out of a `clicked` slot.
3. **`use_polygon()` guards the empty-geometry `IndexError`** — new try/except around ring extraction; the brief's reference let a zero-ring (but non-null) geometry raise uncaught.
4. **`set_digitised()` rejects coincident points** — the brief's reference silently produced `azimuth = 0.0` for two identical clicks; now raises `ValueError`, caught by `plugin.py`'s `done()`.
5. **`open_grid_dialog()` guards the grid-id lookup and the velocity suggestion** — both were unguarded in the brief's reference; a stale id or a bad header would have raised out of a signal-connected slot.
6. **`_start_digitise()`'s `done()` wrapped in try/except/finally** — the brief's reference had no guard at all; combined with fix #4, an uncaught exception would have left the map tool stuck active and the dialog invisible.
7. **Modal guard extended for `QDialog.exec()`, plus new `drive_dialog` fixture** — required by the task brief's "Modal guard" section, not present in the reference code (which only showed the dialog/tool implementations, not the test infrastructure).

All seven are described above with reasoning at the point they're introduced; none weaken any assertion — each either adds a new guard or corrects a message, without touching the widget names/signals/signatures the brief mandates as the public API.

---

# Fix round 1

Spec review passed. Six findings (four Important, two promoted from Minor). All six addressed below, with numeric before/after for Findings 1 and 5, and the Finding 3 contract (three runs, `_dispose` fully removed) confirmed.

## Correction to the original report's root-cause story (Finding 3)

The reviewer is right and my original report was wrong: **a parentless `GridDialog`, with or without a self-capturing lambda, is collected by `gc.collect()` fine.** I mis-attributed the segfault to PyQt signal connections being invisible to Python's cyclic collector. The actual cause is simpler: `dialog` is parented to `self.iface.mainWindow()` (a live, non-cyclic C++ ownership edge), and nothing ever deleted either the dialog or its parent, so `dialog` was never eligible for collection at all — it stayed alive, with its whole widget tree, for the life of the QGIS/test session. The `_dispose()` I added to two tests was masking that by explicitly deleting *those* dialogs; every other `GridDialog` constructed elsewhere in the suite kept leaking the same way (confirmed by instrumenting `qgis_app`'s teardown to list surviving `QWidget`s — dozens showed up, not two), it just never happened to coincide with a live `QgsMapCanvas`/`QgsRubberBand` at shutdown time. Fixed at the actual cause now (`plugin.py`, not the tests).

## Finding 1 — geographic-CRS polygon (Important)

Fixed in `use_polygon()` (`grid_dialog.py`): refuse outright when `layer.crs().isGeographic()`, before touching the geometry at all.

**Numeric reproduction (before the fix), matching the reviewer's own report:**
```
true grid:  Grid("B", (500000.0, 3985000.0), 30.0, 200.0, 80.0, "EPSG:32633", 1.0)
ring:       true grid's world corners, transformed EPSG:32633 -> EPSG:4326 (~36.0 N)
corners_from_polygon(ring_degrees, origin=0, plus_y=3):
    corners.size_x  = 0.0021229508...   (rounds to 0.00 at this dialog's 2 decimals)
    corners.size_y  = 0.0007662889...   (same)
fit_grid_from_corners(corners.local, corners.world):
    azimuth       = 26.31057...   (true 30.0 -- 3.69 degrees wrong)
    residual_rms  = 6.451693e-05
    caption:        "rigid fit RMS 0.000 m"
```
This reproduces the reviewer's figures almost exactly (they reported 26.327 degrees / 0.000064 m from their own chosen point near lat 36; the small difference is only in which UTM zone/point was picked). **After the fix:** `use_polygon()` returns immediately with `polygon_status` naming the problem ("geographic (degrees, not metres)"), `azimuth`/`size_x`/`size_y` stay at their untouched defaults, and `crs_widget` is not overwritten. New test: `test_use_polygon_refuses_a_geographic_crs_layer` (embeds the same reproduction and asserts the refusal).

## Finding 2 — `crs=""` for a valid custom CRS (Important)

Fixed in two places in `grid_dialog.py`:
- `_validate()` now also requires `bool(self.crs_widget.crs().authid())`, wired to a new `self.crs_widget.crsChanged.connect(self._validate)` connection so it re-evaluates when the CRS changes.
- `__init__`'s CRS seeding: previously `if project_crs.isValid(): self.crs_widget.setCrs(project_crs)` (leaving `crs_widget` at its own blank/invalid default otherwise); now falls back to `QgsCoordinateReferenceSystem("EPSG:4326")` when the project has none. This is a genuine, considered addition beyond the literal ask, not incidental: without it, the brief's own verbatim test (`test_ok_is_blocked_until_id_and_velocity_are_set`, which never touches `crs_widget` at all) would break, because a bare `QgsApplication` in this test harness has an *invalid* project CRS (`QgsProject.instance().crs().isValid() == False`), so `crs_widget` would otherwise start with no authid and OK could never enable. The fallback is a placeholder in the same spirit as `size_x`/`size_y` defaulting to 10.0 — a valid, non-blocking value the user is expected to override — and it is immediately superseded the moment anything else sets a CRS (the project's own, `_prefill()`, `use_polygon()`, or the user's own pick), so it does not weaken the guard against Finding 2's actual case (a user-chosen valid-but-authid-less CRS, e.g. the custom oblique Mercator below, is still refused).

New test: `test_ok_is_blocked_by_a_valid_crs_with_no_authid` — builds `QgsCoordinateReferenceSystem.fromProj("+proj=omerc ...")`, confirms it is `isValid() == True` and `authid() == ""` (the exact case), and shows the OK button disables the moment it's selected and re-enables on a normal EPSG choice.

Also fixed the test that ratified the bad state: `test_open_grid_dialog_accepts_and_adds_a_new_grid` never picked a CRS and asserted nothing about `grid.crs`; it now asserts `grid.crs == "EPSG:4326"` (the fallback, since this is the bare test harness) rather than silently accepting `""`. `test_digitise_flow_through_the_plugin_fills_and_restores_the_dialog` had the same gap through a different path (`done()` overwrites `crs_widget` from `canvas.mapSettings().destinationCrs()`, which is also invalid on this bare canvas) — the driver now sets an explicit valid CRS before `accept()`, and the test asserts `grid.crs == "EPSG:32616"`. Both are noted as fixes I made beyond the two findings named verbatim in the review, because they are the same defect class the review flagged and were one line each to close.

## Finding 3 — segfault fixed at the cause (Important)

`open_grid_dialog()`'s dialog construction, `exec()`, and result handling are now wrapped in `try: ... finally: dialog.deleteLater()`. `deleteLater()` only *schedules* deletion (via the event loop), so `dialog` is still fully usable for `result_grid()` and `add_grid`/`replace_grid` before the `finally` runs.

**Contract check — `_dispose` fully removed from the test file (confirmed: `grep -c _dispose` → 0), three consecutive runs of just this file:**
```
run 1: 28 passed in 3.78s, exit 0
run 2: 28 passed in 3.75s, exit 0
run 3: 28 passed in 3.80s, exit 0
```
And the full QGIS tier, twice: `119 passed`, exit 0 both times (91 pre-existing + 28 in this file).

Bonus: this fix also silenced the `QBasicTimer::start` stderr warning entirely — 0 occurrences across all six runs above (previously 8 per run). The reviewer asked for this only if cheap; it came for free from fixing Finding 3 at the actual cause rather than papering over it per-test.

## Finding 4 — no abort path; a right-click completes the pick (Important)

`DigitiseGridTool` (`digitise_tool.py`) gains a `cancelled` signal and a `_finished` flag:
- `_on_click()` now checks the button first: `Qt.MouseButton.RightButton` calls `self.canvas().unsetMapTool(self)` and returns, never touching `_origin` or emitting `points_picked` — regardless of whether zero or one clicks have happened so far.
- `deactivate()` emits `cancelled` whenever it runs *without* a completed pick (`_finished` still `False`) — which covers both the right-click-abort path above (routed through `unsetMapTool`) and a user switching to an entirely different map tool (`QgsMapCanvas.setMapTool()` calls the outgoing tool's `deactivate()` the same way). `_finished` is set immediately before emitting `cancelled` to guard against a hypothetical second `deactivate()` call, and is set before `points_picked.emit()` on the normal path so a *successful* pick's own `deactivate()` (triggered by `plugin.py`'s `canvas.unsetMapTool(tool)` in `done()`) does not also fire `cancelled`.
- `plugin.py`'s `_start_digitise()` factors dialog restoration into a shared `show_dialog()` closure, connected to both `done()`'s `finally` (which also releases the map tool) and directly to `tool.cancelled` (which does not need to release the tool again — by the time `cancelled` fires, the canvas has already moved off it).

I deliberately avoided re-entrant `canvas.unsetMapTool()` calls from inside the `cancelled` handler (only `show_dialog()`, no canvas call) after reasoning through the call stack: `cancelled` already fires from *inside* `deactivate()`, itself already inside an in-progress `unsetMapTool()`/`setMapTool()` call, so calling `unsetMapTool()` again from the handler risked a re-entrant/recursive call into QGIS's own canvas machinery. Untested against QGIS's C++ internals directly (that ordering isn't documented), so I designed around the risk instead of relying on it being safe.

New tests: two directly against `DigitiseGridTool` (`test_digitise_tool_right_click_before_any_pick_cancels`, `test_digitise_tool_right_click_after_origin_cancels_not_completes`) and two through the full plugin wiring (`test_digitise_flow_right_click_restores_the_dialog_without_a_pick`, `test_digitise_flow_switching_map_tools_restores_the_dialog`, the latter using a real `QgsMapToolPan` to simulate the user switching tools).

## Finding 5 — sizes from `max()`, not the extent (Important, promoted)

Fixed in `fit_corners()`: `local[:, i].max()` → `local[:, i].max() - local[:, i].min()`.

**Numeric before/after** (control points not anchored at the local origin — true grid `Grid("B", (300.0, 900.0), 200.0, 20.0, 7.5, "EPSG:32616", 0.5)`, surveyed as local `(100, 50)..(120, 57.5)` instead of `(0, 0)..(20, 7.5)`):
```
fit.origin       = (300.0, 899.9999999999999)   true (300.0, 900.0)
fit.azimuth      = 200.00000000000006           true 200.0
fit.residual_rms = 2.4613922385709617e-14       -> caption "0.000 m"

BEFORE (max()):        size_x = 120.0,  size_y = 57.5    (true 20.0 / 7.5)
AFTER  (max() - min()): size_x = 20.0,   size_y = 7.5
```
New test: `test_corner_fit_sizes_control_points_not_anchored_at_the_local_origin`, embedding this exact reproduction (rotated ground truth, azimuth 200 degrees) and asserting origin/azimuth/size all come back correct with the fixed computation.

## Finding 6 — velocity seeding from the header dielectric, untested (Important, promoted)

New test: `test_open_grid_dialog_seeds_velocity_from_the_header_dielectric`. Builds a real site with one synthetic-DZT line (`epsr = 14.0`, matching the real files per the task's own context), no grids, and drives `plugin.open_grid_dialog(None)` — asserts `dialog.velocity.value() == pytest.approx(VelocityModel.from_dielectric(14.0).surface_velocity, abs=5e-5)` (the `abs` tolerance matches the velocity field's own 4-decimal `QDoubleSpinBox` precision, since `setValue()` itself rounds) and that `velocity_hint` says "from the header dielectric". This exercises `open_grid_dialog()`'s `suggestion = VelocityModel.from_dielectric(lines[0].header.epsr).surface_velocity` path for the first time.

## Both tiers, re-run after all six fixes

```
.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q
→ 313 passed, 2 skipped

.venv/bin/ruff check .          → All checks passed!
.venv/bin/ruff format --check . → 70 files already formatted
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
→ Success: no issues found in 23 source files

QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py -q -p no:xonsh
→ 28 passed, exit 0 (20 from Task 10 + 8 new this round)

QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
→ 119 passed, exit 0 (91 pre-existing + 28 in this file)
```

## Files changed (this round)

- `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py` (Findings 1, 2, 5)
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (Findings 3, 4)
- `packages/nsgeo-qgis/nsgeo_qgis/maptools/digitise_tool.py` (Finding 4)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py` (all six; `_dispose` and its two call sites removed per Finding 3)

## Not touched (per "Not in scope")

Left alone exactly as listed: the raw core message on Fit with an empty table; `QMessageBox.critical`/`getSaveFileName`/`QInputDialog`/`QMenu.exec` still outside the modal guard; the polygon-empty-geometry test's non-blank-only assertion; `reset()` untested; digitised grids keeping default 10x10 sizes; `result_grid()` not raising for velocity 0.

## Concerns carried forward

- The digitise flow's `done()` also does `dialog.crs_widget.setCrs(canvas.mapSettings().destinationCrs())` unconditionally, with no `isGeographic()` check — the same defect *class* as Finding 1, on a different path (canvas CRS rather than a chosen layer's CRS). Not flagged by name in this round's findings or its "not in scope" list, so left alone; flagging it explicitly for the next round rather than silently expanding this round's scope.
- The `EPSG:4326` fallback in `GridDialog.__init__` means a grid created via any tab without ever touching the CRS field (id/velocity/sizes only) now defaults to a geographic CRS backing metric origin/size fields — same unit mismatch as Finding 1's family, but for the placeholder/default state rather than an active wrong choice, and consistent with how `origin`/`azimuth`/`size` already default to non-real placeholder values the user is expected to override. Noting it rather than silently deciding it's fine.

---

# Fix round 2

Round 1 closed F1/F2/F3/F4/F6 properly (verified by the reviewer at the C++ level: `QApplication.allWidgets()` for F3, exact `cancelled`/`points_picked` emission counts for F4). Four findings this round: one on round 1's own F5 fix, one on a concern I flagged myself (confirmed worse than F1), one promoted (silent CRS refusal), one new regression from round 1's dialog-disposal fix. All four addressed below.

## Finding 1 — F5's fix moved the wrong answer, didn't remove it (Important)

`fit_corners()`'s `size_x`/`size_y` fix (round 1) used `local[:, i].max() - local[:, i].min()`, correct on its own, but left `fit.origin` untouched. `fit.origin` is the world position of local `(0, 0)` *in the control points' own local frame* — not the same point as local `(0, 0)` of the fitted grid's own canonical `[0, size_x] x [0, size_y]` rectangle when the control points are offset from it. Fixed by translating `fit.origin` along the fitted axes by `local.min(axis=0)`:

```python
mins = local.min(axis=0)
a = math.radians(fit.azimuth)
y_hat = np.array([math.sin(a), math.cos(a)])
x_hat = np.array([math.cos(a), -math.sin(a)])
origin = np.asarray(fit.origin) + mins[0] * x_hat + mins[1] * y_hat
```

**Distance table, reproducing the reviewer's own scenario** (true grid `Grid("B", (5000.0, 8000.0), 200.0, 37.5, 12.25, "EPSG:32616", 0.5)`, control points surveyed at local `(100, 50)..(137.5, 62.25)` instead of the grid's own canonical `(0, 0)..(37.5, 12.25)`):

| | size written | distance from each of the 4 surveyed corners |
|---|---|---|
| before F5 (`max()`) | 137.5 × 62.25 | 111.80 / 50.00 / 0.00 / 100.00 m |
| after F5 alone (`max()-min()`) | 37.5 × 12.25 | 111.80 m on all four |
| **complete fix (this round)** | 37.5 × 12.25 | **0.00 m on all four** (≈1.3e-12, floating-point zero) |

All three rows reproduced exactly via script before writing the fix, and the "before"/"after F5 alone" rows match the reviewer's own figures precisely.

**Test rebuilt**, not just re-asserted: `test_corner_fit_places_control_points_not_anchored_at_the_local_origin` no longer declares a self-inconsistent "true grid" (round 1's version computed world coordinates via `to_world()` of the *offset* local coordinates directly, which silently made the declared origin correct only because it was circularly defined that way — exactly the pattern the reviewer flagged). The new version derives the true grid's world corners from its own canonical rectangle (`to_world(canonical)`, `canonical = [[0,0],[size_x,0],[size_x,size_y],[0,size_y]]`), keeps the local coordinates entered in the dialog offset (as recorded in the field), and — the substantive check — reconstructs a `Grid` from the dialog's own fitted origin/azimuth/size and asserts `Grid.to_world(canonical) - world` distances are `0.00 m` (to `1e-6`) on all four corners, not just that the origin/azimuth/size scalars match some expected tuple.

## Finding 2 — one CRS guard instead of three per-path checks (Important; confirms round 1's Concern 1)

My own flagged Concern 1 (the digitise flow's `done()` adopting `canvas.mapSettings().destinationCrs()` unconditionally) is confirmed real and numerically worse than round 1's Finding 1: a geographic canvas CRS (EPSG:4326, QGIS's own default for a new project) on a true 200 m / 30° digitised line at ~36N gives azimuth 35.398° (5.398° wrong, vs Finding 1's 3.69°), 18.8 m cross-track at 200 m / 94 m at 1 km, and OK enables with the grid saved and no warning — while the outline itself spans ~1113 km, which *looks* self-announcing but actually hides the azimuth error rather than revealing it (correcting the size fields afterward does not fix the azimuth).

My flagged Concern 2 (the `EPSG:4326` fallback introduced to satisfy the brief's own OK-gating test) is resolved differently than I framed it: `QgsProject.instance().crs()` is invalid only in this bare `QgsApplication` test harness, so that fallback branch is never reached in real QGIS desktop and changes nothing there — the brief's test was never the problem. But the underlying hazard (a geographic CRS silently accepted) is real, and it arrives through the pre-existing project-CRS adoption line regardless of the fallback.

**Fix:** one guard, in `_validate()`, rather than a third per-path check:
```python
crs = self.crs_widget.crs()
...
ok = (... and bool(crs.authid()) and not crs.isGeographic())
```
This covers every route that can ever populate `crs_widget`, because they all funnel through the same widget:

1. **The fallback** (`GridDialog.__init__`, when the project has no CRS of its own) — changed from `EPSG:4326` to `EPSG:3857`: `EPSG:4326` has an authid but *is* geographic, so under this round's stricter guard it would have blocked the brief's own `test_ok_is_blocked_until_id_and_velocity_are_set` from ever enabling OK. `EPSG:3857` (Web Mercator) is valid, projected, and has an authid — a placeholder in the same non-real-answer spirit as `size_x`/`size_y` defaulting to `10.0`, now actually usable by the guard.
2. **The project's own CRS**, when it is geographic (QGIS's out-of-the-box default).
3. **The digitise flow's canvas CRS** (Concern 1, `plugin.py`'s `done()`).
4. **A CRS the user picks by hand** in `crs_widget` directly — geographic, or merely missing an authority code.

All four verified in one test, `test_crs_guard_blocks_every_route_to_a_bad_crs`: constructs the fallback and asserts it passes; temporarily sets `QgsProject.instance()`'s CRS to `EPSG:4326` and constructs a fresh dialog to prove route 2 is blocked (restored in a `finally`); sets `crs_widget` directly to `EPSG:4326` to stand in for route 3 (the mechanism is identical — a `setCrs()` call on the same widget — so this is a faithful proxy without needing a live canvas); and sets both an authid-less custom CRS and a geographic one by hand for route 4, then recovers with a normal EPSG CRS.

**`use_polygon()`'s own `isGeographic()` check (round 1, Finding 1) is kept, deliberately, not removed.** `_validate()`'s new guard makes it redundant for *preventing a save* — but not for preventing the dialog from ever computing and displaying a convincing-but-wrong fit in the first place. Without it, a geographic-CRS polygon would still show a "correct-looking" `azimuth`/`size_x`/`size_y` and a `residual_rms` in `polygon_status` before `_validate()` silently disabled OK — exactly the "success message on a wrong frame" pattern this plan keeps re-shipping, just moved one step later. Documented at the point it's kept in `use_polygon()`'s own comment.

For the record, per the reviewer: the corner tab is not a third instance needing its own check — fitting local metres against degree world coordinates is rejected by the rigid no-scale fit itself (`residual_rms` on the order of tens of metres), so it announces itself through the existing residual caption rather than needing a dedicated CRS check.

## Finding 3 — the CRS refusal is silent, promoted (Important)

Added `self.crs_hint` (a `QLabel` next to `crs_widget`), driven entirely from `_validate()`: `"needs an authority code (e.g. EPSG) -- pick a registered CRS"` when `authid()` is empty, `"must be a projected CRS in metres, not geographic (degrees)"` when geographic, cleared otherwise. Because it's wired to the same single guard from Finding 2, it explains the refusal regardless of *which* of the four routes produced the bad CRS — including the worst case the reviewer verified: a polygon layer in a valid, non-geographic, authid-less custom CRS. `use_polygon()`'s own check doesn't catch that case (correctly: the fit itself is genuinely right, azimuth exact, `residual_rms` genuinely `0.000`), so it proceeds, reports success in `polygon_status`, and overwrites `crs_widget` with the authid-less CRS — silently disabling OK before this fix. New test `test_use_polygon_success_still_gets_a_visible_crs_refusal` drives exactly this: asserts the fit is correct (`azimuth == 30.0`, `"0.000"` in `polygon_status`) *and* that OK is disabled *and* `crs_hint` says why ("authority").

## Finding 4 — a live map tool can outlive the dialog (Minor, new from round 1's own fix)

`open_grid_dialog()`'s `finally` (round 1, Finding 3) deletes `dialog` but never released a map tool `_start_digitise` may have left active — reachable when `dialog.exec()` returns (accept, reject, or otherwise) while a digitise pick is mid-flight and neither `done()` nor the tool's `cancelled` signal ever fired (e.g. the dialog closed directly, bypassing the pick's own completion or right-click-abort path). The stranded `DigitiseGridTool` then calls back into `show_dialog()` against the now-deleted `dialog` on its next interaction — `RuntimeError: wrapped C/C++ object of type GridDialog has been deleted`, swallowed to stderr by the signal-connection hazard, or partially caught (the tool release itself still succeeds) and pushed into the message bar for the two-click-completion variant. No crash either way, and this could not happen before round 1's `deleteLater()` fix (the dialog was never deleted then) — a straightforward consequence of fixing Finding 3, not a pre-existing bug.

**Fix**, in the same `finally` as the `deleteLater()` call, and running *before* it (while `dialog` is still alive, so the tool's own `cancelled` -> `show_dialog()` path runs cleanly instead of racing the deletion):
```python
canvas = self.iface.mapCanvas()
if isinstance(canvas.mapTool(), DigitiseGridTool):
    canvas.unsetMapTool(canvas.mapTool())
```
New test `test_open_grid_dialog_releases_a_stranded_map_tool_on_close`: clicks "Pick on map" (arming the tool), then `dialog.reject()`s immediately without ever clicking the canvas or aborting — asserts `open_grid_dialog()` does not raise and `canvas.mapTool() is None` afterward.

## Both tiers, re-run after all four fixes

```
.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q
→ 313 passed, 2 skipped

.venv/bin/ruff check .          → All checks passed!
.venv/bin/ruff format --check . → 70 files already formatted
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
→ Success: no issues found in 23 source files

QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py -q -p no:xonsh
→ 30 passed, exit 0 (three consecutive runs, all 30 passed / exit 0)

QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
→ 121 passed, exit 0 (91 pre-existing + 30 in this file)
```

## Files changed (this round)

- `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py` (Findings 1, 2, 3)
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (Finding 4)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py` (all four; the round-1 CRS-fallback test's expected value changed from `EPSG:4326` to `EPSG:3857`, and the round-1 F5 test was rebuilt rather than patched)

## Not touched (per "Not in scope")

Left alone exactly as listed: only `RightButton` aborts the digitise pick (a middle-button click still counts as a pick — noted, not fixed, and likely shadowed by the canvas's own middle-button panning in real QGIS); `_start_digitise` creates a fresh `DigitiseGridTool` parented to the canvas on every "Pick on map" click without ever deleting the *tool* object itself (as opposed to unsetting it as the active map tool, which this round's Finding 4 fix does do) — this accumulates the same way the dialogs used to before round 1's fix, and is worth a fix in a future round rather than silently folding into this one.

## Concerns carried forward

- The `_start_digitise`-created `DigitiseGridTool` object itself is never explicitly deleted (only unset as the canvas's active tool) — flagged above per the "not in scope" note, restating it here since it's the same *shape* of leak round 1's Finding 3 was, just smaller (a lightweight `QgsMapToolEmitPoint` + `QgsRubberBand`, not a full dialog widget tree) and explicitly deferred rather than silently fixed.
- `EPSG:3857`, like `EPSG:4326` before it, is still a placeholder chosen only to be valid, projected, and registered — not a claim that it's the "right" CRS for any real grid. This is unavoidable for a fallback that must satisfy the guard without knowing anything about the actual site, and matches how `origin`/`azimuth`/`size` already default to non-real placeholders the user is expected to override.

---

# Fix round 3

All four round-2 findings verified hard by the reviewer (F1 re-derived on the reviewer's own truth across five configurations including negative local minima and a 3-point fit; F4 probed on five exit paths including accept-mid-pick). One finding remains, bigger than either of us thought: the CRS guard was necessary but not sufficient. Two more (minor, new breakage from round 2's own fixes) round out this round.

## Finding 1 — the CRS guard is necessary but not sufficient (Important)

`isGeographic()` (rounds 1-2) catches degrees. It does not catch metres that are not *ground* metres. Two whole families slip through: **EPSG:3857 (Web Mercator)** reports `mapUnits() == Meters` and `isGeographic() == False`, yet its scale factor grows without bound away from the equator; **US survey feet zones** (e.g. EPSG:2264) are not geographic and have a valid authid, but a foot is not a metre.

### Reproduced end to end (polygon tab, EPSG:3857 read against a true UTM 16N grid)

True grid: `Grid("B", (770250.359, 3993660.078), 30.0, 30.0, 20.0, "EPSG:32616", 0.5)` (lat ≈ 36.05N). Ring transformed EPSG:32616 → EPSG:3857 and read through the polygon tab exactly as `use_polygon()` does (`corners_from_polygon` + `fit_grid_from_corners`):

```
fit.azimuth = 31.810°           (bearing distorted less than scale, but still off)
residual_rms = 0.0405 m         -> "rigid fit RMS 0.041 m" -- looks like a fine fit
size_x, size_y = 37.089, 24.775  (true 30.0, 20.0 -- 23.6%/23.9% too large)
```

A residual under 5 cm on a grid whose declared size is 23-24% larger than true, both dimensions — the same "success message on a wrong frame" pattern as rounds 1 and 2, on a third path. (My own reproduction's exact figures — 0.0405 m / 37.09×24.77 m — differ slightly from the reviewer's own 0.039 m / 37.12×24.8 m, expected: different origins were chosen; both demonstrate the identical failure mode from the same root cause.) At `fit.origin` in EPSG:3857 units, my own local-scale check (below) measures **19.41%** — matching the reviewer's own 19.4% at lat 36 almost exactly.

### The fix, in four parts (as specified)

1. **`crs.mapUnits() == Qgis.DistanceUnit.Meters`, not `not crs.isGeographic()`.** Strictly subsumes the geographic check (`Degrees != Meters`) and closes the feet family for free — `EPSG:2264`'s `mapUnits()` is `29` (`Qgis.DistanceUnit.SurveyFeet`; `QgsUnitTypes.toString(...)` gives `"feet (US survey)"`), refused outright regardless of origin, with hint `"must use metres, not feet (US survey)"`.
2. **A `QgsDistanceArea` local scale-factor check**, `_crs_scale_error()`: at the grid's own origin, transform the origin and four cardinal 1000 m-offset points to EPSG:4326, measure the ellipsoidal (WGS84) distance between each pair with `QgsDistanceArea.measureLine()`, and take `max|ground/1000 - 1|` over the four directions (catches anisotropic distortion, not just one axis). Thresholds `CRS_SCALE_WARN = 0.001` (0.1%) and `CRS_SCALE_REFUSE = 0.02` (~2%): warn (but do not block) in between, since refusing at 1% would false-refuse legitimate Albers/LAEA work.
3. **Measured at the grid's own origin, gated on that origin having actually been set, skipped on any failure.** `origin_x`/`origin_y.valueChanged` are now connected to `_validate()` (they were not wired to it at all before this round). `_crs_scale_error()` returns `None` (skip, don't refuse) when the origin is still `(0.0, 0.0)` (the untouched placeholder) — measuring at `(0, 0)` itself was verified to give false positives (EPSG:5070 at its own CRS origin: kE/kN 0.981/1.019; EPSG:3035: 1.038/0.981) — and also returns `None` on any transform/measurement exception, broadly caught.
4. **No fallback CRS.** Rounds 1 and 2 each fell back to a placeholder (`EPSG:4326`, then `EPSG:3857`) when the project had none, reasoning it harmless since a real project's CRS is (almost) never invalid. Round 3: `EPSG:3857` turned out to be exactly the failure this dialog exists to prevent — a CRS chosen as a placeholder only because it passed the guard. `GridDialog.__init__` now leaves `crs_widget` unset when the project has none; the existing `authid()` branch refuses it with the same visible hint. `test_ok_is_blocked_until_id_and_velocity_are_set` (the brief's own test) now sets a CRS explicitly before its final assertion — the one-line change anticipated in the finding, and (per the reviewer) a more faithful test of what a real user's flow requires.

### Verification table (calibration script, `QgsDistanceArea` WGS84 ellipsoid, 1000 m baseline, max over 4 cardinal directions) — embedded in the test as `test_crs_scale_guard_accepts_correct_uses_and_refuses_mismatches`

| CRS / origin | max\|k−1\| | verdict |
|---|---|---|
| UTM 16N, own central meridian | 0.040% | **accept**, no hint |
| UTM 16N, near a zone edge | 0.050% | **accept**, no hint |
| British National Grid | 0.031% | **accept**, no hint |
| NC state plane, metres (32119) | 0.008% | **accept**, no hint |
| Albers CONUS (5070), northern edge | 1.25% | accept, **warn** ("distorted") |
| ETRS89 LAEA (3035), far corner | 0.60% | accept, **warn** ("distorted") |
| US survey feet (2264), any origin | n/a (units) | **refuse** ("must use metres, not feet") |
| EPSG:3857 at lat 36 | 19.36% | **refuse** ("off by 19.4%...") |
| EPSG:3857 at lat 43 | 27.02% | **refuse** ("off by 27.0%...") |

All nine rows are asserted in the test with the exact coordinates used to produce these figures. The accept/warn split matches the reviewer's own false-positive budget (Albers/LAEA up to ~1.26% used correctly; refusing at 1% would have false-refused them); the refuse rows match the reviewer's EPSG:3857 figures (19.4%/27.0%) almost exactly.

## Finding 2 — the CRS selector collapsed behind its own hint (Minor, new from round 2's own fix)

`crs_widget` and `crs_hint` sharing a `QHBoxLayout` row (the way `velocity_hint` shares with `velocity`) squeezed `crs_widget` to unreadable widths once `crs_hint` had a full sentence to show — measured before this fix: `crs_widget` 108 px (`velocity_hint`'s text is always short, so this was never a problem for that row). Undercuts Finding 3's whole purpose (a message telling the user to change the CRS, while hiding what CRS is even selected).

**Fix:** `crs_hint` gets its own `form.addRow("", self.crs_hint)` below `crs_widget`'s row, not a shared `QHBoxLayout`, with `setWordWrap(True)`. Measured after: `crs_widget` 477 px (full field-column width) with a long hint showing simultaneously, wrapped. New test `test_crs_widget_stays_usable_when_the_hint_is_showing`.

## Finding 3 — the tool release re-shows the dialog for one event-loop turn (Minor, new from round 2's own fix)

`open_grid_dialog()`'s `finally` (round 2, Finding 4's fix) releases a still-active digitise tool via `canvas.unsetMapTool(tool)`, which runs `tool.deactivate()` → `cancelled` → `show_dialog()` (`dialog.show()`/`raise_()`) unconditionally. `dialog.deleteLater()` only *schedules* deletion, so if the dialog was already accepted or rejected mid-pick, this briefly re-shows it before its own deletion actually runs.

**Fix:** `tool.blockSignals(True)` immediately before `canvas.unsetMapTool(tool)` in that same `finally` block — `deactivate()`'s own cleanup (releasing the rubber band, clearing state) still runs, but the `cancelled` emission is suppressed, so `show_dialog()` never fires. New test `test_open_grid_dialog_releases_a_stranded_tool_on_accept_without_flashing_the_dialog`: accepts the dialog directly mid-pick (id/velocity/CRS all set validly first, so the accept is genuine, not just gating-bypass) and asserts both `canvas.mapTool() is None` (released) and `calls[0].isHidden()` (never re-shown) immediately after `open_grid_dialog()` returns, before any further event-loop processing could destroy the dialog.

## Both tiers, re-run after all fixes

```
.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q
→ 313 passed, 2 skipped

.venv/bin/ruff check .          → All checks passed!
.venv/bin/ruff format --check . → 70 files already formatted
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
→ Success: no issues found in 23 source files

QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py -q -p no:xonsh
→ 33 passed, exit 0 (three consecutive runs, all 33 passed / exit 0)

QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
→ 124 passed, exit 0 (91 pre-existing + 33 in this file)
```

## Files changed (this round)

- `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py` (Findings 1, 2)
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (Finding 3)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py` (all three; every test that relied on the round-1/2 fallback CRS, or asserted the old `"geographic"` wording, updated to match — see below)

## Tests updated for the fallback's removal (not new findings, consequences of Finding 1 part 4)

- `test_ok_is_blocked_until_id_and_velocity_are_set` — now sets a CRS explicitly (per the finding's own instruction).
- `test_open_grid_dialog_accepts_and_adds_a_new_grid` — its driver now picks a CRS explicitly (previously relied on the `EPSG:3857`/`EPSG:4326` fallback and asserted `grid.crs == "EPSG:3857"`).
- `test_use_polygon_success_still_gets_a_visible_crs_refusal` — dropped an `assert d.ok_button.isEnabled()` that depended on the removed fallback (the test's actual point — a genuinely-correct fit still getting a visible CRS refusal — is unaffected).
- `test_crs_guard_blocks_every_route_to_a_bad_crs` — dropped its "fallback" route entirely (nothing left to test there) and updated two assertions from `"geographic" in ...` to `"metres" in ...`, matching the new units-based message for a geographic CRS.

## Self-review: are the many now-realistic origin values (UTM-scale coordinates, not `(500, 700)`-style placeholders) safe everywhere `_validate()` now runs on origin change?

Checked every existing test that sets `origin_x`/`origin_y` to a non-`(0, 0)` value while a `Meters`-unit CRS is also set (now triggering `_crs_scale_error()` on every such change, via the new `valueChanged` connections): confirmed by direct experiment that `QgsCoordinateTransform`/`QgsDistanceArea` do not raise for small or unrealistic UTM-style coordinates (e.g. `(1.0, 2.0)`, `(500.0, 700.0)`) — they simply return some (possibly large, possibly WARN/REFUSE-tripping) scale-error value, never an exception, since Transverse Mercator's own formula is defined everywhere. None of the affected tests assert on `ok_button`/`crs_hint` in those cases, so no existing assertion was put at risk; this was checked directly rather than assumed.

## Concerns carried forward

- All concerns from rounds 1 and 2 remain as stated (the `DigitiseGridTool` object itself never explicitly deleted; the size/velocity refusals still being silent; the CRS-guard test's session-global project-CRS mutation, restored in a `finally`).
- `CRS_SCALE_WARN`/`CRS_SCALE_REFUSE` are calibrated against the specific CRS families measured (UTM, BNG, state plane, Albers, LAEA, Mercator, an abused UTM zone) — a CRS family not represented in that calibration could in principle sit on either side of either threshold differently than expected. Not something I can rule out in general; flagging it rather than claiming the two constants are universally correct.

---

# Fix round 4

Round 3 confirmed clean — every edge branch held up under direct probing (the `(0,0)` gate, `origin_x == 0` with a real `origin_y`, transform failure at `(1e8, 1e8)`, re-validation in both directions, `_validate`'s 0.059 ms cost). But the review surfaced something that meant Task 10 was not done: the digitise-on-map path — one of the three headline georeferencing routes this task exists to deliver — could not actually work under a real Qt event loop. The coordinator overruled the reviewer's suggestion to split this into its own task and required it fixed here. One Critical finding and two Minor, all addressed below.

## Finding 1 (Critical) — "Digitise on map" could not produce a grid under a real event loop

**Verified independently before touching anything** (not just trusting the finding):
```python
d = QDialog()
QTimer.singleShot(0, d.hide)
result = d.exec()
# result == 0 (Rejected), d.isVisible() == False
```
`QDialog.exec()`'s event loop is application-modal: it terminates the instant the dialog is hidden, from any cause — not only its own Ok/Cancel. `_start_digitise()`'s `dialog.hide()` (called from a slot that only fires while `exec()` is running, to let the user reach the canvas) ends the modal loop in the same turn, before a single click can land. This was in the original `136d90f` commit, not a fix-round regression, and it went undetected through three review rounds because `drive_dialog` — used in all 22 `test_plugin_grid_dialog.py` calls that opened the dialog through the plugin — fakes `exec()` by calling the driver directly, never running Qt's real event loop, so it cannot observe an event loop terminating.

### The fix: GridDialog is now modeless

`open_grid_dialog()` calls `dialog.show()` instead of `dialog.exec()`. The lifecycle that used to run synchronously after a blocking `exec()` call (commit the result to the session, release a still-active digitise tool, `deleteLater()` the dialog) now lives in a `finished(result)` handler connected to `dialog.finished`, which fires exactly once for accept, reject, or the window closed any other way. A new `self._grid_dialog` attribute tracks the currently-open dialog (or `None`): `open_grid_dialog()` raises/activates the existing one instead of opening a second (modeless means the toolbar stays clickable while one is open, unlike the old modal block — a second dialog would fight the first over the canvas's one map tool during a digitise pick), and `unload()` now closes it explicitly (`.close()` runs the same `finished()`-based cleanup via `reject()`) since `unload()` can itself now run while a dialog is still open — impossible under the old modal design.

`_start_digitise()`'s own `dialog.hide()`/`show()` calls are unchanged — they are now *safe* specifically because there is no `exec()` loop left for `hide()` to terminate.

### Test: proven without monkeypatching `QDialog.exec` at all

`test_digitise_flow_through_the_plugin_fills_and_restores_the_dialog` — the test that exposed the bug — now uses a new `_open(plugin, grid_id=None)` helper (calls `open_grid_dialog()`, returns `plugin._grid_dialog`) instead of `drive_dialog`. No `QDialog.exec` monkeypatching anywhere: `open_grid_dialog()` genuinely calls `show()`, and the test drives the real dialog exactly as a user would — two real `canvasClicked` emissions, then `accept()`.

**RED, confirmed by temporarily reverting `plugin.py` to the pre-round-4 `open_grid_dialog()`/`_start_digitise()` (from commit `9f905a3`) and re-running just this test:**
```
FAILED test_digitise_flow_through_the_plugin_fills_and_restores_the_dialog
    dialog = _open(plugin)
        plugin.open_grid_dialog(grid_id)
    if dialog.exec() != QDialog.DialogCode.Accepted:
AssertionError: unexpected modal: QDialog.exec()
```
The test fails immediately and loudly — caught by the *existing* modal guard (`_no_unhandled_modals`), not a hang, since the test never opts in with `drive_dialog`. This is the self-defending property the contract asked for: if `open_grid_dialog()` ever reverts to `exec()`, this test fails at the assertion, not by timing out.

**GREEN, with the round-4 `plugin.py` restored:**
```
QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py -q -p no:xonsh
37 passed
```

All 11 plugin-wiring tests that previously used `drive_dialog` were rewritten to use `_open()` instead (dropping the monkeypatched-`exec()` driver-callback structure entirely, since there is no longer a blocking call to drive around): `test_open_grid_dialog_accepts_and_adds_a_new_grid`, `_cancel_leaves_the_session_untouched`, `_reports_a_duplicate_id_through_the_message_bar`, `_edits_an_existing_grid`, `test_digitise_flow_recovers_from_coincident_points`, `_through_the_plugin_fills_and_restores_the_dialog`, `_right_click_restores_the_dialog_without_a_pick`, `_switching_map_tools_restores_the_dialog`, `test_open_grid_dialog_releases_a_stranded_map_tool_on_close`, `_releases_a_stranded_tool_on_accept_without_flashing_the_dialog`, `test_open_grid_dialog_seeds_velocity_from_the_header_dielectric`. One new test, `test_open_grid_dialog_does_not_open_a_second_dialog_while_one_is_open`, covers the new single-dialog-at-a-time guard. `drive_dialog` itself is kept in `conftest.py` (per the contract, "alongside `drive_dialog`") for any future genuinely-modal dialog (e.g. if Task 11's import dialog turns out to need one); it is simply no longer used by any grid-dialog test, since production code no longer calls `exec()` for `GridDialog`.

### Re-verified: dialog disposal (round 1, F3) and map-tool release (round 2, F4) on every exit path, after the lifecycle rewrite

Six scenarios probed directly with `QApplication.allWidgets()` (filtered to `GridDialog`) and `canvas.mapTool()`, after `gc.collect()` + `sendPostedEvents(None, QEvent.Type.DeferredDelete)`:

| exit path | surviving `GridDialog`s | map tool released |
|---|---|---|
| rejected | 0 | yes |
| accepted | 0 | yes |
| closed via `.close()` | 0 | yes |
| accepted mid-digitise-pick (tool still active) | 0 | yes |
| rejected mid-digitise-pick (tool still active) | 0 | yes |
| **`unload()` while the dialog is still open** (new possibility under a modeless dialog) | 0 | yes |

All six clean, including the genuinely new scenario (unload while open) that could not have happened under the old modal design at all.

## Finding 2 (Minor, new breakage from round 3's own fix) — the scale hints were vertically clipped

`crs_hint` got its own `QFormLayout` row in round 3 (fixing the *width* collapse from Finding 2 of that round) — but a `QFormLayout` row added to the dialog's outer `QVBoxLayout` via `addLayout()` does not participate in Qt's height-for-width layout pass. Measured directly: `crs_hint.height() == 32` while `crs_hint.heightForWidth(crs_hint.width()) == 47` for the two-line scale-check messages (the authority/units hints are one line and were never affected). Confirmed the mechanism by adding an identical `QLabel` straight to a bare `QVBoxLayout` (not nested in a form) in isolation: it sized to 47 px correctly.

**Fix:** the form is split into `form_top` (Id, CRS) and `form_bottom` (Origin onward), with `crs_hint` added directly to the outer `QVBoxLayout` between them — a real sibling, not a nested-layout row — preserving the Id / CRS / [hint] / Origin / ... visual order. Verified: `crs_hint.height() == crs_hint.heightForWidth(crs_hint.width())` now holds for both the long (47 px) and short (24 px) messages, and `crs_widget` stays full-width throughout. New test `test_crs_hint_is_not_vertically_clipped_when_it_wraps_to_two_lines`, using the real `EPSG:3857`-at-lat-36 REFUSE message (not a hand-set string) to reproduce the exact wrapping case.

## Finding 3 (Minor) — neither skip branch of `_crs_scale_error` had a test

Both are pure-accept paths, so a regression in either would silently loosen the guard without failing anything visibly. Two new tests: `test_crs_scale_check_skips_the_untouched_zero_origin` (EPSG:5070, a CRS verified in round 3 to false-positive at its own `(0, 0)`, with the origin still at the untouched placeholder — OK stays enabled, no hint) and `test_crs_scale_check_skips_on_transform_failure_rather_than_refusing` (EPSG:32616 at origin `(1e8, 1e8)` — verified directly that this raises the real `QgsCsException` ("Point outside of projection domain"), not a contrived stand-in — OK stays enabled, no hint).

## Both tiers, re-run after all fixes

```
.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q
→ 313 passed, 2 skipped

.venv/bin/ruff check .          → All checks passed!
.venv/bin/ruff format --check . → 70 files already formatted
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
→ Success: no issues found in 23 source files

QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py -q -p no:xonsh
→ 37 passed, exit 0 (three consecutive runs, all 37 passed / exit 0)

QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
→ 128 passed, exit 0 (91 pre-existing + 37 in this file)
```

## Files changed (this round)

- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (Finding 1; module docstring extended with a "modal-dialog hazard" note for Task 11 and later)
- `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py` (Finding 2)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py` (all three; every `drive_dialog`-based grid-dialog test rewritten to use the new `_open()` helper)

## A note on what I'm leaving for Task 11

The plugin.py module docstring now documents the modal-dialog hazard directly (not just in this report), since Tasks 11/15/16/18/19 all extend this file and Task 11's import dialog faces the same question. The guidance I left: `exec()` is fine for a dialog that never needs anything else to be interactive while it's open; `open_grid_dialog()`'s `show()` + `finished` + tracking-attribute pattern is what to copy only if a future dialog genuinely needs the same thing GridDialog does (the canvas, or some other outside interaction, while it's up).

## Not touched (per "Not in scope")

Left alone exactly as listed: the `DigitiseGridTool` object leak (never explicitly deleted, only unset as the active tool); the silent size/velocity refusals; the CRS-guard test's session-global project-CRS mutation (restored in a `finally`); `_prefill` making a legacy ftUS or high-distortion grid uneditable; `USER:` CRS portability; middle-button digitise picks; the empty ~24 px row under CRS when no hint is showing; the "needs an authority code" wording for a wholly unset CRS.

## Concerns carried forward

- All concerns from rounds 1-3 remain as stated.
- The single-dialog-at-a-time guard (`self._grid_dialog`) is a new, minimal safeguard against a genuinely new possibility (modeless dialogs let "Add grid" be triggered again before the first closes) rather than something the contract explicitly asked for. I judged it necessary rather than optional: without it, a second concurrently-open `GridDialog` would silently steal the canvas's one map tool from the first mid-digitise-pick. Flagging the addition explicitly since it goes slightly beyond the letter of this round's three findings.

---

# Fix round 5 (final round)

Six findings, all with a precise fix already confirmed by the reviewer. The coordinator's framing for this round: two of round 4's own fixes (`unload()` against a visible dialog; the split-form layout) had each been correct for the case named but untested one step to the side (the *hidden* dialog; the *other* form's label column) — the instruction was to walk every change in this round against the states this dialog's own features (the digitise flow, the modeless re-open) actually put it into, not just the state each finding names. That check caught a real problem of my own making, documented under Finding 6 below.

## Finding 1 (Important) — `unload()` used `close()`, which is a no-op on a hidden dialog

Verified directly before touching anything, on a bare `QDialog`:
```python
d = QDialog(); d.hide()
d.finished.connect(lambda r: print("finished", r))
d.close()    # 0 "finished" prints -- isVisible() is False, closeEvent() never calls reject()
d.reject()   # 1 "finished" print
```
`_start_digitise()` hides the `GridDialog` deliberately so the canvas can be clicked — "hidden mid-pick" is this feature's *ordinary* state, not an edge case, and `unload()`'s own fix from round 4 only covered the visible case. Left as `close()`, calling `unload()` while a pick was in progress left `_grid_dialog` stale, the map tool active, and the dialog itself alive and reachable (two more canvas clicks would re-show it over an unloaded plugin; OK would then raise `AttributeError` on `self.session`, swallowed to stderr, closing as if saved when nothing was).

**Fix:** `self._grid_dialog.reject()` instead of `.close()`.

**RED, on the actual new test** (temporarily reverted just this one line back to `.close()`):
```
FAILED test_unload_closes_a_dialog_hidden_mid_digitise_pick
    assert plugin._grid_dialog is None
E   assert <GridDialog ...> is None
PASSED test_unload_closes_a_visible_grid_dialog   # round 4's fix still covers this case
```
**GREEN**, `.reject()` restored: both tests pass; full file 44/44.

New tests: `test_unload_closes_a_visible_grid_dialog` (the case round 4 already covered, kept as a named regression test rather than only implied) and `test_unload_closes_a_dialog_hidden_mid_digitise_pick` (the case this finding is actually about — digitise button clicked, dialog hidden, tool active, then `unload()`; asserts both `_grid_dialog is None` and `canvas.mapTool() is None`).

## Finding 2 (Important) — `finished()` never re-checked which site it was still acting on

Modeless means the toolbar stays clickable while the dialog is open — impossible under round 3's modal `exec()` — so the site the dialog opened against can now close, or be replaced by a different site, before OK is clicked. `finished()` captures `opened_against = self.session.json_path` at open time and checks it before touching the session:

- **(a) site closed under the dialog:** `not self.session.is_open` → a `"no site is open; grid ... was not saved"` message, instead of letting `session.add_grid` raise `ProjectError` (not caught by the existing `except (ValueError, KeyError)`, previously escaping to stderr with an empty message bar while the dialog still closed as if saved).
- **(b) a *different* site opened under the dialog:** `self.session.json_path != opened_against` → `"a different site was opened while the grid dialog was open; grid ... was not saved"`, instead of silently calling `add_grid`/`replace_grid` on whichever site happens to be open now (which could define its own same-id grid, silently overwritten with no error at all — not a case the id-based `except (ValueError, KeyError)` could ever catch, since nothing about the id itself is wrong).

**RED, on both new tests**, with the two new branches removed (reverted to the round-4 `finished()` body — go straight to `dialog.result_grid()` / `add_grid`/`replace_grid` unconditionally):
```
FAILED test_finished_reports_when_the_site_closed_under_the_dialog
FAILED test_finished_reports_when_a_different_site_was_opened_under_the_dialog
    assert grid_b_a.origin == (1.0, 2.0) and grid_b_a.azimuth == 45.0
E   assert (999.0, 999.0) == (1.0, 2.0)   # site B's own grid A silently overwritten by site A's dialog
```
**GREEN**, both branches restored: both tests pass; full file 44/44. Both outcomes are now reported through the message bar rather than one being silent, per the contract.

New tests: `test_finished_reports_when_the_site_closed_under_the_dialog` (closes the site mid-dialog, then `accept()`, asserts the message and that `accept()` does not raise) and `test_finished_reports_when_a_different_site_was_opened_under_the_dialog` (opens site A, edits its grid A's azimuth in the dialog, opens site B — which defines its own grid A — under the dialog, then `accept()`; asserts site B's grid A is untouched and the message names "a different site").

## Finding 3 (Important) — the transform-failure test didn't defend its own branch

`test_crs_scale_check_skips_on_transform_failure_rather_than_refusing` drove the exception path only through `origin_x`/`origin_y.setValue()`, which reach `_crs_scale_error()` solely as a `_validate()` slot connected via `valueChanged` — a signal/slot call. Mutating `_crs_scale_error`'s `except Exception: return None` to `except Exception: raise` still left the test passing: the raised `QgsCsException` is swallowed by Qt before reaching any assertion (the standing signal/slot hazard documented throughout this file), leaving `crs_hint`/`ok_button` at whatever they already were *before* the two `setValue()` calls — which happened to already equal the expected "skip" outcome.

**Fix:** added `assert d._crs_scale_error(d.crs_widget.crs()) is None` — a direct, non-signal call, so a real `QgsCsException` reaches the test instead of being eaten.

**RED, with the mutation** (`except Exception: raise` in `grid_dialog.py`):
```
FAILED test_crs_scale_check_skips_on_transform_failure_rather_than_refusing
    assert d._crs_scale_error(d.crs_widget.crs()) is None
E   _core.QgsCsException: Forward transform (EPSG:32616 to EPSG:4326) of (100000000.0, 100000000.0)
E   Error: Point outside of projection domain
```
**GREEN**, mutation reverted: passes; full file 44/44. No production-code change was needed for this finding — `_crs_scale_error()` was already correct; only the test was blind to a regression in it.

## Finding 4 (Minor) — the split form's two `QFormLayout`s sized their label columns independently

Round 4 split the form into `form_top` (Id, CRS) and `form_bottom` (Origin onward) to fix `crs_hint`'s vertical clipping. Each `QFormLayout` sizes its own label column from only the rows inside it, so the two never agreed: measured `id_edit.x() == crs_widget.x() == 48` against `origin_x.x() == azimuth.x() == 236`, and `crs_widget.width() == 665` against `azimuth.width() == 477`.

**Fix:** a module-level `_FORM_LABELS` tuple and `_label(text, width)` helper; `label_width = max(QLabel(text).sizeHint().width() for text in _FORM_LABELS)` computed once and used to build every row's label in both forms, so both layouts' field columns line up regardless of which form a given row is actually in.

**RED, on the new test**, with the shared-width labels reverted to plain strings (`form_top.addRow("Id", ...)`, etc.):
```
FAILED test_form_columns_stay_aligned_across_the_split_form
    assert d.id_edit.x() == d.origin_x.x() == d.azimuth.x()
E   assert 48 == 236
```
Exactly the numbers measured by hand and quoted in the finding. **GREEN**, fix restored: `id_edit.x() == crs_widget.x() == origin_x.x() == azimuth.x() == 236`, `crs_widget.width() == azimuth.width() == 477`; full file 44/44. Also re-confirmed round 4's vertical-clip fix still holds simultaneously (`crs_hint.height() == crs_hint.heightForWidth(...) == 47` for the two-line message).

New test: `test_form_columns_stay_aligned_across_the_split_form`.

## Finding 5 (Minor) — re-triggering "Add grid" while hidden mid-pick was a silent no-op

The "already open" branch of `open_grid_dialog()` called only `raise_()`/`activateWindow()` on the existing dialog — both no-ops on a window that is hidden (as `_start_digitise()` leaves it deliberately). Re-clicking "Add grid" during a pick produced no window and no message at all.

**Fix:** `self._grid_dialog.show()` added before `raise_()`/`activateWindow()`.

**RED, on the new test**, with `.show()` removed:
```
FAILED test_open_grid_dialog_shows_the_existing_dialog_even_if_hidden_mid_pick
    assert dialog.isVisible()
E   assert False
```
**GREEN**, `.show()` restored: passes; full file 44/44.

New test: `test_open_grid_dialog_shows_the_existing_dialog_even_if_hidden_mid_pick` (clicks the digitise button to hide the dialog and arm the tool, re-triggers `open_grid_dialog(None)`, asserts the same dialog is now visible again).

## Finding 6 (Minor) — `self._grid_dialog` was only ever cleared by `finished()`

A dialog destroyed some other way (probed directly: `setParent(None)` + `deleteLater()`, which bypasses `finished()` entirely) left the tracker stale — the next `unload()` would call `reject()` on an already-deleted C++ object (`RuntimeError`), and every later "Add grid" would wedge forever calling `show()`/`raise_()` on it (Finding 5's own fix, now itself broken).

**Fix:** `dialog.destroyed.connect(clear_if_current)`, where `clear_if_current()` only compares Python identity (`if self._grid_dialog is dialog: self._grid_dialog = None`) — never touches `dialog`'s attributes, since `destroyed()` fires from the C++ destructor itself, after the C++ side is already gone. The `is` check (rather than clearing unconditionally) matters because this dialog's own `deleteLater()` in `finished()` is itself deferred: by the time `destroyed()` actually fires, `self._grid_dialog` may already point at a newer dialog opened in between, and an unconditional clear would wedge that one instead.

**RED, on the new test**, with the `destroyed.connect(...)` line removed:
```
FAILED test_open_grid_dialog_recovers_from_a_dialog_destroyed_outside_finished
    assert plugin._grid_dialog is None  # cleared by destroyed(), not finished()
E   assert <GridDialog ...> is None
```
**GREEN**, connection restored: passes; full file 44/44.

New test: `test_open_grid_dialog_recovers_from_a_dialog_destroyed_outside_finished` (destroys the dialog via `setParent(None)` + `deleteLater()` + a scoped `sendPostedEvents(dialog, QEvent.Type.DeferredDelete)`, asserts the tracker cleared, then that a further open/unload neither raises nor wedges).

## Self-review, following the coordinator's instruction directly: testing my own fixes against the states my own features create

Doing exactly what was asked — walking each change against the state my *own* features put the dialog into, not just the state each finding names — surfaced a seventh problem of my own making, not named by any finding:

**Finding 6's fix, run against this file's full 44-test suite, segfaulted inside `QgsApplication.exitQgis()`** (the session-scoped `qgis_app` fixture's teardown, at the very end of the whole run). Root-caused by bisection (prefix search over the file's test order): not any single test, but *accumulation* — every dialog `finished()`/`clear_if_current()` ever `deleteLater()`'d across the file's 44 tests was previously left un-flushed (nothing in this file had ever run the Qt event loop far enough to actually process a `deleteLater()`), so dozens of them piled up for `exitQgis()` to reap all at once at process teardown. That bulk, simultaneous destruction — now with every one of those dialogs `destroyed()`-connected back into a Python closure in `plugin.py` (this round's own Finding 6 fix) — is what segfaulted, not any individual dialog's destruction (confirmed: the same test passes cleanly in isolation, and even paired with just one neighboring test).

This is exactly the round 1, Finding 3 dialog-leak already carried forward as out of scope ("never explicitly deleted, only unset as active tool" — the underlying leak itself is unchanged and still out of scope), but it had never been *reachable* before because nothing previously connected a Python slot to any dialog's destruction — bulk C++ teardown at process exit ran no Python code at all, so there was nothing for it to crash. Finding 6's own fix is what newly exposes it.

**Fix (test-only, this file):** a new `_flush_deferred_deletes` autouse fixture that runs `qgis_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)` after every test, so no more than one test's worth of dialogs is ever left outstanding for `exitQgis()` — which mirrors what a real QGIS session already does with one dialog at a time, rather than papering over the crash. Also scoped the Finding-6 test's own explicit flush to `sendPostedEvents(dialog, ...)` (the specific receiver, not the global `None` form) so it does not also reap whatever an *earlier* test in the same run left pending.

Verified: the full file now passes 44/44 three consecutive runs in a row, and the full qgis tier (135 tests) and pure/core tier (313 passed, 2 skipped) both pass. This does not touch the underlying, still-deferred `DigitiseGridTool`/dialog-object leak itself — only ensures this test file's own bookkeeping does not let that pre-existing leak reach a crash.

One incidental fix needed alongside this: `test_finished_reports_when_a_different_site_was_opened_under_the_dialog`'s trailing `plugin.unload()` hit the pre-existing "unsaved changes" `QMessageBox.question()` prompt (site B has a real, unsaved edit from the test's own setup) — added the `answer_modal` fixture parameter and a `Discard` answer before `unload()`, matching every other test in this file that leaves a dirty session.

## Also fixed (not a numbered finding, per the coordinator's note)

`_open()`'s docstring claimed `drive_dialog` is "still used elsewhere" — no test in this file uses it any more since round 4's modeless conversion. Reworded to say what is actually true: kept in `conftest.py` for a future genuinely-modal dialog, used by nothing here.

## Both tiers, re-run after all fixes

```
.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q
→ 313 passed, 2 skipped

.venv/bin/ruff check .          → All checks passed!
.venv/bin/ruff format --check . → 70 files already formatted
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
→ Success: no issues found in 23 source files

QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py -q -p no:xonsh
→ 44 passed, exit 0 (three consecutive runs, all 44 passed / exit 0 -- including the exitQgis() segfault window)

QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
→ 135 passed, exit 0 (91 pre-existing + 44 in this file)
```

## Files changed (this round)

- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (Findings 1, 2, 5, 6)
- `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py` (Finding 4)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py` (all six findings' tests, the self-caught `exitQgis()` segfault fix, the `answer_modal` addition, and the `drive_dialog` docstring correction)

## Not touched (per "Not in scope" -- everything previously deferred stays deferred)

The `DigitiseGridTool` object leak (never explicitly deleted, only unset as active tool — now confirmed, via this round's own self-review, to be the actual root cause the `exitQgis()` segfault surfaced, but the leak itself is unchanged); the silent size/velocity refusals; the CRS-guard test's session-global project-CRS mutation (restored in a `finally`); `_prefill` making a legacy ftUS/high-distortion grid uneditable; `USER:` CRS portability; middle-button digitise picks; the empty ~24px row under CRS when no hint shows; "needs an authority code" wording being off-target for a wholly-unset CRS.

## Concerns carried forward

- All concerns from rounds 1-4 remain as stated.
- The dialog-object leak (round 1, Finding 3) is now demonstrated, not just asserted, to be reachable under the right conditions (many dialogs + a `destroyed()` connection + a forced bulk flush). It has not caused a problem in any of this round's own fixes once the test file stopped letting dialogs accumulate across its own run, and a real QGIS session only ever has one dialog open at a time — but it remains an open, out-of-scope defect that a future task touching this file's object lifecycle should be aware carries this specific failure mode, not only a memory leak.
