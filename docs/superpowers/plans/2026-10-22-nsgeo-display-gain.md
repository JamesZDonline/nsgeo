# Display Gain Implementation Plan (#6, #10)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code task is written test-first with superpowers:test-driven-development: the failing test is run and seen to fail before any production code is written.

**Goal:** The profile's brightness scale holds still while a gain curve is edited (#6), and the gain strip shows, under the curve, how close each depth is to burning out (#10).

**Architecture:** Core generalises `StepStack.result_bypassing` to any set of steps and gives it a small memo that survives editing a bypassed step, and adds `nsgeo.render.row_envelope`. In the plugin, `ProfileDock` takes the display limit from the displayed stack with every enabled gain curve bypassed, and hands `RadargramImage` that radargram as its `reference`. It also feeds the gain strip a `Headroom` (limit, envelope) and the cursor trace. The strip paints them under its existing curve.

**Tech Stack:** Python 3, numpy (core); PyQt via `qgis.PyQt` (plugin); pytest on two tiers (core+pure in `.venv`, QGIS in `.venv-qgis`).

**Spec:** `docs/superpowers/specs/2026-10-21-nsgeo-display-gain-design.md`. Read it first. §3 lists the user's decisions and the twelve calls; §4 is the behaviour this plan builds. The mock-up the user chose from is `.lavish/gain-strip-overlay.html` in the main checkout (local only; it embeds a real line).

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

## Review Focus

The inputs most likely to hurt a user that the spec's own test list does not name. Each is pinned by a test in the task named.

1. **Switching channel on a two-channel line with a gain curve in the stack.** `session.set_channel` replaces the stack's source, and a stale memo would scale the new channel by the old one's limit (Task 1: `test_a_bypass_is_recomputed_after_any_other_change[source]`).
2. **Lines that begin with all-zero traces, or data holding NaN or inf.** Real files start with empty traces. The envelope must stay finite with no warning, and the strip must still paint (Task 1: `test_row_envelope_ignores_non_finite_samples_without_warning`).
3. **A gain curve as the very first step.** The bypassed index is 0 and the reference is the source itself (Task 2: `test_agc_after_a_gain_curve_does_not_blank_the_profile` puts the curve at row 0).
4. **The strip shown after the percentile changed while it was hidden.** The band must use the current percentile, not the one it last saw (Task 3: `test_a_strip_shown_after_a_percentile_change_uses_the_new_percentile`).
5. **The cutoff row selected on a stack with no gain curve.** Selecting it must not shift the brightness either (Task 2: `test_selecting_the_cutoff_row_never_changes_the_brightness[no curve]`).

---

### Task 1: Core: bypass several steps, remember the result, and the row envelope

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/processing/stack.py` (`result_bypassing`, the mutators, `source` setter)
- Modify: `packages/nsgeo-core/src/nsgeo/render.py` (add `row_envelope`, add it to `__all__`)
- Test: `packages/nsgeo-core/tests/test_stack.py`, `packages/nsgeo-core/tests/test_render.py`, `packages/nsgeo-core/tests/test_real_files.py`

**Interfaces:**
- Produces: `StepStack.result_bypassing(self, *indices: int) -> Radargram`. What `result()` would be with every step in `indices` switched off. No indices returns `self.result()`. Any index out of range raises `IndexError` with the existing message, `f"step index {i} out of range (0..{len(self._entries) - 1})"`. Duplicates are allowed. The prefix before the smallest index comes from the intermediate cache, as today; the rest is run fresh, skipping the bypassed and the disabled steps.
- Produces: the bypass memo. `result_bypassing` returns the *same object* for the same index set until it is invalidated. It holds at most two index sets and drops the least recently used. `replace_step(i, step)` keeps the memo entries whose set contains `i` and drops the rest. The `source` setter, `append`, `insert`, `remove`, `move` and `set_enabled` drop everything. `cache_size` still counts only real intermediates.
- Produces: `nsgeo.render.row_envelope(data: np.ndarray, percentile: float, max_traces: int = 2048) -> np.ndarray`. For each row, the `percentile` (numpy's default linear method) of `|data[row, :]|` over the traces, as float64 with shape `(n_rows,)`. Above `max_traces` columns it uses the strided subset `data[:, ::ceil(n / max_traces)]`. Non-finite samples are excluded, and a row with no finite sample gives `0.0`, with no warning. `percentile` must be in `(0, 100]` and `max_traces >= 1`, else `ValueError`, matching `PercentileClip`.

- [ ] **Step 1: Write the failing stack tests** in `test_stack.py`, using the file's `stack_of` and `source` helpers. Curve points sit on the helper's 0–12.6 ns axis.

```python
CURVE = ("gain_curve", {"points": [[0.0, 0.0], [12.0, 12.0]]})

