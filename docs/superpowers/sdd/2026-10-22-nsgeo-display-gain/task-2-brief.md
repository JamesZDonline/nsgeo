### Task 2: Plugin: the scale is measured with the gain curves switched off (#6)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/render/qimage.py` (`RadargramImage`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (`curve_param_name`, `_scale_reference`, `_render`, slider tooltip, module docstring)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py:509` (`_curve_param_name` delegates)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py` (`RadargramImage`), `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`

**Interfaces:**
- Consumes: `StepStack.result_bypassing(*indices)` and its memo (Task 1).
- Produces: `RadargramImage(rg, percentile=99.0, colormap_name=DEFAULT_COLORMAP, max_width=8192, reference: Radargram | None = None)`. The attribute `reference: Radargram` is `rg` when `None` is passed, and `limit = PercentileClip(percentile).limit(reference.data)`. `with_display(...)` keeps the reference. `with_radargram(rg, reference=None)` takes a new one.
- Produces: `curve_param_name(step: Any) -> str | None` in `profile_dock.py`, beside `time_param_name`, with the same shape. `plugin.py`'s `_curve_param_name` returns `curve_param_name(step)`.
- Produces: `ProfileDock._scale_reference(self, shown: Radargram) -> Radargram`, the radargram the display limit is taken from:
  - `shown` itself while a difference view is actually displayed (`_effective_difference_index >= 0` after `current_radargram()` has run, since a declined difference resets it).
  - Otherwise, the displayed key's stack (`stack_for(self._key, insert=self._preview_key is None)`, the same call `current_radargram` makes) with every **enabled** step that has a curve parameter bypassed: `stack.result_bypassing(*rows)`. That is `stack.result()` when there are none.
  - It never bypasses the time cutoff, so it ignores `_cutoff_row()` (spec call 11).
  - A `ValueError` from that evaluation falls back to `shown` and is logged at `Warning`.
- Exact copy for `percentile_slider.setToolTip`: `"How much of the profile may saturate. With a gain curve in the processing steps, this is measured as if the gain curve were switched off, so the curve brightens or darkens parts of the profile against a fixed scale."`

- [ ] **Step 1: Write the failing `RadargramImage` tests** in `test_plugin_profile_view.py`.
  - `test_the_limit_comes_from_the_reference_when_one_is_given`: `ri = RadargramImage(rg, reference=ref)` with `ref.data = rg.data * 10`. Assert `ri.limit == PercentileClip(99.0).limit(ref.data)` and `ri.reference is ref`.
  - `test_display_and_radargram_changes_keep_or_replace_the_reference`: `with_display(percentile=90.0).reference is ref`, its limit is taken at 90 on `ref`, `with_radargram(rg2).reference is rg2`, and `with_radargram(rg2, reference=ref).reference is ref`.

