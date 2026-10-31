# Final fix wave — nsgeo-slices-cleanup (one dispatch, all items)

Source: the final whole-branch review of 7069959..8291686. Fix every item below; each names its location, the defect and the fix. Test-first where a test is named.

## 1. Important — a hand-set z bound is lost after the empty-range fallback (both scopes)
Locations: `slices_dock.py` `_on_resolution_edited` (~1920-1948); This grid's clamp fallback `_clamp_z_to_prepared` (~1379); the site's `SiteScope.seed_z` fallback (`site_scope.py` ~785-788).
Sequence: (1) user sets z0 by hand; (2) a crop (time cutoff, or unticking the long grid in the site) puts that z0 past the data's end → the fallback shows the data range and keeps the record (Review Focus 1); (3) user sets z1 by hand → record now holds t0 > t1; (4) next restore (This grid: grid switch; site: any ready-set change) snaps z1 back to the data end; save + reopen → `_clean_resolution` drops the reversed pair, both bounds gone.
Probes (reuse): /tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/ccf55f65-8cef-4c6e-a933-979a44fba24a/scratchpad/final_probe/test_final_probe.py `::test_p1…` (This grid: shows (-11.086, 22.108), after B→A (-11.086, 33.086), after reopen record `{}`) and `::test_p5…` (site: z1 = 60, after a re-tick 99.56).
Coordinator Ruling 15: in BOTH branches of `_on_resolution_edited`, for `t0_ns`/`t1_ns`: if the record holds the other end and the pair would be empty (t1 <= t0), also remember the other end's currently SHOWN spin value in the same call. Clamps still write nothing; seeds/restores still write nothing.
Tests (fail first): one per scope — set one end, force the fallback, edit the other end, then switch grid (This grid) / re-tick (site), assert both shown bounds hold; then save + reopen and assert both remembered and shown.

## 2. Minor — the inner restore in `_seed_dz_z_defaults` has no test (`slices_dock.py` ~1877)
A mutant dropping it survives all 180 tests in the two dock files. Reviewer's probe: /tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/ccf55f65-8cef-4c6e-a933-979a44fba24a/scratchpad/final_mut_inner/ (`test_inner_restore.py`). Add the test: pick an empty grid, set dz and z1 by hand, import lines under it, assert the hand dz and z1 survive and reach the engine, record unchanged.

## 3. Minor — a timing-dependent test (`test_plugin_site_scope.py` ~1715, `test_a_grid_removed_inside_the_wait_window_clamps_the_fallback_grid`)
Wait with `spin_until(lambda: not dock.site_engine.has_live_task and not dock._resolution_owed)` (or the file's equivalent helper) before asserting, so a dropped clamp is caught regardless of machine speed.

## 4. Minor — `OverflowError` blocks opening (`packages/nsgeo-core/src/nsgeo/project.py` ~234 `_clean_resolution`, ~260 the gain cleaner)
`{'cell': 10**400}` makes `load_site` raise. Add one shared finite-number helper (try/except OverflowError/ValueError/TypeError → not finite) used by both cleaners. Core test: a huge int for a resolution field and for gain each read as unset and the survey loads.

## 5. Minor — `_filled_radius_cells` goes stale (`slices_dock.py` ~2172, with the `rebuild_source` elif)
It is set before `fill()` runs and never in coverage mode, so with coverage shown `rebuild_source` redraws on every session signal. Set it only after a successful draw, in both the fill and the coverage branches (or skip the elif while coverage is ticked — pick one, say which). Test: coverage on, a cell edit + flush, then three `presets_changed` → no redraw (count `slice_changed`).

## 6. Minor — stale comments/docstrings (one batch)
- `slices_dock.py` ~222: `_included_is_default`'s comment says "set again only by an actual grid change"; four other paths set it now (restore paths, Task 1's prune fallback). Make it accurate.
- `test_plugin_slice_layer.py` ~171-173: the corrupt-file test's docstring says the folder holds "only what the layer reads"; its asserts also keep `self.path`. Make it accurate.
- `docs/superpowers/plans/2026-10-30-nsgeo-slices-cleanup.md` Task 5 (~213-224): add one line under Task 5's Interfaces: "Superseded during execution by Ruling 14: the site's z bounds are custom per field from the remembered record (`SiteScope.seed_z`); `z_custom` and `seed_z_from_ready` were removed." Do not rewrite the rest of the plan.

## Not in this wave
Filing issues (L46, L48, L73, L78, L92, L118, the #70 preset difference) — the coordinator holds these for the user.