def test_result_bypassing_several_steps_skips_each_of_them():
    st = stack_of(CURVE, ("dewow", {"window_ns": 4.0}), CURVE, ("gain_agc", {"window_ns": 2.0}))
    expected = stack_of(("dewow", {"window_ns": 4.0}), ("gain_agc", {"window_ns": 2.0})).result()
    np.testing.assert_array_equal(st.result_bypassing(0, 2).data, expected.data)

def test_result_bypassing_nothing_is_the_result():
    st = stack_of(("dewow", {"window_ns": 4.0}))
    assert st.result_bypassing() is st.result()

def test_result_bypassing_rejects_any_out_of_range_index():
    with pytest.raises(IndexError, match="out of range"):
        stack_of(("dewow", {"window_ns": 4.0})).result_bypassing(0, 5)

def test_a_bypass_survives_replacing_a_bypassed_step():
    st = stack_of(("dewow", {"window_ns": 4.0}), CURVE, ("background_mean", {}))
    first = st.result_bypassing(1)
    st.replace_step(1, build_step("gain_curve", points=[[0.0, 0.0], [12.0, 30.0]]))
    assert st.result_bypassing(1) is first
```

`test_a_bypass_is_recomputed_after_any_other_change` is parametrised over seven ids, each a mutation of `st = stack_of(("dewow", {"window_ns": 4.0}), CURVE, ("background_mean", {}))` after `first = st.result_bypassing(1)`:

| id | mutation |
|---|---|
| `replace-other` | `st.replace_step(0, build_step("dewow", window_ns=2.0))` |
| `set_enabled` | `st.set_enabled(2, False)` |
| `append` | `st.append(build_step("gain_agc", window_ns=2.0))` |
| `insert` | `st.insert(0, build_step("dewow", window_ns=2.0))` |
| `remove` | `st.remove(2)` |
| `move` | `st.move(0, 2)` |
| `source` | `st.source = source(seed=1)` |

Each asserts `st.result_bypassing(1) is not first`, and that its data equals a fresh stack's: `StepStack.from_dicts(st.to_dicts())` with `.source = st.source`, then `.result_bypassing(1)`. For `remove` and `move`, index 1 must still exist.

`test_the_bypass_memo_holds_the_two_most_recent_sets`: `a = st.result_bypassing(1)`, `c = st.result_bypassing(0)`, then `assert st.result_bypassing(1) is a` (this refreshes `{1}`). Then `st.result_bypassing(2)`, `assert st.result_bypassing(1) is a`, and `assert st.result_bypassing(0) is not c`.

- [ ] **Step 2: Run them and see them fail.** Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_stack.py -q`. Expected: the new tests fail. Several-index calls fail with `TypeError: ... takes 2 positional arguments`, and the memo tests fail on `is`. The four existing `result_bypassing` tests still pass.

- [ ] **Step 3: Implement the generalised `result_bypassing` and its memo** in `stack.py`. Keep `self._bypassed: dict[frozenset[int], Radargram]` alongside `_cache`. A private `_drop_bypassed(keep: int | None = None)` is called from every mutator listed above: `keep` is the replaced index for `replace_step` and `None` everywhere else. Extend the docstring. The fresh suffix is still never written into `_cache`, because those intermediates belong to a chain the stack does not have. The memo keeps only each final result, and holds it while an edit confined to a bypassed step cannot change it, which is what a gain-curve drag needs.

- [ ] **Step 4: Run them and see them pass.** Same command. Expected: all pass, including the existing four bypass tests and `test_result_bypassing_reuses_the_prefix_and_leaves_the_real_chain_alone` (`cache_size == 1`).

- [ ] **Step 5: Write the failing envelope tests** in `test_render.py`.

