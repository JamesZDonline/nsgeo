# Task 5 report

**Already gone**
- `_azimuth_in`: removed in 0776c4d (`git log -S_azimuth_in`); no references remain in packages/.
- F-9: `SlicesDock._resume_grid` hands the hook back in a `finally` (ui/slices_dock.py ~3531, docstring cites #75 F-9).
- M17a CRS note: `SiteEngine._site_crs()` reads `session.site_crs()` on every call (`site.effective_crs()`), never cached, so
  nothing is stale. Only the lattice's CRS string is held, and it is rebuilt on any grid removal via `_on_grids_changed`.
  Nothing left to fix; no code change needed.

**New tests**
- geometry tests (4 tests, 5 cases): failed with ModuleNotFoundError (site_geometry absent), now pass.
- mixed-CRS gather test: was untested, now pinned (passed before and after the move; the move is behaviour-preserving).
- failure-path test (B's `Line.load` raises OSError "disk gone"): was untested, now pinned (passed at once).
- constructor-hook test: edited, disposes both engines.
- Relative speed test is looped >= 3x batched, same run, same machine.

**WKB**: header read back with `struct.unpack_from("<BII")` and asserted == (1, 2, n) plus total length 9+16n; otherwise
RuntimeError. `fromWkb` is an instance method in PyQGIS (`QgsGeometry().fromWkb(bytes)`). n=0 returns (0,2); n=1 is padded
to two points and trimmed. Transform result is checked against `Qgis.GeometryOperationResult.Success`.

**Thread safety**: `world_to_frame` still captures two authids and a context copy; `move` calls `transform_points`, which builds
a fresh `QgsCoordinateTransform` and `QgsGeometry` per call. No Qt object is shared across threads.

**grids_changed rebuild**: documented, not deferred (docstring on `_on_grids_changed`). It only runs for gone grids, reads session
state plus the remaining ready engines, and the dock reads geometry straight after `remove_grid`; a deferral would leave it stale
for a tick. The module docstring's claim "never in the synchronous slot" is about moved grids; left as is.

**site_engine.py lines**: 1535 -> 1471 (new site_geometry.py ~140). `_limit_windows_ns` now uses `window_levels(thickness_ns,
thickness_ns, dz)[0]`.

**Results**: geometry+engine+export 101 passed; site_scope 177 passed (478 s); `-m real_data` 46 passed; pure 396 passed, 4 skipped;
ruff check and format clean; mypy (CI list) clean. No flakes hit.

**Deviations**: none. Engine's transform used `QgsProject.instance()` as context; it now passes `QgsProject.instance().transformContext()`.
