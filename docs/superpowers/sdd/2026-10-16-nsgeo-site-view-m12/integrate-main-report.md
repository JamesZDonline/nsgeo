# Report: merge main (M9, v0.1.0) into nsgeo-m12

**Status: DONE_WITH_CONCERNS.** The concerns are judgement calls and environment notes, listed at
the end. No test fails, and no assertion was weakened.

## Commits (pushed to origin/nsgeo-m12)

| SHA | Subject |
|---|---|
| `146d3d0` | Merge main (M9, v0.1.0) into nsgeo-m12. Parents: `e68419a` (M12) and `6a7f112` (main). |
| `b78379b` | docs(core): name the site-view API in the public surface |

- I merged; I did not rebase.
- I confirmed `origin/main` at `6a7f112` with a real `git fetch`. The first fetch failed inside the
  tool sandbox (DNS). I ran network operations (fetch, push, pip and Docker pulls) outside it.
- The worktree is clean, and level with origin at `b78379b`.

## Conflicts and their resolution

### 1. `packages/nsgeo-core/src/nsgeo/slices/__init__.py`

- **Imports (lines 28–54):** M12's import block for `nsgeo.slices.site` is kept. M9's removal of
  every `# noqa: F401` is kept, and M9's `npz_path` import is kept.
- **`__all__` (lines 56–104):** M9's list plus all 21 M12 site names, 47 names in total.
  - The list is sorted with Python's `sorted()`, because `test_public_api` asserts
    `__all__ == sorted(__all__)`.
  - The 21 names: `AXIS_SNAP_CELLS`, `BACKGROUND_FRACTION`, `MIN_SEAM_CELLS`,
    `NORMALISATION_METHODS`, `SEAM_WIDTH_SPACINGS`, `Footprint`, `Seam`, `SiteLattice`,
    `background_level`, `compose`, `compose_footprints`, `edge_match_solve`, `find_seams`,
    `footprint`, `grid_axis`, `lattice_pixel`, `normalise`, `seam_masks`, `site_axis`,
    `snap_azimuth`, `window_on`.

### 2. `packages/nsgeo-qgis/nsgeo_qgis/slice_layer.py`

M9's write/repoint/sweep now lives inside M12's `update_north_up`. Both paths reach the map
through it: This grid's `update` → `update_north_up`, and the site's `update_north_up` directly.
So both follow the Windows rule.

**Taken from M9 unchanged:**
- The module docstring.
- `_remove = os.remove` (:61).
- `slice-000000.tif` and `_serial`.
- `_sweep` (:260): the directory scan that keeps `self.path` and the layer's live `source()`.
- `_repoint(path)` (:284): `setDataSource` with the layer's current name and
  `ReadFlags()`; `self.path` moves only once the layer is valid.
- `_write(path, …)`.

**`update_north_up` (:152):**
- `_serial += 1` (:184), then a fresh `slice-NNNNNN.tif`.
- Then, in `try`, `_write` followed by `_create_layer` or `_repoint`.
- `finally: self._sweep()` (:198). This is M9's sequence verbatim, with `crs` and
  `tuple(geotransform)` passed in as M12 had them.

**From M12, kept:**
- The `update` → `update_north_up(array, geotransform, crs, *, limit, colormap_name, unipolar,
  subtitle, name=LAYER_NAME)` split (:127, :152).
- `SITE_LAYER_NAME` (:65).
- The extent and CRS sync after the repoint (:204–209), as ruling T5-b requires.
- `_create_layer(path, name=LAYER_NAME)` (:374). This combines M9's `path` with M12's `name`.

**The rename: the one place the two sides clashed.**
- M12 renamed whenever `layer.name() != name`. That undoes a user's rename on every tick.
- M9's `bf2e2a2` requires that "a rename by the user must survive a tick", and
  `test_the_renderer_survives_a_repoint` asserts it.
- **Resolution:** a new field, `self._name` (:124). It records the name this class last applied,
  and is set in `_create_layer` (:382) and on rename (:203).
- `update_north_up` renames only when `name != self._name` (:201), which means a scope switch.
- Result: a user's rename survives every tick (M9), and switching scope still renames in place
  (M12).

**Docstring:** I corrected `update_north_up`'s docstring, which described `reloadData()`. I
measured on QGIS 3.44.7 and, in Docker, on 4.2.3: **`setDataSource` moves the layer's extent and
CRS itself.** The sync is now a no-op guard on both versions (see concern 2).

**Windows hazard:** no path rewrites the file the layer reads.
- `update` delegates to `update_north_up`.
- `clear()` and `dispose()` write nothing.
- `plugin._on_slice_changed`'s site branch calls `update_north_up`.

### 3. `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_layer.py`

- **Import conflict (line 16):** the union of both sides' imports: `LAYER_NAME`,
  `SITE_LAYER_NAME`, `SliceLayer`, `build_shader` and `QgsSingleBandPseudoColorRenderer`.
