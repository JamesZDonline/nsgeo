### Task 5: The Slices dock's *Whole site* scope

Spec §4.1–§4.5. The dock consumes Tasks 2–4 and computes nothing.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_panel.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`, `packages/nsgeo-qgis/nsgeo_qgis/slice_layer.py`,
  `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`, plus
  `test_plugin_slice_layer.py` for `update_north_up`

**Interfaces:**
- Consumes: everything above.
- Produces (`ui/site_panel.py`, widgets only):
  - `@dataclass(frozen=True) class SiteRow: grid_id: str; preset: str; lines: str; state: str;
    included: bool`.
  - `class SiteSourcePanel(QWidget)`:
    - signals: `included_changed = pyqtSignal(object)` (a tuple of grid ids),
      `transform_changed = pyqtSignal(str)`, `selected_changed = pyqtSignal(str)` and
      `choose_lines_requested = pyqtSignal(str)`;
    - methods: `set_rows(rows: Sequence[SiteRow])`, `selected_grid() -> str | None`,
      `included() -> tuple[str, ...]`, `set_transform(name: str)`.
    - The table has columns ✓ / Grid / Preset / Lines / State, and is refilled under a guard
      (trap 8).
    - The button reads `Choose lines for <grid>…` and is disabled with no selection.
  - `class NormalisationPanel(QWidget)`:
    - signals: `method_changed = pyqtSignal(str)` (a method id) and
      `gain_changed = pyqtSignal(str, float)`;
    - methods: `set_method(method: str)`, `method() -> str`, and
      `set_grid(grid_id: str | None, gain: float)`.
    - Combo labels map to method ids: `None` → none, `Background level` → background,
      `Edge match` → edge, `Histogram match` → histogram.
    - The gain spin has prefix `×`, range 0.10–10.00, step 0.05 (trap 7), 2 decimals, and default
      1.00. It is disabled with no grid selected. A `Reset` button sets it to 1.00.
- Produces (`slice_layer.py`):
  - `SITE_LAYER_NAME = "Site slice (live preview)"`;
  - `SliceLayer.update_north_up(array, geotransform, crs, *, limit, colormap_name, unipolar,
    subtitle, name: str = LAYER_NAME) -> None`. `update` now resamples and delegates to it, with
    unchanged behaviour. `name` renames the existing layer in place and does not rebuild it.
- Produces (`SlicesDock`):
  - `scope() -> str` (`"grid"` or `"site"`) and `set_scope(scope: str) -> None`;
  - the attributes `grid_scope_button`, `site_scope_button` (checkable, exclusive, at the top of
    the body), `site_engine`, `site_panel`, `normalisation_panel`, `radius_spacing_spin` and
    `site_depths_label`;
  - `current_site_slice() -> SiteSlice | None`;
  - `line_choice_grid() -> str | None` and `line_choice_keys(grid_id: str) -> tuple[str, ...]`;
  - `set_included_for(grid_id: str, keys: tuple[str, ...]) -> None`;
  - `site_velocities() -> dict[str, VelocityModel | None]`.
- Behaviour, scope by scope:
  - ***This grid*:** exactly M11, with Task 2's memory.
  - ***Whole site*, groups:**
    - `source_group` is hidden; `site_panel` and `normalisation_panel` are shown;
    - `radius_spin` is hidden and `radius_spacing_spin` shown (suffix ` × line spacing`, 0–10,
      step 0.25, default 1.5, with a tooltip giving each grid's radius in metres);
    - `save_button` is hidden; `export_button` reads `Export site GeoTIFF…`.
  - ***Whole site*, stretch:** item 0 of `stretch_combo` reads `shared across the site`. Its index
    meaning is unchanged.
  - ***Whole site*, resolution:**
    - the cell size is seeded by M11's rule applied to the finest-spaced included grid, only when
      the included set changes;
    - dz, z0 and z1 are seeded from the union of the ready grids' prepared bounds, with the
      first-ready clamp M11 uses;
    - the slider runs over `site_engine.site_z`.
  - ***Whole site*, readout:** `slice i / N · lo–hi ns`, with `site_depths_label` below it reading,
    for example, `A 0.60–0.80 m · B 0.52–0.70 m · C no data`. Each depth uses that grid's resolved
    velocity, the way M11's `_resolved_velocity` does per grid.
  - **Both scopes, profile band:** `window_changed(lo_ns, hi_ns)` is emitted from the window
    shown.
  - **Switching scope:**
    - It keeps the window's time. The new slider is set to the level nearest the old top time.
    - Leaving *Whole site* calls `site_engine.cancel()`.
    - Entering it builds a `SiteSource` from `session.site_view()` and each grid's
      `slice_source()`. Default included grids are every grid with lines. A grid's default preset
      is its remembered one, else the first preset.
  - **Persistence:** the included set, transform and method go to `session.set_site_view`; a gain
    edit goes to `session.set_grid_gain`.
  - **Normalisation is off by default** (spec §4.6). The panel starts at `None`, and a survey
    with no `site_view["normalisation"]` restores `None`.
- Plugin:
  - `_on_slice_changed` in site scope calls `slice_layer.update_north_up(site_slice.array,
    lattice.geotransform, lattice.crs, ..., name=SITE_LAYER_NAME)`. In grid scope it is M11's
    path, with the layer name restored.
  - `open_line_choice_dialog` uses `dock.line_choice_grid()` and `line_choice_keys()`, and commits
    through `set_included_for`. Ruling Z's check compares `line_choice_grid()` at `finished` with
    the grid at open time.
  - `export_geotiff` routes to a new `export_site_geotiff()` when `dock.scope() == "site"`. That
    method:
    - asks for a path, defaulting to `slices/site.tif`;
    - calls `export_site` with the dock's thickness and step levels, method, radius, gains and
      `site_velocities()`;
    - adds the layer to the site group and applies the temporal properties;
    - writes the coverage companion when the coverage toggle is on, following M11's
      `export_geotiff`, including the separate `try` for the companion (Ruling AH).
  - `unload` disposes `site_engine`.

- [ ] **Step 1: Write the failing tests** (`site3` from conftest, plus a `plugin` built with it):

```python
def test_the_scope_switch_swaps_the_source_controls(...): ...
def test_whole_site_draws_one_layer_covering_every_grid(...): ...       # SITE_LAYER_NAME, extent
def test_one_slider_moves_every_grid(...): ...
def test_switching_scope_keeps_the_window_time(...): ...
def test_unticking_a_grid_removes_it_from_the_map(...): ...
def test_the_method_combo_changes_the_drawn_values(...): ...
def test_the_gain_spin_scales_only_the_selected_grid(...): ...
def test_choose_lines_acts_on_the_selected_grid_only(...): ...
def test_the_site_view_survives_save_and_reopen(...): ...              # grids, transform, method, gains
def test_the_readout_names_each_grids_depth_and_any_absent_grid(...): ...
def test_export_routes_to_the_site_geotiff_in_site_scope(answer_modal, ...): ...
def test_flipping_scope_mid_preparation_never_overlaps_and_settles(..., monkeypatch): ...
def test_unload_with_the_site_scope_open_leaves_nothing_running(...): ...
def test_the_gain_spin_steps_by_a_useful_increment(...): ...           # singleStep == 0.05
def test_update_north_up_renames_the_layer_in_place(...): ...           # test_plugin_slice_layer.py
```

- [ ] **Step 2: Run them; all fail.** M11's whole dock suite must still pass unchanged, apart from
  any test Task 2 already updated.
- [ ] **Step 3: Implement `site_panel.py`, `update_north_up`, then the dock and plugin wiring.**
  Keep the site-scope logic in a few dock methods that delegate (`_refresh_site_slice`,
  `_site_source`, `_on_site_changed`, `_apply_site_resolution`), so `slices_dock.py` grows by
  composition, not by a second copy of M11's flow.
- [ ] **Step 4 (conditional on Task 3's ruling): drag degradation.** While
  `slice_slider.isSliderDown()`, site ticks call `slice_at(..., radius_spacings=0.0)`. Fill is
  skipped and normalisation still applies. `sliderReleased` triggers one full refresh. The test is
  `test_dragging_draws_unfilled_and_release_draws_full`. If the ruling is that it isn't needed,
  record that and skip this step.
- [ ] **Step 5: Both tiers green; ruff, format and mypy clean.**
- [ ] **Step 6: Mutants.** Each must fail at least one test:
  1. the scope switch not cancelling the site engine;
  2. the window not carried across scopes;
  3. the gain applied to every grid;
  4. `set_included_for` writing to the *This grid* inclusion in site scope.
- [ ] **Step 7: Commit and push.**
  `feat(qgis): the Slices dock's Whole site scope`

