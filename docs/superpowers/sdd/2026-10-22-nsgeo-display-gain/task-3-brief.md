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

