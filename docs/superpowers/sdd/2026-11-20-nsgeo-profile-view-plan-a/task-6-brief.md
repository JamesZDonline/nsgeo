### Task 6: A time zoom survives a clock change on the same line (#163 item 2, spec §4.8)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`: add `carry_time_window`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`: `_set_axes_holding` (about line 572) and its three callers (about lines 851, 944 and 1925), plus a new `self._axes_zero`.
- Test: `tests/pure/test_pure_view_transform.py` and `tests/qgis/test_plugin_profile_dock.py`

**Interfaces:**
- Produces:
  - `carry_time_window(old: ViewTransform, new: ViewTransform, old_zero: float, new_zero: float) -> ViewTransform`, a pure function;
  - `ProfileDock._set_axes_holding(key, n_traces, n_samples, t0_ns, dt_ns, distance, zero_ns: float = 0.0)`;
  - `ProfileDock._axes_zero: float`, set at the end of every `_set_axes_holding` and reset with `_axes_key`.
- Plan B uses both functions, unchanged.

**`carry_time_window`'s rule.** The spec's §4.8, in code terms:
- trace window: `old.trace_lo`, `old.trace_hi`;
- **whole** (`old.time_lo <= old.t0_ns + old.dt_ns/2` and `old.time_hi >= old.t_end - old.dt_ns/2`) → `(new.t0_ns, new.t_end)`;
- **top** (`old.time_lo <= old.t0_ns + old.dt_ns/2`) → `(new.t0_ns, new.t0_ns + span)`;
- **otherwise** → `(lo + old_zero - new_zero, hi + old_zero - new_zero)`, which is `retime_ns`;
- the result goes through `new.with_window(...)`.

**The new rule in `_set_axes_holding`.** It sits after rule 1 and before rule 2. It applies when:
- `old` and `new` exist;
- `key == old_key` and `not is_cut_key(key)`;
- `(n_traces, dt_ns, bounds, mirrored)` are equal;
- any of `t0_ns`, `n_samples` or the zero (`zero_ns` vs `self._axes_zero`) differ.

Then `view.transform = carry_time_window(old, new, self._axes_zero, zero_ns)`, and `view_changed` is emitted.

**What the callers pass as `zero_ns`:**
- `_render`: `rg.zero_ns`;
- `_take_down_picture`: `0.0`, since the header's axes are on the radar clock;
- the cut path: `0.0`, since the rule skips cuts.

- [ ] **Step 1: Write the failing pure tests**

```python
def _old():
    return ViewTransform.fit(200, 512, -11.0, 0.2, 696, 264)          # -11 .. 91.4 ns, radar clock

def test_a_whole_record_stays_whole():
    new = ViewTransform.fit(200, 460, 0.0, 0.2, 696, 264)
    c = carry_time_window(_old(), new, 0.0, -0.6)
    assert (c.time_lo, c.time_hi) == pytest.approx((0.0, 92.0))

def test_the_top_stays_the_top():
    old = _old().with_window(0.0, 200.0, -11.0, 4.0)
    new = ViewTransform.fit(200, 460, 0.0, 0.2, 696, 264)
    c = carry_time_window(old, new, 0.0, -0.6)
    assert (c.time_lo, c.time_hi) == pytest.approx((0.0, 15.0))

def test_a_window_in_the_middle_keeps_its_radar_times():
    old = _old().with_window(20.0, 120.0, 30.0, 45.0)
    new = ViewTransform.fit(200, 460, 0.0, 0.2, 696, 264)
    c = carry_time_window(old, new, 0.0, -0.6)
    assert (c.time_lo - 0.6, c.time_hi - 0.6) == pytest.approx((30.0, 45.0))   # radar = zero + t
    assert (c.trace_lo, c.trace_hi) == pytest.approx((20.0, 120.0))
```

- [ ] **Step 2: Run and check that they fail.** Expected: `ImportError`.

- [ ] **Step 3: Implement `carry_time_window`.**

