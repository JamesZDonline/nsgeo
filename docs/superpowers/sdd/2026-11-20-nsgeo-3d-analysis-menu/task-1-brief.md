### Task 1: The drop-down, the Slices panel and the tests

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`. Touches:
  - the tip constants near `ADD_DATA_TIP` (~171);
  - the attribute declarations (~305–330);
  - the toolbar block in `initGui` (~389–420);
  - the `paraview_requested` connect (~456);
  - `_build_add_data_button` (~628) and `_build_panels_menu` (~644);
  - `unload` (~890–915);
  - `_update_enabled` (~975);
  - the `export_paraview` docstring (~1561).
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`. Remove:
  - `paraview_requested` (~303);
  - the button and its comment (~839–845);
  - its `clicked` connect (~894);
  - its enabling line (~1030).
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_analysis3d_menu.py`
- Modify: `packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_dialog.py`, in `_open_dialog` (~59–63), the button test (~77–84) and the module docstring's "the Slices panel's button".

**Interfaces:**
- Produces, as attributes on `NsgeoPlugin`, all `None` before `initGui` and after `unload`:
  - `act_analysis3d: QAction | None`, the toolbar's widget action for the button;
  - `analysis3d_menu: QMenu | None`;
  - `act_surface`, `act_view3d` and `act_paraview: QAction | None`, the menu's three entries. The first two keep their names; they are menu entries now, not toolbar actions.
- Produces: `NsgeoPlugin._toolbar_menu_button(self, text: str, tip: str, menu: QMenu) -> QAction`. It makes a `QToolButton(self.toolbar)` with that text, tip and menu in `InstantPopup` mode, adds it with `self.toolbar.addWidget`, appends the returned action to `self.toolbar_actions`, and returns it. It adds no separator, so callers add their own. `_build_add_data_button` and `_build_panels_menu` call it in place of their own six lines.
- Produces: module constants `ANALYSIS_3D_TIP` and `PARAVIEW_TIP` in `plugin.py`, with the text under Copy.

- [ ] **Step 1: Write the failing tests** in `tests/qgis/test_plugin_analysis3d_menu.py`. Model the imports and fixtures on `test_plugin_panels_menu.py`: `NsgeoPlugin(fake_iface)`, `initGui()`, and `unload()` in `finally`.

```python
def test_the_toolbar_has_a_3d_analysis_button_after_cut(fake_iface):
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        button = plugin.toolbar.widgetForAction(plugin.act_analysis3d)
        assert isinstance(button, QToolButton) and button.text() == "3D Analysis"
        assert button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
        assert button.toolTip() == ANALYSIS_3D_TIP
        menu = button.menu()
        assert menu is plugin.analysis3d_menu and menu.toolTipsVisible()
        assert menu.actions() == [plugin.act_surface, plugin.act_view3d, plugin.act_paraview]
        assert [a.text() for a in menu.actions()] == [
            "Surface from picks…", "3D view", "Export for ParaView…"
        ]
        assert plugin.act_view3d.toolTip() == BUTTON_TIP
        assert plugin.act_paraview.toolTip() == PARAVIEW_TIP
        actions = plugin.toolbar.actions()
        i = actions.index(plugin.act_analysis3d)
        assert actions[i - 1].isSeparator() and actions[i - 2] is plugin.act_cut
        assert actions[i + 1].isSeparator() and actions[i + 2] is plugin.act_panels
        assert plugin.act_surface not in actions and plugin.act_view3d not in actions
    finally:
        plugin.unload()


def test_the_3d_analysis_button_and_its_entries_grey_until_a_site_opens(fake_iface, tmp_path):
    # the four: act_analysis3d, act_surface, act_view3d, act_paraview
    # no site: all four disabled; new_site(tmp_path / "site"): all four enabled;
    # close_site(): all four disabled again.


def test_unload_tidies_the_3d_analysis_button_away(fake_iface):
    # As test_plugin_panels_menu.py's unload test: keep menu, act_analysis3d and
    # list(menu.actions()) before unload(); afterwards analysis3d_menu, act_analysis3d,
    # act_surface, act_view3d and act_paraview are all None; after
    # QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete),
    # sip.isdeleted() is true for the menu, the button action and every entry.


def test_the_slices_panel_has_no_paraview_button(fake_iface):
    # After initGui: no QPushButton among plugin.slices_dock.findChildren(QPushButton)
    # has "ParaView" in its text, and the dock has no attribute paraview_button.