- **All tests kept:** 16 from M9 (M11's tests, M9's rename of one of them, and M9's six new
  ones) plus M12's three. **No assertion was changed.**
- **M12's two `reloadData()` docstrings** (`test_update_north_up_follows_a_crs_change` :379,
  `test_the_layer_extent_follows_a_lattice_that_grows` :393) now say what was measured:
  - M11's `reloadData()` kept the creation extent and CRS.
  - `setDataSource` moves them.
  - `update_north_up` checks them either way.
- **Two new tests**, with a `_site_tick` helper (:409):
  - `test_the_site_path_never_rewrites_the_file_the_layer_reads` (:422): M9's Windows `Create()`
    model applied to the site path. It asserts no refusal, a scratch folder holding only
    `sl.path`, `SITE_LAYER_NAME`, and the new pixels.
  - `test_a_user_rename_survives_site_ticks_but_a_scope_switch_renames` (:456): pins the rename
    resolution above.

**Mutants** (`PYTHONDONTWRITEBYTECODE=1`, every `__pycache__` removed before each run;
file-level run of `test_plugin_slice_layer.py`):

| Mutant | Result | Killed by |
|---|---|---|
| a. The site path rewrites one fixed file (`site.tif`) | 1 failed | `the_site_path_never_rewrites…` |
| b. The rename compares `layer.name()` (M12 as it was) | 2 failed | `the_renderer_survives_a_repoint` (M9), `a_user_rename_survives…` |
| c. The rename is never applied | 3 failed | `update_north_up_renames_the_layer_in_place` (M12), plus both new tests |
| d. `_name` is not recorded on rename | 2 failed | M12's rename test, `a_user_rename_survives…` |
| e. Extent sync removed | **survives** (21 passed) | see concern 2 |
| e2. CRS sync removed | **survives** (21 passed) | see concern 2 |

## Convention changes applied to M12 code

1. **Public API (`4e10579`).**
   - The enforcing tests are `tests/pure/test_plugin_boundary.py::test_plugin_imports_only_the_named_core_api`,
     which reads each public module's `__all__` from source, and
     `packages/nsgeo-core/tests/test_public_api.py`.
   - Every M12 plugin import of core names was already at subpackage level (`from nsgeo.slices
     import …` in `site_engine.py`, `site_export.py`, `ui/site_scope.py` and `slices_plan.py`).
     So once the site names joined `__all__`, the boundary test passed with no import changes.
   - `test_the_readme_names_every_public_name` then failed on the 21 site names. `b78379b` adds a
     README row for each, in `packages/nsgeo-core/README.md` under `nsgeo.slices`, in sorted
     order. It also extends the section intro, and `Site`'s row now names `slice_sources` and
     `site_view`.
   - M12 added no public names to `nsgeo.project` or `nsgeo.model`; only private helpers and
     `Site` fields.
2. **Qt6-safe conventions (`ea89aa5`).** I audited every M12-added line in
   `nsgeo_qgis/**` and `tests/**`:
   - Unscoped `Q*.Member` enum access: none. Every enum is scoped (`Qt.CheckState.*`,
     `Qt.ItemFlag.*`, `QAbstractItemView.SelectionMode.*`, `QHeaderView.ResizeMode.*`,
     `QEventLoop.ProcessEventsFlag.*`, `Qgis.MessageLevel.*`, and so on).
   - No `exec_`/`exec`, no `QTest.mouseMove` hover, no `messageReceived`, and no Qt5-only API
     (`QRegExp`, `fontMetrics().width`, `.delta()`, `desktop()`).
   - M12's harness additions (`LoadCounter`, `spin_until`, `site3`) are Qt6-safe.
   - **No change was needed.** The QGIS 4 run below confirms it.
3. **Zip and metadata (`64dedb4`).**
   - `build_zip.py` builds from `git ls-files`, so new tracked modules ship automatically. No
     change was needed.
   - **Zip check:** I built `nsgeo_qgis-0.1.0.zip` at `b78379b` (69 entries, VERSION
     `commit=b78379b…`). It contains `nsgeo_qgis/site_engine.py`, `nsgeo_qgis/site_export.py`,
     `nsgeo_qgis/ui/site_panel.py`, `nsgeo_qgis/ui/site_scope.py` and
     `nsgeo_qgis/_vendor/nsgeo/slices/site.py`.
   - No `tests/` or `scripts/` entries ship, so M12's `scripts/bench_site.py` is excluded.
   - `metadata.txt` needs nothing.

## Tooling, lint and mypy

- Installed the CI pins (`fa9a5db`) into `./.venv`: **ruff 0.17.1, mypy 2.4.0**. These replace
  0.16.8 and 2.3.1.
- I ran CI's commands as `.github/workflows/ci.yml` has them:
  - `ruff check .`: All checks passed.
  - `ruff format --check .`: 141 files already formatted.
  - `mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent …` (CI's four
    targets): Success, no issues found in 34 source files.
- **No findings, so no fixes.**

