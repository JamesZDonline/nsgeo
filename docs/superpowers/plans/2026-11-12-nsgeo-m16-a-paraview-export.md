# M16 Plan A: Prepared Volume and Export for ParaView Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One action exports any grid to a folder that ParaView opens ready to explore. The folder holds:
- the prepared volume (an envelope-style cube, balanced against its depth trend), shown as a cloud, an isosurface and three slices;
- the grid's picks;
- its survey lines.

**Architecture:**
- **The core** (numpy only) gets:
  - `nsgeo.slices.volume`: fill, square, RMS over one wave period, sideways blur, a uniform depth axis, depth-trend balance. It works in slabs.
  - `nsgeo.vtkxml`: streaming VTK XML writers.
- **The plugin** gets:
  - a pure module `paraview_scene.py` (the per-grid volume record, export.json, picks and lines as points, the scene templates);
  - `paraview_export.py`, which runs the export with QGIS: lines, the cube at the grid's own 3-D resolution, a cached fill, writing, replacing the folder;
  - a dialog opened from a Slices panel button.

  It follows the existing exports: synchronous, behind the window-modal `_export_progress` dialog, which keeps QGIS responsive and cancellable.

**Tech Stack:** Python 3.9+ and numpy (core); QGIS 3.40 / 3.44 / 4.2 with PyQt5 and PyQt6 (plugin); pytest; ParaView 6.2.1's `pvpython` for one optional test.

**Spec:** `docs/superpowers/specs/2026-11-11-nsgeo-m16-3d-design.md`. Read it first:
- §2 holds the measured recipe and every number used below;
- §4 holds the decisions;
- §5.1 and §5.2 are the behaviour this plan builds.

## Global Constraints

- **Run every test from the worktree root with `PYTHONPATH=packages/nsgeo-core/src`.** Below, `R=/home/jameszd/Documents/Github/archaeo_geophysics`.
  - **Core and pure:** `PYTHONPATH=packages/nsgeo-core/src $R/.venv/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`
  - **QGIS:** `PYTHONPATH=packages/nsgeo-core/src QT_QPA_PLATFORM=offscreen $R/.venv-qgis/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`. The whole suite takes about 12 minutes, so run single files while iterating.
- **Lint as CI does,** with line length 100:
  - `$R/.venv/bin/ruff check .`
  - `$R/.venv/bin/ruff format --check .`
  - `$R/.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py packages/nsgeo-qgis/nsgeo_qgis/line_edit.py`

  mypy checks the whole core.
- **The core uses numpy only.** It has a Python 3.9 floor: `from __future__ import annotations`, no `zip(strict=...)` and no `match`. No new dependency anywhere. The CI pure tier runs 3.9.
- **No ParaView code lives in a `.py` file inside `packages/`.** ruff (F403), mypy and three AST-scanning tests would all reject it. Scene files ship as `.txt` templates in `packages/nsgeo-qgis/nsgeo_qgis/paraview/`. `build_zip.py` only ships tracked `.py`, `.txt` and `.md` files.
- **Plugin boundary.** Arithmetic and message text live in the core, in `slices_plan.py` or in `paraview_scene.py`, never in widgets.
- **Qt.**
  - Use fully qualified enums.
  - Every Qt-invoked slot guards its body with `try/except Exception`.
  - Every new `pyqtSignal` is connected (`tests/pure/test_no_orphan_signals.py`).
  - Modal dialogs in tests go through `drive_dialog` / `answer_modal` (`tests/qgis/conftest.py`).
- **Never two line preparations at once:** they segfault (`slices_engine.py` docstring, lines 86–111). A standalone engine starts only when `dock.engine.has_live_task` and `dock.site_engine.has_live_task` are both False.
- **Exporting never changes what the Slices panel shows** (spec call 2).
- **No site coordinates, real survey files or site pictures are committed.** Sunnyside's origin and the trial prototypes stay outside the repo.
- **Commits:**
  - every message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - push each one to `origin nsgeo-m16` as you make it;
  - the sandbox cannot resolve github.com, so pushes need it turned off.
- **Other open branches touch the same files:**
  - `nsgeo-m15-cut-anywhere` (`slices_dock.py`, `plugin.py`, `layers.py`);
  - `nsgeo-fine-cells-export` (`site_export.py`, `plugin.py`);
  - `nsgeo-auto-destagger` (placement, Edit lines).

  Before Task 3, run `git fetch && git merge origin/main`.