- [ ] **Step 4: Write the failing dock tests**

  Give the line its samples synchronously with `session.set_profiles(key, line.load())`, as other tests in this file do, so stack changes render at once.

```python
def _radar_window(dock):
    t = dock.view.transform
    return (dock.shown_zero_ns() + t.time_lo, dock.shown_zero_ns() + t.time_hi)

def _zoom_middle(dock):
    t = dock.view.transform
    mid = (t.time_lo + t.time_hi) / 2
    dock.view.transform = t.with_window(t.trace_lo + 20, t.trace_hi - 20, mid - 5.0, mid + 5.0)

def test_a_time_zoom_survives_adding_time_zero_on_an_unruled_line(opened):
    session, dock, key, line = opened
    k2, l2 = _add_line(session, "U1", GridPlacement("A", "y", 0.0, 0.0, 1, "U1"), traces_per_metre=0.0)
    session.open_line(k2); session.set_profiles(k2, l2.load())
    _zoom_middle(dock)
    before = _radar_window(dock)
    session.append_step(k2, build_step("time_zero", mode="sample", sample=20))
    assert _radar_window(dock) == pytest.approx(before)          # today: reset to Fit
    session.replace_step(k2, 0, build_step("time_zero", mode="sample", sample=26))
    assert _radar_window(dock) == pytest.approx(before)

def test_a_time_zoom_survives_adding_time_zero_on_a_ruled_line(opened):
    ...the same on `opened`'s own ruled line...

def test_a_zoom_at_the_top_stays_at_the_top(opened):
    ...zoom to (t0, t0 + 10) first; after adding time_zero the window is (new t0, new t0 + 10)...

@needs_real_data
def test_a_time_zoom_survives_time_zero_on_the_campus_line(opened):
    # FILE__007 (next(p for p in CAMPUS_LINES if p.name == "FILE__007.DZT")) on GRID at
    # GridPlacement("A", "y", 0.0, 0.0, 1, "FILE__007"), samples set, _zoom_middle, then:
    #   append time_zero(mode="first_break")          -> _radar_window unchanged
    #   replace it with time_zero(mode="sample", sample=52) -> _radar_window unchanged
    ...

@pytest.mark.skipif(not GPS_LINES, reason="needs the with-dzg lines in tests/data/local")
def test_a_time_zoom_survives_time_zero_on_a_gps_line(qgis_app, tmp_path):
    # GPS_LINES[0] on Grid("G", (500.0, 700.0), 0.0, 30.0, 29.98, "EPSG:32616", 0.5) at
    # GridPlacement("G", "y", 0.25, 0.0, 1, "l0"), as test_plugin_edit_lines_measure.py places
    # them; the same two edits (sample=47 for the second) and the same two assertions.
    ...
```

- [ ] **Step 5: Run and check that they fail.** Expected: the unruled test fails (reset to Fit), and the ruled tests fail (window slid by the zero change).

- [ ] **Step 6: Implement** the new rule, `_axes_zero` and the callers' `zero_ns`.

- [ ] **Step 7: Run the touched files, then `test_plugin_time_cutoff.py`, `test_plugin_profile_cut.py`, `test_plugin_velocity_fit.py`, the real-data marker and pure**

  The broad trigger can change older expectations on unruled lines. A failure must be one of two things:
  - **the intended change:** the same line kept its zoom on a record or clock change. Re-pin that test with a comment citing spec §4.8, and list it in the task report;
  - **a bug:** anything else. Fix it.

- [ ] **Step 8: Commit and push**

```bash
git commit -am "feat(profile): a time zoom survives a change of clock or record on the same line (#163 item 2)"
git push
```

---

## After Plan A

- Plan B (#158) is written next, from spec §4.9–§4.13. It reuses `carry_time_window`, `_set_axes_holding(zero_ns=…)` and the `_axes_zero` bookkeeping unchanged.
- The walkthrough, deploy and merge wait for Plan B; one PR covers both plans.
