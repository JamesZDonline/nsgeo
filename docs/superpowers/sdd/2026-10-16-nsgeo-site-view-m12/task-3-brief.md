### Task 3: `SiteEngine`

This is the engine behind *Whole site*. It owns one M11 `SliceEngine` per included grid and
prepares them one at a time (Ruling 1, trap 1). Each grid is drawn as soon as it is ready, and
each tick is composed into a normalised site slice. The task also measures responsiveness (spec
§4.8).

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/site_engine.py`, `packages/nsgeo-qgis/scripts/bench_site.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`, `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_site_engine.py`,
  `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py`

**Interfaces:**
- Consumes:
  - Task 1's `SiteLattice`, `lattice_pixel`, `compose`, `site_axis`, `grid_axis`, `window_on`,
    `find_seams`, `normalise`;
  - M11's `SliceEngine` (`set_source`, `set_resolution`, `slice_at`, `prepared_z_bounds`,
    `frame`, `z`, `is_running`, `is_prepared`, `choice`, `provenance`, `estimate`, `clear`,
    `dispose`) and `fill`, `slice_extent`, `limit_over_slices`;
  - `session.grid(grid_id)` for each grid's `default_spacing`, `crs` and frame. Manual gains
    arrive as the `manual` argument; the engine never reads them from the session.
- Produces (`slices_plan.py`, Qt-free, with pure-tier tests):
  - `@dataclass(frozen=True) class SiteSource: transform: str; grids: tuple[SourceChoice, ...]`.
    `__post_init__` raises `ValueError` if any `choice.transform != transform` or if a grid id
    repeats.
  - `radius_cells_for(spacing_m: float, radius_spacings: float, cell: float) -> int`, which is
    `max(0, round(radius_spacings · spacing_m / cell))`.
  - `SITE_LIMIT_WINDOWS = 12` and
    `limit_windows(z: ZAxis, thickness_levels: int, max_windows: int = SITE_LIMIT_WINDOWS) ->
    tuple[SliceWindow, ...]`. This takes `plan_windows(z, thickness, thickness)` plus
    `display.shared_limit`'s thinner tail window. If there are more than `max_windows`, it keeps
    an evenly spaced subset that always includes the first and the last.
- Produces (`slices_engine.py`): `SliceEngine.cancel_preparation() -> None`. It is public and
  wraps `_cancel_in_flight()`, and its docstring explains why it exists (Ruling 1). Afterwards
  `is_running` is False. The engine's lines are not trusted: the caller re-dispatches.
- Produces (`site_engine.py`):
  - `@dataclass(frozen=True) class SiteSlice: array: np.ndarray; lattice: SiteLattice; windows:
    dict[str, SliceWindow | None]; factors: dict[str, tuple[float, float]]`.
    - `array` is `(height, width)` float32, with NaN for nodata.
    - `windows` covers every ready grid, with None meaning absent at this time.
    - `factors` is the applied `(a, b)` for each grid present, with the manual gain included.
  - `class SiteEngine(QObject)`:
    - `__init__(session, on_changed: Callable[[], None] | None = None, on_error:
      Callable[[str], None] | None = None, exclusive_with: Sequence[SliceEngine] = (), parent:
      QObject | None = None)`. `on_changed` fires whenever a grid becomes ready, fails or is
      dropped, or the geometry is rebuilt. It connects `session.site_closed` to `clear` and
      `session.grids_changed` to a geometry rebuild.
    - `set_source(source: SiteSource) -> None`. It diffs against the current source:
      - unchanged grids keep their prepared lines;
      - changed grids are queued;
      - removed grids' engines are disposed;
      - a grid with no line keys is state `"no lines"` and is never dispatched.
    - `set_resolution(resolution: Resolution) -> None`. This stores the site resolution and
      re-derives the geometry. For the bounds of the ready grids:
      - `site_z = site_axis(...)`;
      - per ready grid, `gz = grid_axis(site_z, engine.prepared_z_bounds())`, then
        `engine.set_resolution(Resolution(res.cell, res.dz_ns, gz.t0_ns, gz.t_end_ns))`, or no
        resolution when `gz` is None;
      - the lattice: grid extents transformed to the site CRS, `lattice_pixel` over the ready
        grids' azimuths.

      It raises `ValueError` naming the pixel count when `lattice.n_pixels > MAX_FRAME_CELLS`, as
      spec §4.7's size guard requires.
    - Properties: `site_z -> ZAxis | None`, `lattice -> SiteLattice | None`,
      `ready_grids -> tuple[str, ...]`, `is_running -> bool`.
    - `grid_state(grid_id: str) -> str`, one of `"ready"`, `"preparing"`, `"queued"`,
      `"no lines"`, or `"failed: <message>"`.
    - `engine_for(grid_id: str) -> SliceEngine | None`, for read-only use: provenance, z, frame.
    - `slice_at(top_ns: float, thickness_ns: float, *, radius_spacings: float, method: str,
      manual: Mapping[str, float], coverage: bool = False) -> SiteSlice`.
    - `shared_limit(thickness_ns: float, clip: Any, *, radius_spacings: float, method: str,
      manual: Mapping[str, float]) -> float`.
    - `cancel() -> None`, `clear() -> None`, `dispose() -> None`, `status_text() -> str`, and
      `wait_until_idle(timeout_ms: int = 60_000) -> bool` for tests.

**One tick, `slice_at`:**
1. For each ready grid with a z, `w = window_on(engine.z, top_ns, thickness_ns)`. If `w` is
   None, the grid is absent.
2. `values, cov = engine.slice_at(w)`.
3. `factors = normalise(method, {g: (values, cov)}, seams, manual)`.
4. For each present grid, `shown = a·fill(values, cov, radius_cells_for(spacing_g,
   radius_spacings, cell)) + b`. In `coverage` mode, show the coverage with 0 as NaN, and skip
   normalisation.
5. `compose(lattice, [(gather_g, shown_g)])`.

Caches, each dropped on any resolution change, grid edit or source change:
- **Gathers:** computed once per (grid, frame, lattice). Lattice pixel centres are transformed
  with `QgsCoordinateTransform` into a frame's CRS when it differs from the site's.
- **Seams:** computed once per geometry, from each ready grid's coverage. Coverage does not depend
  on the window, so take it from any one slice. Spacings are each grid's `default_spacing`.

**Preparation (`_dispatch_next`):** if any own engine or `exclusive_with` peer `is_running`, do
`QTimer.singleShot(50, self._dispatch_next)` and return. Otherwise pop the queue head and call its
engine's `set_source(choice)`. The engine's `on_prepared` and `on_error` mark the grid's state,
call `on_changed`, re-derive geometry and dispatch the next grid. Every callback guards itself
(trap 2).

- [ ] **Step 1: Write the failing tests.** Pure tier: `SiteSource` validation,
  `radius_cells_for`, and `limit_windows` (count ≤ 12, first and last included, the tail
  included). The qgis tier uses a fixture `site3` with three adjacent 6 × 6 m synthetic grids,
  `"A"`, `"B"` and `"C"`, four lines each, in `EPSG:32616`.

```python
def test_two_engines_never_prepare_at_once(site3, monkeypatch):
    # Line.load patched to sleep 0.05 s under a lock-guarded counter (M11's
    # test_two_different_choices_back_to_back_never_run_concurrently pattern).
    # A peer SliceEngine passed as exclusive_with is set_source'd at the same moment as
    # SiteEngine.set_source(3 grids); later, cancel() then set_source again.
    assert max_concurrent == 1 and all(states == "ready")