```python
def test_row_envelope_is_the_per_row_percentile_of_magnitudes():
    x = np.random.default_rng(0).normal(size=(6, 50))
    np.testing.assert_array_equal(row_envelope(x, 90.0), np.percentile(np.abs(x), 90.0, axis=1))

def test_row_envelope_subsamples_wide_data_deterministically():
    x = np.random.default_rng(1).normal(size=(4, 5000))
    got = row_envelope(x, 99.0, max_traces=1000)
    np.testing.assert_array_equal(got, np.percentile(np.abs(x[:, ::5]), 99.0, axis=1))

def test_row_envelope_ignores_non_finite_samples_without_warning():
    x = np.ones((3, 4))
    x[0, 0], x[1, :] = np.inf, np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        got = row_envelope(x, 50.0)
    np.testing.assert_array_equal(got, [1.0, 0.0, 1.0])
```

`test_row_envelope_validates_its_arguments`: `percentile` 0.0 and 100.5, and `max_traces` 0, each raise `ValueError`.

In `test_real_files.py`, add `test_row_envelope_on_a_real_line_is_exact_below_the_cap`, parametrised over `FILES`. Process each file through `time_zero` (`mode="first_break", threshold=0.25`) and `dewow` (`window_ns=4.0`), assert `n_traces <= 2048`, and assert `row_envelope(rg.data, 99.0)` equals `np.percentile(np.abs(rg.data), 99.0, axis=1)` exactly.

- [ ] **Step 6: Run them and see them fail** with `ImportError: cannot import name 'row_envelope'`. Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_render.py packages/nsgeo-core/tests/test_real_files.py -q`.

- [ ] **Step 7: Implement `row_envelope`** in `render.py`, and add it to `__all__` in sorted position. Take the magnitudes of the strided columns, set the non-finite ones to NaN, and use `np.nanpercentile` along axis 1, wrapping only the all-NaN case so it gives `0.0` with no `RuntimeWarning`. The docstring records why the cap is 2048. Every real line in the corpus is under it, so ordinary lines get an exact answer, and a strided subset measured up to 0.14 of the display limit off at stride 2 on a real line.

- [ ] **Step 8: Run the full core + pure command, lint and types.** Expected: everything passes. The real-data test must not skip.

- [ ] **Step 9: Commit and push.**

```bash
git add packages/nsgeo-core
git commit -m "feat(core): bypass several steps with a memo that survives a bypassed edit; row_envelope"
git push
```

---

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

### Task 3: Plugin: the strip shows headroom under the curve (#10)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/gain_strip.py` (`Headroom`, `set_headroom`, `set_trace`, `x_of_amplitude`, colours, `paintEvent`, module docstring)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (`_push_headroom`, `_push_trace`, and the call sites below)
- Modify: `docs/guide/getting-started.md:229` (the `gain_curve` bullet)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py`

**Interfaces:**
- Consumes: `row_envelope` (Task 1); `dock.image.limit`, `dock.image.rg` and `_scale_reference` (Task 2).
- Produces, in `gain_strip.py`:

```python
@dataclass(frozen=True)
class Headroom:
    limit: float          # the display limit, > 0
    t0_ns: float          # time of the first displayed row
    dt_ns: float
    envelope: np.ndarray  # one value >= 0 per displayed row
    one_sided: bool       # unipolar output: draw the band on the positive side only
