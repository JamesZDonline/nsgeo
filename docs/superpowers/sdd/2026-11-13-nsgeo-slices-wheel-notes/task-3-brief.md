### Task 3: dz's floor and the level limit (#177)

Spec §3.

**Files:**
- Modify: `nsgeo_qgis/slices_plan.py` (add the limit beside `Resolution`)
- Modify: `nsgeo_qgis/slices_engine.py` (`set_resolution` ~1018, `_rebuild_geometry`)
- Modify: `nsgeo_qgis/site_engine.py` (`_rebuild_geometry`'s per-grid loop)
- Modify: `nsgeo_qgis/ui/site_scope.py` (`Spins`, `capture_spins`, `restore_spins`, new
  `set_dz_floor` and `site_dt_floor`, `seed_z`)
- Modify: `nsgeo_qgis/ui/slices_dock.py` (`_seed_dz_z_defaults`, `restore_cube`, `_apply_resolution`)
- Test: `tests/pure/test_pure_slices_plan.py`, `tests/qgis/test_plugin_slices_engine.py`,
  `tests/qgis/test_plugin_slices_dock.py`, `tests/qgis/test_plugin_site_scope.py`

**Interfaces:**
- Consumes: Task 2's `Entry`, `REFUSAL`, `SlicesDock._grid_refusal`, `show_warnings()`,
  `SiteEngine.geometry_problem`.
- Produces, in `slices_plan`:
  - `LEVELS_PER_SAMPLE = 2`.
  - `class TooManyLevels(ValueError)`.
  - `level_limit_problem(resolution: Resolution, samples: Sequence[int]) -> str | None`:
    - it returns `None` when `samples` is empty;
    - it counts levels as `ZAxis.from_range(t0, t1, dz).nz`, and the limit is
      `LEVELS_PER_SAMPLE * max(samples)`;
    - over the limit, it returns `f"Too many levels: dz {dz:.4g} ns from {t0:,g} to {t1:,g} ns makes {nz:,} levels; this cube allows {limit:,} ({why}). Narrow z0–z1 or raise dz."`;
    - `why` is `f"twice the {n:,} samples in each line"` when every count is equal, else
      `f"twice the {max:,} samples in its deepest line"`.
- Produces `SliceEngine.set_resolution(resolution)`. It raises `TooManyLevels` *before* storing
  anything, so the engine keeps its geometry. `samples` is the raw `header.n_samples` of
  `self._choice.line_keys` still in the session; no choice means no check.
  `SliceEngine._rebuild_geometry` leaves `frame`/`z` `None` when the stored resolution is over the
  limit for the current choice. It doesn't raise there, because it runs inside `set_source` and task
  callbacks.
- Produces `SiteEngine._rebuild_geometry`. A grid's `TooManyLevels` is re-raised as
  `TooManyLevels(f"Grid {grid_id}: {exc}")`, which reaches `SiteScope.problem`.
- Produces, in `site_scope`:
  - `Spins.dz_min: float`, captured from `dz_spin.minimum()` and restored first;
  - `set_dz_floor(dock, floor: float) -> None`, signals blocked, as `set_cell_floor`;
  - `site_dt_floor(session, included: Iterable[str]) -> float | None`, the smallest `header.dt_ns`
    among each included grid's first source line (as `header_z_seed` finds them).
- Produces `SlicesDock._apply_resolution`. `except TooManyLevels` sets `_grid_refusal`, calls
  `show_warnings()` and returns, leaving the engine and the map as they were. It sits before the
  generic `except`.
- The generic minimum before any line exists stays today's 0.001 ns *(spec §3.2, my call: "keeps")*.

- [ ] **Step 1: Write the failing tests.**

Pure:

```python
def test_the_level_limit_message_is_exact():
    res = Resolution(cell=0.25, dz_ns=0.2165, t0_ns=0.0, t1_ns=100_000.0)
    assert level_limit_problem(res, [512, 512, 512]) == (
        "Too many levels: dz 0.2165 ns from 0 to 100,000 ns makes 461,894 levels; this cube "
        "allows 1,024 (twice the 512 samples in each line). Narrow z0–z1 or raise dz.")

def test_the_level_limit_names_the_deepest_line_when_counts_differ():
    res = Resolution(cell=0.25, dz_ns=0.2165, t0_ns=0.0, t1_ns=100_000.0)
    assert "allows 2,048 (twice the 1,024 samples in its deepest line)" in level_limit_problem(res, [512, 1024])

def test_native_dz_over_the_whole_record_is_within_the_limit():
    assert level_limit_problem(Resolution(0.25, 0.21653, -11.086, 99.546), [512]) is None
    assert level_limit_problem(Resolution(0.25, 0.001, 0.0, 100.0), []) is None
```

QGIS tests:
- **The floor in This grid.** `test_dz_cannot_go_below_the_sample_interval_in_this_grid(docked)`:
  - `dz_spin.minimum()` is within 1e-4 of the first line's `header.dt_ns`;
  - `setValue(0.001)` gives the minimum;
  - `stepBy(1)` from the minimum gives minimum + dt, within 1e-4.
- **The floor in Whole site.** `test_dz_cannot_go_below_the_finest_interval_in_whole_site(plugin)`:
  the same, with `site_dt_floor`.
- **Remembered records** (Review Focus 1, one test each). In every case the box shows the floor,
  the cube builds (`engine.z.nz <= 1024`), and the record still says 0.001:
  - `test_a_remembered_dz_below_the_floor_comes_back_at_the_floor(docked_two_grids)`:
    `remember_slice_resolution("A", dz_ns=0.001)`, then switch to B and back to A;
  - `test_a_site_dz_below_the_floor_comes_back_at_the_floor(plugin)`:
    `remember_site_resolution(dz_ns=0.001)`, then `whole_site`;
  - `test_a_saved_cube_with_dz_below_the_floor_restores_at_the_floor(docked)`: a `_save_cube`
    record whose `"dz_ns"` is set to 0.001.
- **The floor follows the scope.** `test_the_dz_floor_travels_with_the_scope(docked_two_grids)`:
  `capture_spins(dock).dz_min` in This grid is unchanged after a trip to Whole site and back.
- **The limit in This grid.**
  `test_a_z_range_past_the_level_limit_is_refused_in_this_grid_and_the_map_stays(docked)`:
  - **Setup:** `_ready(dock)`, then record `z = dock.engine.z` and catch errors.
  - **Action:** `z1_spin.setValue(100_000.0)`, then flush.
  - **Asserts:**
    - `dock.engine.z is z`;
    - one `REFUSAL` entry starting `"Too many levels: dz 0.5 ns from 2 to 100,000 ns"`;
    - `errors == []`.
  - **Then:** `z1_spin.setValue(30.0)` and a flush leave no entries.
- **The same z range in Whole site.** `test_the_same_z_range_is_clipped_not_refused_in_whole_site(plugin)`:
  `z1` 100,000 gives `scope.problem is None`, a drawn site, and a site axis ending at the data.
- **Engine guards.**
  - `test_a_stored_resolution_past_the_limit_builds_nothing_once_lines_arrive(...)`, in
    `test_plugin_slices_engine.py`: `set_resolution` with no choice, then `set_source` with three
    lines and a wait. `engine.frame is None and engine.z is None`.
  - `test_set_resolution_refuses_before_storing(...)`: `TooManyLevels` raises, and
    `engine.z is` the old one.
- **Mixed radars.** `test_a_site_mixing_radars_never_refuses_its_seeded_defaults(open_plugin, first)`
  (Review Focus 2):
  - parametrized `first` in `("A", "B")`;
  - grid A has 512-sample lines and grid B has 1,024-sample lines over the same 110.864 ns
    (`write_dzt` with 1,024 rows);
  - `whole_site` gives `scope.problem is None` and both grids ready;
  - `dz_spin.minimum()` is within 1e-4 of B's interval.
- **Real data.** `@needs_real_data test_real_lines_floor_at_0_2165_and_allow_1024_levels(qgis_app, tmp_path)`:
  four `REAL_DZT` lines on one grid;
  - the floor is 0.2165 (`approx 1e-4`);
  - `level_limit_problem` at the floor over the seeded range is `None`;
  - at z1 100,000 its message names "1,024 (twice the 512 samples in each line)".

- [ ] **Step 2: Run them; expect failures.** The import fails, the minimum is 0.001, and the limit
  doesn't exist yet.

- [ ] **Step 3: Implement.**
  - **`_seed_dz_z_defaults`:** call `site_scope.set_dz_floor(self, header.dt_ns)` before setting the
    values.
  - **`restore_cube`:** sets the floor from its kept keys' first line before setting `dz_spin`
    (beside Task 2's `_set_cell_floor`).
  - **`SiteScope.seed_z`:** sets the floor from `site_dt_floor(self.session, self.included())`
    before `set_spins_quietly`.
  - **No record writes:** none of the three writes a record. `_seeding` and `_updating` already
    keep the clamps from being remembered; check that each floor raise sits inside one of them.

- [ ] **Step 4: Run the four test files and the pure tier; all green.** Also run
  `test_plugin_site_engine.py` and `test_plugin_slice_export.py`, which build resolutions through
  the engines.

- [ ] **Step 5: Commit and push.** Message:
  `feat(slices): dz floors at the sample interval; refuse a cube past twice its samples (#177)`.

---

