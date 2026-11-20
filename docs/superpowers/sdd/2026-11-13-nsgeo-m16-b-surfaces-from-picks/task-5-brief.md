### Task 5: The Surfaces panel, the New surface dialog, the toolbar action and the guide

**The mockup review is done** (spec call 15; `.lavish/surfaces.html`, 2026-11-13). The user chose:
- **layout A,** with the list and the details together in the panel;
- **every grid's surfaces listed,** with a Grid filter that defaults to All grids;
- **clicking an outlier** selects that pick on the map **and** opens its line in the Profile panel (`session.open_line(key)`), at the pick's trace.

Follow the mockup's wording for the dialog, the refusals, the fit rows and the delete question.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/surfaces_dock.py`, `packages/nsgeo-qgis/nsgeo_qgis/ui/new_surface_dialog.py`
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`:
    - a toolbar action "Surface from picks…", enabled while a site is open;
    - the dock, tabbed with Slices in `_tabify_slices_dock`;
    - "Surfaces" in the Panels menu;
    - `Surfaces` and `SurfaceLayers` made when a site opens and disposed when it closes;
    - the build flow behind `_export_progress`, with `refining_paused`, as `export_paraview` does;
    - `ParaViewExport(..., surfaces=...)` in `export_paraview`.
  - `docs/guide/getting-started.md`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_surfaces_dock.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_new_surface_dialog.py`

**Interfaces:**
- Consumes: Tasks 2–4; `_export_progress`, `busy_cursor` and `refining_paused` from Plan A; `Surfaces.check` for the dialog's live refusal and move note.
- Produces:
  - **`NewSurfaceDialog(check: SelectionCheck, n_label: str, parent=None)`:**
    - Fields: a name box, and Settings folded with their values shown (join, window in cm, strength, smoothing in m).
    - Create and build is disabled while any refusal stands.
    - `name()` and `settings()` read the result.
    - Return in a spin box does not accept, using Plan A's event filter.
  - **`SurfacesDock(session, surfaces, parent=None)`:**
    - **Signals:** `new_requested`, `build_requested(list)`, `select_picks_requested(list)`.
    - **Widgets:**
      - a Grid filter;
      - a table (Name, Grid, Picks, Fit as within-2-cm/picks, a state column reading "stale" or "not built");
      - the buttons New from selected picks…, Rebuild, Rename… and Delete…;
      - a group for the selected surface: its stale reason, Select its picks, Add selected picks, Remove selected picks, Settings, the fit rows and the outlier list.
    - **Behaviour:**
      - Rebuild acts on every selected surface. The plugin groups the ids by grid and builds each group in turn, under one progress dialog.
      - Changing a setting saves it at once (`set_settings`), and the surface shows as stale.
      - Clicking an outlier selects that pick on the map, opens its line in the Profile panel and moves to the pick's trace. A pick whose line is no longer in the site is only selected.
      - It refreshes on the same signals as `SurfaceLayers`.
      - Its contents sit in a `QScrollArea(widgetResizable=True)`, and long sentences go in tooltips (the dock-size rule in the environment notes).

- [ ] **Step 1: Write the failing tests:**
  - `test_the_toolbar_action_opens_the_dialog_on_the_selected_picks`
  - `test_with_no_picks_selected_it_says_how_to_select`
  - `test_the_dialog_shows_the_refusal_and_disables_create`
  - `test_the_dialog_states_picks_that_will_move`
  - `test_return_in_a_spin_box_does_not_create`
  - `test_create_and_build_adds_the_surface_and_its_layer`
  - `test_the_panel_lists_surfaces_with_fit_and_state`
  - `test_changing_a_setting_marks_it_stale_and_rebuild_clears_it`
  - `test_clicking_an_outlier_selects_its_pick_and_opens_its_line`
  - `test_delete_asks_first_and_keeps_the_picks`
  - `test_rename_refuses_a_taken_name`
  - `test_the_panels_menu_lists_surfaces`
  - `test_the_export_includes_surfaces_from_the_plugin`
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** In the guide, add two things:
  - **"Making a surface from picks":** pick only where the reflection is clear, and the same part of the wave each time; select, build, read the fit, rebuild after changes.
  - **A line in "Where your data lives":** surfaces are saved as you go in `site.nsgeo.gpkg`, like picks; built surfaces and exports are regenerable files in the site folder.
- [ ] **Step 4: Run the whole QGIS tier, the pure and core tiers, lint and the zip build.** All pass.
- [ ] **Step 5: Commit and push.** `feat: the Surfaces panel and New surface (M16 B)`.

---

