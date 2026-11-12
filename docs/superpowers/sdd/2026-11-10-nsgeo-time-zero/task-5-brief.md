### Task 5: Cubes on the time-zero clock

Run `git fetch && git merge origin/main` first (Global Constraints).

**Files:**
- Modify:
  - `packages/nsgeo-core/src/nsgeo/slices/binning.py` (`PreparedLine`)
  - `packages/nsgeo-core/src/nsgeo/slices/store.py` (`_meta`)
  - `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`: the prepare `work()`, plus `line_zero`
    and `median_zero`.
  - `packages/nsgeo-qgis/nsgeo_qgis/site_engine.py` (`line_zero`)
  - `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`: `cube_record`, `CubeRecipe`,
    `recipe_from_record`.
  - `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py` (`old_cube_note`)
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`: `restore_cube`, `_on_prepared`, and
    `line_zero_in_cube`.
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`: `set_slice_band`, `clear_slice_band`,
    and `_render`.
  - `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: the cube save call and the band lookup wiring.
- Test:
  - `packages/nsgeo-core/tests/test_slices_store.py`
  - `packages/nsgeo-qgis/tests/pure/` (the existing `slices_plan` test file)
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py:1694-1700` (comment and numbers
    only)

**Interfaces:**
- Consumes:
  - from Task 1: `zero_ns`, `retime_ns`, `sets_time_zero`, `time_base_of`;
  - from Task 2: `shown_zero_ns`.
- Produces:
  - **`PreparedLine.zero_ns: float = 0.0`,** the last field. The engine sets it from
    `result.zero_ns`.
  - **On `SliceEngine`:**
    - `SliceEngine.line_zero(key: str) -> float | None`, from the prepared lines;
    - `SliceEngine.median_zero() -> float | None`, the `np.median` of the prepared lines' zeros,
      or None when nothing is prepared.
  - **`SiteEngine.line_zero(key: str) -> float | None`:** the first non-None answer from its grid
    engines.
  - **`SlicesDock.line_zero_in_cube(key: str) -> float | None`:** from the scope on screen. That
    is `self.engine` for This grid, or the site engine.
  - **`cube_record(..., *, line_keys, time_base: str)`:** a new required keyword, written as
    `record["time_base"]`. The one caller in `plugin.py` passes
    `time_base_of(engine.provenance().steps)`.
  - **`CubeRecipe.time_base: str | None = None`.** None means the record predates the marker.
    `recipe_from_record` raises `ValueError` for a present value that is not one of the two
    constants.
  - **The cube store's `_meta`** gains `"time_base": time_base_of(cube.provenance.steps)`.
    `STORE_VERSION` is unchanged, because the key is additive and readers ignore it.
  - **`slices_plan.old_cube_note(shift_ns: float) -> str`:**
    `f"This cube was saved before times were measured from each line's first break. It was rebuilt that way, with its range moved by {shift_ns:+.2f} ns."`
  - **`ProfileDock.set_cube_zero_lookup(fn: Callable[[str], float | None] | None) -> None`.**
    - `set_slice_band(lo, hi)` stores the cube-clock band and draws it through
      `_push_slice_band()`.
    - `_push_slice_band()` converts with
      `retime_ns(t, fn(displayed_key) if known else self.shown_zero_ns(), self.shown_zero_ns())`.
    - `_render` calls `_push_slice_band()`.
    - `clear_slice_band` forgets the stored band.
    - `plugin.py` wires it with `set_cube_zero_lookup(self.slices_dock.line_zero_in_cube)`.

- [ ] **Step 1: Write the failing tests**

In `test_plugin_slices_dock.py`:
- Rework `test_prepared_z_bounds_is_the_intersection_not_the_union` (`:1785-1860`).
  `assert len(starts) == 3` becomes two assertions:
  - `assert starts == {0.0}`: decision 1, every line reads 0 at its first break;
  - `assert len({round(l.zero_ns, 6) for l in prepared}) == 3`: three different zeros.

  Keep the ends and the tightness checks. Update the docstring.
