### Task 3: Plugin settings, saved settings, and the Interpolation panel

Everything in this task is **additive**. The dock still uses Fill radius until Task 4, so `radius_spacings` stays accepted everywhere for now.

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`. Add the constants, `SliceFinish` and `FINISH_FIELDS`. Add `MemoryEstimate.weights_bytes` and count it in `total_bytes`. `estimate_memory` fills it in.
- Modify: `packages/nsgeo-core/src/nsgeo/project.py`, in `_RESOLUTION_KEYS` and `_clean_resolution`:
  - add `max_distance_spacings`, `smooth_x_m` and `smooth_y_m` as numbers, each dropped if negative;
  - add `method` as a string, kept only if it is in `METHODS`;
  - the return type becomes `dict[str, float | str]`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py`:
  - `_merge_resolution` keeps a `str` value as is, and floats as now.
  - `remember_slice_resolution` and `remember_site_resolution` gain the keyword arguments `method: str | None`, `max_distance_spacings`, `smooth_x_m` and `smooth_y_m`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`, on `ViewSettings`:
  - new fields, each with its default;
  - a `finish` property;
  - `to_dict` / `from_dict` compatibility both ways.
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/finish_panel.py` with `FinishPanel` and `busy_cursor`.
- Test:
  - `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py`
  - `packages/nsgeo-core/tests/test_project.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py`
  - Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_finish_panel.py`

**Interfaces:**
- Consumes: `METHODS`, `NEIGHBOURS_PER_QUADRANT` (Task 1); `FinishSettings` (Task 2).
- Produces, in `slices_plan.py`:
  ```python
  DEFAULT_METHOD = "kriging"
  DEFAULT_MAX_DISTANCE_SPACINGS = 0.5
  SEARCH_RADIUS_SPACINGS = 2.0
  METHOD_LABELS: dict[str, str]          # ordered as METHODS, labels from Global Constraints
  WEIGHT_BYTES_PER_CELL = 4 * NEIGHBOURS_PER_QUADRANT * 8   # int32 source + float32 weight
  FINISH_FIELDS = ("method", "max_distance_spacings", "smooth_x_m", "smooth_y_m")

  @dataclass(frozen=True)
  class SliceFinish:
      method: str = DEFAULT_METHOD
      max_distance_spacings: float = DEFAULT_MAX_DISTANCE_SPACINGS
      smooth_x_m: float = 0.0
      smooth_y_m: float = 0.0
      def in_metres(self, spacing_m: float) -> FinishSettings: ...
          # max_distance_m = max_distance_spacings * spacing_m
          # search_radius_m = max(SEARCH_RADIUS_SPACINGS * spacing_m, 2 * max_distance_m)
          # ValueError if spacing_m <= 0
      def updated(self, fields: Mapping[str, object]) -> SliceFinish: ...
          # lays FINISH_FIELDS from `fields` over self; a bad method or a negative or
          # non-finite number is ignored, as is every other key
  ```
- Produces, in `ViewSettings`:
  - New fields: `method: str = DEFAULT_METHOD`, `max_distance_spacings: float = DEFAULT_MAX_DISTANCE_SPACINGS`, `smooth_x_m: float = 0.0`, `smooth_y_m: float = 0.0`.
  - `radius_m` stays.
  - `finish` property → `SliceFinish`.
  - `to_dict` writes all ten keys.
  - `from_dict` reads `radius_m` with `.get(..., 0.0)`. It reads the four new keys only when `"method"` is present, through `SliceFinish().updated(doc)`; otherwise it uses the defaults.
- Produces, in `ui/finish_panel.py`:
  ```python
  @contextmanager
  def busy_cursor() -> Iterator[None]: ...     # wait cursor; always restored, even on an exception

  class FinishPanel(QGroupBox):                 # title "Interpolation"
      edited = pyqtSignal(str, object)          # (field, value): only a user's edit
      def __init__(self, parent: QWidget | None = None, *, metres_label: bool) -> None: ...
      method_combo: QComboBox                   # labels from METHOD_LABELS, itemData = key
      max_distance_spin: QDoubleSpinBox         # 0–10, 2 dp, step 0.25, suffix " × line spacing"
      max_distance_metres: QLabel               # "= 0.25 m"; exists only when metres_label
      smooth_x_spin: QDoubleSpinBox             # 0–5, 2 dp, step 0.05, suffix " m"
      smooth_y_spin: QDoubleSpinBox             # same
      def value(self) -> SliceFinish: ...
      def set_value(self, finish: SliceFinish) -> None: ...   # quiet: emits nothing
      def set_spacing(self, spacing_m: float | None) -> None: ...  # refreshes the metres label; "" for None
  ```
- **Panel rows:** `Method`, `Max distance to data` (with the metres label beside it, when present), `Smoothing X`, `Smoothing Y`.
- **Panel behaviour:** `max_distance_spin` is disabled while the method is `"none"`.
- **Tooltip copy, verbatim:**
  - **Method:** `"How cells that no line crossed are filled from the cells around them.\nKriging: a weighted average that follows how values vary with distance; the usual choice.\nInverse distance: a weighted average in which nearer cells count more.\nNone: show only the cells a line crossed."`
  - **Max distance to data:** `"Cells farther than this from any line are left blank, so the edge of the survey or a missing line is never filled in.\nHalf a line spacing just closes the gap between neighbouring lines; raise it if a line strayed and left a blank stripe."`
  - **Smoothing X:** `"Blurs the slice along the grid's X axis by this distance (the standard deviation of a Gaussian), after filling. 0 is off.\nOnly smoothing changes the cells a line crossed."`
  - **Smoothing Y:** the same with `Y`.

- [ ] **Step 1: Write the failing tests.**

  Pure (`test_pure_slices_plan.py`):
  - `test_slice_finish_defaults`: `SliceFinish() == SliceFinish("kriging", 0.5, 0.0, 0.0)`.
  - `test_in_metres_scales_by_the_spacing_and_sets_the_search_radius`:
    - spacing 0.5 → `max_distance_m == 0.25` and `search_radius_m == 1.0`;
    - `max_distance_spacings=3.0` → `search_radius_m == 3.0`.
  - `test_in_metres_refuses_a_spacing_that_is_not_positive`.
  - `test_updated_lays_known_fields_over_and_ignores_the_rest`:
    - `{"method": "idw", "radius_spacings": 0.5, "cell": 0.2}` → only `method` changes.
  - `test_updated_ignores_a_bad_method_or_number`: `"bogus"`, `3`, `-1.0`, `nan` and `True`.
  - `test_the_estimate_counts_the_fill_weights` (Review Focus 5):
    - `estimate_memory(0, 1000, 10).weights_bytes == 1000 * WEIGHT_BYTES_PER_CELL`;
    - `total_bytes` includes it.

  Core (`test_project.py`):
  - `test_remembered_finish_fields_are_kept_and_cleaned`:
    - kept: `"kriging"`, `0.75`, `0.3`;
    - dropped: `"bogus"`, `3`, `-1`, `nan`.
  - `test_an_old_radius_spacings_still_loads`. Task 5 flips this test.

  QGIS:
  - `test_plugin_session.py`:
    - `test_remembering_a_method_keeps_it_a_string_and_marks_dirty_once`;
    - `test_remembering_the_same_method_again_does_not_mark_dirty`.
  - `test_plugin_slice_export.py`:
    - `test_view_settings_round_trip_the_finish`;
    - `test_a_0_2_0_view_record_loads_with_the_new_defaults` (a record with only the six 0.2.0 keys, `radius_m: 0.25`);
    - `test_a_view_record_with_a_bad_method_falls_back_to_the_defaults`;
    - `test_a_record_from_this_build_still_loads_in_0_2_0`. Its fixture is a verbatim copy of 0.2.0's `ViewSettings.from_dict` body, `git show v0.2.0:packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`, as a local function. It must not raise on `ViewSettings(...).to_dict()`.
  - `test_plugin_finish_panel.py`:
    - `test_the_panel_starts_at_the_defaults`: `value() == SliceFinish()`, and the combo's labels match `METHOD_LABELS` in order.
    - `test_the_spins_have_the_pinned_ranges_steps_and_suffixes`.
    - `test_set_value_is_quiet_and_round_trips`.
    - `test_a_user_edit_emits_the_field_and_value`: picking IDW emits `("method", "idw")`; setting the spin to 0.75 emits `("max_distance_spacings", 0.75)`; likewise for both smoothing spins.
    - `test_max_distance_is_disabled_for_none`.
    - `test_the_metres_label_follows_the_spacing`: `"= 0.25 m"` at spacing 0.5; `""` for None.
    - `test_the_tooltips_are_the_pinned_copy`.
    - `test_busy_cursor_is_restored_after_an_exception`: `QApplication.overrideCursor()` is None afterwards.

- [ ] **Step 2: Run them and see them fail.** Run each file with its tier's command. Expected: FAIL on missing names.

- [ ] **Step 3: Implement**, as specified in the Interfaces block.

- [ ] **Step 4: Run the new tests, then every suite, and see them pass.** Then run ruff and mypy. `slices_plan.py` is in the mypy set.

- [ ] **Step 5: Commit.**

  ```bash
  git commit -m "feat(slices): SliceFinish settings, saved both ways with 0.2.0, and the Interpolation panel (interpolation spec §8)"
  git push
  ```

---

