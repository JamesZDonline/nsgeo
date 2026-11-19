# Task 4 report: Import GPS lines… (plugin)

Status: DONE. Commit 4b485f1 "feat(plugin): Import GPS lines… — place DZTs along their RTK track (#134)", pushed to origin nsgeo-m17-gps.

## Implemented
- `nsgeo_qgis/crs_rule.py`: CRS_SCALE_WARN/REFUSE, crs_scale_error, crs_check, usable_at, project_reason, choose_crs (GridDialog's rule moved unchanged). choose_crs has a new keyword `site_has_grids=True`: a site CRS that is not the project's is noted "picked for you: the CRS the site's other grids use" when the site has grids, else "picked for you: the site's CRS" (Task 3 carry-over). GridDialog passes `bool(site.grids)`.
- `GridDialog` delegates (`_crs_check`, `_choose_crs`, plus thin `_crs_scale_error`/`_project_reason` delegates kept because existing grid-dialog tests call them; test file unchanged).
- `nsgeo_qgis/gps_import.py` (no Qt/qgis; added to ci.yml mypy list): GpsRow, first_fixed_lonlat (R4: DZT path, dzg_for), plan_gps_rows, shifted_lines, import_messages (bridges for all rows, then end runs, then refusals, per the Copy's bullet order).
- `ui/gps_import_dialog.py`: modeless dialog per the Copy; rows re-planned whenever the file set changes (first readable file decides CRS when the site has none); accept re-checks session identity, then set_site_crs if none, then one add_lines call, messages kept in `dialog.messages` and shown by the plugin. Extra guard: if the site gained a CRS while open and it differs from the planned one, accept re-plans and reports instead of importing.
- `plugin.py`: `Import GPS lines…` toolbar action after Import DZT… with the exact tip, enabled with an open site, `open_gps_import_dialog` (single instance, guarded slots, rejected on unload).
- R11: `END_LIMIT_M` and `ToXY` added to `nsgeo.geometry.__all__` (sorted) and to the core README table (test_the_readme_names_every_public_name required it).
- R10: `SiteSession.add_lines` refuses a GPS line whose placement.crs differs from site_crs() (ValueError "line X is placed in A, but the site is in B"), nothing added, no signal.
- tests/plugin_testing.py: `synthetic_gps_dzt`.

## Tests and results
- core+pure: 1645 passed, 5 skipped (first run 1644 + the README test fixed afterwards and re-run; skips unchanged).
- test_plugin_crs_rule.py 10 passed; test_plugin_gps_import_dialog.py 17 passed (real-data 60-line test ran, not skipped); test_plugin_session.py 138 passed; test_plugin_import_dialog.py 41 passed; test_plugin_grid_dialog.py 147 passed (unchanged); test_plugin_loads.py 15 passed.
- ruff check + format: clean. mypy (full types command incl. gps_import.py): no issues, 57 files.
- Real data: FILE__011 walked length within 29.5-31.0 m (R2); all 60 import; no bridge message. No real coordinate anywhere.

## TDD evidence
- Pure tests written first against a stub gps_import: 11 failed behaviourally (empty rows/lists), 1 passed. Then implemented: 12 passed (one test-expectation fix: default DZT has 60 traces).
- R10 test failed first with "DID NOT RAISE ValueError", then passed after the add_lines change.
- QGIS dialog/crs tests were written after the implementation of those pieces; I verified each rule with mutations (restored afterwards, scratch backups): skip set_site_crs -> import test fails; remove same-site check -> replaced-site test fails; shift ignored -> import test fails; note wording reverted -> gridless-site note test fails; taken() disabled -> already-in-site test fails; usable() disabled -> outside-CRS test fails; CRS-appeared guard disabled -> replan test fails.

## Files changed
packages/nsgeo-core/src/nsgeo/geometry/__init__.py, packages/nsgeo-core/README.md, .github/workflows/ci.yml, packages/nsgeo-qgis/nsgeo_qgis/{crs_rule.py,gps_import.py,session.py,plugin.py,ui/gps_import_dialog.py,ui/grid_dialog.py}, tests: pure/test_pure_gps_import.py, qgis/test_plugin_crs_rule.py, qgis/test_plugin_gps_import_dialog.py, qgis/test_plugin_session.py, plugin_testing.py.

## Concerns
- I had no copy of the C1 mockup; layout is my reading of the Copy (buttons row, table, Destagger form row, Coordinates row, status, Import/Cancel). Check against the mockup.
- If add_lines fails after set_site_crs (e.g. a key clash on a grid-free site), the site keeps the CRS it was just given with no lines. Harmless but dirty; matches the brief's ordering.
- Importing GPS lines into the live plugin runs through the map layers and Survey dock, which Tasks 5-6 teach about GPS lines; the plugin tests passed with no visible error but the map/dock rendering of them is untested here.
- Dialog planning re-reads every file on each add/remove (60 files took about 1 s).
- Full QGIS tier not run (per instruction).

## Fix round 1

Changes (mockup .lavish/m17a-gps-import.html sections 1-2 read):
- Cues: amber bg #fbf3df / fg #8a5a00 on Without RTK (a bridge) and Ends (a run over END_LIMIT_M); light-red bg #fbe9e7 / fg #a12a1e on refused Status cells. Messages after the count are posted at Qgis.MessageLevel.Warning.
- R12: refused rows show "—" in empty cells; an already-in-the-site row is planned first, then refused, and keeps counts and ends (taken is now checked after placement; "no DZG" etc. win over it); destagger text is an inline grey note beside the spin box (tooltip kept); Coordinates is a form row under Destagger; status and Import/Cancel share one footer row; Traces right-aligned.
- R13: m4 shifted_lines uses dataclasses.replace on the planned Line (no re-read) and runs before set_site_crs; m5 the Coordinates line is decided before the first file (tested with a site in EPSG:32616); m6 usable is asked at the first RTK fix before projecting (a NaN-failing to_xy now gives "outside what X can place"); lonlat_to_xy NaN and exception path tested with a refusing transform; m8 duplicate GridDialog._site_crs removed.
- Finding 2: new pure test test_a_dzg_naming_a_trace_beyond_its_dzt_is_refused (fix at trace 250 of 200, asserts "could not read it: ... names trace 250 ... 200 traces").

Mutant killed: changing `read_dzg(dzg, n_traces)` to `read_dzg(dzg)` in gps_import.py now fails that test (13 passed, 1 failed); it survived before. Restored afterwards.

Results: pure test_pure_gps_import 14 passed; QGIS: test_plugin_gps_import_dialog 23 passed, test_plugin_crs_rule 10 passed, test_plugin_grid_dialog 147 passed (unchanged); core+pure 1647 passed, 5 skipped; ruff check/format clean; mypy (with gps_import.py) clean, 57 files.
