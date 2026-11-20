### Task 3: The site's CRS, and GPS lines in the survey file (core + session)

**Files:**
- Modify:
  - `packages/nsgeo-core/src/nsgeo/model/survey.py`: `Site.crs` and `Site.validate`.
  - `packages/nsgeo-core/src/nsgeo/project.py`: the track dict, the `"crs"` key, `TRACK_SCHEMA_VERSION` and `READABLE_SCHEMA_VERSIONS`.
  - `packages/nsgeo-qgis/nsgeo_qgis/session.py`: `site_crs`, `set_site_crs`.
  - `packages/nsgeo-qgis/nsgeo_qgis/layers.py`: `crs()` reads `session.site_crs()`.
  - `packages/nsgeo-qgis/nsgeo_qgis/site_engine.py`: `_site_crs` likewise.
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py`: `_site_crs` likewise.
- Test:
  - `packages/nsgeo-core/tests/test_project.py`, `test_schema.py` and `test_survey.py`, which gain the tests below.
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py` likewise.

**Interfaces:**
- Consumes: Task 2's `TrackPlacement` and `TrackFix`.
- Produces:

```python
# nsgeo/model/survey.py — Site gains
crs: str | None = None  # P9; GPS lines are placed in it

# nsgeo/project.py
TRACK_SCHEMA_VERSION = VELOCITY_SOURCE_SCHEMA_VERSION + 1  # 4 (P8, P15)
READABLE_SCHEMA_VERSIONS = (..., TRACK_SCHEMA_VERSION)


# nsgeo_qgis/session.py — SiteSession gains
def site_crs(self) -> str | None: ...  # site.crs, else the first grid's crs, else None
def set_site_crs(
    self, crs: str
) -> None: ...  # ValueError(f"the site already uses {old}") when site_crs() is set; marks dirty
```

- [ ] **Step 1: Write the failing core tests.**
  - `test_a_gps_line_round_trips_with_identical_positions_without_its_dzg`:
    - Save a site with one GPS line: synthetic DZT + DZG, `track_from_log`, `travel_shift=0.24`, one fix with `alt_m=None`.
    - Delete the DZG, then load the site.
    - The loaded placement equals the saved one (dataclass equality, NaN fields compared with `math.isnan`). `trace_coords` matches to 1e-9.
  - `test_a_site_with_a_gps_line_saves_as_schema_4_and_names_its_crs`: `doc["schema_version"] == 4` and `doc["crs"] == "EPSG:32632"`.
  - `test_a_site_without_gps_lines_saves_exactly_as_before`: a grid-and-tape-line site saves with no `"crs"` key, as schema 1. With a cut it saves as 2, and with a velocity source as 3, as on `origin/main`. Loading and saving again gives the same JSON text.
  - `test_an_older_site_takes_its_crs_from_its_first_grid` (load, then `site.crs == grids[0].crs`).
  - `test_a_grid_free_site_keeps_its_crs` (GPS lines and no grids round-trip `crs`).
  - `test_travel_shift_and_grid_id_are_written_only_when_set`.
  - `test_a_gps_line_in_another_crs_is_refused_by_validate` (the Copy's message).
  - `test_schema_4_is_readable_and_5_is_not`.
- [ ] **Step 2: Write the failing QGIS tests** (`test_plugin_session.py`):
  - `test_site_crs_is_the_first_grids_until_the_site_has_its_own`;
  - `test_set_site_crs_refuses_to_change_a_set_crs`;
  - `test_layers_crs_follows_the_site_crs_on_a_grid_free_site`.
- [ ] **Step 3: Run them and see each fail.**
- [ ] **Step 4: Implement** to P8/P9. The version is the highest that applies: track, then velocity source, then cuts, then 1.
- [ ] **Step 5: Run core + pure, the touched QGIS files (`test_plugin_session.py`, `test_plugin_grid_dialog.py`, `test_plugin_layers.py`, `test_plugin_site_engine.py`), lint and types.**
- [ ] **Step 6: Commit** (`feat: a site has its own CRS; GPS lines save as schema 4 (#134)`) and push.

---

### Checkpoint C1 (coordinator, before Task 4)

- [ ] Mock up the **Import GPS lines** dialog and the GPS rows of the Survey panel in lavish. Use the Copy above, made-up file names and made-up numbers. The author approves, changes or waives it. Record the answer in the ledger, and fold any copy change into Tasks 4 and 6 before they start.

---

