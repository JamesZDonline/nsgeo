### Task 6: Files GPS cannot place, and Fit to these tracks

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/gps_import.py` (`TapeGuess`, `guess_tape_rows`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/lookup.py` (`ImportRow.guess`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/import_dialog.py` (`GridImportPage.hand_on`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/add_data_dialog.py` (after a GPS import with leftovers)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py` (`proposed`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (`open_grid_dialog(..., proposed=, move_keys=)`; the `fit_tracks_requested` slot replacing Task 2's stub)
- Modify: `docs/guide/getting-started.md` (the hand-on; Fit to these tracks)
- Test: `tests/pure/test_pure_gps_import.py`, `tests/qgis/test_plugin_add_data_dialog.py`, `tests/qgis/test_plugin_grid_dialog.py` (or the existing grid dialog test file), `tests/qgis/test_plugin_survey_dock.py`

**Interfaces:**
- Consumes: `GpsImportResult` (Task 5), `fit_frame` / `measure_spacing` (Task 1), `fit_tracks_requested` (Task 2), `session.move_lines` for GPS lines (Task 2).
- Produces:
  - `@dataclass(frozen=True) class TapeGuess: axis: str; offset: float; direction: int; note: str`
  - `guess_tape_rows(order: Sequence[Path], placed: Mapping[Path, np.ndarray], grid: Grid) -> dict[Path, TapeGuess]` — §16's rule: for each path in `order` not in `placed`, interpolate the offset by file position between the nearest placed paths before and after it; at an end, `grid.default_spacing` per file further on, away from the placed line before it (or `+` when there is only one placed line); direction opposite the line before it in file order (placed or guessed), or opposite the line after it for the first file; omitted unless every neighbour used runs within `ALONG_DEG` of the same grid axis. A placed line's offset is its mean local cross coordinate (local x for axis `y`, local y for axis `x`); its direction is the sign of its local along change.
  - `ImportRow.guess: str = ""` — the guess note; non-empty means the row's offset and direction are a guess the user has not changed. `set_offset` / `set_direction` clear it.
  - `GridImportPage.hand_on(paths: Sequence[Path], grid_id: str, guesses: Mapping[Path, TapeGuess], *, n_placed: int) -> None` — replaces the rows with `paths` planned on `grid_id`, sets the axis to the guesses' (the most common, when they differ; rows of the other axis lose their guess), applies each guess as edited offset and direction with its `guess`, shows the hand-on banner (`n_placed` is the GPS line count for its first sentence), and hides the Direction and First line at rows until the page's next Import or the dialog closes.
  - `GridDialog(session, grid=None, parent=None, canvas=None, *, proposed: Grid | None = None)` — fills every field from `proposed` except Id, which stays empty and editable.
  - `plugin.open_grid_dialog(grid_id: str | None, *, proposed: Grid | None = None, move_keys: Sequence[str] = ()) -> None` — after OK on a new grid, `session.move_lines(move_keys, new_id)` and the copy's message (plus any skipped lines, as Edit lines names them).

- [ ] **Step 1: Write the failing tests.**
  - Pure `guess_tape_rows`, on a synthetic grid with azimuth 0 and lines along +Y at 0.25, 0.75, …: a gap between two placed lines gets the midpoint and `"between FILE__303 and FILE__305"`; two leftovers in a row interpolate by file position; a leftover after the last placed line gets one spacing on and `"1 spacing after FILE__309"`; the first file gets `"1 spacing before FILE__302"`; directions alternate from the neighbour before (zigzag); neighbours at 45° to both axes → no guess; lines along X → axis `x` with offsets in local y.
  - Hand-on (`AddDataDialog`, synthetic survey of ten files where files 4 and 7 have no DZG): GPS mode, New grid `G4`, Import → `G4` holds eight GPS lines, the dialog is still open, in Grid mode, on `G4`, with two rows whose offsets and directions match the guesses, amber Offset and Dir cells, the notes in the Note column, the banner's copy, Direction and First line at hidden; the `imported` signal carried the GPS summary without listing files 4 and 7 as not imported. Import → two tape lines on `G4`, the dialog closes. Cancel instead → nothing more added, and the GPS lines stay.
  - Editing a guessed row's offset clears its amber and its note.
  - A refused `already in the site` file is not handed on; when every refusal is of that kind the dialog closes after the GPS Import as before.
  - `GridDialog(proposed=…)`: the fields read the proposal's origin, azimuth, size and spacing, Id is empty and editable, OK is disabled until an Id is typed.
  - Fit to these tracks: three unattached GPS lines selected → `Fit a grid to these 3 tracks…` opens the grid dialog with the fitted proposal; typing an Id and OK adds the grid and moves the three lines into it (tracks unchanged), with the copy's message; Cancel adds and moves nothing. One line → the proposal's spacing is the grid dialog's default and its width one spacing.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** to the interfaces above. In `AddDataDialog.accept`, when the GPS page's `import_lines()` returns True and `last_import.leftovers` is non-empty: emit `imported`, call `grid_page.hand_on(last_import.leftovers, last_import.grid_id, guess_tape_rows(last_import.order, last_import.placed, session.grid(last_import.grid_id)), n_placed=len(last_import.placed))`, clear the GPS page's files, `set_mode(GRID)` without carrying files, and stay open. The Grid page's amber uses Add data's GPS colours (`FLAG_BG`, `FLAG_FG`). `GridDialog._prefill` gains the `proposed` path (Id left alone). The plugin's `fit_tracks_requested` slot builds the proposal from the lines' `trace_coords` (`measure_spacing`, else the grid dialog's default spacing) in the site CRS and calls `open_grid_dialog(None, proposed=…, move_keys=keys)`.
- [ ] **Step 4: Run the touched files, the pure tier and the real-data tier to pass**; lint, types.
- [ ] **Step 5: Commit and push** (`feat(m17b): files GPS cannot place are handed on to Grid mode with a guess; Fit a grid to these tracks (#134)`).

---

## After the tasks

- The coordinator runs `qgis_tests.sh full` once, reads CI on both QGIS versions, merges main if it moved, and builds the walkthrough (spec §11, M17b) on its own QGIS profile `ns_geo_m17b`, deployed with `scripts/dev_link.py`. The walkthrough's checks: Add data ▾ ▸ GPR… with GPS on the sixty lines into a new grid (the rectangle lined up with the lines, half a spacing outside the outer ones; slices of it); the second survey into an existing grid with a line partly outside named in the summary; a tape import through the same dialog with its GPS note and no marker anywhere after; a hand-on of files with their DZG hidden; M17a's unattached lines moved into a grid, and a grid fitted around others; Edit lines with GPS rows; editing the grid leaves its GPS lines in place; the toolbar and Survey panel copy.
- Merging waits for the user's go after the walkthrough.
