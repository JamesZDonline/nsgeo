### Task 5: The cursor read-out (#11, spec §4.7)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py`: hover tracking, `leaveEvent`, `readout_text`, and `_paint_readout`, called after `_paint_axes`.
- Test: `tests/qgis/test_plugin_profile_view.py`, plus one cut test in `tests/qgis/test_plugin_profile_cut.py`.

**Interfaces:**
- Consumes: Task 3's `metres_at_trace_units`, and Task 4's `axis_units` and `has_velocity`.
- Produces: `ProfileView.readout_text() -> str`, which is `""` when the pointer isn't over the image.

**The spec fixes these values:**
- The hover position is set in `_handle_mouse_move` when `0 <= x < t.width` and `0 <= y < t.height`, and set to None otherwise. `leaveEvent` sets it to None and updates.
- **The format.** The parts are joined with `" · "`:
  - first, `f"{m:.2f} m along (trace {i})"`, with `m = metres_at_trace_units(i + 0.5)`, or `f"trace {i}"` when that is None;
  - then, for each side's unit in order (left, right), skipping a unit already shown:
    - `ns`: `f"{t0 + s*dt:.2f} ns"`;
    - `sample`: `f"sample {s}"`;
    - `m`: `f"{depth:.2f} m deep"`. Left out when there is no velocity, or when `t0 + s*dt < 0`.
  - `i = t.trace_at(x)` and `s = t.sample_index_at(y)`. When `i` is None (blank ruler space), there is no read-out.
- **How it is painted:** 9 pt, `AXIS_COLOUR`, in `QRectF(r.left(), 0, r.width(), MARGIN_TOP)`, aligned right and vertically centred.

- [ ] **Step 1: Write the failing tests.** These use Task 4's `_sampled` view: 200 traces at 60 per metre, 128 samples, dt 0.25, t0 0, and 0.1 m/ns.

```python
def _hover_at(v, trace, sample):
    t, r = v.transform, v.image_rect()
    send_hover(v, QPoint(int(r.left() + t.x_of_trace(trace + 0.5)), int(r.top() + t.y_of_time((sample + 0.5) * 0.25))))

def test_the_readout_reads_the_sample_under_the_pointer(make_view):
    v = _sampled(make_view)
    _hover_at(v, 100, 40)
    assert v.readout_text() == "1.67 m along (trace 100) · 10.00 ns · 0.50 m deep"

def test_the_readout_follows_the_axis_units(make_view):
    v = _sampled(make_view)
    v.set_axis_units("sample", "m"); _hover_at(v, 100, 40)
    assert v.readout_text() == "1.67 m along (trace 100) · sample 40 · 0.50 m deep"
    v.set_axis_units("ns", "ns"); _hover_at(v, 100, 40)
    assert v.readout_text() == "1.67 m along (trace 100) · 10.00 ns"

def test_the_readout_without_metres_or_velocity(make_view):          # Review Focus 2
    v = make_view(); v.resize(VIEW_W, 264 + MARGIN_TOP + 28); v.show()
    v.set_axes(200, 128, 0.0, 0.25)
    _hover_at(v, 100, 40)
    assert v.readout_text() == "trace 100 · 10.00 ns"

def test_the_readout_leaves_depth_out_above_zero(make_view):
    v = make_view(); v.resize(VIEW_W, 264 + MARGIN_TOP + 28); v.show()
    v.set_axes(200, 128, -2.0, 0.25, distance_along=np.arange(200) / 60.0)
    v.set_velocity(VelocityModel.constant(0.1))
    t, r = v.transform, v.image_rect()
    send_hover(v, QPoint(int(r.left() + t.x_of_trace(100.5)), int(r.top() + t.y_of_time(-2.0 + 4.5 * 0.25))))
    assert v.readout_text() == "1.67 m along (trace 100) · -1.00 ns"

def test_the_readout_clears_off_the_image(make_view):
    v = _sampled(make_view); _hover_at(v, 100, 40)
    send_hover(v, QPoint(5, MARGIN_TOP + 40))            # the left axis strip
    assert v.readout_text() == ""

def test_a_mirrored_line_reads_its_own_metres(ruled):                 # Review Focus 1
    ...hover the column of trace 10 on the `ruled` fixture; assert the metres equal D[10] to 2 dp...
```

In `test_plugin_profile_cut.py`, reuse its fixture that draws a cut section (Review Focus 3):
- hover the middle of the image and assert `readout_text()` is non-empty;
- open the axis menu with `_on_axis_menu_requested("left", QPoint(0, 0))`, trigger "Samples", and repaint without raising;
- `one_to_one_button` is disabled when the cut has no velocity.

- [ ] **Step 2: Run and check that they fail.** Expected: `AttributeError: readout_text`.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the touched files, the real-data marker and pure.** Expected: PASS.

- [ ] **Step 5: Commit and push**

```bash
git commit -am "feat(profile): a cursor read-out in the axes' units, above the profile (#11)"
git push
```

---