## Before Task 1 (coordinator)

- Symlink the real data into `packages/nsgeo-core/tests/data/local/` file by file. `README.md` there is tracked: link the files, not the folder, and give `with-dzg/` its own folder of per-file links.
- Record a baseline: the core and pure suites, then QGIS.
- Point the optional ParaView test at the user's install: `export NSGEO_PVPYTHON=/home/jameszd/Documents/Software/ParaView-6.2.1-MPI-Linux-Python3.12-x86_64/bin/pvpython`.

## Review Focus

These are the inputs the spec implies, but none of its tests feed. Each is pinned by a test in the task named.

1. **A preset with no `time_zero`** (radar clock): the picks must still land on their reflections. Each pick time moves from its row's `zero_ns` to the cube's clock. *Task 3:* `test_picks_land_on_the_cube_clock_with_and_without_time_zero`.
2. **A grid with no picks:** `picks.vtp` is still a valid file, and the scene still opens. *Task 2:* `test_an_empty_point_set_is_a_valid_file`. *Task 2 pvpython test:* run on an export with no picks.
3. **Cancelling halfway, or failing:** the previous export of that grid stays intact, and no half-written folder looks complete. *Task 3:* `test_a_cancelled_export_leaves_the_previous_one_intact`.
4. **A grid velocity with two layers:** the volume's depth axis is uniform, and picks use the same depth conversion. *Task 1:* `test_layered_velocity_gives_a_uniform_depth_axis`. *Task 3:* `test_pick_depths_use_the_volume_velocity`.
5. **A 3-D cell size so fine the frame exceeds `MAX_FRAME_CELLS` (4,000,000)**: the dialog refuses it and says why, the way the Slices panel does. Nothing is written. *Task 4:* `test_a_too_fine_cell_is_refused_before_export`.

---

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

### Task 2: The ParaView files: VTK writers (core) and the scene (plugin, pure)

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/vtkxml.py` (a public module, with `__all__`)
- Modify: `packages/nsgeo-core/tests/test_public_api.py` (add `"vtkxml"` to `EXPECTED_PUBLIC`)
- Create: `packages/nsgeo-core/tests/vtk_reader.py` (a test helper: a numpy reader for the appended-raw format)
- Test: `packages/nsgeo-core/tests/test_vtkxml.py`
- Create: `packages/nsgeo-qgis/nsgeo_qgis/paraview_scene.py` (no qgis or PyQt imports)
- Create the templates in `packages/nsgeo-qgis/nsgeo_qgis/paraview/`:
  - `open_scene.py.txt`
  - `open.sh.txt`
  - `open.bat.txt`
  - `README.md.txt`
- Test: `packages/nsgeo-qgis/tests/pure/test_paraview_scene.py`

**Interfaces:**
- Produces (core `nsgeo.vtkxml`):
  - `write_image_data(path: Path, *, origin: tuple[float, float, float], spacing: tuple[float, float, float], shape: tuple[int, int, int], arrays: Sequence[tuple[str, Callable[[], Iterator[np.ndarray]]]]) -> int`
    - `shape` is `(nx, ny, nz)`.
    - Each callable yields float32 chunks in VTK order: x fastest, then y, then z rising.
    - The file is written to `path` plus `.part`, then renamed.
    - If an array's chunks total anything but `nx*ny*nz` values, it raises `ValueError` and leaves no file.
    - Returns the bytes written.
  - `write_poly_data(path: Path, points: np.ndarray, point_data: Mapping[str, np.ndarray], *, verts: Sequence[Sequence[int]] = (), lines: Sequence[Sequence[int]] = (), polys: Sequence[Sequence[int]] = ()) -> int`
  - `image_data_bytes(shape: tuple[int, int, int], n_arrays: int) -> int`: the exact payload plus a fixed header allowance (4096).
- Produces (plugin `paraview_scene.py`):
  - `SCENE_FILES = ("open_scene.py", "open.sh", "open.bat", "README.md")`
  - `write_scene_files(folder: Path, record: dict, paraview_path: str) -> None`. It writes `export.json` (`record`, sorted keys, indent 2) and the four templates, with `{{PARAVIEW}}` replaced by `paraview_path or "paraview"`. `open.sh` is made executable.
  - `scene_record(**fields) -> dict`. It returns a `dict` with exactly these keys:
    - `grid`, `title`, `stretch`
    - `crs`, `origin`, `azimuth_deg`
    - `cell_m`, `dz_ns`, `depth_step_m`, `max_depth_m`
    - `source` (preset, transform, lines, time_base)
    - `fill` (FinishSettings fields), `volume` (VolumeSettings dict)
    - `iso_level` (2.5), `cloud_ramp` (`[[1.8, 0.0], [5.0, 0.6]]`), `strength_range` (`[0.0, 5.0]`), `amplitude_range` (`[0.0, p99]`)
    - `slices` (depth, x, y of the three starting slices)
    - `n_picks`, `paraview_checked` (`"6.2.1"`), `nsgeo_version`, `written_utc`

- [ ] **Step 1: Write the failing tests.**

```python
# test_vtkxml.py
def test_image_data_round_trips_in_vtk_order(tmp_path):
    vol = np.arange(4 * 3 * 2, dtype=np.float32).reshape(2, 3, 4)   # (nz, ny, nx)
    chunks = lambda: iter([vol[0].ravel(), vol[1].ravel()])
    n = write_image_data(tmp_path / "c.vti", origin=(0.025, 0.025, -1.0), spacing=(0.05, 0.05, 0.01),
                         shape=(4, 3, 2), arrays=[("strength", chunks), ("amplitude", chunks)])
    doc = read_vtk_xml(tmp_path / "c.vti")
    assert doc["WholeExtent"] == (0, 3, 0, 2, 0, 1) and doc["Spacing"] == (0.05, 0.05, 0.01)
    np.testing.assert_array_equal(doc["point_data"]["strength"], vol.ravel())
    assert n == (tmp_path / "c.vti").stat().st_size

