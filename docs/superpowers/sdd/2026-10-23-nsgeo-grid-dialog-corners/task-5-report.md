# Task 5 report — Pick on the map, with snapping (#63)

Implementer: Claude Opus 5.5. Base 23da978. Status: DONE_WITH_CONCERNS (minor). Commit 2e1d1db, pushed.

## What was built

### `maptools/pick_tool.py` (new) — `SNAP_TOLERANCE_PX = 12`, `PickPointTool(QgsMapTool)`

- `__init__(canvas, mode="point")`, mode `"point"` or `"polygon"` (anything else is a ValueError).
- Signals: `picked(QgsPointXY, str)`, `polygon_picked(object, "qint64")`, `skipped()`,
  `stopped()`, `cancelled()`, and one the brief did not list, `failed(str)` (see Deviations).
- `snap(map_point) -> (QgsPointXY, str)`, `snap_label`, `finish()`, `dispose()`.
- Snapping (C2): its own `QgsMapCanvasSnappingUtils(canvas, self)` with its own
  `QgsSnappingConfig` (enabled, `AllLayers`, `Vertex`, 12, `Pixels`); the project's config is
  never read or written. Two synchronous `snapToMap(point, filter, False)` passes: a
  `QgsPointLocator.MatchFilter` subclass accepting only `Qgis.GeometryType.Point` layers,
  then (only if that found nothing) no filter. The utils take their layers from the canvas's
  map settings, so only `canvas.layers()` is considered, and they follow `setLayers`.
- Label: `f"{display string} · {layer name}"` from `QgsVectorLayerUtils.getFeatureDisplayString`
  (falls back to `#<fid>` if the display expression is empty), or `"free click"`.
- Marker: a `QgsSnapIndicator` (its `QgsVertexMarker` is the only scene item the tool ever
  creates). Label shown with `QToolTip` at the snapped point, not a canvas item.
- Release: reuses the last move's match when the release is on the same pixel **and the same
  view** (map-to-pixel transform + CRS); otherwise snaps again.
- Polygon mode: no snapping; the release searches `canvas.layers(True)` in order (first is
  drawn on top) for polygon layers only, transforms the click into each layer's CRS
  (`QgsCsException` → skip that layer), filters by a ±1 px box, tests `intersects`, and takes
  the last matching feature in a layer (drawn last = on top). No hit → nothing emitted.
- Right-click → `skipped`; Esc → `stopped` (consumed with `e.ignore()`, see traps).
- `deactivate()` clears the marker/label/hover and emits `cancelled` once if `finish()` was
  not called. `dispose()` is idempotent: clears the match (the indicator deletes its marker
  from whatever scene holds it), drops the indicator, hides the label; never touches
  `canvas.scene()`. A disposed tool still snaps and emits but draws nothing.
- Every Qt-invoked override (`canvasMoveEvent`, `canvasReleaseEvent`, `keyPressEvent`,
  `deactivate`) guards its body and reports through `failed`.

### `plugin.py`

- `open_grid_dialog` connects `pick_requested` → `_start_pick(dialog, [row])`,
  `pick_all_requested` → `_start_pick(dialog, [0, 1, 2, 3])`, `pick_polygon_requested` →
  `_start_pick_polygon(dialog)`.
- `_arm_pick(dialog, tool, text) -> end`: ends a pick already running first (the dialog can be
  re-shown mid-pick by Add grid, so Pick can be pressed again), hides the dialog, sets the tool,
  focuses the canvas (Esc only reaches the tool through canvas key events), pushes the message
  with `createMessage("nsgeo", text)` + `pushWidget(item, Info)`. Returns `end(unset=True)`, the
  single finisher: `tool.finish()`, unset if still current, pop the message,
  `_finish_with_pick_tool`, then — in a `finally` — show and raise the dialog. Idempotent.
  `cancelled` → `end(unset=False)`; `stopped` → `end()`; `failed` → message + `end()`.
- `_start_pick(dialog, rows)`: message texts verbatim from the brief (`"of {len(rows)}"`,
  i.e. 4 for Pick all). `picked` → `dialog.set_corner(row, point, canvas destination CRS,
  label)`; next corner or `end()`. `skipped` → next corner (on a single pick, skipping its
  only corner is the cancel). `set_corner` returning False (transform refused) ends the pick:
  the dialog returns with the reason in its status line.