```

  - `GainStrip.set_headroom(self, headroom: Headroom | None) -> None`. `None` draws the curve alone, and also clears the trace.
  - `GainStrip.set_trace(self, trace: np.ndarray | None) -> None`. One value per displayed row. Ignored while there is no headroom.
  - Read-only properties `headroom` and `trace`.
  - `GainStrip.x_of_amplitude(self, a: float) -> float` = `w / 2 + clip(a / limit, -OVERSHOOT, OVERSHOOT) * LIMIT_FRACTION * (w / 2 - PAD_X)`, where `w = self.width()`, `LIMIT_FRACTION = 0.8` and `OVERSHOOT = 1.25`. At the overshoot the value lands exactly on `w - PAD_X`. Defined only with a headroom set.
  - Row `i` is drawn at `y_of_time(t0_ns + i * dt_ns)`, the times `GainCurve.apply` evaluates at.
  - Colours: `ENVELOPE_COLOUR = QColor(0, 0, 0, 31)`, `PAST_LIMIT_COLOUR = QColor(179, 38, 62)` (the band uses it at alpha 184, the trace solid), `TRACE_COLOUR = QColor(20, 20, 20)`, `LIMIT_COLOUR = QColor(60, 60, 60)` (1 px, `Qt.PenStyle.DotLine`), and `ZERO_COLOUR` changes to `QColor(130, 185, 222)` (still dashed).
  - Paint order, bottom to top: background, band, trace, limits, then today's 0 dB line, curve, handles and labels. The band and the trace are each painted twice: clipped to the strip inside the limits in their own colour, then clipped to the two outside regions in red.
- Produces, in `ProfileDock`:
  - `_push_headroom(self) -> None`. It returns at once if the strip is hidden (`isHidden()`) or there is no image. While a difference is displayed it calls `set_headroom(None)`. Otherwise it builds `Headroom(limit=self.image.limit, t0_ns=rg.t0_ns, dt_ns=rg.dt_ns, envelope=row_envelope(rg.data, self.percentile), one_sided=<displayed stack>.output_unipolar)` from `rg = self.image.rg`, then calls `_push_trace()`.
  - `_push_trace(self) -> None`. With a headroom set, it calls `set_trace(rg.data[:, c])` for `c = self.session.current_trace` when `0 <= c < rg.n_traces`, else `set_trace(None)`.
  - Call sites: the end of `_render` (after `_show_cutoff`); `_display_changed` (after the image update); `show_gain_strip` (after `show()`); `_exit_preview`, where it re-shows the strip; and `_on_trace_changed` (`_push_trace` only). Cursor moves must never recompute the envelope (spec §5).

- [ ] **Step 1: Write the failing strip tests** in `test_plugin_gain_strip.py`, on the existing `strip` fixture (96 px wide, 200 rows of 0.5 ns from 0 ns, curve `[[0, 0], [100, 20]]`). `h(env, one_sided=False)` builds `Headroom(2.0, 0.0, 0.5, env, one_sided)`. Probe pixels with `strip.grab().toImage().pixelColor(x, y)`, using `y = int(strip.y_of_time(0.5 * row))`.
  1. `test_amplitudes_map_to_the_centre_the_limits_and_the_edge`: after `set_headroom(h(np.zeros(200)))`, `x_of_amplitude` gives `0 -> 48.0`, `2.0 -> 78.4`, `-2.0 -> 17.6`, `10.0 -> 86.0` and `-10.0 -> 10.0` (all `approx`).
  2. `test_a_depth_past_the_limit_is_painted_red`: the envelope is `1.0` for rows 0–99 and `2.4` for rows 100–199. At `x = 82` (between the limit, 78.4, and 1.2 × limit, 84.5) row 150 is red (`red > 150`, `green < 100`), and row 50 is the background (`> 240` in all three channels).
  3. `test_inside_the_limits_the_band_is_grey`: with that same headroom, at `x = int(x_of_amplitude(0.25))` row 50 is grey: channels within 3 of each other and below 245.
  4. `test_a_one_sided_band_leaves_the_negative_side_empty`: `one_sided=True`, envelope `1.0` everywhere. At `x_of_amplitude(-0.5)` row 50 is the background, and at `x_of_amplitude(0.5)` it is grey.
  5. `test_the_cursor_trace_is_drawn_and_can_be_cleared`: envelope zeros, then `set_trace(np.full(200, 1.0))`. Some pixel in `x_of_amplitude(1.0) ± 1` at row 50 is darker than 80. After `set_trace(None)`, none is.
  6. `test_no_headroom_draws_the_curve_alone`: `set_headroom(None)`. At `x = 78` row 150 is the background, and `strip.trace is None`.
  7. `test_the_zero_db_line_is_blue`: in the column `round(strip.x_of_db(0.0))`, rows 20 to 40, at least one pixel has `blue > red + 40`.

- [ ] **Step 2: Write the failing dock tests** in the same file. Use the pattern of `test_profile_dock_shows_the_strip_only_when_asked`, with `dewow` and `gain_curve` (`FLAT`, as in Task 2) in the stack and `dock.show_gain_strip(FLAT, "c")`.
  8. `test_the_strip_receives_the_displayed_envelope_and_the_display_limit`: `headroom.limit == dock.image.limit`, `headroom.envelope` equals `row_envelope(dock.image.rg.data, dock.percentile)`, and `headroom.t0_ns == dock.image.rg.t0_ns`.
  9. `test_a_curve_edit_keeps_the_limits_still_and_moves_the_band`: replace the curve with `DEEP`. `headroom.limit` is unchanged, and the envelope's last row has grown about 31.6 times (`approx`, `rel=1e-6`).
  10. `test_the_cursor_trace_follows_the_session_cursor`: just after opening, `strip.trace is None`. After `session.set_trace(key, 0)` it equals `rg.data[:, 0]`. After `session.set_trace(key, 10**6)` (the session clamps it) it equals the last column.
  11. `test_the_difference_view_draws_the_curve_alone`: `dock.set_difference_index(1)`, then `strip.headroom is None`.
  12. `test_the_percentile_slider_rescales_the_band`: `percentile_slider.setValue(950)`. The envelope equals `row_envelope(rg.data, 95.0)` and the limit equals the new `dock.image.limit`.
  13. `test_a_strip_shown_after_a_percentile_change_uses_the_new_percentile`: `show_gain_strip(None)`, `setValue(950)`, then `show_gain_strip(FLAT, "c")`. The envelope is at 95.0.
  14. `test_unipolar_output_gives_a_one_sided_band`: append `amp_envelope` after the curve, and `headroom.one_sided` is true.

- [ ] **Step 3: Run them and see them fail.** Run `test_plugin_gain_strip.py` with the qgis command. Expected: the new tests fail with `ImportError: cannot import name 'Headroom'` or `AttributeError`.

- [ ] **Step 4: Implement** the strip's headroom drawing, then the dock's `_push_headroom` and `_push_trace` and their call sites. Extend `gain_strip.py`'s module docstring with a short paragraph: what the band, trace and limits are; that their amplitude axis is separate from the curve's dB axis; and that the 0 dB line is blue so it reads as part of the curve.

- [ ] **Step 5: Update the guide.** Replace the `gain_curve` bullet at `docs/guide/getting-started.md:229` with exactly:

```markdown
- Select a `gain_curve` step, and a strip beside the profile lets you drag its
  control points. The profile's brightness is measured as if the gain curve were
  switched off, so raising part of the curve brightens only that part, and
  pushing too far turns it solid black and white. Under the curve, the grey band
  shows how loud the loudest parts of the line are at each depth, and the black
  line is the trace under the cursor. The dotted lines are the limits of what the
  profile can show. Anything past them is drawn red, and is solid black or white
  on the profile.