def test_a_short_array_raises_and_leaves_no_file(tmp_path):
    # one chunk of 23 values for shape (4, 3, 2): ValueError; neither c.vti nor c.vti.part exists
def test_poly_data_round_trips_points_verts_lines_and_polys(tmp_path):
    # 5 points, 1 vert, one 3-point line, one triangle: the reader returns the same points,
    # connectivity/offsets and point arrays
def test_an_empty_point_set_is_a_valid_file(tmp_path):
    write_poly_data(tmp_path / "p.vtp", np.empty((0, 3)), {"true_depth_m": np.empty(0, np.float32)})
    assert read_vtk_xml(tmp_path / "p.vtp")["NumberOfPoints"] == 0
def test_image_data_bytes_is_within_the_header_allowance_of_the_file(tmp_path):
    # file size <= image_data_bytes(shape, n) and >= image_data_bytes(shape, n) - 4096

# test_paraview_scene.py
def test_write_scene_files_writes_every_file_and_the_record(tmp_path):
    write_scene_files(tmp_path, scene_record(**FIELDS), "/opt/pv/bin/paraview")
    assert {p.name for p in tmp_path.iterdir()} == {"export.json", *SCENE_FILES}
    assert "/opt/pv/bin/paraview" in (tmp_path / "open.sh").read_text()
    assert os.access(tmp_path / "open.sh", os.X_OK)
    assert json.loads((tmp_path / "export.json").read_text())["iso_level"] == 2.5

def test_no_template_is_a_py_file():
    names = [p.name for p in (PLUGIN / "paraview").iterdir()]
    assert names and all(n.endswith(".txt") for n in names)

@pytest.mark.skipif(not os.environ.get("NSGEO_PVPYTHON"), reason="set NSGEO_PVPYTHON to a pvpython")
def test_the_scene_opens_in_pvpython(tmp_path):
    # Build a 20x16x30 export with nsgeo.vtkxml: a strength blob at the centre,
    # zero picks and one line. Then run
    # [NSGEO_PVPYTHON, "--force-offscreen-rendering", CHECK], where CHECK is a script
    # written to tmp_path that does the following:
    #   set NSGEO_SCENE_DIR;
    #   exec open_scene.py WITHOUT defining __file__ (as the ParaView window does);
    #   print the registration names;
    #   save a 400x300 screenshot.
    # Assert returncode 0 and no "Traceback" in stderr.
    # Assert the names include "Cloud", "Isosurface", "Isosurface inside a box",
    # "Depth slice", "Slice along a line", "Slice across the lines", "Your picks",
    # "Survey lines" and "Box around the cube".
    # Assert the screenshot is > 10 kB.
