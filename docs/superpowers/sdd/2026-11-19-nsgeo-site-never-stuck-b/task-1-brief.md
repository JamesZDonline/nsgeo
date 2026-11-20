### Task 1: Core, plans that can stop and say how far they are

**Files:**
- Create: `C/slices/stopping.py`. `SolveStopped` moves here; `curvature.py` and `nsgeo.slices` re-export it unchanged.
- Modify: `C/slices/interpolate.py`: `plan_fill`, `reach_mask`, `_reach`, `_neighbourhoods`, `_kriging_weights` and the plan-chunk loop.
- Modify: `C/slices/curvature.py`: `plan_curvature`, `_grow`, `_stencil`.
- Modify: `C/slices/multigrid.py`: `build_hierarchy`, checked once per level.
- Test: `CT/test_slices_interpolate.py`, `CT/test_slices_curvature.py`.

**Interfaces:**
- **Produces:**
  - `plan_fill(populated, cell, method, max_distance_m, search_radius_m, *, should_stop: Callable[[], bool] | None = None, progress: Callable[[float], None] | None = None) -> SliceFill`
  - `plan_curvature(populated, cell, max_distance_m, *, should_stop=None, progress=None) -> CurvaturePlan`
  - `reach_mask(populated, cell, max_distance_m, *, should_stop=None) -> ndarray`
- **When `should_stop()` returns True,** they raise `SolveStopped`. The checks sit:
  - between neighbour offsets in `_reach` and `_neighbourhoods`, at least every 32 offsets;
  - between plan chunks;
  - between kriging solve chunks;
  - between `plan_curvature`'s stages;
  - once per hierarchy level.

  `eigh` cannot be stopped and is left alone.
- **`progress`** receives non-decreasing fractions in [0, 1], ending with exactly `1.0` on success. The split between stages is the builder's.

- [ ] **Step 1: Write the failing tests**
  - `test_a_plan_with_stop_and_progress_is_bit_identical`: IDW, kriging and `min_curvature`, on the fixture of the existing `test_the_plan_does_not_depend_on_the_chunk_size`. With `should_stop=lambda: False` and a progress list, every array equals the plain call's (`np.array_equal`, including `CurvaturePlan.coefficients` and each hierarchy level). The progress list is non-decreasing, inside [0, 1], and ends at 1.0.
  - `test_a_plan_stops_when_asked`: for each method, `should_stop` returns True from its third call onward, and `pytest.raises(SolveStopped)`.
  - `test_a_plan_stops_inside_the_neighbour_search`: a fixture large enough that `_neighbourhoods` runs more than 64 offsets. `should_stop` flips once `progress` has reported any fraction above 0. Raises within the search, which the progress value at the raise shows below the weight stage's start.
  - `test_solve_stopped_is_one_class_everywhere`: `nsgeo.slices.SolveStopped is nsgeo.slices.curvature.SolveStopped is nsgeo.slices.stopping.SolveStopped`.
- [ ] **Step 2: Run them and see them fail.** Expected: a TypeError on the unknown keyword arguments, and an ImportError for `stopping`.
- [ ] **Step 3: Implement.** Thread `should_stop` and `progress` through without changing any arithmetic. Python 3.9 only: no `zip(strict=)` and no `match`.
- [ ] **Step 4: Run** the core suite and `ruff`. Expected: all pass.
- [ ] **Step 5: Commit:** `feat(slices): fill and curvature plans can stop and report progress (#193)`.

---