---

## After Task 5: whole-branch review, deploy, and the acceptance walkthrough

The tests cannot make this check, and the user must make it (spec §9). It follows the standing
procedure, as M11 did: build and walk through before any merge decision.

1. Run the whole-branch review, then fix and re-review until it is clean.
2. Deploy this worktree to the `ns_geo` profile for the walkthrough with
   `.venv/bin/python packages/nsgeo-qgis/scripts/dev_link.py --profile ns_geo`. Afterwards,
   re-point the profile's plugin symlink at `.worktrees/nsgeo-main`, the standing deploy target
   for `main`. Check `ls -la` on the profile's plugins directory before and after.
3. Build the walkthrough as an Artifact with persisted results. The user runs it **on their own
   multi-grid data, privately**; nothing from that data enters the repo. The steps are below.
   Phrase each one positively and only ask for what can be seen.
   - Open a survey with several grids. The Slices dock has *This grid* and *Whole site* buttons
     at the top.
   - Click *Whole site*. Every grid with lines is listed and ticked, and each prepares in turn.
     Each grid appears on the map as soon as its state reads *ready*.
   - Drag the depth slider. Every grid moves together. The readout gives the ns window, and the
     line below it gives each grid's depth range.
   - With Normalisation set to *None*, note any step in brightness at a seam. Switch to
     *Background level*, *Edge match* and *Histogram match* in turn. The map updates each time.
     Which method gives the most continuous site?
   - Select one grid and raise its gain to ×1.50. Only that grid brightens. *Reset* returns it.
   - Untick a grid. It leaves the map. Tick it again. It returns without re-preparing.
   - Choose lines for one grid. Only that grid re-prepares.
   - Switch to *This grid*. The same window is shown for the selected grid. Switch back. The site
     returns at the same window.
   - Export the site GeoTIFF. It opens as one layer covering every grid, and its bands step
     through depth. `gdalinfo` on the file lists `NSGEO_SITE_NORMALISATION` and each band's
     `NSGEO_GRID_FACTORS`.
   - Save, close and reopen the survey, then click *Whole site*. The same grids, transform, method
     and gains are restored.
   - Drag the slider continuously across the whole range on your largest site. It keeps up with
     the drag.
4. Record every finding in the decision record. Only then present the merge decision.
