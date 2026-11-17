### Task 1: The prepared volume (core)

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/volume.py`
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py` (add the new names to the imports and `__all__`, sorted)
- Test: `packages/nsgeo-core/tests/test_slices_volume.py`

**Interfaces:**
- Consumes:
  - `SliceCube.level(k) -> (ny, nx)`; `SliceCube.coverage()`; `SliceCube.provenance.transform`
  - `finish_slice(values, weights, cell, settings)`; `FinishSettings`; `SliceFill`
  - `smooth(values, cell, sigma_x_m, sigma_y_m)`
  - `ZAxis`; `VelocityModel.depth_at`, `VelocityModel.is_constant`
- Produces:
  - `VolumeSettings(period_ns: float = 2.5, blur_m: float = 0.1, trend_m: float = 0.15)`: frozen, validated, with `to_dict() -> dict` and `from_dict(doc) -> VolumeSettings`. `from_dict` lays valid fields over the defaults, like `SliceFinish.updated`.
  - `class VolumeStopped(Exception)`
  - `fill_levels(cube: SliceCube, weights: SliceFill, finish: FinishSettings, out: np.ndarray, *, progress: Callable[[int, int], bool] | None = None) -> None`. It writes squared amplitude, float32, NaN where nothing was filled, into `out` (shape `(nz, ny, nx)`; `out` may be an `np.lib.format.open_memmap`). A cube whose `provenance.transform == "amp_square"` goes in as it is; any other transform is squared (spec call 3). `progress(k + 1, nz)` returning False raises `VolumeStopped`.
  - `depth_axis(z: ZAxis, velocity: VelocityModel) -> tuple[np.ndarray, np.ndarray]`: `(depths_m, source_level)`, both of shape `(nd,)`. Depths are uniform, start at the first level with `t >= 0`, and are shallow first. `source_level` is the fractional source level of each depth.
  - `PreparedVolume`: a frozen dataclass with `depths_m`, `trend` (`(nd,)` float64), `covered` (`(ny, nx)` bool), `settings`, and method `slab(j0: int, j1: int) -> tuple[np.ndarray, np.ndarray]`. The method returns `(amplitude, strength)`, each `(j1 - j0, ny, nx)` float32 with NaN off `covered`.
  - `prepare_volume(filled: np.ndarray, z: ZAxis, velocity: VelocityModel, cell: float, settings: VolumeSettings, *, slab_levels: int = 64) -> PreparedVolume`

- [ ] **Step 1: Write the failing tests** in `test_slices_volume.py`. The synthetic cubes use `SliceCube.from_dense` with `plan_fill(populated, cell, "none", 0, 0)`. Real data comes from `tests/real_lines.py`: `radargrams()` goes through `amp_envelope`, binned at `CELL = 0.2` on `AXIS`.

