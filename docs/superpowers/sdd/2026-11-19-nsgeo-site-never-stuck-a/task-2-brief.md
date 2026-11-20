### Task 2: #157 items 1 and 3, the coverage edge line and north-up plan memory

**Files:**
- Modify: `C/slices/site.py` (`compose_footprints`, ~line 287)
- Modify: `C/slices/resample.py` (`Taps.lean`, `Taps.take`, `sample_counts`)
- Modify: `C/slices/display.py` (the north-up plan cache, ~lines 262–275, `north_up_plans_nbytes`,
  `clear_north_up_plans`)
- Modify: `C/slices/__init__.py` (export the two new functions)
- Modify: `P/slices_plan.py` (`format_status(..., extra_bytes=0)`)
- Modify: `P/slices_engine.py` (`status_text` counts the plans)
- Test: `CT/test_slices_site.py`, `CT/test_slices_resample.py`, `CT/test_slices_display.py`,
  `T/pure/test_pure_slices_plan.py`, `T/qgis/test_plugin_slices_engine.py`

**Interfaces:**
- **Produces `Taps.lean() -> Taps`.**
  - When not `exact`, it returns `self`.
  - When `exact`, it returns taps with the same `nearest`, `nx`, `ny` and `exact=True`, but `ids`
    and `weights` of shape `(4, 0)`.
  - `take()` on lean taps returns lean taps.
  - `sample` already returns before reading `ids` when exact. `sample_counts` gains an exact path
    that reads `nearest` only: the count at the nearest cell, NaN where outside or not finite and
    positive. Exact means each point sits on one cell centre, so this equals today's largest
    positive-weight corner.
  - Only the north-up plan uses `lean()`. Cut sections (`C/slices/section.py`) read `ids` and
    `weights` and keep full taps.
- **Produces `north_up_plans_nbytes() -> int` and `clear_north_up_plans() -> None`** in
  `C/slices/display.py`, both exported from `nsgeo.slices`.
  - The `functools.lru_cache` on `_north_up_plan` is replaced by an explicit two-slot LRU (an
    `OrderedDict` behind a `threading.Lock`, since exports call `to_north_up` on a worker thread).
  - `north_up_plans_nbytes()` sums `taps.nbytes` over the plans held.
  - `_build_north_up_plan` stores `taps.lean()`.
- **Produces `format_status(mode, n_lines, estimate, redraw_ms, *, extra_bytes: int = 0) -> str`.**
  `extra_bytes` is added to the held figure.
- **Produces a change to `SliceEngine.status_text()`:** it passes
  `extra_bytes=north_up_plans_nbytes()`, so This grid's status line counts the cached plans.

- [ ] **Step 1: Write the failing tests**

```python
# CT/test_slices_site.py: the phase sweep (#157 item 1)
@pytest.mark.parametrize("ratio", [8, 16])
def test_a_coarse_preview_never_misses_a_grids_edge_line(ratio):
    cell, n = 0.05, 400
    pixel = cell * ratio
    misses = []
    for k in range(64):  # the lattice phase, across one whole pixel
        offset = k * pixel / 64
        frame = CubeFrame((offset, offset), 0.0, cell, n, n, CRS)
        lat = SiteLattice.covering([slice_extent(frame)], pixel, CRS)
        where = footprint(bilinear_taps(frame, lat.pixel_centres()), lat.height, lat.width)
        for axis, index in (("col", 0), ("col", n - 1), ("row", 0), ("row", n - 1)):
            one = np.full((n, n), np.nan, dtype=np.float32)
            if axis == "col":
                one[:, index] = 1.0
            else:
                one[index, :] = 1.0
            out = compose_footprints(lat, [(where, one)], counts=True, cells_per_pixel=ratio)
            if not np.isfinite(out).any():
                misses.append((k, axis, index))
    assert misses == []
```

- **`CT/test_slices_resample.py`:**
  - `test_lean_taps_drop_ids_and_weights_and_sample_the_same`. On an axis-aligned frame whose
    points are its cell centres, `taps.exact` holds. `lean = taps.lean()` has
    `lean.ids.size == 0 and lean.weights.size == 0`.
    - `sample(v, lean)` equals `sample(v, taps)`, NaNs included. The values hold NaN and inf.
    - `sample_counts(c, lean)` equals `sample_counts(c, taps)`. The counts hold 0, NaN and positive
      values.
    - `lean.take(idx)` is lean and samples the same as `taps.take(idx)`.
  - `test_lean_on_inexact_taps_is_the_same_object`. On a rotated frame, `taps.lean() is taps`.
- **`CT/test_slices_display.py`:**
  - `test_the_north_up_cache_reports_what_it_holds`:
    1. `clear_north_up_plans()`, then `north_up_plans_nbytes() == 0`.
    2. `to_north_up` on a rotated frame F1 and an axis-aligned frame F2 makes `north_up_plans_nbytes()`
       equal `_north_up_plan(F1)[0].nbytes + _north_up_plan(F2)[0].nbytes`.
    3. F2's cached taps hold `ids.size == 0`.
    4. A third frame F3 evicts F1, so the total equals F2's plus F3's.
  - `test_an_exact_north_up_plan_holds_no_ids_or_weights` covers point 3 alone, on an 800 × 1000
    axis-aligned frame. Its `nbytes` is under 4 MB (`nearest` only: 3.2 MB).
- **`T/pure/test_pure_slices_plan.py`:**
  - `test_format_status_counts_extra_bytes`. `format_status(…, extra_bytes=50 * 2**20)` names 50 MB
    more than the same call without it. Use the existing test's estimate and compare through
    `format_bytes`.
- **`T/qgis/test_plugin_slices_engine.py`:**
  - `test_this_grids_status_counts_the_cached_north_up_plans`. A prepared engine, after a
    `to_north_up` on a rotated frame, has `north_up_plans_nbytes() > 0`. Its `status_text()` equals
    `format_status(engine.mode, engine.line_count, engine.estimate, engine._redraw_ms,
    extra_bytes=north_up_plans_nbytes())`.

- [ ] **Step 2: Run them and see them fail**
  - Core: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_site.py packages/nsgeo-core/tests/test_slices_resample.py packages/nsgeo-core/tests/test_slices_display.py -q -p no:xonsh -k "edge_line or lean or north_up"`
  - Pure: `./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py -q -p no:xonsh -k extra_bytes`
  - QGIS: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py -k north_up -q`

  **Expected:**
  - the sweep fails with misses (#157 measured 8 of 64 phases at 8× and 20 of 64 at 16× for first
    or last lines);
  - the others fail with ImportError, AttributeError or TypeError.

- [ ] **Step 3: Implement**
  - The reach in `compose_footprints` becomes
    `max(math.ceil(cells_per_pixel / math.sqrt(2.0)), cells_per_pixel - 1)`. Keep the
    `counts and cells_per_pixel > 1` condition.
  - Fix the docstring sentence about the reach.
  - Then add the Interfaces block's `lean`, `take`, `sample_counts` path, cache, functions,
    `format_status` and `status_text` changes.
  - The comment above `_NORTH_UP_PLANS` says "about 52 bytes a point". Make it say an exact plan
    holds 4.

- [ ] **Step 4: Run the Step 2 commands, then the whole core and pure suites.** Expected: all pass.
  The existing `test_a_preview_shows_every_one_cell_line_of_coverage` still passes.

- [ ] **Step 5: Commit and push:** `fix(slices): a coarse preview keeps a grid's edge line; north-up plans count and shed what they don't read (#157)`.

---

