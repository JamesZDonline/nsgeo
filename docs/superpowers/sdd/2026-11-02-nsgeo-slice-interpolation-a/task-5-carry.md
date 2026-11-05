# Task 5 — coordinator carry-ins (binding, in addition to the brief)

These come from the pre-flight scan and from Tasks 1–4's reviews. Each is a requirement of this task.

## A. Tests the brief's list missed (Ruling 4)
1. Also update every test that uses the site names this task removes — `radius_spacings` keyword arguments, `radius_spacing_spin`, `DEFAULT_RADIUS_SPACINGS`, `radius_cells_for`, `fill`, `disc_kernel`, `clear_kernel_cache`, `NSGEO_SITE_FILL_RADIUS_SPACINGS`. Known files: `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py` (radius_spacings kwargs), `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py` (tests of DEFAULT_RADIUS_SPACINGS / radius_cells_for go with their subject), `test_plugin_site_scope.py` (radius_spacing_spin), `test_plugin_site_engine.py` (`TICK = {"radius_spacings": 1.5, ...}`, `expected_shown`'s `a * fill(v) + b` oracle at ~:84-108, ~20 `slice_at`/`shared_limit` calls with `radius_spacings=`, a `fill(values, coverage, 0)` at ~:670), `test_plugin_site_export.py` (`radius_spacings` kwargs and `NSGEO_SITE_FILL_RADIUS_SPACINGS` asserts at ~:31, :93, :134, :281, :296, :303). Rewrite each to the new API keeping its intent: e.g. `expected_shown` becomes `a * engine.finish(values, cov, finish) + b` built from the core pipeline, a radius-0 case becomes method "none". Say in your report which tests you rewrote, removed (and why), or added.
2. Keep `test_a_0_2_0_remembered_radius_is_ignored` (test_plugin_slices_dock.py) green: it plants `{"radius_spacings": ...}` in the record directly, not through the keyword you remove.
3. Tighten `test_the_interpolation_group_replaces_fill_radius` (test_plugin_slices_dock.py ~:676): it currently allows one "Fill radius" label, pinned to `radius_spacing_spin`. After this task there must be none.
4. `packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py` pins `"edited"` in SHADOWED with an exact connects count; raise it when `site_finish.edited` is connected.

## B. Interfaces from earlier tasks
5. `SliceEngine` (slices_engine.py) now has `finish_settings(finish: SliceFinish) -> FinishSettings` (RuntimeError with no source), `weights_cached(finish) -> bool`, `finish(values, coverage, finish) -> np.ndarray` (cache keyed on (frame, method, max_distance_m, search_radius_m) plus a populated-mask check — Ruling: smoothing never changes weights), and `shared_limit(thickness_levels, clip, finish)`. `SiteEngine._engines: dict[str, SliceEngine]` holds one per grid.
6. `FinishPanel(parent=None, *, metres_label: bool)` in ui/finish_panel.py, signal `edited(str, object)`, `value()`, quiet `set_value`, `set_spacing`, widgets `method_combo`, `max_distance_spin`, `smooth_x_spin`, `smooth_y_spin`; `busy_cursor()` in the same module. `dock.grid_finish` already exists (metres_label=True) and is placed directly after `resolution_group`; put `site_finish` (metres_label=False) beside it.
7. `session.remember_site_resolution(*, ..., method=None, max_distance_spacings=None, smooth_x_m=None, smooth_y_m=None)`; kwarg names equal `FINISH_FIELDS`, so `remember_site_resolution(**{field: value})` works. `site_resolution()` returns `dict[str, float | str]`; seed with `SliceFinish().updated(remembered)`.
8. A raising receiver of `FinishPanel.edited` is reported by PyQt's unraisable hook, not caught by the panel. The site scope's slot for `site_finish.edited` must guard its own body (`try/except Exception` → `_log` / `dock.error`), as site_scope.py's other slots do.

## C. Small fixes in code this task touches
9. `SiteEngine.held_bytes` (site_engine.py ~:969-984) counts lines and cube bytes but not the weights each grid engine now holds; count them (each SliceEngine's cached `FillWeights.nbytes` when present, or the estimate's `weights_bytes` — say which and why). This grid's `format_status` already counts `weights_bytes` (Task 4).
10. Stale "five Resolution widgets/spins" text in slices_dock.py (~:494, :633, :758, :1913) — after `radius_spacing_spin` goes, recount and correct each (some "five" there count session signals, not widgets — check each). The comment at ~:1930 naming `SiteScope._on_radius_changed` goes with that method.
11. `radius_cells_for`'s docstring (slices_plan.py ~:455-458) goes with the function.

## D. Do not touch
12. The unmerged `nsgeo-m14` branch has a test that imports `fill` from `nsgeo.slices`. Do not touch that branch; whichever merges second updates it (Global Constraints).
