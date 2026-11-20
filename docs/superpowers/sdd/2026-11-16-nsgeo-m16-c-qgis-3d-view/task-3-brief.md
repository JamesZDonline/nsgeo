### Task 3: The 3D view button, the Slices panel's grid, and the guide

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`, which gains a `scope_changed` signal
- Modify: `docs/guide/getting-started.md`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_scene3d.py` (plugin-level tests) and `packages/nsgeo-qgis/tests/qgis/test_plugin_panels_menu.py` (the toolbar)

**Interfaces:**
- Consumes: `Scene3D` (Task 2).
- Produces:
  - `SlicesDock.scope_changed = pyqtSignal(str)`, emitted by `set_scope` only when the scope actually changes, with the new scope;
  - `NsgeoPlugin.act_view3d`, labelled "3D view";
  - `NsgeoPlugin.scene3d`;
  - `NsgeoPlugin.open_view3d(self) -> None`.

- [ ] **Step 1: Write the failing tests**, using the `surface_plugin` fixture with a `FakeIface` that has the fake canvas.

```python
def test_the_3d_view_button_greys_until_a_site_opens(fake_iface):
    ...
    # plugin.initGui() -> act_view3d disabled; after new_site -> enabled; after close -> disabled


def test_the_3d_view_button_opens_the_scene_of_the_slices_panels_grid(surface_plugin):
    ...
    # plugin.open_view3d() -> plugin.scene3d.is_open() and grid_id == the dock's grid


def test_a_scope_change_reaches_the_scene(surface_plugin):
    ...
    # slices_dock.set_scope("site") emits scope_changed("site") once; a second set_scope("site")
    # emits nothing


def test_closing_the_site_closes_the_view(surface_plugin):
    ...
    # open, then plugin.session.close_site() -> view closed, picks layer gone, no surface
    # layer keeps a renderer3D


def test_unload_closes_the_view(surface_plugin): ...
```

- [ ] **Step 2: Run them; they fail.**

- [ ] **Step 3: Implement.**
  - **The action.** `act_view3d = self._toolbar_action("3D view", self.open_view3d)` goes right after `act_surface`. Its tooltip is `scene3d_plan.BUTTON_TIP`. Add it to `_update_enabled`'s tuple.
  - **Building `scene3d`.** Construct it after `slices_dock` exists, with `export_for=self._surface_export`.
  - **`open_view3d`** calls `scene3d.open()` and turns `ValueError` and `RuntimeError` into a message-bar warning.
  - **Wiring:**
    - `session.site_closed` connects to `scene3d.close`;
    - `slices_dock.scope_changed` and `slices_dock.grid_combo.currentTextChanged` connect to `scene3d.request_refresh`;
    - `unload` calls `scene3d.dispose()` before the docks go.
  - **The signal.** Emit `scope_changed` at the end of `set_scope`'s real-change path.

- [ ] **Step 4: Write the guide.**
  - Add a toolbar row after **Surface from picks…**: "**3D view** | Opens QGIS's 3-D view of the grid the Slices panel shows: its picks at their depths and its surfaces, with depth stretched (see [The 3D view](#the-3d-view))."
  - Add **3D view** to the greyed-until-a-site-is-open sentence.
  - Add an unnumbered `### The 3D view` section after "Making a surface from picks", saying:
    - which grid it shows, and that in Whole site it keeps its last grid;
    - the stretch, where it comes from (the grid's ParaView export setting, ×3 by default), and that the title states it;
    - that it follows new picks and rebuilt surfaces, and that stale surfaces are labelled in the Layers panel and counted in the title;
    - that it shows no slices or walls, which ParaView does better;
    - that rotating, zooming and **Save as image** are QGIS's own;
    - that the "Picks at depth (3D view)" layer is temporary and goes when the view closes.

- [ ] **Step 5: Run `test_plugin_scene3d.py`, `test_plugin_panels_menu.py` and `test_plugin_slices_dock.py`, then the whole QGIS tier once, and the lint commands.** All pass.

- [ ] **Step 6: Commit and push.**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/plugin.py packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py docs/guide/getting-started.md packages/nsgeo-qgis/tests/qgis/test_plugin_scene3d.py packages/nsgeo-qgis/tests/qgis/test_plugin_panels_menu.py
git commit -m "feat(3d): the 3D view button follows the Slices panel's grid; guide (M16 C)"
git push origin nsgeo-m16-c
```

## After Task 3: the walkthrough (human gate)

Deploy to a fresh profile, `ns_geo_m16c`, copied from `ns_geo` with the plugin linked to this worktree. Use a copy of the Sunnyside site that holds the Plan B walkthrough's surfaces. Write the walkthrough as an Artifact with a results database, as for Plans A and B.

1. **The button.** It is greyed with no site. Open the site, and it is enabled.
2. **Open on Grid 1.** You see the picks as spheres on the bowl surface and Feature1, and the title says "depth stretched ×3". Rotate, zoom, and use **Save as image**.
3. **Live updates.** Add a pick on a Grid 1 line, and it appears. Rebuild a surface, and it is replaced in place. Change a surface's join, and the title counts it as stale.
4. **The stretch.** Export Grid 1 for ParaView at ×2. The view flattens to ×2 and its title says so.
5. **The scene grid.** Switch the Slices panel to another grid in This grid, and the scene moves. In Whole site it stays.
6. **Closing.** Close the view with its own close button, and the "Picks at depth" layer goes. Reopen it. Close the site with the view open, and it closes.
7. **Speed.** Note how long opening takes. Build up to ten surfaces on Grid 1, or as many as the picks allow, and check the view still turns smoothly (spec §6).
