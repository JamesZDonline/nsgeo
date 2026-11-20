### Task 5: GPS lines into a grid: existing or new, with the preview

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/gps_import_dialog.py` (`GpsImportPage`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/gps_import.py` (`with_grid`, `import_messages`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/preset_box.py` (`set_grid(..., new=True)`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/add_data_dialog.py` (the preview)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (pass the canvas; dispose the preview in `finished` and the `destroyed` guard, as `open_grid_dialog` does with its overlay)
- Modify: `docs/guide/getting-started.md` (Step 3a: into a grid, new or existing)
- Test: `tests/pure/test_pure_gps_import.py`, `tests/qgis/test_plugin_gps_import_dialog.py`, `tests/qgis/test_plugin_add_data_dialog.py`, `tests/qgis/test_plugin_preset_box.py`

**Interfaces:**
- Consumes: `fit_frame`, `measure_spacing`, `main_direction`, `metres_outside`, `TrackFrame.as_grid` (Task 1); the pages and `AddDataDialog` (Task 4).
- Produces:
  - `gps_import.OUTSIDE = "outside {gid}"`; `with_grid(rows: Sequence[GpsRow], grid: Grid) -> tuple[list[GpsRow], dict[Path, float]]` — rows whose ready line has no trace inside the grid become refused `OUTSIDE`; the dict holds metres outside per remaining ready row.
  - `import_messages(rows, imported, *, into: str, outside: Mapping[Path, float] = {}, handed_on: Collection[Path] = ()) -> list[str]` — `into` is `"new grid {gid} ({w:.1f} × {l:.1f} m, spacing {s:.2f} m)"` or `"{gid}"`; refused rows in `handed_on` are not listed as "not imported".
  - `GpsImportPage.target() -> str | None` (None for New grid); `GpsImportPage.proposal() -> Grid | None` (the grid Import would make, from the ready rows, or None while it cannot); `GpsImportPage.last_import: GpsImportResult | None` with `@dataclass(frozen=True) class GpsImportResult: grid_id: str; order: list[Path]; placed: dict[Path, np.ndarray]; leftovers: list[Path]` (`order`: every path the page held at Import, in its order; `placed`: each imported line's `trace_coords`; `leftovers`: refused paths whose refusal is neither `ALREADY_IN_SITE` nor `OUTSIDE`, in file order) — read by Task 6.
  - `PresetBox.set_grid(grid_id: str | None, *, new: bool = False)` — `new=True`: starts on the site's last choice, and the Slices note shows for any chosen preset with `{grid}` = `grid_id or "The new grid"`.

- [ ] **Step 1: Write the failing tests.** Synthetic surveys: `gps_file(folder, name, lon=LON0 + k * dlon)` with `dlon` putting lines 0.5 m apart, alternate files walked south (reverse the fix order).
  - Pure: `with_grid` refuses a line wholly outside and reports 3.0 m for one that runs 3 m past the grid's end; `import_messages` with `into` for both forms, an outside warning, and a handed-on refusal left out.
  - New grid: eight files → Target grid starts on `New grid` on a grid-free site; Name empty → Import disabled, status `"Name the new grid."`; Name `"G4"` → Spacing shows 0.500 with the measured note; Fitted reads the copy with `4.0 × 20.0 m` (or the synthetic survey's sizes); typing 0.6 sticks through adding a file; Import makes grid `G4` (`default_spacing` 0.6, `crs` the site's) and eight lines with `grid_id="G4"`; messages start with the new-grid copy.
  - A name already used → `"A grid named {name} already exists."`, Import disabled; a grid with the typed name added elsewhere after typing → Import refuses on the status line and adds nothing (Review Focus 1).
  - One file → Spacing `—` with the one-line note, Import disabled until a spacing is typed, then a grid one spacing wide.
  - Two crossing sets of four lines (north and east) → Spacing `—` with the no-direction note, and once typed, Fitted reads the smallest-rectangle copy.
  - Existing grid: the `Outside {gid}` column, amber metres, a wholly outside line red with `outside {gid}`; Import adds the ready lines with that `grid_id`; the grid itself is unchanged.
  - The preset: New grid with a preset chosen shows `"G4's first lines: this becomes its Slices preset too."`; after Import the grid's Slices preset is that preset and every new line carries it; the import preset is remembered for `G4`.
  - Review Focus 2: monkeypatch `session.add_lines` to raise `ValueError` → no grid `G4` remains, no slice source for it, the status shows the message.
  - Review Focus 3: grid-free site with no CRS, project in EPSG:4326 → the new grid's `crs` and the site's CRS are the picked UTM zone, and the lines are placed in it.
  - The preview (`AddDataDialog` with `iface.mapCanvas()`): while on New grid with ready rows its overlay's `grid` holds four corners equal to `proposal()`'s corners transformed to the canvas CRS; switching Target grid to an existing grid or to Grid mode clears it; the dialog finishing (accept, reject, close) disposes it; the target grid removed or the site closed under the dialog makes Import refuse with the status line (Review Focus 1).
  - Real data (skip on missing `GPS_LINES`, reason naming `tests/data/local`): the sixty lines into a new grid → 60 lines on it, its spacing within 0.01 of 0.496, every line's traces ≥ 99 % inside it.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** The Target grid combo (`New grid`, data `""`, then the grids) with Name / Spacing / Fitted rows shown only for New grid (hide label and field together; `QFormLayout.setRowVisible` does not exist on Qt 5). Spacing is a `QDoubleSpinBox` (0.000–100.000, 3 decimals, `setSpecialValueText("—")` at 0) that follows the measurement until the user types (`_spacing_own`, like Grid mode's `_first_offset_own`). Replan on files, target and spacing changes: `with_grid` for an existing target; `measure_spacing` / `fit_frame` on the ready rows for New grid. Import, in this order, after M17a's re-checks: name checks; for a site with no CRS, `set_site_crs`; `add_grid(proposal)` for New grid; Slices preset rule (`import_sets_slice_preset` / `set_slice_preset`) for the target; lines with `grid_id` set (`dataclasses.replace` on each placement); `add_lines`; on its `ValueError`, put the slice preset back and `remove_grid` the new grid, then report. Then preset applied, remembered per grid, `last_import` filled, and `messages = [(text, i > 0) for i, text in enumerate(import_messages(...))]` (the count is news, the rest warnings, as M17a's plugin showed them). The preview: the dialog owns one `GridOverlay` when given a canvas, sets `set_grid(corners)` from `gps_page.proposal()` on every `changed` while in GPS mode on New grid, else `set_grid(None)`; corners in the canvas CRS through a `QgsCoordinateTransform` from the site CRS.
- [ ] **Step 4: Run the touched test files and the real-data tier to pass**; lint, types.
- [ ] **Step 5: Commit and push** (`feat(m17b): GPS lines into an existing grid or a new one fitted around them, with a map preview (#134)`).

---

