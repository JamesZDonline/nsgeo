### Task 5: Say it in the panel: the preview note, the reason nothing is drawn, the export's pixel size

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`. Add `self.site_note =
  ElidedLabel("")` directly under the readout row (around line 445). It is visible only in Whole
  site; its full text is in its tooltip (`set_hint`) and its height is fixed, kept when empty.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`:
  - `apply_resolution` (~832) keeps the reason when `set_resolution` raises, in
    `self.problem: str | None`, and clears it when it succeeds;
  - `refresh_slice` (~911) shows `engine.preview_note` while drawn, or `f"Not drawn: {problem}"`
    when nothing is drawn and a problem is known, else empty.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: both export success messages (~1013 and
  ~1193) gain the cell and pixel size (#112).
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`, and
  `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export_dialogs.py` (or wherever the export
  messages are asserted today).

**Interfaces:**
- Consumes: Task 4's `SiteEngine.preview_note`, `export_refusal`, `full_lattice` and `lattice`.
- Produces: `SlicesDock.site_note: ElidedLabel` and `SiteScope.problem: str | None`.
- The export message's exact copy is `f"exported {n} bands to {path} ({cell:g} m cell, {pixel:g} m pixels)"`.
  The site export takes the cell and pixel from `plan.cell_m` and `plan.lattice.pixel`; This grid's
  from `plan.frame.cell` and the written pixel, which is the cell after Task 2.

- [ ] **Step 1: Write the failing tests.**
  - `test_the_preview_note_shows_in_the_panel_while_the_site_is_a_preview`: lower
    `max_pixels`, and `dock.site_note.text()` equals the engine's note. Its tooltip also holds the
    export refusal (`"can't be exported at full detail"`), so that refusal is in the panel before
    anyone clicks Export (spec §5.5).
  - `test_the_note_clears_when_the_site_fits_again`.
  - `test_the_note_clears_on_switching_to_this_grid`: `site_note` is hidden.
  - `test_a_failed_resolution_says_why_in_the_panel_not_only_a_toast`. Make `set_resolution`
    raise (monkeypatch); then `dock.site_note.text().startswith("Not drawn: ")` and the reason is
    in the tooltip.
  - `test_the_site_note_never_widens_the_dock`: set a 300-character note, and the dock's
    `minimumSizeHint().width()` is unchanged.
  - `test_export_messages_name_the_cell_and_the_pixel`, for both exports.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.** Follow `refine_label`'s pattern for an `ElidedLabel` (fixed height,
  Ignored width). While the site is a preview, the label shows `preview_note`, and its hint is
  `preview_note + " " + export_refusal`. The site scope's existing show and hide on scope switch also covers `site_note`.
  `dock.error.emit` stays, so the toast still appears, but the panel is where the reason lives.
- [ ] **Step 4: Run** the three files and `test_plugin_site_engine.py`, plus lint. All pass.
- [ ] **Step 5: Commit**: `feat(slices): the panel says why: preview note, not-drawn reason, export pixel size`.

---

