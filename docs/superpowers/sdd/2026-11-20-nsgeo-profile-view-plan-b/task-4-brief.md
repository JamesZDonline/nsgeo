### Task 4: The Time zero line: drawn, dragged and written (spec §4.11, §4.12)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py` (add `snap_row`).
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py` (the handle kind, dimming side, snap and tag).
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (`_show_cutoff` and `_on_cutoff_dragged` for a `row` handle).
- Test:
  - `tests/pure/test_pure_view_transform.py`
  - `tests/qgis/test_plugin_profile_view.py`
  - `tests/qgis/test_plugin_profile_dock.py`
  - a new `tests/qgis/test_plugin_time_zero_drag.py` (plugin-level, built like `test_plugin_time_cutoff.py`'s `_plugin_with_line`)

**Interfaces:**
- Consumes:
  - Task 3's `handle_spec`, `_handle_row` and the relabelled input.
- Produces:
  - **`ViewTransform.snap_row(time_ns: float) -> float`:** `t0 + clamp(round((t − t0)/dt), 0, n − 1)·dt`. These are the row tops, inside the record.
  - **`ProfileView.set_cutoff(time_ns: float | None, kind: str = "end") -> None`,** where `kind` is `"end"` (today's cutoff) or `"start"` (a row handle):
    - `"start"` dims from the image top down to the line.
    - `"start"` snaps with `snap_row`.
    - `"start"` tags `f"Time zero · sample {k}"` at rest and `f"sample {k} · {t:.2f} ns"` while dragging. Here `k = round((t − t0)/dt)` on the drawn record, and `t` is the line's time on the shown clock, which is the offset from the line's current zero, because the view is on that clock.
    - `cutoff_dragged` still emits the snapped time.
    - `"end"` is byte-for-byte today's behaviour.
  - **`ProfileDock._show_cutoff`** for a `row` handle calls `view.set_cutoff(shown.t0_ns + sample·dt, kind="start")`, where `shown` is the relabelled input.
  - **`ProfileDock._on_cutoff_dragged(t)`** for a `row` handle works out `row = round((t − shown.t0_ns)/shown.dt_ns)`.
    - It writes nothing when `row == step.params["sample"]`.
    - Otherwise it does `build_step(step.name, **{**step.params, "sample": row})` and `replace_step`, with the identity check against the step the line was drawn from, as for the cutoff.

- [ ] **Step 1: Write the failing tests**

```python
def test_snap_row_lands_on_row_tops_inside_the_record():              # pure
    t = ViewTransform.fit(10, 100, -2.0, 0.25, 696, 264)
    assert t.snap_row(-2.1) == -2.0
    assert t.snap_row(-1.6) == pytest.approx(-1.5)
    assert t.snap_row(99.0) == pytest.approx(-2.0 + 99 * 0.25)

def test_a_start_handle_dims_above_and_tags_its_row(view):            # view
    ...set_cutoff(t, kind="start"); grab; pixels above the line are dimmed, below are not;
    the tag text is "Time zero · sample k"...

def test_the_line_shows_only_in_sample_mode_while_selected(...):      # dock, Review Focus 3
    ...

def test_dragging_time_zeros_line_writes_its_row(...):                # plugin-level
    # select time_zero(sample=20); view.cutoff_dragged.emit(shown.t0 + 26*dt) ->
    # step.params["sample"] == 26; the form's row editor shows 26; an unmoved emit writes nothing
    ...

def test_a_typed_row_moves_the_line(...):
    # form row editor -> 30, commit -> view.cutoff_ns == shown.t0 + 30*dt
    ...

def test_after_a_drag_the_line_reads_zero_again_and_the_picture_holds(...):
    # mid-record zoom, drag from 20 to 26 -> the line sits at 0 ns on the new clock
    # (view.cutoff_ns == pytest.approx(0.0)); the radar window is unchanged
    ...

def test_a_drag_to_either_end_clamps_and_is_accepted(...):            # Review Focus 5
    ...

def test_a_disabled_time_zero_handle_matches_the_cutoffs_rule(...):   # Review Focus 2
    # read what `_cutoff_row` does today for a disabled step and pin the same for the handle
    ...

@needs_real_data
def test_time_zero_by_eye_on_the_campus_line(...):
    # FILE__007: switching first_break -> sample seeds 49; selecting shows the line at 0 ns
    # with 49 rows above; dragging two rows up writes 47
    ...

@pytest.mark.skipif(not GPS_LINES, reason="needs the with-dzg lines in tests/data/local")
def test_time_zero_by_eye_on_a_gps_line(...):
    # with-dzg FILE__010 (seed 44), the same three checks
    ...
```

  E's rule needs one more check: the drag path must not undo the decline. Selecting Time zero with Difference on, then dragging, leaves the Difference button off and writes the row.

- [ ] **Step 2: Run them and check they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `test_plugin_profile_view.py`, `test_plugin_profile_dock.py`, `test_plugin_time_cutoff.py` (unchanged and green), `test_plugin_time_zero_drag.py`, `test_plugin_difference_presets.py`, pure and real data. Expected: PASS.
- [ ] **Step 5: Commit and push**

```bash
git commit -am "feat(profile): drag Time zero's line on the profile; the form and the line share one row (#158)"
git push
```

---

## After Plan B

1. A whole-branch review of Plans A and B.
2. Deploy to its own QGIS profile.
3. A walkthrough artifact on a floating Profile panel at about 1361 × 448. It covers:
   - the band hidden and shown;
   - Fit width and Fit height;
   - 1:1;
   - each axis unit and the read-out;
   - a time zoom held across a Time zero edit;
   - dragging Time zero by eye, with Difference on and off;
   - R18's question: the velocity label shortened at 1361 px in the worst case.
4. Ask before merging.