```python
def test_settings_defaults_validation_and_round_trip():
    s = VolumeSettings()
    assert (s.period_ns, s.blur_m, s.trend_m) == (2.5, 0.1, 0.15)
    for bad in ({"period_ns": 0.0}, {"trend_m": -1.0}, {"blur_m": float("nan")}):
        with pytest.raises(ValueError):
            VolumeSettings(**bad)
    assert VolumeSettings.from_dict(s.to_dict()) == s
    assert VolumeSettings.from_dict({"period_ns": "x", "blur_m": 0.2}) == VolumeSettings(blur_m=0.2)

def test_fill_levels_squares_unless_the_cube_is_already_squared():
    # 3 levels, 2x2 cells, one uncovered. "amp_envelope" -> out == v**2; "amp_square" -> out == v.
    # The uncovered cell is NaN at every level.

def test_fill_levels_stops_when_progress_says_so():
    calls = []
    with pytest.raises(VolumeStopped):
        fill_levels(cube, weights, finish, out, progress=lambda k, n: calls.append(k) or k < 2)
    assert calls == [1, 2]

def test_rms_turns_one_reflection_into_one_hump():
    # One column: a 400 MHz Ricker at 20 ns, sampled at 0.1 ns, squared.
    # Count local maxima above half the column max:
    # the squared input has >= 2; slab()'s amplitude has exactly 1, within 1.5 ns of 20 ns.

def test_depth_axis_constant_velocity_is_the_levels_from_time_zero():
    z = ZAxis(t0_ns=-0.476, dz_ns=0.1, nz=455)
    depths, src = depth_axis(z, VelocityModel.constant(0.071))
    assert depths[0] >= 0 and src[0] == 5          # the first level with t >= 0
    assert np.allclose(np.diff(depths), 0.071 * 0.1 / 2)

def test_layered_velocity_gives_a_uniform_depth_axis():
    v = VelocityModel(layers=((0.0, 0.10), (20.0, 0.06)))
    depths, src = depth_axis(ZAxis(0.0, 0.2, 300), v)
    assert np.allclose(np.diff(depths), np.diff(depths)[0])
    assert np.all(np.diff(src) > 0) and src[-1] <= 299

@needs_real_files
def test_strength_is_about_one_at_every_depth_on_real_lines():
    # Bin CAMPUS lines 0-9 at CELL 0.2 on AXIS; fill with finish method "idw";
    # prepare with VolumeSettings(). For at least 90% of depths,
    # the median of strength over covered cells is within [0.7, 1.3].

def test_uncovered_cells_are_nan_in_both_arrays_and_blur_keeps_holes():
    # covered == False columns are NaN in amplitude and strength;
    # a covered cell next to a hole is finite.

def test_slabs_equal_the_whole():
    a0, s0 = vol.slab(0, nd)
    parts = [vol.slab(j, min(j + 7, nd)) for j in range(0, nd, 7)]
    np.testing.assert_array_equal(np.concatenate([p[0] for p in parts]), a0)
    np.testing.assert_array_equal(np.concatenate([p[1] for p in parts]), s0)
```

- [ ] **Step 2: Run them and see them fail**

Run: core command on `packages/nsgeo-core/tests/test_slices_volume.py`
Expected: FAIL. ImportError for `nsgeo.slices.volume`.

- [ ] **Step 3: Implement `volume.py`.** The algorithm, as the trial ran it (spec §2.1, `~/nsgeo-m4-check/m16-paraview-trial/envelope_try.py`):
  1. `w = max(1, round(settings.period_ns / z.dz_ns))` source levels.
  2. **RMS:** each source level's amplitude is `sqrt(mean of filled over the w levels centred on it)`, edge-padded. Compute it from a float64 cumulative sum over a slab read with `w // 2 + 1` levels of overlap.
  3. **Blur:** `smooth(level, cell, blur_m, blur_m)` on each RMS level. NaN stays NaN.
  4. **To depth:** output level `j` blends the two RMS levels either side of `source_level[j]`. A constant velocity gives integer positions, so nothing is blended.
  5. **Balance:** `prepare_volume` makes one pass over all output levels to take the median over `covered` of each level's amplitude. It then takes a moving mean over `max(1, round(trend_m / depth_step))` levels, edge-padded, as `trend`. `slab` returns `strength = amplitude / trend[j]`, with NaN where `trend <= 0`.

  `covered` is `np.isfinite(filled[k])` at the first level with `t >= 0`. Coverage and fill reach are the same at every level.

  `slab` recomputes steps 2–4 for its own range, so no second full copy of the cube is held.

- [ ] **Step 4: Run them and see them pass.** Then run the whole core suite, ruff and mypy.

Run: core command on `packages/nsgeo-core/tests`
Expected: all pass. `test_public_api.py` still passes, because `slices` is already public.

- [ ] **Step 5: Commit**

```bash
git add packages/nsgeo-core/src/nsgeo/slices/volume.py packages/nsgeo-core/src/nsgeo/slices/__init__.py packages/nsgeo-core/tests/test_slices_volume.py
git commit -m "feat(core): the prepared volume — RMS over a wave period, blur, depth-trend balance (M16 A)"
```

---

