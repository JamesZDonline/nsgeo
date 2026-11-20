### Task 5: Reading the slice — the band on the radargram, and shift + scroll

§9.3's one new thing, and the navigation gesture users of other packages already have. The band
is what answers *is this anomaly real, or is the fill inventing a feature between two lines?* —
by pointing at it.

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (two signals, one method)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py` (`depth_scroll_delta`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (wire both)
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py` (append)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py` (append)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py` (append)

**Interfaces:**

- Produces:
  - `ProfileView.set_slice_band(lo_ns: float, hi_ns: float)`, `ProfileView.clear_slice_band()`,
    `ProfileView._slice_band_bounds(t) -> tuple[float, float] | None`
  - `ProfileDock.set_slice_band(lo_ns, hi_ns)`, `ProfileDock.clear_slice_band()`
  - `SlicesDock.window_changed = pyqtSignal(float, float)`,
    `SlicesDock.window_cleared = pyqtSignal()` (both connected in `plugin.py` here)
  - `slices_plan.depth_scroll_delta(angle_delta_y: int, shift_held: bool) -> int`
  - `slices_dock.CanvasDepthScroll(canvas, dock, parent=None)` with `dispose()`

---

- [ ] **Step 1: The pure scroll rule, test first**

Append to `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py`:

```python
def test_shift_scroll_steps_deeper_downward_and_is_inert_without_shift():
    """Spec 9.2: shift + scroll on the canvas cycles depth, which is the
    convention users of other packages already have. The direction is the
    one the world uses -- scrolling down goes deeper -- and the rule is a
    plain function so it is pinned without synthesising a Qt event, whose
    constructor signature differs between Qt 5 and Qt 6."""
    from nsgeo_qgis.slices_plan import depth_scroll_delta

    assert depth_scroll_delta(-120, shift_held=True) == 1  # down: deeper
    assert depth_scroll_delta(120, shift_held=True) == -1  # up: shallower
    assert depth_scroll_delta(-120, shift_held=False) == 0  # plain scroll is a map zoom
    assert depth_scroll_delta(0, shift_held=True) == 0  # a horizontal-only wheel
```

Implement in `slices_plan.py`:

```python
def depth_scroll_delta(angle_delta_y: int, shift_held: bool) -> int:
    """-1, 0 or +1 slice steps for one wheel event.

    Kept here, away from Qt, for two reasons: the plugin's boundary rule
    keeps arithmetic out of widgets, and `QWheelEvent`'s constructor
    differs between Qt 5 and Qt 6, so a rule pinned only through a
    synthesised event would be pinned only on one of them.

    Without shift this returns 0 and the event is not consumed: plain
    scrolling stays the map's zoom, because spec 9.3 is explicit that the
    slice introduces no new tool and takes no gesture away.
    """
    if not shift_held or angle_delta_y == 0:
        return 0
    return 1 if angle_delta_y < 0 else -1
```

- [ ] **Step 2: Write the failing band tests**

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py` (matching its existing
fixtures for building a view with axes):

```python
def test_the_slice_band_spans_the_windows_time_range(qgis_app):
    view = ProfileView()
    view.resize(400, 300)
    view.set_axes(n_traces=100, n_samples=200, t0_ns=0.0, dt_ns=0.5)
    view.set_slice_band(20.0, 30.0)
    bounds = view._slice_band_bounds(view.transform)
    assert bounds is not None
    y0, y1 = bounds
    assert y0 == pytest.approx(view.transform.y_of_time(20.0))
    assert y1 == pytest.approx(view.transform.y_of_time(30.0))
    assert y1 > y0


def test_a_single_level_window_still_draws_a_visible_band(qgis_app):
    """A one-level window averages a single sample and so has zero time
    extent -- which is the truth, and a zero-height rectangle no user can
    see. The data stays honest; the PAINTER enforces a floor."""
    view = ProfileView()
    view.resize(400, 300)
    view.set_axes(n_traces=100, n_samples=200, t0_ns=0.0, dt_ns=0.5)
    view.set_slice_band(20.0, 20.0)
    y0, y1 = view._slice_band_bounds(view.transform)
    assert y1 - y0 >= 2.0


def test_clearing_the_band_removes_it(qgis_app):
    view = ProfileView()
    view.resize(400, 300)
    view.set_axes(n_traces=100, n_samples=200, t0_ns=0.0, dt_ns=0.5)
    view.set_slice_band(20.0, 30.0)
    view.clear_slice_band()
    assert view._slice_band_bounds(view.transform) is None