- [ ] **Step 2: Write the failing dock tests** in `test_plugin_profile_dock.py`. Use the `opened` fixture and `session.set_profiles(key, line.load())`. The synthetic axis runs about −11 to 99 ns. Let `FLAT = [[-11.0, 0.0], [99.0, 0.0]]` and `DEEP = [[-11.0, 0.0], [40.0, 0.0], [99.0, 30.0]]`, and let `clip = PercentileClip(dock.percentile).limit`.
  1. `test_without_a_gain_curve_the_limit_is_taken_from_what_is_shown`: append `dewow`. Assert `dock.image.reference is session.stack_for(key).result()` and `dock.image.limit == clip(...result().data)`.
  2. `test_a_gain_curve_edit_never_moves_the_limit`: append `dewow`, then `gain_curve` with `FLAT`, and record `limit0`. Replace row 1 with `DEEP`. Assert `dock.image.limit == limit0`. Also assert `clip(stack.result().data) > limit0`, which proves today's rule would have moved it.
  3. `test_a_curve_edit_reuses_the_cached_reference`: as in 2, `dock.image.reference` is the same object before and after the replace.
  4. `test_agc_after_a_gain_curve_does_not_blank_the_profile`: append `gain_curve` with `[[-11.0, 12.0], [99.0, 12.0]]` at row 0, then `gain_agc`. Assert `dock.image.limit == clip(stack.result_bypassing(0).data)`. The hazard is real: assert `clip(stack.source.data) > 1e3 * dock.image.limit`. The image is not flat: `np.std(to_index8(stack.result().data, dock.image.limit)) > 20`.
  5. `test_two_gain_curves_are_both_left_out_of_the_scale`: `gain_curve`, `dewow`, `gain_curve`. Assert `dock.image.limit == clip(stack.result_bypassing(0, 2).data)`.
  6. `test_a_disabled_gain_curve_leaves_todays_scale`: `dewow`, `gain_curve` (`DEEP`), then `session.set_step_enabled(key, 1, False)`. Assert `dock.image.reference is stack.result()`.
  7. `test_the_difference_view_keeps_the_scale_of_what_is_shown`: `dewow`, `gain_curve` (`DEEP`), then `dock.set_difference_index(1)`. Assert `dock.image.limit == clip(stack.difference(1).data)`.
  8. `test_selecting_the_cutoff_row_never_changes_the_brightness`, parametrised with ids `curve` and `no curve`. The stack is `dewow`, then (`curve` only) `gain_curve` with `DEEP`, then `time_cutoff` with `end_ns=50.0`. Record `limit0`, `dock.set_selected_step(<cutoff row>)`, and assert `dock.image.rg.n_samples > stack.result().n_samples` (the bypass is shown) and `dock.image.limit == limit0`. Then `dock.set_selected_step(-1)` and assert the limit is still `limit0`.
  9. `test_a_preview_takes_its_scale_from_its_own_gain_curve`: add a second line `FILE__002.DZT` (`synthetic_dzt`, its own `GridPlacement` at offset 1.0), call `session.set_profiles(key2, line2.load())`, and `session.append_step(key2, build_step("gain_curve", points=DEEP))`. Then call `session.set_preview(key2, 5)`. Assert `dock.image.limit == clip(session.stack_for(key2).result_bypassing(0).data)`.
  10. `test_the_percentile_slider_says_what_it_measures`: `"gain curve" in dock.percentile_slider.toolTip()`.

  Add a real-data test, `test_a_real_line_balanced_by_a_gain_curve_keeps_its_limit` (`@needs_real_data`, `REAL_DZT[0]`). Use the `bare` fixture's pattern to place the real file. The stack is `time_zero` (`first_break`, 0.25), `dewow` (4.0), `background_sliding` (`window_traces=200`) and `gain_curve`. The curve is flat at 0 dB from the record's start, rising to +40 dB at 50 ns and held. Then raise every point by 6 dB, and assert the limit is unchanged and equals `clip(stack.intermediate(2).data)`.

- [ ] **Step 3: Run them and see them fail.** Run the two test files with the qgis command, adding `-k "reference or limit or scale or brightness or blank or gain_curve or tooltip or says"`. Expected: the new tests fail. The `RadargramImage` tests fail with `TypeError: unexpected keyword 'reference'`.

- [ ] **Step 4: Implement** the `RadargramImage` reference, `curve_param_name` and the `plugin.py` delegation, then `_scale_reference`. `_render` must pass `reference=self._scale_reference(rg)` on both the construct and the `with_radargram` path. Add the slider tooltip. In `profile_dock.py`'s module docstring, add a paragraph naming what the limit is taken from and why (spec §3 calls 1, 4 and 11, briefly).

- [ ] **Step 5: Run the two files, then the whole qgis tier, lint and types.** Expected: all pass. Existing tests that assert a limit taken from the shown data still pass, because they have no gain curve. If one fails, read it before touching it: it may be pinning call 11's deliberate change to the cutoff.

- [ ] **Step 6: Commit and push.**

```bash
git add packages/nsgeo-qgis
git commit -m "feat(plugin): the display limit is measured with the gain curves switched off (#6)"
git push
```

---


---

# Plan-wide sections that bind this task (copied from the plan)

## Global Constraints

- Core stays numpy-only, with no Qt imports. `packages/nsgeo-core/tests/test_boundary.py` and `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py` must stay green.
- `nsgeo.render.__all__` stays sorted (`test_public_api.py` checks it).
- The plugin imports Qt only through `qgis.PyQt`.
- Every slot connected to a signal, and every Qt-invoked override (`paintEvent` included), guards its own body and reports through `_log`, never raises. Read the module docstrings of `profile_dock.py` and `gain_strip.py` before touching either file.
- Which step is a gain curve is decided by the schema's `kind == "curve"`, never by the step's name. Which step is a time cutoff is decided by `kind == "time"` (`time_param_name`).
- Display gain is never recorded in a stack and nothing here changes what a project saves.
- Any profile without an enabled gain curve renders exactly as today, except while the time cutoff's row is selected (spec call 11).
- ruff 0.17.1 and mypy 2.4.0, as pinned in CI.

## Verification commands (exactly these)

- core + pure: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q`
- qgis: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh` (several minutes; run single files while iterating)
- lint: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- types: `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`

The coordinator builds the worktree's `.venv` and `.venv-qgis` and symlinks the real DZT files into `packages/nsgeo-core/tests/data/local/` before Task 1, and records the baseline pass counts in the ledger. A real-data test that skips has validated nothing, so check the skip count.