- Rework the comment and numbers in `:1723-1780` (−0.476..99.561). Keep the assertions unless the
  numbers move.

Then add:

```python
def test_a_cube_built_with_time_zero_starts_at_zero(...):
    # Preset [time_zero] on two synthetic lines.
    assert dock.engine.prepared_z_bounds()[0] == 0.0
    assert dock.z0_spin.value() == 0.0


def test_an_old_recipe_with_time_zero_restores_its_range_moved_by_the_median_zero(...):
    # A record without "time_base", z {t0_ns: 5.0, t1_ns: 40.0, dz_ns: 0.5}, preset [time_zero].
    # After restore and preparation, z0 == approx(5.0 - median), where median is the engine's
    # median_zero(). dock.error received old_cube_note(-median) exactly once.
    ...


def test_an_old_recipe_without_time_zero_restores_unchanged(...):
    ...


def test_an_old_recipe_with_nothing_prepared_is_not_shifted(...):   # Review Focus 5
    # Every line's file renamed away; restore: z0 stays 5.0, no note, no exception logged.
    ...


def test_the_slice_band_marks_the_same_samples_on_a_line_whose_stack_differs(...):
    # Preset [time_zero]; the working line's own stack is empty (radar clock). Band (10, 12) on the
    # cube clock is drawn at (10 + line_zero, 12 + line_zero) on the profile.
    ...
```

In `test_plugin_slice_export.py`:

```python
def test_a_cube_record_names_its_time_base(...):
    assert record["time_base"] == "time_zero"
    assert recipe_from_record(record).time_base == "time_zero"
    assert recipe_from_record({**record_without_time_base}).time_base is None
    with pytest.raises(ValueError):
        recipe_from_record({**record, "time_base": "sideways"})
```

In `test_slices_store.py`, add a test that a saved cube's metadata carries `"time_base"`,
matching its provenance steps, and that `load_cube` still reads it.

- [ ] **Step 2: Run them to make sure they fail**

Run the QGIS command on `test_plugin_slices_dock.py test_plugin_slice_export.py`, and the core
command on `test_slices_store.py`.
Expected: FAIL.

- [ ] **Step 3: Implement**

- **The Interfaces items above.**
- **`restore_cube`:** when `recipe.time_base is None` and the record's preset sets a time zero,
  set `self._pending_z_shift = True`. Check this with `sets_time_zero` on
  `session.site.presets.get(recipe.choice.preset, [])`.
- **`_on_prepared`:** consume the flag before `_clamp_z_to_prepared()`, the way it consumes
  `_pending_palette`.
  - If `engine.median_zero()` is not None, move both z spins by `-median`, using the same
    signal-blocked writes `_clamp_z_to_prepared` uses.
  - Emit `old_cube_note(-median)` once on `self.error`.
  - Clear the flag on every pass, so it never outlives one preparation.
- **The header seeds** (`_seed_dz_z_defaults`, `site_scope.header_z_seed`) need no change. Their
  −11.09 ns start is clamped into the prepared bounds. Confirm that the existing
  `test_the_seeded_z_range_survives_a_preset_that_crops_the_sample_axis` still passes, and record
  the result in your report (spec §4.3, "shown harmless").

- [ ] **Step 4: Run every slices file**

Run the QGIS command on
`test_plugin_slices_dock.py test_plugin_slices_engine.py test_plugin_slice_export.py test_plugin_site_engine.py test_plugin_site_scope.py test_plugin_slice_layer.py`,
and the core command on `packages/nsgeo-core/tests`.
Expected: all pass.

- [ ] **Step 5: Lint, then commit and push**

```bash
git commit -am "feat(slices): cubes on the time-zero clock; old recipes restore at their old depths (#97)"
git push
```

---