```

- [ ] **Step 6: Run the whole qgis tier, core + pure, lint and types.** Expected: all pass. In the task report, record one timing: the mean time of `dock._render()` with the strip shown, on `REAL_DZT[0]` tiled to 6301 traces (`np.tile` on the loaded profile, set through `session.set_profiles`), over 20 curve replacements. The spec's budget is ~120 ms per render (`render.py:50`). Report the number; don't assert it.

- [ ] **Step 7: Commit and push.**

```bash
git add packages/nsgeo-qgis docs/guide/getting-started.md
git commit -m "feat(plugin): the gain strip shows the line's envelope, the cursor trace and the display limits (#10)"
git push
```

---

## After the tasks (coordinator)

1. Final whole-branch review on opus, then one fix wave if needed.
2. **Human gate: build and walkthrough.** Deploy the branch to a QGIS profile (ask which: `ns_geo`'s symlink points at `.worktrees/nsgeo-main`). Publish a walkthrough page with results recorded, and have the user balance a real line by hand on Windows QGIS 3 and QGIS 4 before any merge decision. It must cover: a curve with no AGC now doing something; raising the deep point brightening only the deep part; pushing past the limit and seeing red in the strip as the profile goes solid; the cursor trace following the mouse; selecting and deselecting the cutoff and the gain curve with no jump in brightness; and a profile with no gain curve looking as it did.
3. Note in the help-pages ledger (`.worktrees/help-pages/.superpowers/sdd/2026-10-15-nsgeo-help-pages-chunk1/`) that the drafted `gain_curve` page describes the old renormalisation and needs rechecking once this merges.
4. Merge only on the user's go. The PR closes #6 and #10.
