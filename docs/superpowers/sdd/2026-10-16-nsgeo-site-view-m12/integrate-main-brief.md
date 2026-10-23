# Integration brief: merge main (M9, v0.1.0) into nsgeo-m12

## Situation

nsgeo-m12 is M12, the site view. All five tasks are built and every review is clean, at head `e68419a`. It branched from main at `2a6293d`.

Main has since gained M9, the first release. That is merge `6a7f112`, 19 commits (`git log --oneline 2a6293d..origin/main`):

- **`4e10579`**: the core names its public API with `__all__`, and the plugin imports only that API. Check how this is enforced; there is probably a boundary or API test. M12 adds core names in `nsgeo.slices.site`, and the plugin's new modules import them.
- **`ea89aa5`**: the plugin runs on QGIS 4. This brings `qgisMaximumVersion`, a Qt6-safe test harness, and CI on 3.44 and 4.2. M12 adds new UI and tests (`ui/site_panel.py`, `ui/site_scope.py`, dock and plugin changes, `test_plugin_site_*.py`) that were written before this commit. They must follow its Qt6-safe conventions: scoped enums, no Qt5-only APIs, and whatever its harness requires.
- **`84672f6` and `bf2e2a2`**: a Windows fix in `slice_layer.py`. The slice preview now writes a fresh file per update, because GDAL `Create()` cannot replace a file QGIS holds open, and a directory-scan sweep cleans up the scratch folder even after a failed update.
- **`64dedb4`**: `build_zip.py` builds the release zip with the core vendored.
- **`fa9a5db`**: CI pins ruff 0.17.1 and mypy 2.4.0, plus runner images.

A trial merge (`git merge-tree`) conflicts in three files:

- `packages/nsgeo-core/src/nsgeo/slices/__init__.py`
- `packages/nsgeo-qgis/nsgeo_qgis/slice_layer.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_layer.py`

## Job

1. **Merge**, don't rebase: `git merge origin/main` on nsgeo-m12, after `git fetch`.
2. **Resolve each conflict, keeping both sides' intent exactly.**
   - **`slices/__init__.py`**: keep M12's site names and M9's `__all__`, and add every M12 public name to `__all__`.
   - **`slice_layer.py`**: two things must both survive.
     - M9's fresh-file-per-update write and its directory-scan sweep must stay behaviourally identical, including on Windows. Read the two commits and their tests.
     - M12's `update` → `update_north_up(array, geotransform, crs, *, limit, colormap_name, unipolar, subtitle, name=LAYER_NAME)` split, `SITE_LAYER_NAME`, the rename-in-place, and the extent/CRS sync after a reload (ruling T5-b) must all survive.
     - The combined code must not re-open the Windows replace hazard on any path, including the site-layer path.
   - **`test_plugin_slice_layer.py`**: keep every test from both sides, adapted so each still tests what it was written for.
3. **Bring M12's code up to M9's conventions.**
   - Apply the public-API rule to every M12 plugin import of core names, and make the enforcing test pass.
   - Apply the Qt6-safe conventions from `ea89aa5` to every M12 UI module and test.
   - If the release zip build (`build_zip.py`) or the plugin metadata needs to know about new modules, it should pick them up. Check that a built zip contains `site_engine.py`, `site_export.py`, `ui/site_panel.py`, `ui/site_scope.py` and the core's `slices/site.py`.
4. **Tooling.** Install the CI-pinned versions into this worktree's venv (`./.venv/bin/pip install ruff==0.17.1 mypy==2.4.0`, or whatever `fa9a5db` pins). Run CI's lint and mypy commands exactly as `.github/workflows/ci.yml` now has them, and fix any finding in M12 code.
5. **Verify.**
   - Run both test tiers. Baseline: core+pure 609 passed, 2 skipped; qgis 846 passed at `e68419a`. M9's own test additions add to that.
   - Run the M12 concurrency tests 20 times in a loop (the `LoadCounter` tests in `test_plugin_site_engine.py` and `test_plugin_site_scope.py`), plus ruff check, format and mypy as CI runs them.
   - If M9 left a local way to run the qgis tier under QGIS 4 (a Docker recipe in its decision record `docs/superpowers/sdd/2026-10-15-nsgeo-release-m9*` or its plan), run at least `test_plugin_site_scope.py`, `test_plugin_site_engine.py` and `test_plugin_slice_layer.py` under QGIS 4 and report the result. If there is no such way, say so; do not build one.
6. **Commit and push.** Commit the merge with a message such as `Merge main (M9, v0.1.0) into nsgeo-m12`, followed by any follow-up commits for conventions and lint. Each commit ends with a `Co-Authored-By:` trailer naming your own model. Push to origin nsgeo-m12, and retry once on a network failure.

## Rules

- Trap 1 is still the top rule: at most one line-preparation QgsTask may run at a time, across all engines. Nothing in the merge may change a dispatch path.
- M9's and M11's tests stay as they are, apart from conflict resolution in `test_plugin_slice_layer.py`. M12's tests may be adapted to M9's harness conventions, but no assertion may be weakened.
- Do not touch main or any other branch.

## Report

Write the report to `integrate-main-report.md` in this directory. Include:

- each conflict and how you resolved it, with file:line;
- every convention change applied to M12 code;
- lint and mypy findings and their fixes;
- the zip-content check;
- both tiers' counts, the 20-run loop, and the QGIS 4 result or why there is none;
- commits and concerns.