```

- [ ] **Step 2: Rewrite the ParaView dialog tests' way in** (`test_plugin_paraview_dialog.py`):
  - `_open_dialog` calls `plugin_obj.act_paraview.trigger()` in place of `paraview_button.click()`. Its docstring says "Choose the 3D Analysis menu's Export for ParaView… …".
  - Replace `test_the_button_is_on_whenever_a_site_is_open_in_either_scope` with `test_the_menu_entry_is_on_whenever_a_site_is_open_in_either_scope`. It asserts that `plugin_obj.act_paraview.text() == "Export for ParaView…"` and that the entry is enabled. It then calls `dock.set_scope("site")`, asserts the entry is still enabled, and triggers it through `_open_dialog` with a driver that records `isinstance(d, ParaViewExportDialog)` and rejects. Exactly one dialog is shown.
  - Rename `test_the_button_opens_the_dialog_on_the_panels_grid` to `test_the_entry_opens_the_dialog_on_the_panels_grid`, and `test_the_button_refuses_while_a_geotiff_export_runs` to `test_the_entry_refuses_while_a_geotiff_export_runs`. Leave their bodies as they are.

- [ ] **Step 3: Run them and see them fail.**
  Run: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/test_plugin_analysis3d_menu.py packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_dialog.py`
  Expected: FAIL, with `AttributeError` on `act_analysis3d` / `act_paraview`, and ImportError on `ANALYSIS_3D_TIP` / `PARAVIEW_TIP`.

- [ ] **Step 4: Build it** in `plugin.py`:
  1. Add `ANALYSIS_3D_TIP` and `PARAVIEW_TIP` beside `ADD_DATA_TIP`, and declare the new attributes beside `act_add_data`, with a `#:` comment like Add data's.
  2. Add `_toolbar_menu_button`, and switch `_build_add_data_button` and `_build_panels_menu` to it. Panels keeps its `addSeparator()` before the call.
  3. Add `_build_analysis3d_button(self) -> None`, which builds the menu (`QMenu(self.iface.mainWindow())`, `setToolTipsVisible(True)`) with its three entries:
     - `act_surface` → `self.new_surface`;
     - `act_view3d` → `self.open_view3d`;
     - `act_paraview` → `self.export_paraview`.
     Give each entry its tooltip from Copy. In `initGui`, it replaces the two `_toolbar_action` calls for Surface from picks… and 3D view: `self.toolbar.addSeparator()`, then `self._build_analysis3d_button()`. Leave the Panels button's place unchanged: it is still built later in `initGui`.
  4. Delete the `self.slices_dock.paraview_requested.connect(...)` line.
  5. In `_update_enabled`, add `self.act_analysis3d` and `self.act_paraview` to the `is_open` tuple, which keeps `act_surface` and `act_view3d`.
  6. In `unload`, set `act_analysis3d` and `act_paraview` to `None`, and `deleteLater()` `analysis3d_menu` and set it to `None`, as `add_data_menu` is: the menu is parented to the main window, and its entries are its children and go with it.
  7. Update `export_paraview`'s docstring to "The 3D Analysis menu's Export for ParaView…: …".

  Then remove the four ParaView pieces from `slices_dock.py`. The button row keeps **Save cube…** and **Export GeoTIFF…**.

- [ ] **Step 5: Run the touched files, and the ones that use the moved controls.**
  Run: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/test_plugin_analysis3d_menu.py packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_dialog.py packages/nsgeo-qgis/tests/qgis/test_plugin_panels_menu.py packages/nsgeo-qgis/tests/qgis/test_plugin_add_data_dialog.py packages/nsgeo-qgis/tests/qgis/test_plugin_scene3d.py packages/nsgeo-qgis/tests/qgis/test_plugin_new_surface_dialog.py packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`
  Expected: all pass.
  Then run the pure, core and real-data runs, ruff and mypy, as in Global Constraints. Expected: all green.
  Also check that `grep -rn "paraview_button\|paraview_requested" packages/` prints nothing.

- [ ] **Step 6: Commit and push.**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/plugin.py packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py \
  packages/nsgeo-qgis/tests/qgis/test_plugin_analysis3d_menu.py \
  packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_dialog.py
git commit -m "feat(toolbar): a 3D Analysis drop-down for Surface from picks, 3D view and the ParaView export; ParaView… leaves the Slices panel (#227)"
git push origin nsgeo-3d-menu
```