## Verification

| Check | Result |
|---|---|
| core + pure (`./.venv`) | **651 passed, 2 skipped**. That is the baseline 609/2 plus M9's 42: `test_public_api` 12, `test_build_zip` 17, `test_dev_link` 2, `test_metadata` 3, `test_release_docs` 5, shim +2, boundary +1. |
| qgis tier, QGIS 3.44.7 (`./.venv-qgis`, offscreen, `-p no:xonsh`) | **885 passed in 341.89 s**, no skips. That is the baseline 846, plus M9's 37 (30 pure tests the tier also runs, `test_plugin_qt_compat` 1, slice-layer 6), plus the 2 new tests. |
| 20-run concurrency loop | **20/20 runs exited 0 with "25 passed"**, 33.1–46.3 s per run, one pytest process per run. The 25 tests are every `LoadCounter` test in `test_plugin_site_engine.py` (15) and `test_plugin_site_scope.py` (8), plus the two timing tests the final-fix loop also ran (`a_burst_of_slider_moves…`, `leaving_an_idle_site…`). |
| QGIS 4.2.3 / Qt 6.9.2, **full qgis tier** | **869 passed, 15 skipped, 1 xfailed, exit 0**, 559.6 s. |

**QGIS 4 details:**
- The 15 skips are `test_build_zip.py`'s git-backed tests. They skip by design in the
  containers, because the copied worktree's `.git` file points outside the container.
- The xfail is M9's strict Qt6 dock-width xfail (#50). It stayed an xfail with M12's dock, not
  an XPASS.
- This run covers `test_plugin_site_scope.py`, `test_plugin_site_engine.py`,
  `test_plugin_slice_layer.py` and every other file.
- One non-failing `FutureWarning` came from the test's own `gdal.Open` in
  `test_export_routes_to_the_site_geotiff_in_site_scope`, not from product code.

**Trap 1:** the merge touched no dispatch path.
- `site_engine.py`, `ui/site_scope.py` and `ui/slices_dock.py` are byte-identical to `e68419a`.
- `slices_engine.py` changed only in M9's import line (`clear_kernel_cache` via `nsgeo.slices`).
- `plugin.py` and `session.py` changed only in M9's About text and import lines.
- No M9 or M11 test was edited, apart from the conflict resolution in
  `test_plugin_slice_layer.py`.

## Concerns

1. **The rename semantics are my call.** A user's rename of the preview layer now survives
   ticks, but a scope switch replaces it with `LAYER_NAME` or `SITE_LAYER_NAME`. The
   alternative is to never rename once the user has renamed. That would keep M9's rule even
   across scope switches, but drop M12's "the name says the scope". It is a one-line change if
   the controller prefers it.
2. **The extent/CRS sync no longer discriminates.**
   - On both QGIS 3.44.7 and 4.2.3, `setDataSource` moves the layer's extent and CRS itself (I
     measured both with a probe).
   - The T5-b sync is kept as the brief requires, but it is now a no-op guard.
   - M12's two tests still pin the behaviour, the layer following the lattice and the CRS, so a
     regression to an in-place `reloadData()` would fail them. Mutants that remove only the sync
     code survive, though (e and e2 above).
   - Task 5's mutant table (#13, #14) no longer holds for this code.
3. **How the QGIS 4 run was made.**
   - I used M9's `in_qgis_docker.sh` unchanged, but with `DOCKER_HOST=unix:///var/run/docker.sock`,
     the system daemon.
   - I did not use Docker Desktop, the CLI's current context. Its user service had been
     **OOM-killed at 16:57**, and the host had about 5 GB available, so I did not restart it.
   - I pulled `qgis/qgis:4.2` (3.09 GB) into the system daemon for the run and **removed it
     afterwards**: the disk is 96% full, with 42 GB free.
   - To reproduce:
     `DOCKER_HOST=unix:///var/run/docker.sock packages/nsgeo-qgis/scripts/in_qgis_docker.sh qgis/qgis:4.2 python3 -m pytest packages/nsgeo-qgis/tests -q -p no:cacheprovider`.
     It re-pulls about 1.1 GB.
4. **Windows is untested.** The site path's Windows behaviour is proven only by the `Create()`
   model test. Linux permits in-place rewrites, so neither local tier nor CI can observe the
   real hazard.
   - For the walkthrough: on Windows, drag the depth slider in *Whole site* and confirm the map
     updates past the second tick.
   - On any OS: rename the preview layer, drag the slider (the name is kept), then switch scope
     (the layer is renamed).
5. **Housekeeping.** The session scratchpad holds files from earlier M12 tasks. My
   `mutants.py`, `loop.sh` and `probe_setdatasource.py` may have overwritten scratch files of
   the same name. They held nothing tracked.

## Manual checkpoint (not passed here)

The user's walkthrough in the `ns_geo_m12` profile has not happened yet. M12 now sits on
`main`, so the walkthrough tests the code that would be merged.
