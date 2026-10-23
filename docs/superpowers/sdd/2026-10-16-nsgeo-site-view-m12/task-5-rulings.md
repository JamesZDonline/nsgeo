# Task 5 — controller rulings and interfaces the brief predates

These are requirements of Task 5 alongside the brief. Where one conflicts with the brief, this file wins.

## R-P5 — the This-grid engine never prepares while the site scope is showing (trap 1)

Two preparations at once segfaulted M11. SiteEngine already waits for its `exclusive_with` peer (the dock's This-grid engine) before every dispatch, but nothing makes the dock's engine wait for the site. Close that direction in the dock:

- On entering site scope, set the dock engine's `on_grid_moved` (the public hook Task 3 added to `SliceEngine`; see `slices_engine.py`) to a small guarded handler that only marks the This-grid source stale. When that hook is set, a moved grid's engine calls `clear()` instead of re-preparing itself. On leaving site scope, reset the hook to `None`, restoring M11's self-re-preparation.
- While `scope() == "site"`, `prepare()` never dispatches. That includes `rebuild_source`'s automatic call, which fires on `grids_changed`, `lines_changed`, `presets_changed` and site open. Record that a prepare is pending instead.
- `set_scope("grid")` calls `site_engine.cancel()` and then runs the pending prepare, but only once `site_engine.has_live_task` is False. Retry on a 50 ms `QTimer` until then. Never block, and guard the slot.
- Never dispatch the dock engine from inside SiteEngine's `on_changed` callback. SiteEngine notifies "preparing 0 of n" between its gate and its dispatch, so `has_live_task` can read False in that window.
- Test `test_editing_a_grid_in_site_scope_never_overlaps_preparations`:
  - patch `Line.load` to sleep under a lock-guarded counter, using the pattern in `test_plugin_site_engine.py`;
  - have the This-grid engine hold grid A, then enter site scope;
  - while the site prepares, move grid A, then trigger `lines_changed`;
  - assert `max_concurrent == 1`;
  - return to This grid and assert A prepares again at its new registration.
- Prove it against two mutants: the hook not set in site scope, and `prepare()` not deferred.

## T3-g — the plan's Step 4 is replaced

Do NOT build the fill-skipping drag degradation. Task 3's benchmark measured the following, after its residency fix:

- a 10 × 50 m site ticks in 67.9 ms median, under the rule's 100 ms threshold;
- the fill is 2.6 of 46 ms per streaming grid, so skipping it would buy nothing.

Instead, coalesce site-scope ticks:

- A slider move in site scope schedules one refresh, for example with a pending flag and `QTimer.singleShot(0, ...)`.
- At most one site tick runs per event-loop pass, always with the latest slider value, so a slow tick on a large streaming site never queues a backlog.
- The slice shown is always the full one.
- Grid scope is exactly M11's, uncoalesced.

Test `test_a_burst_of_slider_moves_draws_once_with_the_last_value`: set the slider several times with no event processing in between, then process events once. Assert one `slice_at` call, at the last value.

## T3-d — per-grid progress in the list

Spec §4.2 asks for each grid's preparation state in the list ("ready / preparing n of m / no lines"):

- `SiteEngine.grid_progress(grid_id) -> tuple[int, int] | None` is `(lines done, total)` while preparing.
- The State column shows `preparing n of m` from it. Other states come from `grid_state`.
- `on_changed` fires when a grid starts preparing and on each progress step, so refresh the rows there. Keep it cheap: the rows only.

## T2-c — a stale transform on disk

`session.set_site_view` does not validate `transform`. When building a `SiteSource` from `session.site_view()`, use the dock's default transform if the stored one is not among the transform combo's entries.

## Things measured in Task 3 that Task 5 must respect

- `SiteEngine.shared_limit` is expensive: about 3 s on a 10 × 50 m streaming site, less when resident. Cache it by key the way M11's dock caches its stretch, so it is recomputed only when the thickness, source, resolution, method, gains or radius change, never on a slider move.
- The first tick after grids become ready can include one-time cube builds of about 230 ms per 50 m grid. That is expected.

## Interfaces from Tasks 2–4 (done) — read their docstrings

- `session.py` (Task 2):
  - `slice_source(grid_id) -> dict | None`;
  - `remember_slice_source(grid_id, *, preset, lines)`;
  - `grid_gain(grid_id) -> float`;
  - `set_grid_gain(grid_id, gain)`;
  - `site_view() -> dict`;
  - `set_site_view(*, grids=None, transform=None, normalisation=None)`.

  Each mutator marks the survey dirty only on a real change.
- `slices_plan.py` (Task 3): `SiteSource(transform, grids: tuple[SourceChoice, ...])`, `radius_cells_for`, `limit_windows`, `SITE_LIMIT_WINDOWS`.
- `site_engine.py` (Task 3):
  - `SiteEngine(session, on_changed, on_error, exclusive_with, parent)`;
  - `set_source`, `set_resolution`;
  - `site_z`, `lattice`, `ready_grids`, `is_running`, `has_live_task`;
  - `grid_state`, `grid_progress`, `engine_for`;
  - `slice_at(top_ns, thickness_ns, *, radius_spacings, method, manual, coverage=False) -> SiteSlice`;
  - `shared_limit(thickness_ns, clip, *, radius_spacings, method, manual)`;
  - `cancel`, `clear`, `dispose`, `status_text`, `wait_until_idle`.
- `site_export.py` (Task 4): `plan_site_export`, `export_site`, `GeoTiffSiteWriter`, `apply_site_temporal_properties`, `write_site_coverage`. Check its actual signatures.
- Test fixtures: `site3` and `site3_factory` in `tests/qgis/conftest.py`. `test_plugin_site_engine.py` and `test_plugin_site_export.py` show how they are used.

## T4-a and T4-b — exporting the site

- **T4-a: no grid is left out of the file silently.**
  - Disable `Export site GeoTIFF…` while any included grid is queued or preparing.
  - If any included grid is left out of the file because it failed or has no lines, the success message names it.
- **T4-b: a failed export leaves no file behind.**
  - If `export_site` raises, `export_site_geotiff` removes the partly written file.
  - The layer is added only when the export succeeds.
  - M11's grid export keeps its current behaviour.
- Tests: the button is disabled while a grid prepares; a failure leaves no file and adds no layer; the message names a left-out grid.