```

- [ ] **Step 2: Run them and see them fail**

Run: the core command on `test_vtkxml.py`, then the pure command on `test_paraview_scene.py`.
Expected: ImportError.

- [ ] **Step 3: Implement `nsgeo/vtkxml.py`.**
  - **Format:** VTK XML 1.0, `byte_order="LittleEndian"`, `header_type="UInt64"`, with one `<AppendedData encoding="raw">_` block. Each array is an 8-byte length followed by its bytes.
  - **ImageData:** carries `Direction="1 0 0 0 1 0 0 0 1"`, and the `Scalars` attribute names the first array.
  - **PolyData:** writes `Verts`, `Lines` and `Polys` as `Int64` `connectivity`/`offsets` pairs, always present, even when empty.
  - **Reference:** the trial's `export_vtk.py` writer is the prototype. Streaming means the XML header is written first, and each array's length is known from `shape`.

  Then write `tests/vtk_reader.py`: about 40 lines that parse the header with `xml.etree` and slice the appended block.

- [ ] **Step 4: Write the templates and `paraview_scene.py`.**
  - **`open_scene.py.txt`** is the trial's `grid1-envelope/open_envelope.py`, changed so that:
    - it reads `export.json` from `HERE` for every number and name (title, stretch, iso level, ramps, ranges, slice positions);
    - `HERE` is found from `__file__`, else `$NSGEO_SCENE_DIR`, else `os.getcwd()`;
    - the arrays are `strength`, `amplitude` and `true_depth_m`;
    - the pipeline names are exactly those the pvpython test lists;
    - colour scales are set last;
    - it uses `try_set` and `apply_preset` with fallbacks, `ColorBy` is never called with `None`, and legend formats are `{:.1f}` (spec §2.3).
  - **`open.sh.txt`** does `cd` to its folder and runs `NSGEO_SCENE_DIR="$HERE" exec "{{PARAVIEW}}" --script="$HERE/open_scene.py"`.
  - **`open.bat.txt`** is the Windows equivalent.
  - **`README.md.txt`** is the trial's `THINGS-TO-TRY.md`, made generic: no Sunnyside numbers, and the stretch and levels read "as stated in the title / export.json".

- [ ] **Step 5: Run the tests and see them pass,** including the pvpython test with `NSGEO_PVPYTHON` set. Then run ruff, mypy and `tests/pure/test_build_zip.py`.

Expected: all pass. The zip test passes because the templates are `.txt`.

- [ ] **Step 6: Commit**

```bash
git add packages/nsgeo-core/src/nsgeo/vtkxml.py packages/nsgeo-core/tests/test_public_api.py packages/nsgeo-core/tests/vtk_reader.py packages/nsgeo-core/tests/test_vtkxml.py packages/nsgeo-qgis/nsgeo_qgis/paraview_scene.py packages/nsgeo-qgis/nsgeo_qgis/paraview packages/nsgeo-qgis/tests/pure/test_paraview_scene.py
git commit -m "feat: streaming VTK writers and the ParaView scene files (M16 A)"
```

---

### Task 3: The export: per-grid 3-D settings, the cube at its own resolution, writing the folder

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/project.py`
  - `_clean_slice_source` keeps a `"volume"` entry;
  - a new `_clean_volume` keeps exactly `cell`, `dz_ns`, `transform`, `stretch`, `period_ns`, `blur_m` and `trend_m`, each validated the way `_clean_resolution` validates.