- `_start_pick_polygon(dialog)`: `polygon_picked` → `dialog.set_polygon_feature`, then `end()`;
  `skipped` → `end()`.
- `_say_pick` keeps one message per pick and updates its text (re-pushes if the user closed it);
  `_pop_pick_message` removes it if still present. `self._pick_message` tracks it.
- `finished`'s stranded branch now checks `PickPointTool`, keeps `blockSignals(True)` +
  `unsetMapTool` + `_finish_with_pick_tool`, and always pops the pick message.
- `_finish_with_digitise_tool` → `_finish_with_pick_tool`, docstring reasoning kept.
- `maptools/digitise_tool.py` deleted. Stale digitise comments swept (module docstring, `unload`,
  `open_grid_dialog`, `finished`).

### `grid_dialog.py` (carried Task 3 minor)

- `set_polygon_feature(layer, fid) -> bool` now checks the layer combo offers the layer
  **before** calling `setLayer` (verified: `QgsMapLayerComboBox.setLayer` on a layer it does
  not list sets the index to -1, dropping the user's current choice, and emits
  `layerChanged(None)`); if not offered, nothing changes and `fit_status` says
  `"<name> is not a polygon layer of this project, so it cannot be chosen"`.
- `chosen_polygon` and `_fill_from_polygon` read the layer from `feature_picker.layer()`, the
  same widget the fid comes from.
- Module docstring and the `_validate` comment updated.

### Tests and helpers

- `tests/qgis/conftest.py`: `_real_canvas`'s 1 m/px guard uses `pytest.approx` (carried Task 4
  minor); new `real_iface` fixture (a FakeIface with the real canvas, for plugin flows);
  `real_canvas` now built on it.
- `tests/plugin_testing.py`: `map_pixel`, `send_map_mouse`, `send_map_key`, `named_layer`,
  `feature_id` (Qt imports local, as the module requires).
- `tests/pure/test_no_orphan_signals.py`: `pick_all_requested`, `pick_polygon_requested`,
  `points_picked`, `cancelled` removed from `KNOWN_UNCONSUMED`; `corners_changed` stays with an
  updated reason (Task 6); `pick_requested` pinned at 3 declared / 3 connects with an honest
  comment. All five new tool signals (and `cancelled`) have a real connect in plugin.py.
- `tests/qgis/test_plugin_import_dialog.py`: one stale "digitise pick" comment → "map pick".

## Old → new test port mapping (old names from fe2ea5a)

| Old test | New test |
|---|---|
| test_digitise_flow_through_the_plugin_fills_and_restores_the_dialog | test_pick_flow_fills_the_row_and_restores_the_dialog |
| test_digitise_flow_right_click_restores_the_dialog_without_a_pick | test_single_pick_right_click_restores_the_dialog_untouched |
| test_digitise_flow_switching_map_tools_restores_the_dialog | test_switching_map_tools_mid_pick_restores_the_dialog |
| test_open_grid_dialog_releases_a_stranded_map_tool_on_close | (same name) |
| test_open_grid_dialog_releases_a_stranded_tool_on_accept_without_flashing_the_dialog | (same name) |
| test_open_grid_dialog_shows_the_existing_dialog_even_if_hidden_mid_pick | (same name) |
| test_unload_closes_a_dialog_hidden_mid_digitise_pick | test_unload_closes_a_dialog_hidden_mid_pick |
| test_completed_digitise_picks_do_not_pile_rubber_bands_into_the_scene | test_completed_picks_leave_no_canvas_items |
| test_an_aborted_digitise_pick_gives_its_rubber_band_back | test_an_aborted_pick_leaves_no_canvas_items[right-click, esc, switch tools] |
| test_a_dialog_closed_mid_pick_gives_the_rubber_band_back | test_a_dialog_closed_mid_pick_leaves_no_canvas_items |
| test_a_disposed_digitise_tool_is_disposable_again_and_still_usable | test_pick_tool.py::test_a_disposed_pick_tool_is_disposable_again |
| test_digitise_flow_recovers_from_coincident_points | no direct port (one click has no coincident pair); its intent — a refused input still hands control back with a reason — is test_a_pick_that_cannot_be_converted_ends_and_says_why and test_a_pick_that_fails_says_so_and_restores_the_dialog |
| test_digitise_tool_emits_after_two_clicks, ..._right_click_before_any_pick_cancels, ..._right_click_after_origin_cancels_not_completes | deleted per the brief (the three that were still in the file); right-click is now test_right_click_skips_and_esc_stops and the single-pick flow test |

