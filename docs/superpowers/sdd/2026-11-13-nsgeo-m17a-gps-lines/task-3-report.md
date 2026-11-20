# Task 3 report: the site's CRS, and GPS lines in the survey file

Status: DONE (one design note below).

## Implemented
- core `Site.crs` field, `Site.has_gps_lines()`, `Site.effective_crs()`; `Site.validate` compares each GPS line's crs with the effective CRS (R3 messages: "...but the site has no CRS" / "...but the site is in {b}").
- `project.py`: track dict (`crs`, `grid_id` only when set, `label`, `travel_shift` only when non-zero, `fixes` rows; NaN x/y/lat/lon <-> null -> NaN float, alt_m/geoid_m None <-> null -> None); `TRACK_SCHEMA_VERSION = 4`, readable set 1-4; version order track > velocity source > cuts > 1; top-level `"crs"` only with GPS lines; load sets `site.crs` from the file, else first grid, else None; load validates (so a mismatch raises ValueError as for other validate failures); save refuses GPS lines with no CRS anywhere (ProjectError).
- plugin: `SiteSession.site_crs()`, `set_site_crs()` (ValueError "the site already uses {old}", dirty); `layers.crs()`, `site_engine._site_crs`, `grid_dialog._site_crs` read it.

## Design note (deviation, small)
`effective_crs()` returns `site.crs` only when the site has GPS lines or no grids; otherwise the first grid's crs. Reason: load copies the first grid's crs into `site.crs` (the brief's test), and the existing "package CRS follows the first grid" behaviour would otherwise go stale after the first grid's CRS is edited. With GPS lines it is exactly "site.crs, else first grid".

## Tests
- core+pure: 1631 passed, 5 skipped (baseline 1614/5; skips unchanged).
- QGIS: test_plugin_session.py 131 passed; test_plugin_grid_dialog.py 147; test_plugin_layers.py 110; test_plugin_site_engine.py 58.
- ruff check/format clean; mypy (list without gps_import.py) clean.
- Existing tests updated: `test_rejects_future_schema_version` (4 -> 5), `test_loads_schema_1_2_and_3_and_refuses_4` renamed `..._1_to_4_and_refuses_5`.

## TDD evidence
RED (after stubbing only the constant and the `Site.crs` field so collection works): `pytest packages/nsgeo-core/tests/test_project.py test_survey.py` -> 15 failed: "cannot serialise placement of type TrackPlacement", `assert (4 in (1,2,3))`, `None == 'EPSG:32616'` (crs not derived), `DID NOT RAISE ValueError` (validate). QGIS: 5 failed with AttributeError no `site_crs`/`set_site_crs`. GREEN: all pass after implementation. No mutation probes run (shared worktree rule); each rule has a dedicated test: version order (schema 4 with cut, no-GPS 1/2/3), crs key only with GPS lines, derivation on load, file crs wins, both validate messages + first-grid comparison, set_site_crs refusal (set and via grid), save refusal.

## Files
survey.py, project.py, session.py, layers.py, site_engine.py, ui/grid_dialog.py; tests: test_project.py, test_survey.py, test_plugin_session.py.

## Concerns
None blocking. test_plugin_grid_dialog/site_engine have no new tests of their own (covered by existing suites passing, which exercise `_site_crs`).

## Fix round 1 (R9: pinned site CRS)
Changed: `Site.crs` is only a pinned CRS (file's "crs", set on first GPS line, or set_site_crs); load never copies the first grid's CRS; `effective_crs()` = crs, else first grid's, else None (no has_gps condition); `SiteSession.add_lines` pins `site.crs = site_crs()` when a TrackPlacement is added and none is pinned (ValueError, nothing added, with no CRS); `save_site` raises ProjectError when a GPS line's crs differs from the effective CRS. TrackPlacement is imported via `nsgeo.geometry` (boundary test).
Tests: test_project.py (older file loads crs None; direct save refusal (d); pinned survives grid edit through save/load), test_plugin_session.py (a, b, c, e, no-CRS refusal, tape lines don't pin).
Results: core+pure 1632 passed, 5 skipped before the import fix, then pure 301 passed after (boundary test was the one failure, fixed); test_project/survey/schema 199 passed; session 137; layers 110; ruff and mypy clean.
