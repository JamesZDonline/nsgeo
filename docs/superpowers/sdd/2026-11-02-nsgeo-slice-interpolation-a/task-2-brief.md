### Task 2: Smoothing, the finished slice, and a north-up resample that drops nothing

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/smooth.py`
- Create: `packages/nsgeo-core/src/nsgeo/slices/finish.py`
- Modify, in `packages/nsgeo-core/src/nsgeo/slices/display.py`:
  - `to_north_up` gets the half-pitch rule.
  - Rewrite the docstring's "Nearest neighbour, not bilinear" paragraph, which names `fill`, so it names interpolation and smoothing as the user's visible choices.
- Modify: `packages/nsgeo-core/src/nsgeo/slices/frame.py:10-13`. The docstring says directional smoothing (interpolation spec §6) now covers the X/Y need, so cells stay square. Drop "the fill radius".
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`, the module docstring's Ruling AE paragraphs (lines 36–70). The rotated-frame loss is gone, because the export pitch now follows Ruling 2. Keep a one-line history note.
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py` to export `smooth`, `FinishSettings` and `finish_slice`.
- Test: `packages/nsgeo-core/tests/test_slices_smooth.py`, `packages/nsgeo-core/tests/test_slices_finish.py`, `packages/nsgeo-core/tests/test_slices_display.py`
- Test, adjust only: `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py`, `test_plugin_slice_layer.py`. Change only expectations that assumed pitch = cell on a **rotated** frame.

**Interfaces:**
- Consumes: `FillWeights`, `METHODS` (Task 1); `lattice_pixel` and `snap_azimuth` from `nsgeo.slices.site`. Import them inside `to_north_up`, because `site.py` imports `display.py`.
- Produces:
  ```python
  # smooth.py
  SMOOTH_TRUNCATE_SIGMAS: float = 4.0
  def smooth(values: np.ndarray, cell: float, sigma_x_m: float, sigma_y_m: float) -> np.ndarray: ...
      # (ny, nx) -> (ny, nx) float32; axis 1 is frame X, axis 0 is frame Y

  # finish.py
  @dataclass(frozen=True)
  class FinishSettings:
      method: str
      max_distance_m: float
      search_radius_m: float
      smooth_x_m: float = 0.0
      smooth_y_m: float = 0.0
  def finish_slice(values: np.ndarray, weights: FillWeights, cell: float, settings: FinishSettings) -> np.ndarray: ...
      # = smooth(weights.apply(values), cell, settings.smooth_x_m, settings.smooth_y_m)
  ```
- **`FinishSettings.__post_init__` raises `ValueError` for:**
  - a method not in `METHODS`;
  - any of the four distances non-finite or negative;
  - `search_radius_m < max_distance_m`.
- **How `smooth` works:**
  - It smooths `value × finite-mask` and the mask with the same truncated 1-D Gaussians, one per axis, then divides.
  - Cells that were NaN stay NaN.
  - A σ of 0 leaves that axis untouched.
- **`to_north_up`'s new pitch:**
  - `pixel = lattice_pixel(frame.cell, [snap_azimuth(frame.azimuth, hypot(frame.nx, frame.ny) * frame.cell, frame.cell)])`.
  - The pixel centres, width, height, epsilon and geotransform all use `pixel`.
  - An axis-aligned frame is unchanged.

- [ ] **Step 1: Write the failing tests.**

  `test_slices_smooth.py`:
  - `test_zero_sigma_is_the_identity`: equal arrays, including NaN positions.
  - `test_sigma_x_alone_spreads_a_spike_only_along_x`: spike `1.0` at (10, 10) in a 21 × 21 zero field, cell 0.1, σx 0.3. Only row 10 is non-zero.
  - `test_sigma_y_alone_spreads_a_spike_only_along_y`: the mirror image.
  - `test_a_spike_spreads_as_a_gaussian_of_the_given_sigma`: for `k` in 0–3, `out[10, 10 + k] / out[10, 10] ≈ exp(-(0.1 k)² / (2 · 0.3²))`, `rtol=1e-6`.
  - `test_blanks_stay_blank_and_nothing_new_is_filled`: same NaN mask before and after, σ 0.5 on both axes.
  - `test_an_edge_beside_a_blank_is_not_pulled_toward_zero`: a field of 5.0 whose right half is NaN. Every finite output ≈ 5.0.
  - `test_smoothing_is_affine_equivariant`.
  - `test_smooth_refuses_a_negative_sigma` (`ValueError`).

  `test_slices_finish.py`:
  - `test_finish_slice_interpolates_then_smooths`: equals `smooth(w.apply(v), cell, σx, σy)`.
  - `test_finish_settings_refuse_bad_values`: each `ValueError` case above.
  - `test_finish_slice_refuses_a_shape_mismatch`.

  `test_slices_display.py`:
  - `test_a_rotated_frame_is_resampled_at_half_the_cell`: azimuth 10.497, cell 0.2. `gt[1] == 0.1` and `gt[5] == -0.1`.
  - `test_no_cell_is_dropped_on_a_rotated_frame`, parametrized over azimuths 10.497, 33, 45 and 77.3:
    - `values = np.arange(nx * ny).reshape(ny, nx)` on a 25 × 40 frame;
    - the set of finite output values equals `set(range(nx * ny))`.
  - `test_an_axis_aligned_frame_keeps_the_full_pitch`: azimuths 0, 90 and 180 give `gt[1] == cell`, and azimuth 0 keeps today's exact shape.
  - `test_a_hair_off_axis_frame_keeps_the_full_pitch`: azimuth `1e-7` on a 20 m frame.

- [ ] **Step 2: Run them and see them fail.** Run `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_smooth.py packages/nsgeo-core/tests/test_slices_finish.py packages/nsgeo-core/tests/test_slices_display.py -q -p no:cacheprovider`. Expected: FAIL. The modules are missing, and a rotated frame comes back at `gt[1] == cell`.

- [ ] **Step 3: Implement** `smooth`, `FinishSettings`, `finish_slice` and the `to_north_up` pitch, and make the docstring edits listed under Files.

- [ ] **Step 4: Run the tests and see them pass.** Run the Step 2 command. Then run the full core + pure suite.

- [ ] **Step 5: Run the affected QGIS files.** Run `test_plugin_slice_export.py`, `test_plugin_slice_layer.py`, `test_plugin_site_export.py` and `test_plugin_slices_dock.py`. Fix only expectations that assumed pitch = cell on a rotated frame, and list each one in your report. Any other failure is a bug in this task.

- [ ] **Step 6: Run ruff and mypy, then commit.**

  ```bash
  git commit -m "feat(slices): Gaussian X/Y smoothing, the finished slice, and a north-up resample that keeps every cell (interpolation spec §6, §8)"
  git push
  ```

---

