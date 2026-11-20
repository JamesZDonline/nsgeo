### Task 4: Import GPS lines… (plugin)

**Files:**
- Create:
  - `packages/nsgeo-qgis/nsgeo_qgis/crs_rule.py`;
  - `packages/nsgeo-qgis/nsgeo_qgis/gps_import.py`, which has no Qt;
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/gps_import_dialog.py`.
- Modify:
  - `ui/grid_dialog.py`: delegate to `crs_rule`, and import `CRS_SCALE_WARN`/`CRS_SCALE_REFUSE` from it;
  - `plugin.py`: the toolbar action, `open_gps_import_dialog` and the messages;
  - `.github/workflows/ci.yml`: add `gps_import.py` to the mypy list;
  - `packages/nsgeo-qgis/tests/plugin_testing.py`: `synthetic_gps_dzt`.
- Test:
  - `packages/nsgeo-qgis/tests/pure/test_pure_gps_import.py`;
  - `tests/qgis/test_plugin_crs_rule.py`;
  - `tests/qgis/test_plugin_gps_import_dialog.py`.
  - `test_plugin_grid_dialog.py` must stay green, unchanged.

**Interfaces:**
- Consumes: Tasks 1–3 (`read_dzg`, `dzg_for`, `track_from_log`, `ToXY`, `Bridge`, `END_LIMIT_M`, `site_crs`, `set_site_crs`).
- Produces:

```python
# nsgeo_qgis/crs_rule.py  (qgis.core)
CRS_SCALE_WARN = 0.001
CRS_SCALE_REFUSE = 0.02
def crs_scale_error(crs: QgsCoordinateReferenceSystem, point: QgsPointXY) -> float | None: ...
def crs_check(crs: QgsCoordinateReferenceSystem, point: QgsPointXY | None) -> tuple[str | None, float | None]: ...  # None point: no scale check
def usable_at(crs: QgsCoordinateReferenceSystem, lonlat: QgsPointXY) -> tuple[str | None, float | None]: ...
def project_reason(crs: QgsCoordinateReferenceSystem, kind: str | None, scale_error: float | None) -> str: ...
def choose_crs(site: QgsCoordinateReferenceSystem | None, project: QgsCoordinateReferenceSystem,
               lonlat: QgsPointXY) -> tuple[QgsCoordinateReferenceSystem, str]: ...   # GridDialog._choose_crs's rule and notes, unchanged

# nsgeo_qgis/gps_import.py  (no Qt, no qgis)
@dataclass(frozen=True)
class GpsRow:
    path: Path
    line: Line | None              # placed at travel_shift 0; None when refused
    n_traces: int | None
    n_fixes: int
    n_fixed: int
    bridges: tuple[Bridge, ...]
    end_runs: tuple[float, float]
    refusal: str | None            # the Copy's refusal words, or None when ready
    @property
    def without_rtk_m(self) -> float: ...          # sum of bridge metres

def first_fixed_lonlat(path: Path) -> tuple[float, float] | None: ...   # (lon, lat) of the DZG's first RTK fix; None if unreadable or none
def plan_gps_rows(paths: Sequence[Path], to_xy: ToXY, crs: str,
                  taken: Callable[[Path], bool],
                  usable: Callable[[float, float], bool]) -> list[GpsRow]: ...
def shifted_lines(rows: Sequence[GpsRow], metres: float) -> list[Line]: ...   # ready rows only, travel_shift set
def import_messages(rows: Sequence[GpsRow], imported: int) -> list[str]: ...  # the Copy's after-import messages, in order

# tests/plugin_testing.py
def synthetic_gps_dzt(folder: Path, name: str, track: Sequence[tuple[int, float, float, int]],
                      n_traces: int = 200, **kw) -> Path: ...   # DZT via synthetic_dzt + DZG via tests.dzg_data.write_dzg; (trace, lat, lon, quality)
