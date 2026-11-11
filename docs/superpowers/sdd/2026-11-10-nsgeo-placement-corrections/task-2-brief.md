### Task 2: The placement rules, fitted lines that follow their grid, and proof that picks and slices follow

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/line_edit.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py`, in `replace_grid` only.
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_line_edit.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`

**Interfaces:**
- Consumes: Task 1's `GridPlacement.scale` and `GridPlacement.travel_shift`.
- Produces (all in `line_edit.py`, and all added to `__all__`):
  - `SCALE_NOTE = 0.2`
  - `span_m(n_traces: int, traces_per_metre: float) -> float`: `(n_traces - 1) / traces_per_metre`. Returns `0.0` when `traces_per_metre <= 0` or `n_traces < 2`.
  - `fit_scale(span: float, length: float) -> float`: `length / span`. `ValueError` when either is `<= 0`.
  - `@dataclass(frozen=True) class Fit: span: float`. This is a scale worked out when the edit is applied, against the grid's length then (the twin of `Inset`).
  - `is_fitted(placement: GridPlacement, span: float, length: float) -> bool` (call 7).
  - `LineEdit` gains `scale: float | Fit | None = None` and `travel_shift: float | None = None`. `placed()` resolves `Fit` against `length_along(frames[g], axis)` of the target grid `g`, and carries `scale` and `travel_shift` into the returned placement.
  - `LineEdit.fitted(self, span: float) -> LineEdit` returns `replace(self, start_along=Inset(0.0), scale=Fit(span))`. `ValueError` when `span <= 0`.
  - `same_placement` also compares `scale` and `travel_shift` within `SAME_M`.
  - `placement_note` adds the scale part (call 8) after the existing parts, joined with `; ` as now.
  - `followed_length(placement, old_length, new_length, span: float = 0.0) -> GridPlacement`. With `span > 0` and `is_fitted(placement, span, old_length)`, it returns the line fitted to `new_length`: Start from the inset rule and `scale=fit_scale(span, new_length)`. Otherwise it behaves as today.
  - `GridEditReport` gains `refitted: tuple[tuple[str, float, int], ...] = ()`, holding `(axis, new length, fitted lines refitted)`. `message()` produces the copy in Global Constraints. The existing `moved` field and its message are unchanged.

- [ ] **Step 1: Write the failing pure tests** in `test_pure_line_edit.py`, alongside its `GRID` (15 m along y), `FRAMES`, `FWD` and `REV`:

```python
def test_fit_puts_both_ends_on_the_edges_whichever_way_the_line_runs():
    span = 15.5  # a line that read 0.5 m long on the 15 m grid
    for seen in (dataclasses.replace(FWD, start_along=0.3), REV):
        p = LineEdit("k", seen).fitted(span).placed(FRAMES)
        first, last = p.start_along, p.start_along + p.direction * p.scale * span
        assert sorted([first, last]) == [pytest.approx(0.0), pytest.approx(15.0)]
    assert span_m(931, 60.0) == pytest.approx(15.5) and span_m(1, 60.0) == 0.0
    assert span_m(100, 0.0) == 0.0
    with pytest.raises(ValueError):
        LineEdit("k", FWD).fitted(0.0)


def test_flip_and_move_keep_scale_and_shift_and_a_pending_fit_refits():
    seen = dataclasses.replace(FWD, scale=1.02, travel_shift=0.24)
    flipped = LineEdit("k", seen).flipped(FRAMES).placed(FRAMES)
    assert (flipped.scale, flipped.travel_shift) == (1.02, 0.24)
    typed = LineEdit("k", seen).moved_to("B", FRAMES).placed(FRAMES)  # GB is 9 m along y
    assert typed.scale == 1.02
    fitted = LineEdit("k", seen).fitted(15.5).moved_to("B", FRAMES).placed(FRAMES)
    assert fitted.scale == pytest.approx(9.0 / 15.5) and fitted.travel_shift == 0.24


def test_setting_the_values_a_line_already_has_is_no_change():
    e = LineEdit("k", REV, scale=1.0, travel_shift=0.0)
    assert not e.changes(FRAMES)
    assert LineEdit("k", REV, travel_shift=0.1).changes(FRAMES)
    assert not same_placement(REV, dataclasses.replace(REV, scale=1.001))


def test_a_scale_far_from_one_is_noted():
    assert placement_note(dataclasses.replace(FWD, scale=1.45), GRID) == (
        "scale ×1.450 stretches it by 45%"
    )
    assert placement_note(dataclasses.replace(FWD, scale=0.7), GRID) == (
        "scale ×0.700 compresses it by 30%"
    )
    assert placement_note(dataclasses.replace(FWD, scale=1.19), GRID) == ""
    assert placement_note(dataclasses.replace(FWD, travel_shift=3.0), GRID) == ""  # call 4


def test_a_fitted_line_is_fitted_again_when_its_grid_changes_length():
    span = 15.5
    fitted_rev = dataclasses.replace(REV, scale=15.0 / span)
    assert is_fitted(fitted_rev, span, 15.0)
    again = followed_length(fitted_rev, 15.0, 16.0, span)
    assert (again.start_along, again.scale) == (pytest.approx(16.0), pytest.approx(16.0 / span))
    typed = dataclasses.replace(FWD, scale=1.02)  # ends at 15.81, not on the edge
    assert not is_fitted(typed, span, 15.0) and followed_length(typed, 15.0, 16.0, span) == typed
    as_recorded = dataclasses.replace(FWD)  # scale 1 is never "fitted"
    assert not is_fitted(as_recorded, 15.0, 15.0)
    shifted = dataclasses.replace(fitted_rev, travel_shift=0.3)  # call 4: ends judged unshifted
    assert is_fitted(shifted, span, 15.0)


def test_the_length_report_counts_refitted_lines():
    both = GridEditReport("F", moved=(("y", 11.0, 1),), refitted=(("y", 11.0, 2),))
    assert both.message() == (
        "F is now 11.00 m along y; its 1 reversed line(s) moved with the far edge, "
        "and its 2 fitted line(s) were fitted to the new length."
    )
    assert GridEditReport("F", refitted=(("y", 11.0, 2),)).message() == (
        "F is now 11.00 m along y; its 2 fitted line(s) were fitted to the new length."
    )
```

