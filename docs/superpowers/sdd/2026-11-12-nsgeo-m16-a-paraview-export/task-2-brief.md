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