def test_grids_prepare_in_order_and_each_is_drawn_as_soon_as_ready(site3): ...
    # after the first on_changed, slice_at returns finite pixels over A only
def test_changing_one_grids_preset_re_prepares_only_that_grid(site3, monkeypatch): ...
    # count Line.load calls: 4, not 12
def test_a_grid_with_no_lines_is_listed_and_skipped(site3): ...
def test_a_grid_outside_the_window_is_nodata_and_named(site3): ...
    # C's lines cropped to a shorter time range: windows["C"] is None, its pixels NaN
def test_background_normalisation_evens_out_a_grid_recorded_at_double_gain(site3): ...
    # B's synthetic data written x2: with "none" mean(B pixels) ~ 2 x mean(A); with "background" ~ equal (rtol 0.05)
def test_the_manual_gain_multiplies_only_that_grids_pixels(site3): ...
def test_normalising_a_signed_site_gives_finite_factors(site3): ...      # transform NO_TRANSFORM
def test_the_shared_limit_follows_normalisation(site3): ...
def test_a_grid_in_another_crs_lands_where_its_coordinates_say(site3): ...
    # B re-declared in EPSG:26916; the B cell centre transformed to 32616 holds B's value
def test_grids_too_far_apart_for_the_lattice_are_refused_by_pixel_count(site3): ...
def test_moving_a_grid_rebuilds_the_lattice_and_seams(site3): ...
def test_removing_a_grid_drops_it_from_the_site(site3): ...
def test_a_velocity_edit_does_not_re_prepare_or_change_the_slice(site3): ...
def test_closing_the_site_mid_preparation_clears_without_overlap(site3, monkeypatch): ...
```

- [ ] **Step 2: Run them; all fail.**

- [ ] **Step 3: Implement** `slices_plan.py`'s additions, `cancel_preparation`, then
  `site_engine.py`. `status_text` reads, for example,
  `3 grids · 62 lines held in memory, 74 MB · slices redraw in 11 ms`. The memory is the sum of the
  engines' `estimate.total_bytes`. The redraw time is the smoothed time of `slice_at`, using M11's
  `_REDRAW_SMOOTHING`.

- [ ] **Step 4: Both tiers green.** Run the concurrency test 20 times in a loop and record that it
  never fails.

- [ ] **Step 5: Mutants.** Each must fail at least one test:
  1. `_dispatch_next` ignores `exclusive_with`;
  2. it ignores its own other engines;
  3. `set_source` re-queues unchanged grids;
  4. gathers not transformed for another CRS;
  5. normalisation factors applied before `fill` with `b ≠ 0` (histogram): assert the composed
     values equal `a·fill(v) + b`;
  6. the shared limit measured on unnormalised slices.

- [ ] **Step 6: Measure (spec §4.8).** `scripts/bench_site.py` builds synthetic sites of ten grids,
  20 m and 50 m on a side, at 0.5 m line spacing and M11's default resolution. It runs in
  `.venv-qgis` offscreen, with no plugin or iface. It prints, for each size:
  - preparation time for the whole site;
  - median and 90th-percentile `slice_at` over 20 windows;
  - `shared_limit` time;
  - the M11 baseline: one 50 m grid's `SliceEngine.slice_at` plus `fill`.

  Put the table in the task report. **The coordinator then rules** whether Task 5's conditional
  step applies. The rule: it applies when the 10 × 50 m median `slice_at` exceeds 100 ms or 3 × the
  one-grid baseline, whichever is larger.

- [ ] **Step 7: Commit and push.**
  `feat(qgis): SiteEngine -- one engine per grid, prepared one at a time`

---