Each port restates the old test's comment (round/finding and why). The three scene-item ports
also assert the tool object itself is deleted (`sip.isdeleted` after flushing DeferredDelete),
because `deactivate()` alone already clears the marker and would otherwise keep those tests
green with `end()`'s release removed (mutant M4).

New tests beyond the brief's list:
- tool: `test_the_radius_is_twelve_pixels_whatever_the_zoom` (12 in / 13 out, and 10 m/px zoom),
  `test_with_no_point_in_range_the_nearest_vertex_wins` (the second pass — without it no listed
  test fails if pass 2 is removed), `test_a_click_after_the_view_moved_snaps_afresh`,
  `test_project_snapping_settings_are_neither_read_nor_changed`,
  `test_esc_reaches_the_tool_through_the_canvas_and_stops_there`,
  `test_polygon_picked_carries_a_64_bit_feature_id`,
  `test_an_exception_in_a_handler_becomes_failed_not_a_traceback` (through the real canvas),
  `test_leaving_the_canvas_takes_the_marker_off_the_map`.
- flow: `test_a_pick_that_fails_says_so_and_restores_the_dialog[the tool, the dialog]`,
  `test_a_pick_that_cannot_be_converted_ends_and_says_why`,
  `test_a_pick_started_while_one_runs_replaces_it`,
  `test_set_polygon_feature_refuses_a_layer_the_list_does_not_offer` (carried Task 3 minor; with
  the old code `chosen_polygon()` came back None — the combo had dropped the user's choice).

R4 applied: the free-click test clicks (384, 300).

## TDD evidence

RED 1 (no module):
```
$ PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest \
    packages/nsgeo-qgis/tests/qgis/test_pick_tool.py packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py -q -p no:xonsh
E   ModuleNotFoundError: No module named 'nsgeo_qgis.maptools.pick_tool'
ERROR packages/nsgeo-qgis/tests/qgis/test_pick_tool.py
ERROR packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py
2 errors in 0.46s
```
RED 2 (a behaviourless stub declaring only the signals, so each test fails on its own
assertion): `36 failed, 73 passed in 9.13s` — every new test failed, every existing test
passed. Failure reasons were the intended ones: `isinstance(None, PickPointTool)` (no tool
armed), `isHidden()` False, `[] == [((400.0, 300.0), 'G4 · gps')]` (no snapping),
`1 == (1 + 1)` (no marker), `set_polygon_feature(...)` returning None.

RED 3 (the view check, added after GREEN): `test_a_click_after_the_view_moved_snaps_afresh`
failed with `[((400.0, 300.0), 'G4 · gps')] == [((514.0, 300.0), 'plot 7 · plan')]` (the stale
match reused), then passed with the fix.

RED 4: `test_a_pick_that_cannot_be_converted_ends_and_says_why` was written to kill mutant M13
(below) and does.

GREEN: see Verification.

## Mutation check (PYTHONDONTWRITEBYTECODE=1; source restored after each)

| Mutant | Result |
|---|---|
| M1 finished does not pop the message | killed (stranded_map_tool_on_close) |
| M2 a running pick is not ended before a new one | killed (a_pick_started_while_one_runs_replaces_it) |
| M3 finished does not blockSignals | killed (…_without_flashing_the_dialog) |
| M4 end() does not release the tool | killed (completed_picks_leave_no_canvas_items, via sip.isdeleted) |
| M5 end() does not pop the message | killed (pick_flow_fills_the_row…) |
| M6 deactivate never emits cancelled | killed (switching_tools_cancels_once_unless_finished) |
| M7 no points-first pass | killed (the_radius_is_twelve_pixels…) |
| M8 set_polygon_feature takes any layer | killed (…refuses_a_layer_the_list_does_not_offer) |
| M9 deactivate leaves the marker | killed (leaving_the_canvas_takes_the_marker_off_the_map) |
| M10 dispose does not clear the match | **survived — equivalent**: dropping the last reference to the indicator destroys it and its marker anyway; the explicit clear only makes that independent of refcounting |
| M11 Esc accept()ed | killed (right_click_skips_and_esc_stops) |
| M12 single right-click goes through next_corner | was equivalent; the special case was deleted instead (skipping a single pick's only corner is its cancel) |
| M13 a refused set_corner does not end the pick | killed (a_pick_that_cannot_be_converted_ends_and_says_why) |
| M14 failed does not end the pick | killed (a_pick_that_fails_says_so…[the tool]) |
| M15 release always re-snaps | killed (the_label_names_the_target_and_the_click_uses_it) |
| M16 canvas not focused on arm | killed (pick_flow_fills_the_row…, after making it discriminating: a dock widget holds the focus first; before that it survived because the canvas was the window's focus widget anyway) |

## Excepthook check

The tier's conftest already carries a permanent autouse `_no_swallowed_slot_exceptions` that
fails a test if `sys.excepthook` or `sys.unraisablehook` fired, so every run above had it.
Rather than add a duplicate, I ran a negative control proving it catches this code's path:
a temporary plugin (`-p conftest_unguarded`, uncommitted, in the scratchpad) replaced
`PickPointTool.canvasMoveEvent` with an unguarded version, and
`test_an_exception_in_a_handler_becomes_failed_not_a_traceback` (which sends the event through
the real canvas viewport) then errored with "1 exception(s) escaped a Qt slot and were
swallowed … RuntimeError: index exploded". With the real code, both files pass with the guard
active: no slot exception escaped.

## Verified traps (recorded in pick_tool.py's module docstring)

- QgsMapCanvas hands a key press to the tool already accepted and continues its own handling
  unless the tool ignore()s it (QGIS 3.44: accept() on Esc → canvas still emits keyPressed;
  ignore() → it does not; Left key: accepted → canvas pans). Esc is therefore ignore()d.
- `pyqtSignal(object, int)` wraps a fid past 2**31 silently (2**31 + 7 → -2147483641); hence
  qint64.
- `QgsMapLayerComboBox.setLayer` on a layer it does not list clears its current choice.
- `QgsSnapIndicator`'s marker is created lazily on a valid match and deleted on an empty
  match or with the indicator; deleting the canvas first and the indicator after did not crash
  (probed both orders).

## Verification (final code, from the worktree root)

- Tool + dialog files: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_pick_tool.py packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py -q -p no:xonsh` → **111 passed** (17 tool + 94 dialog file).
- QGIS tier: `... -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh` → **991 passed in 410.71s** (was 957: −4 digitise tests, +17 tool, +21 flow/dialog). Run twice; the second on the final code.
- Core + pure: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q` → **748 passed, 3 skipped** (unchanged).
- `ruff check .` → All checks passed; `ruff format --check .` → 145 files already formatted.
- mypy (the brief's command) → Success: no issues found in 34 source files.
- Commit 2e1d1db `feat(plugin): pick corners and polygons on the map with snapping; Digitise on map removed (#63)`, pushed (23da978..2e1d1db).

## Files changed

- packages/nsgeo-qgis/nsgeo_qgis/maptools/pick_tool.py (new)
- packages/nsgeo-qgis/nsgeo_qgis/maptools/digitise_tool.py (deleted)
- packages/nsgeo-qgis/nsgeo_qgis/plugin.py
- packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py
- packages/nsgeo-qgis/tests/qgis/test_pick_tool.py (new)
- packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py
- packages/nsgeo-qgis/tests/qgis/conftest.py
- packages/nsgeo-qgis/tests/plugin_testing.py
- packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py
- packages/nsgeo-qgis/tests/qgis/test_plugin_import_dialog.py (one comment)

## Deviations from the brief (each deliberate)

1. `polygon_picked` is `pyqtSignal(object, "qint64")`, not `(object, int)` — verified that `int`
   silently wraps feature ids past 2**31 into a different feature. Python still receives an int.
2. An extra signal, `failed(str)`: the global constraint says every Qt-invoked override guards
   its body and an exception ends the pick with a message; the tool has no message bar, so it
   reports through this signal, which plugin.py turns into a message and `end()`. The name is
   unique in the package; it is connected.
3. `set_polygon_feature` returns `bool` (was `None`); it refuses a layer the combo does not list.
4. The release reuses the last move's match only when the pixel **and the view** are unchanged
   (an arrow-key pan or a CRS change between move and click otherwise reused a stale point,
   in the CRS case in the wrong CRS).
5. A conversion `set_corner` refuses ends the pick (Pick all included) rather than staying on
   the corner with the dialog hidden and the reason in its hidden status line.
6. The canvas is given focus when a pick starts (Esc otherwise goes to whatever dock had it).
7. Message title `"nsgeo"` (the bar shows "nsgeo: <text>"; `item.text()` is the brief's text).

## Self-review

Read the whole diff after GREEN. Changes made from that review (all re-verified above):
- The release's reuse rule compared pixels only; added the view check (RED 3) and then moved it
  from stringified extent/authid to `QgsMapToPixel` + CRS objects (rotation was invisible and two
  custom CRSs with empty authids compared equal).
- The scene-item ports were not discriminating for `end()`'s release (deactivate clears the
  marker anyway); they now also assert `sip.isdeleted(tool)`.
- The focus assertion was vacuous until a dock widget held focus first (M16).
- `skipped`'s single-pick branch was redundant (M12); removed.
- A refused `set_corner` ending the pick had no test (M13); added.
- Stale wording swept: plugin.py module docstring, `unload`, `open_grid_dialog`, `finished`;
  grid_dialog.py docstring and `_validate`; the tests' `_open` docstring and two comments; one
  comment in test_plugin_import_dialog.py. No "digitis" left in plugin.py, pick_tool.py or
  grid_dialog.py.

Checked and left: every slot and Qt-invoked override guards its body; `end()` shows the dialog
in a `finally`; `cancelled` never unsets; `finished` keeps `blockSignals` and pops the message;
`dispose()` never touches `canvas.scene()`; snapping config is the tool's own; messages verbatim.

## Concerns (all minor)

1. **Label as QToolTip.** Qt hides a tooltip on a mouse press, wheel or timeout and it comes
   back on the next move; positioning is `canvas.mapToGlobal(toCanvasCoordinates(point))`, which
   ignores the canvas frame (1-2 px). Worth a look in the walkthrough on the user's desktop; if
   it reads poorly, a small QgsMapCanvasItem label is the alternative (dispose would then remove
   it via `item.scene()`).
2. **Synchronous snapping index.** `snapToMap(..., relaxed=False)` builds a layer's locator on
   the first move over it; on a very large layer the first move can stall briefly. Fine for GPS
   points and a few polygons; watch for it with real overlay layers in the walkthrough.
3. **Esc needs canvas focus.** The canvas is focused when a pick starts; if the user clicks into
   a dock mid-pick, Esc goes there. Right-click still cancels/skips, and switching tools ends it.
4. **Task 6's grep check.** `git grep -i digitis -- docs/guide README.md packages/nsgeo-qgis/nsgeo_qgis`
   also returns pre-existing, unrelated verb uses in layers.py:382, :1498 and map_link.py:517
   (users digitising features into editable layers), plus metadata.txt's `about` (Task 6's to
   rewrite). Task 6's brief expects only the changelog line; those three are not about grids.
5. **Deviations 1-2** (qint64 fid, extra `failed` signal) change the brief's interface; both
   are additive and justified above, but the controller should know.
6. Scale-dependent layer visibility is not consulted: a layer in `canvas.layers()` but outside
   its scale range is still snapped to (the snapping utils' own behaviour). Not probed.
7. M10 survives as an equivalent mutant (see the table).

No human gates in this brief; the coordinator's later walkthrough covers items 1-3.
