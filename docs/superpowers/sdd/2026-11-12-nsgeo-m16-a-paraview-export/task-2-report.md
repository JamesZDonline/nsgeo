# Task 2 report: VTK writers and ParaView scene

Commit bd5122c (pushed to origin nsgeo-m16).

## Implemented
- core `nsgeo/vtkxml.py`: `write_image_data` (streaming, `.part` then `os.replace`, ValueError on wrong length incl. too many values, no file left), `write_poly_data` (Verts/Lines/Polys always present, point arrays float32/float64/int32/int64, length-checked), `image_data_bytes`. `__all__` sorted (a repo test requires it). Added to EXPECTED_PUBLIC and a README section (a repo test requires the README to name every public name).
- test helper `tests/vtk_reader.py`; tests `test_vtkxml.py` (6 cases incl. too-long array).
- plugin `paraview_scene.py`: `SCENE_FILES`, `scene_record` (rejects unknown/missing keys with TypeError, bad `slices` with ValueError; fills the 4 defaults), `write_scene_files` (open.bat written with CRLF; uses `open()` not `write_text(newline=)`, which is 3.10+).
- templates in `nsgeo_qgis/paraview/`: open_scene.py.txt (all from export.json; R9 slice rule; R2 picks coloured by true_depth_m only; HERE from __file__ / NSGEO_SCENE_DIR / cwd; apply_preset/try_set; no ColorBy None; {:.1f}; colours last; clip box and camera derived from the cube's bounds), open.sh.txt, open.bat.txt, README.md.txt (generic).
- `tests/pure/test_paraview_scene.py`: 7 tests, FIELDS has the R9 slices shape.

## Tests
- core: 1056 passed, 4 skipped. pure: 257 passed, 2 skipped. ruff check, ruff format --check, mypy: clean.
- Pure scene tests without NSGEO_PVPYTHON: 6 passed, 1 skipped.
- With NSGEO_PVPYTHON (pvpython 6.2.1, --force-offscreen-rendering): 7 passed in 7 s. Zero picks, one line. All nine names registered (plus "Note"). No "skipped property" prints. pvpython stderr only a harmless "Could not determine array range" warning. Screenshot 24401 bytes: /tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/7ec288b0-6c3d-4401-b51d-656c73323d21/scratchpad/task2-scene.png (shows the box, the blob cloud, the line, both legends; I viewed it). The test saves it elsewhere if NSGEO_KEEP_SHOT is set.
- build_zip: the built zip contains all four `paraview/*.txt` templates and paraview_scene.py (subfolder .txt files ship); test_build_zip passes (files were `git add`ed first).

## TDD evidence
Honest gap: I wrote vtkxml.py before running the tests, so there is no recorded RED run for the core tests. The first run (GREEN attempt) failed 4 (reader bug with `count=-1`, unsorted `__all__`, README missing names), all fixed to green. The scene tests were also written alongside the implementation; no RED run recorded.

## Self-review
- No site names or coordinates in the repo (grepped for Sunnyside/Grid 1). FIELDS uses made-up values.
- The scene's amplitude/strength ranges, ramp, slice positions all come from export.json.
- ruff --fix reordered one import in the pure test.

## Concerns
- `title` text in the scene comes only from export.json["title"]; Task 3 must build it (grid name + stretch).
- Camera assumes looking from -y at the grid; fine for grid-local coordinates.
- ParaView volume rendering in the pvpython test is offscreen; the blob renders (visible in the screenshot).