- [ ] **Step 2: Run the pure file and see the new tests fail.**
- [ ] **Step 3: Implement the `line_edit.py` interfaces above.**
- [ ] **Step 4: Write the failing QGIS tests.**
  - **`test_plugin_session.py`:** a new test, `test_a_grid_length_change_keeps_fitted_lines_fitted`.
    - **Setup:** Grid `F` is 10.5 m along y, with lines from `synthetic_dzt(..., n_traces=601)` (span 10.0 m at 60/m):
      - a forward line fitted to the grid (`start_along=0.0`, `scale=1.05`);
      - a reversed line fitted to the grid (`start_along=10.5`, `scale=1.05`);
      - a forward line at scale 1.
    - **Action:** `replace_grid(replace(F, size_y=11.0))`.
    - **Assert:**
      - The first two lines have `scale == approx(1.1)`, and their recorded ends lie on 0 and 11.
      - The third line is unchanged.
      - `report.message()` is the "both kinds" copy with `n=1`, `m=2`.
      - There was one `grids_changed` and one `lines_changed`.
  - **`test_plugin_layers.py`:** a new test, `test_a_pick_follows_a_destagger_and_a_scale_edit`, using the `populated` fixture, `_a_pick` and `_rows`.
    - **Setup:** write a pick at trace 30 on `raw/FILE__001.DZT`.
    - **Action:** `session.edit_lines([LineEdit(key, placement, travel_shift=0.24, scale=0.95)])`.
    - **Assert:**
      - The row's `distance_m` equals `session.line_for_key(key).distance_along()[30]`.
      - Its point equals `_line_point(session, key, 30)` (abs 1e-9).
      - `trace` and `note` are unchanged.
  - **`test_plugin_slices_engine.py`:** a new test beside `test_a_placement_edit_to_a_prepared_line_re_prepares`, named `test_a_scale_or_destagger_edit_to_a_prepared_line_re_prepares`, using the same `sourced` fixture and the module's `_edit`.
    - **Action:** `_edit(session, key, scale=0.95)`.
    - **Assert:** one more preparation, with the prepared coords equal to `trace_coords`.
    - **Then:** the same for `_edit(session, key, travel_shift=0.2)`.
- [ ] **Step 5: Run those three files and see the session test fail.** The layers and slices tests should pass as soon as `same_placement` compares the new fields (call 12). If either fails, that is a finding: report it rather than adding code to the engine.
- [ ] **Step 6: Change `replace_grid`.**
  - Run every line on the changed axis, not only the reversed ones, through `followed_length(p, old_len, new_len, span_m(line.n_traces, line.header.traces_per_metre))`.
  - Count reversed lines moved into `moved`, as today. Count fitted lines refitted into `refitted`.
  - Replace a line only when its placement changed.
- [ ] **Step 7: Run core + pure, the four test files above, `test_plugin_edit_lines_dialog.py` and `test_plugin_grid_dialog.py`. All of them pass.** Then run lint and types.
- [ ] **Step 8: Commit** `feat: fit and destagger rules; a fitted line stays fitted when its grid changes length (#3, #47)`, then push.

---

