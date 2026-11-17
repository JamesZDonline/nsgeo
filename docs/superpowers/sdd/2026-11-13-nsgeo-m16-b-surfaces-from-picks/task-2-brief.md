### Task 2: The features table and membership

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/surface_plan.py` (pure: no qgis import)
- Create: `packages/nsgeo-qgis/nsgeo_qgis/surfaces.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/layers.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py`: `features_changed = pyqtSignal()`
- Modify: `.github/workflows/ci.yml`: mypy list
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_surface_plan.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_surfaces_membership.py`. Build its site the way `test_plugin_layers.py` does: a real `SiteLayers` on a real package, with two grids and picks written through `write_pick`.

**Interfaces:**
- Consumes: `SurfaceSettings` and `picks_span_an_area` (Task 1); `SiteLayers.write_pick`, `_row_to_pick` and `_attr`; `session.grid_for_line` and `line_for_key`; `is_cut_key`.
- Produces:
  - **In `surface_plan.py`:**
    - `FeatureRecord(feature_id: str, name: str, grid_id: str, kind: str, settings: SurfaceSettings, created: str)`: frozen, with `to_row() -> dict[str, str]` and `from_row(row) -> FeatureRecord`. A bad `settings_json` reads as the defaults.
    - `KIND_SURFACE = "surface"`
    - `clean_name(text) -> str`: trims and collapses whitespace.
    - `name_refusal(name, taken: Iterable[str], own: str | None = None) -> str`: "" when the name is fine. Names compare case-folded; `own` is the record being renamed. Empty, taken, and over 80 characters are refused.
    - `selection_refusal(*, n: int, unsaved: int, on_cuts: int, grids: Collection[str], spans_area: bool) -> str`. Checks run in this order: none selected, unsaved, on cuts, two grids, fewer than 3 or in a straight line. The wording is the mockup's (`.lavish/surfaces.html`, "When the selection can't make a surface").
    - `move_note(moving: Mapping[str, int], n: int) -> str`: for example, "4 of them are in “Bowl”; they will move to this surface, and “Bowl” will need a rebuild."
    - `remove_refusal(left: int) -> str`: refuses leaving fewer than 3.
    - `delete_question(name: str, n_picks: int) -> str`
  - **In `layers.py`:**
    - `FEATURES = "features"`, with the spec `[("feature_id","str"), ("name","str"), ("grid_id","str"), ("kind","str"), ("settings_json","str"), ("created","str")]`.
    - The table is created with `QgsWkbTypes.Type.NoGeometry` from `ensure_tables`, only when it is absent. It is never in `TABLES` and never rebuilt. Missing fields on an older table are added with `provider.addAttributes`.
    - `PickRow(fid: int, pick: Pick, point: tuple[float, float] | None)`: `point` is the row's map position in the package CRS.
    - `selected_pick_ids() -> list[int]`
    - `pick_rows(fids) -> list[PickRow]`
    - `members_by_feature() -> dict[str, list[PickRow]]`: one scan; a `feature_id` naming no record is ignored.
    - `set_pick_feature(fids, feature_id: str | None) -> None`: committed rows only, through `changeAttributeValues`; raises RuntimeError on failure.
    - `feature_records() -> list[FeatureRecord]`
    - `write_feature(record)`
    - `update_feature(feature_id, *, name=None, settings=None)`
    - `remove_feature(feature_id)`
  - **In `surfaces.py`, `Surfaces(session, layers, export_for: Callable[[], ParaViewExport] | None = None)`:** `export_for` is first used in Task 3, where the plugin passes a factory bound to the Slices dock.
    - `records() -> list[FeatureRecord]`
    - `check(fids, *, into: str | None = None) -> SelectionCheck(refusal: str, grid_id: str | None, moving: dict[str, int], n: int)`
    - `create(name, fids, settings=SurfaceSettings()) -> FeatureRecord`
    - `rename(feature_id, name)`
    - `set_settings(feature_id, settings)`
    - `add_picks(feature_id, fids)`
    - `remove_picks(feature_id, fids)`
    - `delete(feature_id)`
    - `members(feature_id) -> list[PickRow]`

    Each refused change raises ValueError with the `surface_plan` text. Each completed one emits `session.features_changed` after the write.
    - **Order of writes in `create`:** the row first, then the picks. If the picks fail, remove the row and re-raise.
    - **Order of writes in `delete`:** clear the picks first, then remove the row.

- [ ] **Step 1: Write the failing pure tests:**
  - `test_record_round_trips_and_bad_settings_read_as_defaults`
  - `test_names_are_trimmed_and_unique_case_folded`, covering `"  Bowl  "`, `"bowl"` against `"Bowl"`, renaming to its own name, `""`, and 81 characters.
  - `test_selection_refusals_come_in_order`
  - `test_move_note_names_each_surface_once`
- [ ] **Step 2: Write the failing QGIS tests:**
  - `test_the_features_table_is_created_once_and_survives_a_crs_change`: the table exists after `ensure_tables`. A row survives `replace_grid` with a new CRS (which rebuilds every spatial table), with its rows and fids unchanged. The table is not in the project's layers.
  - `test_a_package_without_the_features_table_gains_it_with_picks_intact`
  - `test_create_sets_feature_id_on_exactly_the_selected_picks`, and `seq` stays null.
  - `test_picks_already_in_a_surface_move_and_the_check_says_so`
  - `test_delete_clears_membership_and_keeps_every_pick`: the pick count and every row's time are unchanged.
  - `test_picks_from_two_grids_are_refused`
  - `test_fewer_than_three_or_collinear_picks_are_refused`
  - `test_picks_on_a_cut_are_refused`
  - `test_unsaved_picks_are_refused_until_saved`: add a pick through `startEditing` and `addFeature`, select it, and check that it is refused. After `commitChanges` it is accepted.
  - `test_removing_below_three_picks_is_refused`
  - `test_names_are_unique_trimmed_and_never_used_in_paths`: a name `Bowl "north" / é` is stored as typed (trimmed). Creating a second "bowl " is refused.
  - `test_a_feature_and_its_picks_survive_closing_without_save`: create, rename, close the site without Save site, reopen. Everything is as last edited, and `session.dirty` was never set by these edits.
  - `test_features_changed_follows_each_write`
- [ ] **Step 3: Run them and see them fail.**
- [ ] **Step 4: Implement** `surface_plan.py`, the `layers.py` additions, `features_changed`, and `surfaces.py` (membership only). `detach()` releases the features layer along with the others.
- [ ] **Step 5: Run the new files, `test_plugin_layers.py`, `test_plugin_session.py`, the pure tier and lint.** All pass.
- [ ] **Step 6: Commit and push.** `feat: surfaces' features table and pick membership (M16 B)`.

---