```

- **The plugin's `to_xy`:** a `QgsCoordinateTransform` from EPSG:4326 to the chosen CRS over `QgsProject.instance()`. It is applied point by point (about 100 fixes a line), and NaN stays NaN.
- **`usable`** is `crs_rule.usable_at(crs, lonlat)[0] is None`, at each row's own first RTK fix.
- **`taken`** is `lambda p: nsgeo.project.line_key(p, session.root, allow_absolute=True) in set(session.keys())`, the key `SiteSession.line_key` computes.

- [ ] **Step 1: Write the failing pure tests** (`test_pure_gps_import.py`, with a fake `to_xy` and synthetic files from `tests.synthetic` and `tests.dzg_data`):
  - `test_a_ready_row_carries_its_line_counts_bridges_and_ends`.
  - `test_rows_that_cannot_be_placed_are_refused_with_their_reason`. One row each gives `no DZG beside it`, `no RTK-fixed position`, `only one RTK-fixed position`, and `could not read it: …` for a DZG with a falling trace. Its `line` is None.
  - `test_a_file_already_in_the_site_is_refused_with_how_to_switch`.
  - `test_a_file_outside_the_site_crs_is_refused` (`usable` returns False; the refusal names the CRS).
  - `test_shifted_lines_sets_the_shift_on_ready_rows_only`.
  - `test_import_messages_follow_the_copy_in_order`: one bridge, one start run of 2.5 m, one refusal. The exact strings, in the Copy's order.
- [ ] **Step 2: Write the failing QGIS tests.**
  - `test_plugin_crs_rule.py`:
    - `test_a_metre_project_crs_usable_here_is_kept`: project EPSG:32632 at lon 10.5, lat 45.2 gives EPSG:32632 with note `""`.
    - `test_a_geographic_project_gets_the_utm_zone_with_a_note`: project EPSG:4326 at the same point gives EPSG:32632, with a note starting `"picked for you:"`.
    - `test_the_site_crs_wins_when_usable`.
  - `test_plugin_gps_import_dialog.py`:
    - `test_adding_files_plans_rows_and_shows_the_coordinates` (cells per the Copy).
    - `test_import_adds_gps_lines_sets_the_site_crs_and_applies_the_shift`: a grid-free site, two synthetic GPS files, spin 0.24. The result is two `TrackPlacement` lines with `travel_shift == 0.24`, `session.site_crs() == "EPSG:32632"`, and the messages are shown.
    - `test_an_import_into_a_site_with_grids_uses_their_crs`.
    - `test_import_after_the_site_was_replaced_adds_nothing` (`"The site changed; nothing was imported."`).
    - `test_the_tape_import_still_places_by_the_tapes_beside_a_dzg`: `ImportDialog` on a DZT with a DZG beside it gives a `GridPlacement`.
    - `test_the_toolbar_action_needs_an_open_site_but_no_grid`.
    - `test_importing_the_first_gps_survey` (real data, skips without `GPS_LINES`): all 60 import. `FILE__011`'s walked length is 29.5–30.6 m, and no message names a bridge.
- [ ] **Step 3: Run them and see each fail.**
- [ ] **Step 4: Implement `crs_rule.py`.** Move the methods' bodies out of `GridDialog` unchanged. `GridDialog._crs_check(crs, None)` keeps substituting the form's origin before delegating. Run `test_plugin_grid_dialog.py`: green and unchanged.
- [ ] **Step 5: Implement `gps_import.py`, the dialog and the plugin wiring** to P10/P11 and the Copy. Accept re-checks `session.json_path` against the one the dialog opened with. Then, in this order:
  1. `set_site_crs` if the site has none;
  2. `add_lines(shifted_lines(rows, spin))` in one call;
  3. `plugin.message` for each `import_messages` line.
- [ ] **Step 6: Run core + pure, the three new QGIS files plus `test_plugin_grid_dialog.py` and `test_plugin_import_dialog.py`, lint, and types (now with `gps_import.py`).**
- [ ] **Step 7: Commit** (`feat(plugin): Import GPS lines… — place DZTs along their RTK track (#134)`) and push.

---