- Modify: `packages/nsgeo-core/tests/test_project.py` (extend `test_slice_sources_and_site_view_round_trip` and `test_a_wrong_typed_inner_value_reads_as_unset`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py`: add `volume_record(grid_id) -> dict` and `remember_volume(grid_id, **fields) -> None`. The latter marks the site dirty, like `remember_slice_resolution`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`: add `VolumeChoice` and `volume_choice()`.
- Create: `packages/nsgeo-qgis/nsgeo_qgis/paraview_export.py`
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_volume_choice.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_export.py`

**Interfaces:**
- Consumes:
  - from Task 1: `fill_levels`, `prepare_volume`, `VolumeSettings`, `VolumeStopped`;
  - from Task 2: `write_image_data`, `write_poly_data`, `image_data_bytes`, `write_scene_files`, `scene_record`;
  - existing: `SliceEngine`, `SourceChoice`, `SliceFinish`, `site_scope.default_preset` / `source_keys` / `transform_value`, `CubeFrame.for_grid`, `ZAxis.from_range`, `plan_line`, `build_cube`, `plan_fill`, `session.picks_for`, `session.resolved_velocity`, `retime_ns`, `time_base_of`.
- Produces:
  - `VolumeChoice(cell: float, dz_ns: float, transform: str, stretch: float = 3.0, settings: VolumeSettings = VolumeSettings())`: frozen, validated, with `to_record() -> dict`.
  - `volume_choice(record: Mapping | None, *, cell_default: float, dz_default: float, transform_default: str) -> VolumeChoice`. This is spec decision 8: the first use takes the defaults, and after that the record wins, field by field.
  - `export_size_bytes(nx: int, ny: int, nd: int) -> int` in `slices_plan.py`: `image_data_bytes((nx, ny, nd), 3)`. Picks and lines are small enough to ignore.
  - `class ParaViewExport` in `paraview_export.py`:
    - `__init__(self, session, dock)`
    - `defaults(grid_id) -> VolumeChoice`. It returns `volume_choice(session.volume_record(grid_id), ...)` with these defaults:
      - `cell_default`: `session.slice_resolution(grid_id)["cell"]` if remembered, else `default_cell(grid.default_spacing, max(0.01, smallest_safe_cell(...)))` (as `SlicesDock._seed_resolution_defaults` does);
      - `dz_default`: the remembered `dz_ns`, else the first line's `header.dt_ns`;
      - `transform_default`: `transform_value(dock.transform_combo.currentText())`.
    - `estimate(grid_id, choice) -> int`
    - `run(grid_id, choice, *, progress: Callable[[int, int], bool]) -> Path`: returns the export folder.
  - `class ParaViewExportCancelled(Exception)`
  - `paraview_folder(session, grid_id) -> Path`: `session.root / "paraview" / safe(grid_id)`, where `safe` maps anything outside `[A-Za-z0-9_-]` to `_`.

- [ ] **Step 1: Write the failing tests.**

```python
# test_pure_volume_choice.py
def test_first_use_takes_the_panel_defaults_then_the_record_wins():
    c = volume_choice(None, cell_default=0.05, dz_default=0.2165, transform_default="amp_square")
    assert (c.cell, c.dz_ns, c.transform, c.stretch) == (0.05, 0.2165, "amp_square", 3.0)
    r = volume_choice({"dz_ns": 0.1, "stretch": "bad"}, cell_default=0.2, dz_default=0.2165,
                      transform_default="amp_square")
    assert (r.cell, r.dz_ns, r.stretch) == (0.2, 0.1, 3.0)
def test_volume_choice_round_trips_through_its_record():
    c = VolumeChoice(0.05, 0.1, "amp_square", 4.0, VolumeSettings(period_ns=3.0))
    assert volume_choice(c.to_record(), cell_default=1, dz_default=1, transform_default="") == c
def test_export_size_matches_three_float32_arrays():
    assert export_size_bytes(400, 320, 450) == image_data_bytes((400, 320, 450), 3)

# test_project.py: a "volume" entry survives save/load; an unknown key in it is dropped;
# a wrong-typed value in it reads as unset.

# test_plugin_paraview_export.py
# Inline real-lines site, as test_plugin_slices_engine.py:229 builds it: four REAL_DZT lines
# on Grid "A", preset with time_zero + amp_square; plus a fake dock carrying engine/site_engine
# SliceEngines and transform_combo.
@needs_real_data
def test_export_writes_the_folder_ParaView_opens(tmp_path): ...
    # files == {"cube.vti", "picks.vtp", "lines.vtp", "export.json", *SCENE_FILES};
    # the cube's WholeExtent matches the frame at choice.cell and the depth axis at choice.dz_ns;
    # export.json "cell_m" == choice.cell; the Slices dock engine's choice/frame/z are unchanged.
@needs_real_data
def test_export_reuses_the_dock_engines_lines_when_the_source_matches(monkeypatch): ...
    # SliceEngine.set_source is never called on a new engine.
@needs_real_data
def test_a_cancelled_export_leaves_the_previous_one_intact(tmp_path):
    # Export once. Export again with progress returning False after 3 calls:
    # ParaViewExportCancelled; the first export's files are unchanged; no "*.partial" remains.
@needs_real_data
def test_picks_land_on_the_cube_clock_with_and_without_time_zero(): ...
    # A pick added at a known reflection's time (on the line's zero) lands in picks.vtp at
    # -depth*stretch where `strength` peaks within 2 levels: once for a preset with time_zero,
    # once for one without.
@needs_real_data
def test_pick_depths_use_the_volume_velocity(): ...
    # Grid velocity with two layers: a pick's true_depth_m == volume depth at its cube time.
@needs_real_data
def test_the_fill_cache_is_reused_and_replaced(tmp_path): ...
    # A second run with only the stretch changed calls fill_levels zero times (monkeypatch spy).
    # A change of dz_ns refills it and leaves one cache file for the grid.
def test_a_second_preparation_is_refused_while_the_dock_is_preparing(): ...
    # dock.engine.has_live_task True and the sources differ: run() raises RuntimeError
    # with "Slices are still preparing".
```

- [ ] **Step 2: Run them and see them fail.** Run the pure, core and QGIS commands on the new and changed files. Expected: FAIL.

- [ ] **Step 3: Implement the settings.** That is `_clean_volume` in `project.py`, `volume_record` and `remember_volume` in `session.py`, and `VolumeChoice` and `volume_choice` in `slices_plan.py`. Then run the pure and core tests and see them pass.

- [ ] **Step 4: Implement `ParaViewExport.run`,** in this order:
  1. **The source.** `SourceChoice(grid_id, default_preset(session, grid_id), choice.transform, source_keys(session, grid_id))`.
  2. **The lines.**
     - Use `dock.engine.prepared_lines()` when `dock.engine.choice` is the same source (`same_source`).
     - Otherwise:
       - refuse while either dock engine has a live task;
       - build `SliceEngine(session)`, call `set_source`, then `wait_for_preparation(timeout_ms=600_000)`;
       - take its prepared lines;
       - `dispose()` it in a `finally`.
  3. **The geometry.**
     - The frame is `CubeFrame.for_grid(grid, choice.cell)`, checked against `MAX_FRAME_CELLS` before anything else.
     - `z` is `ZAxis.from_range(t0, t1, choice.dz_ns)`, where `t0`/`t1` is the intersection of the prepared lines' time ranges (as `prepared_z_bounds` computes it).
     - Then the plans, and `build_cube`.
  4. **The fill and its cache.**
     - Weights: `plan_fill(cube.coverage() > 0, cell, method, max_d, search_r)`, with `FinishSettings` from `SliceFinish().updated(session.slice_resolution(grid_id)).in_metres(grid.default_spacing)`.
     - The cache file is `<site>/paraview/.cache/<safe grid>-<key>.npy`, opened with `np.lib.format.open_memmap`.
     - `key` is the first 16 hex characters of the sha1 of the JSON of: the sorted line keys, the steps, the transform, cell, dz_ns, t0, t1, the FinishSettings fields and the frame.
     - Reuse the file if it exists. Otherwise `fill_levels` into it, mapping `VolumeStopped` to `ParaViewExportCancelled`, and delete the grid's other cache files.
  5. **The volume.** The velocity is `session.resolved_velocity(lines[0].key)`. Call `prepare_volume(filled, z, velocity, cell, choice.settings)`.
  6. **Writing,** into `paraview_folder(...)` plus `.partial`:
     - **`cube.vti`:** `strength`, `amplitude` and `true_depth_m`, streamed deepest slab first and flipped within each slab. Origin `(cell/2, cell/2, -max_depth*stretch)`, spacing `(cell, cell, depth_step*stretch)`.
     - **`picks.vtp`:**
       - from `session.picks_for(key)` for each line;
       - xy is `frame.to_local(line.coords[clamp(trace)])`;
       - the time is moved with `retime_ns(p.time_ns, p.zero_ns or 0.0, target)`, where `target` is the prepared line's `zero_ns` when `time_base_of(steps) == "time_zero"`, else `0.0`;
       - the depth is `velocity.depth_at(t)` and `z = -depth*stretch`;
       - arrays `true_depth_m` and `line_index`.
     - **`lines.vtp`:** each line's local coords at `z = 0`, at most 200 points per line, plus the frame outline.
     - **The scene:** `write_scene_files` with `scene_record(...)`. `amplitude_range` uses the p99 of the amplitude, taken from the slab pass. The slices start at the mid depth, the middle line's x and the mid y.
  7. **Replacing.** Rename any existing folder to `.old`, rename `.partial` to the final name, then remove `.old`. On any exception or cancellation, remove `.partial` and re-raise.

  `progress` counts the fill levels plus the written slabs. A False return raises `ParaViewExportCancelled`.

- [ ] **Step 5: Run the tests and see them pass.** Then run the QGIS files `test_plugin_slices_engine.py` and `test_plugin_slices_dock.py` to check that the dock is untouched, then ruff and mypy.

- [ ] **Step 6: Commit**

```bash
git add -A packages/nsgeo-core/src/nsgeo/project.py packages/nsgeo-core/tests/test_project.py packages/nsgeo-qgis/nsgeo_qgis/session.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py packages/nsgeo-qgis/nsgeo_qgis/paraview_export.py packages/nsgeo-qgis/tests/pure/test_pure_volume_choice.py packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_export.py
git commit -m "feat: export a grid for ParaView at its own 3-D resolution (M16 A)"
```

---

### Task 4: The dialog, the Slices panel button, launching ParaView, and the guide

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/paraview_dialog.py`
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`: `paraview_button` ("ParaView…") in `button_row`, plus signal `paraview_requested = pyqtSignal()`. It is enabled whenever a site is open, in either scope.
  - `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`:
    - `_PARAVIEW_KEY = "nsgeo/paraviewPath"`;
    - connect `paraview_requested` to `export_paraview`;
    - `export_paraview()` and `launch_paraview()`.
  - `docs/guide/getting-started.md`: a new step, "Export for ParaView" (spec §10).
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_dialog.py`

**Interfaces:**
- Consumes: Task 3's `ParaViewExport`, `VolumeChoice`, `export_size_bytes`, `paraview_folder`, `ParaViewExportCancelled`; `MAX_FRAME_CELLS`; `NsgeoPlugin._export_progress`, `message`.
- Produces:
  - `ParaViewExportDialog(QDialog)`, constructed with `(grid_ids, current_grid, choice_for: Callable[[str], VolumeChoice], size_for: Callable[[str, VolumeChoice], int], paraview_path: str, parent=None)`. Its methods: `grid_id() -> str`, `choice() -> VolumeChoice`, `paraview_path() -> str`, `open_after() -> bool`. It has a `size_label`, refreshed on every edit, and an Export button that is disabled with a reason in `size_label` while the frame would exceed `MAX_FRAME_CELLS`.
  - `launch_paraview(paraview: str, folder: Path) -> bool`: `QProcess.startDetached(paraview, [f"--script={folder / 'open_scene.py'}"], str(folder))`. It returns False when `paraview` is empty or not executable.

- [ ] **Step 1 (coordinator, human checkpoint): get the dialog's layout approved with a lavish mockup before any code.** The fields:
  - **Grid.**
  - **3-D cell (m) and depth step (ns),** with the note "This grid's own; the Slices panel keeps its settings".
  - **Amplitude transform.**
  - **Depth stretch.**
  - **An "Advanced" group:** wave period (ns), sideways blur (m), depth-trend window (m).
  - **The size on disk.**
  - **The ParaView program,** with Browse.
  - **Buttons:** Export, Export and open, Cancel.

  Record the user's verdict in the ledger, and apply any layout changes to this task's widget list before Step 2.

- [ ] **Step 2: Write the failing tests.**

```python
def test_the_button_opens_the_dialog_on_the_panels_grid(plugin_with_site, drive_dialog):
    # clicking paraview_button opens ParaViewExportDialog; dialog.grid_id() equals the
    # Slices panel's grid_combo text; the cell spin shows ParaViewExport.defaults(grid).cell
def test_editing_the_cell_refreshes_the_size(dialog):
    before = dialog.size_label.text(); dialog.cell_spin.setValue(dialog.cell_spin.value() / 2)
    assert dialog.size_label.text() != before
def test_a_too_fine_cell_is_refused_before_export(dialog):
    dialog.cell_spin.setValue(0.002)
    assert not dialog.export_button.isEnabled() and "too fine" in dialog.size_label.text()
def test_accepting_remembers_the_grids_volume_record_and_the_paraview_path(...):
    # session.volume_record("A")["dz_ns"] == the edited value;
    # QgsSettings().value(_PARAVIEW_KEY) == the path; reset the key in teardown.
def test_export_and_open_launches_paraview_with_the_folder(monkeypatch, ...):
    # QProcess.startDetached is spied: args == (path, ["--script=<folder>/open_scene.py"], "<folder>").
def test_with_no_paraview_path_it_writes_and_says_how_to_open(message_log, ...):
    # the message names the folder and open.sh.
def test_a_cancelled_export_reports_cancelled_and_writes_nothing(...):
    # the progress dialog is cancelled at its first update: message_log has "ParaView export
    # cancelled"; <site>/paraview/<grid> does not exist; no "*.partial" remains
```

- [ ] **Step 3: Run them and see them fail.** Run the QGIS command on the test file. Expected: FAIL.

- [ ] **Step 4: Implement** the dialog, the button and signal, `export_paraview()` and `launch_paraview()`.
  - **`export_paraview()`:**
    - builds `ParaViewExport(session, slices_dock)`;
    - runs the dialog;
    - remembers the choice (`session.remember_volume`) and the path (`QgsSettings`);
    - runs `run(...)` inside `busy_cursor()`, `dock.refining_paused()` and `_export_progress("Exporting for ParaView", total)`;
    - on success calls `message("Exported Grid A for ParaView to <folder>")` and launches ParaView if asked;
    - on `ParaViewExportCancelled` calls `message("ParaView export cancelled")`.
  - **The guide:** add the getting-started step:
    - what the folder holds;
    - how to open it, through the button or `open.sh`;
    - the stretch, and that legends show true depth;
    - the size warning.

- [ ] **Step 5: Run the tests and see them pass.** Then run `tests/pure/test_no_orphan_signals.py`, `test_plugin_loads.py` (unload must not leave the button connected) and `test_plugin_slices_dock.py`, then ruff.

- [ ] **Step 6: Commit**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/ui/paraview_dialog.py packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py packages/nsgeo-qgis/nsgeo_qgis/plugin.py packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_dialog.py docs/guide/getting-started.md
git commit -m "feat: Export for ParaView from the Slices panel, with a launch setting (M16 A)"
```

---

### Task 5: Spike: fill in 3-D along the reflection's dip (spec call 16; human checkpoint)

This is throwaway work outside the repo. It decides whether a later task builds anything.

**Files:**
- Create, outside the repo: `~/nsgeo-m4-check/m16-paraview-trial/fill3d/`, with a prototype and comparison renders.

- [ ] **Step 1: Prototype a dip-following fill on Sunnyside Grid 1.**
  - Use the export from Task 3 at 0.05 m and 0.1 ns.
  - For each empty cell between two lines, estimate the time shift between the two nearest lines' columns by cross-correlation within ±2 ns, over a 3 ns window.
  - Interpolate along that shifted path instead of level by level.
  - Keep holes as holes.
  - Only numpy, so that it could move into the core later.

- [ ] **Step 2: Render the same views for both fills:**
  - an isosurface at 2.5 around the bowl, seen from the south;
  - a depth slice at 0.6 m;
  - a slice across the lines through the bowl.

  Use pvpython with `--force-offscreen-rendering`.

- [ ] **Step 3 (human checkpoint): show the user both side by side.** Their question was whether it takes out the lumps. Record the verdict in the ledger.
  - **Adopted:** draft a small follow-up plan (the core function plus an option in `VolumeSettings`) to run before Plan B.
  - **Not adopted:** draft an issue, with the renders described in text only. File it only when the user says so.

---

### Task 6: Final review, deploy, walkthrough

- [ ] **Step 1:** Run every suite and lint: core, pure, all of QGIS, ruff, mypy, and the zip build (`packages/nsgeo-qgis/scripts/build_zip.py`). Run the pvpython test with `NSGEO_PVPYTHON` set.
- [ ] **Step 2:** Run a whole-branch review on the most capable model. Fix its findings, re-run Step 1, and push.
- [ ] **Step 3: Deploy** to a new QGIS profile `ns_geo_m16`: `cp -a` from `ns_geo`, plus a `dev_link` to this worktree. Probe that the branch's code loads.
- [ ] **Step 4 (human checkpoint): the walkthrough** on Sunnyside Grid 1. Record it on an Artifact page with a results database. It covers spec §9, steps 1 and 6:
  1. The dialog opens on the panel's grid. Set 0.05 m and 0.1 ns, and check that the size reads about 0.7 GB.
  2. Export and open. ParaView shows the cloud, and its title gives the stretch.
  3. The isosurface at 2.5 shows cohesive bodies, and the box version can be dragged.
  4. The three slices move, show holes as holes, and are coloured black for strong.
  5. The 88 bowl picks sit on the bowl's reflection.
  6. Change only the stretch and export again: it is fast, because the fill is reused.
  7. Cancel an export halfway: the previous export still opens.
  8. Browsing the Slices panel at other settings never changed the export.
  9. The 3-D fill verdict from Task 5 is recorded.
- [ ] **Step 5:** Commit the walkthrough results and the decision record. Update the README roadmap (M16 Plan A → In progress, then Done at merge). The merge decision goes to the user.