def test_painting_with_a_band_raises_nothing(qgis_app):
    """paintEvent is a Qt-invoked virtual: an escaping exception leaves
    the QPainter bound to the widget and the NEXT repaint segfaults the
    process -- measured, not theorised (see the module docstring's C1)."""
    view = ProfileView()
    view.resize(400, 300)
    view.set_axes(n_traces=100, n_samples=200, t0_ns=0.0, dt_ns=0.5)
    view.set_slice_band(-50.0, 500.0)  # a window entirely outside the view
    view.grab_image()
    view.set_slice_band(20.0, 30.0)
    view.grab_image()
```

- [ ] **Step 3: Implement the band in `profile_view.py`**

Add a module-level colour beside the existing ones:

```python
# Spec 9.3's one overlay. Distinct from SELECTION_COLOUR, which is a
# vertical trace range: these two can be on screen together and must not
# read as the same thing.
SLICE_BAND_COLOUR = QColor(80, 200, 255, 48)
SLICE_BAND_EDGE = QColor(80, 200, 255, 170)
MIN_BAND_PX = 2.0
```

In `__init__`, `self._slice_band: tuple[float, float] | None = None`. Then:

```python
    def set_slice_band(self, lo_ns: float, hi_ns: float) -> None:
        """Draw the active slice's time window across this radargram.

        Spec 9.3: the only new thing the slice adds to the profile view.
        It answers "is this anomaly real, or is the fill inventing a
        feature between two lines?" by pointing at the depths the slice
        averaged, on data that was never filled.
        """
        if not all(math.isfinite(v) for v in (lo_ns, hi_ns)):
            self._slice_band = None
        else:
            self._slice_band = (min(lo_ns, hi_ns), max(lo_ns, hi_ns))
        self.update()

    def clear_slice_band(self) -> None:
        self._slice_band = None
        self.update()

    def _slice_band_bounds(self, t: ViewTransform) -> tuple[float, float] | None:
        """Local (unoffset) y-bounds of the band, or None when there is
        none. Factored out the same way `_selection_bounds` is, and for
        the same reason: a plain pair a test can assert on without
        rendering a pixel.

        A one-level window has zero time extent -- it averages a single
        sample, and saying otherwise would overstate what was averaged --
        so the floor is applied HERE, in pixels, rather than by widening
        the window the readout reports.
        """
        if self._slice_band is None:
            return None
        y0 = t.y_of_time(self._slice_band[0])
        y1 = t.y_of_time(self._slice_band[1])
        if y1 - y0 < MIN_BAND_PX:
            centre = (y0 + y1) / 2.0
            y0, y1 = centre - MIN_BAND_PX / 2.0, centre + MIN_BAND_PX / 2.0
        return y0, y1

    def _paint_slice_band(self, p: QPainter, r: QRect, t: ViewTransform) -> None:
        bounds = self._slice_band_bounds(t)
        if bounds is None:
            return
        y0, y1 = r.top() + bounds[0], r.top() + bounds[1]
        p.fillRect(QRectF(r.left(), y0, r.width(), y1 - y0), SLICE_BAND_COLOUR)
        p.setPen(QPen(SLICE_BAND_EDGE, 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(r.left(), y0), QPointF(r.right(), y0))
        p.drawLine(QPointF(r.left(), y1), QPointF(r.right(), y1))
```

Call it in `paintEvent` inside the existing `setClipRect(r)` block, **before**
`_paint_selection` — the band is context and must sit under the selection and the picks, not over
them. Add `self._slice_band = None` to `clear()`.

In `profile_dock.py`, two relays, each guarded, and each calling straight through to the view:

```python
    def set_slice_band(self, lo_ns: float, hi_ns: float) -> None:
        self.view.set_slice_band(lo_ns, hi_ns)

    def clear_slice_band(self) -> None:
        self.view.clear_slice_band()
```

- [ ] **Step 4: Emit the window from the Slices dock and wire it**

In `slices_dock.py`, declare beside `slice_changed`:

```python
    window_changed = pyqtSignal(float, float)  # (lo_ns, hi_ns) of the averaged window
    window_cleared = pyqtSignal()
```

and in `refresh_slice()`, right after `self._update_readout(window)`:

```python
            lo_ns, hi_ns = window_times_ns(self.engine.z, window)
            self.window_changed.emit(lo_ns, hi_ns)
```

with `self.window_cleared.emit()` on the early-return branch where there is no window. Add
`CanvasDepthScroll` to the same module:

```python
class CanvasDepthScroll(QObject):
    """Shift + scroll on the map canvas cycles depth (spec 9.2).

    An event filter rather than a map tool: spec 9.3 is explicit that the
    slice introduces no new tool, and taking over the canvas would break
    the ambient hover and the Select-to-promote gesture M7 already built.
    Without shift the event is not consumed, so plain scrolling remains
    the map's zoom.

    `eventFilter` is a Qt-invoked virtual, the same hazard class as
    `paintEvent`: an exception escaping it is swallowed locally and
    reaches `qFatal()` in the CI container, so the body is guarded.
    """

    def __init__(self, canvas: Any, dock: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self._dock = dock
        canvas.viewport().installEventFilter(self)

    def eventFilter(self, obj: Any, event: Any) -> bool:  # noqa: N802
        try:
            if event.type() != QEvent.Type.Wheel:
                return False
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            delta = depth_scroll_delta(int(event.angleDelta().y()), shift)
            if delta == 0:
                return False
            self._dock.step_slice(delta)
            return True  # consumed: the map must not also zoom
        except Exception as exc:  # noqa: BLE001 -- see the class docstring
            _log(f"could not step the slice from the canvas: {exc}")
            return False

    def dispose(self) -> None:
        try:
            if self._canvas is not None and not sip.isdeleted(self._canvas):
                self._canvas.viewport().removeEventFilter(self)
        except (RuntimeError, AttributeError):
            pass
        self._canvas = None
        self._dock = None
```

In `plugin.py`'s `initGui`, after the slice layer:

```python
        self.slices_dock.window_changed.connect(self.profile_dock.set_slice_band)
        self.slices_dock.window_cleared.connect(self.profile_dock.clear_slice_band)
        self.depth_scroll = CanvasDepthScroll(self.iface.mapCanvas(), self.slices_dock)
```

with `self.depth_scroll: CanvasDepthScroll | None = None` in `__init__` and, in `unload`, before
the docks are removed: `if self.depth_scroll is not None: self.depth_scroll.dispose();
self.depth_scroll = None`.

- [ ] **Step 5: Write the failing wiring tests**

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`:

```python
def test_moving_the_slider_announces_the_window_it_averaged(docked):
    dock, _ = docked
    _ready(dock)
    seen: list[tuple[float, float]] = []
    dock.window_changed.connect(lambda lo, hi: seen.append((lo, hi)))
    dock.thickness_spin.setValue(4.0)
    dock.slice_slider.setValue(12)
    assert seen
    lo, hi = seen[-1]
    window = dock.current_window()
    assert (lo, hi) == pytest.approx(window_times_ns(dock.engine.z, window))


def test_step_slice_moves_by_the_step_not_by_one_level(docked):
    """Spec 6.6: thickness and step answer different questions. Stepping
    by one level would make shift+scroll take dozens of turns to cross a
    slice at native dz."""
    dock, _ = docked
    _ready(dock)
    dock.thickness_spin.setValue(5.0)
    dock.step_spin.setValue(2.5)
    start = dock.slice_slider.value()
    dock.step_slice(1)
    moved = dock.slice_slider.value() - start
    assert moved == round(2.5 / dock.engine.z.dz_ns)
    assert moved > 1
```

And to `test_plugin_loads.py`:

```python
def test_the_profile_band_follows_the_slice_window(fake_iface, qgis_app, tmp_path):
    """The one thing spec 9.3 adds to the profile view, end to end through
    the plugin's own wiring rather than by calling the dock directly."""
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        plugin.slices_dock.window_changed.emit(12.0, 16.0)
        assert plugin.profile_dock.view._slice_band == (12.0, 16.0)
        plugin.slices_dock.window_cleared.emit()
        assert plugin.profile_dock.view._slice_band is None
    finally:
        plugin.unload()
```

- [ ] **Step 6: Run both tiers, and prove discrimination**

Mutants:

1. `_paint_slice_band` called AFTER `_paint_picks`. No test catches ordering — say so in the
   report rather than inventing one; it is a visual judgement, and the manual walkthrough is
   where it is checked.
2. `depth_scroll_delta` → `return 1 if angle_delta_y > 0 else -1` (inverted). Expect the pure
   test to FAIL.
3. `_slice_band_bounds` → drop the `MIN_BAND_PX` floor. Expect
   `test_a_single_level_window_still_draws_a_visible_band` to FAIL.
4. `set_slice_band` → do not guard against non-finite input. Feed it `float("nan")` in a scratch
   check and confirm `grab_image()` then logs rather than raising; if the guard is genuinely
   unreachable from the dock, record that and keep the guard, since `paintEvent` is the one place
   where an escape is a process hazard rather than a nuisance.

- [ ] **Step 7: Commit and push**

```bash
git add packages/nsgeo-qgis
git commit -m "feat(slices): the slice window drawn on the radargram, and shift+scroll

Spec 9.3's one overlay: what answers whether an anomaly is real or the
fill inventing a feature between two lines. The scroll rule is a pure
function, so it is pinned without a Qt-version-specific event.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push origin nsgeo-m11
```

---

