### Task 3: #75 Site export

**Already gone, verified while planning (at 3104edb):**
- **The writer duplicates M11:** `GeoTiffSiteWriter` now calls `slice_export.write_north_up`, and
  `apply_site_temporal_properties` calls `apply_band_windows`.
- **`NSGEO_SITE_CELL_M` can be the lattice pixel:** `_tag_dataset` writes `plan.cell_m`, the export
  cell, always.
- **The docstring lists the fill-radius key as always present:** the module docstring now names the
  four interpolation keys as absent on the coverage companion.

Confirm each, and list it in the report.

**Files:**
- Modify: `P/site_export.py` (`plan_site_export`, `site_export_job`: the transform from the
  engines; type fixes)
- Modify: `P/plugin.py` (`_export_site`, ~line 1683: stop passing `transform=`)
- Modify: `.github/workflows/<the lint workflow>` (add `site_export.py` to the mypy list)
- Modify: `T/qgis/conftest.py` (receive `make_site`), `T/qgis/test_plugin_site_engine.py`,
  `T/qgis/test_plugin_site_export.py`
- Test: `T/qgis/test_plugin_site_export.py`

**Interfaces:**
- **Produces `plan_site_export(site_engine, thickness_levels, step_levels, *, cell, lattice,
  method, finish, gains, velocities, left_out=None) -> SiteExportPlan`**, with no `transform`
  parameter.
  - `plan.transform` is the ready engines' common `choice.transform`.
  - It raises `RuntimeError("the grids were prepared with different transforms: …")` naming each
    grid and transform, if they differ.
  - `site_export_job` loses `transform` the same way.
- **Produces a `make_site` fixture moved to `T/qgis/conftest.py`,** unchanged, for both the engine
  and the export tests.

- [ ] **Step 1: Write the failing tests** in `test_plugin_site_export.py`
  - `test_the_file_records_the_transform_the_grids_were_prepared_with`. The site is prepared from
    `site3.source(transform="amp_abs")`. `export_site(...)` is called without `transform=`, so `KW`
    loses its `transform` key. The file's `NSGEO_SITE_TRANSFORM == "amp_abs"`.
  - `test_a_grid_with_no_velocity_exports_null_depths`. `velocities` omits C. Every band's
    `NSGEO_GRID_DEPTHS_M["C"]` is `None`, and its description holds no depth text for C, while A's
    depths are set.
  - **Fix these existing tests in place:**
    - the no-resident-cube test (~line 340) asserts `not site.engine_for(g).has_cube` instead of
      `mode != "resident"`;
    - the CRS assertion (~line 152) compares
      `QgsCoordinateReferenceSystem.fromWkt(ds.GetProjection()).authid()` with the site's CRS;
    - `test_a_ready_grid_with_no_site_axis_exports_as_absent` uses its `make_site` fixture instead
      of building and disposing a `SiteEngine` by hand.

- [ ] **Step 2: Run them and see them fail**

Run: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/test_plugin_site_export.py -q`

Expected: the transform test fails with a TypeError (a missing `transform` argument). The no-velocity
test passes or fails on what it shows. If it passes at once, note that and keep it: it is a missing
test, not a missing fix.

- [ ] **Step 3: Implement**
  - Derive the transform as above, and update `P/plugin.py`'s `_export_site` and every test caller.
    Find them with `grep -rn "transform=" packages/nsgeo-qgis/tests/qgis/test_plugin_site_export.py`
    and `grep -rn "site_export_job\|plan_site_export" packages/nsgeo-qgis`.
  - Move `make_site` to `T/qgis/conftest.py` and drop both copies.
  - Add `packages/nsgeo-qgis/nsgeo_qgis/site_export.py` to the CI mypy list. Run that mypy command
    locally (`./.venv/bin/python -m pip install mypy==2.4.0` if it is missing) and fix what it
    reports. #75 expects an `arg-type` at the `slice_at` call and `union-attr` where `engine_for()`
    returns an Optional; see #18.

- [ ] **Step 4: Run** the export and engine test files, the pure suite, `ruff`, and the mypy command.
  Expected: all pass.

- [ ] **Step 5: Commit and push:** `fix(site-export): record the grids' own transform; type-check the site export; test gaps (#75)`.

---

