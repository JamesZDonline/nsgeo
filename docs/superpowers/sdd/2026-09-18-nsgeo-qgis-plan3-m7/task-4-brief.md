## Task 4: Ambient hover previews the line under the pointer

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/map_link.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/loader.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py` (append)

**Interfaces:**
- Consumes (Tasks 1, 3): `session.set_preview`, `session.clear_preview`, `MapLink._geometries()`.
- Produces:
  - `MapLink.HOVER_DWELL_MS = 100`, `MapLink.HOVER_TOLERANCE_PX = 12` (module constants)
  - `MapLink._hit_test(point: QgsPointXY) -> tuple[str, int] | None`
  - `MapLink._dwell: QTimer` (single-shot)
  - `LineLoader._on_preview_changed(key: str, trace: int) -> None`

- [ ] **Step 1: Write the failing tests**

**First, restore two imports.** Task 3 legitimately removed `REAL_DZT` and `needs_real_data` from this module — nothing there used them, and ruff flagged them. The real-data test below is their first consumer, so put them back:

```python
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt
```

Then append to `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`:

```python
# ---- ambient hover (spec §3.2) ----------------------------------------------


def _fire_dwell(link):
    """Drive the dwell timer deterministically instead of waiting on it."""
    link._dwell.timeout.emit()


def test_hovering_a_line_previews_it_at_the_hovered_trace(linked):
    link, session, _layers, canvas, keys = linked
    target = QgsPointXY(link._geometries()[keys[1]].vertexAt(7))

    canvas.xyCoordinates.emit(target)
    _fire_dwell(link)

    assert session.preview_key == keys[1]
    assert session.preview_trace == 7


def test_hover_never_moves_the_working_line(linked):
    """The headline guard of the whole design (spec §3.3)."""
    link, session, _layers, canvas, keys = linked
    opened = []
    session.line_opened.connect(opened.append)
    target = QgsPointXY(link._geometries()[keys[1]].vertexAt(7))

    canvas.xyCoordinates.emit(target)
    _fire_dwell(link)

    assert session.current_key == keys[0]
    assert opened == []


def test_hovering_the_working_line_moves_its_cursor_not_a_preview(linked):
    """Ruling 12: the working line's cursor IS `current_trace`. Routing a
    hover over it through `set_preview` would give one line two sources of
    truth for one cursor, and the map marker would stop following a drag
    in the profile."""
    link, session, _layers, canvas, keys = linked
    target = QgsPointXY(link._geometries()[keys[0]].vertexAt(11))

    canvas.xyCoordinates.emit(target)
    _fire_dwell(link)

    assert session.preview_key is None
    assert session.current_trace == 11
    assert session.current_key == keys[0]


def test_hovering_the_working_line_ends_a_preview_of_another(linked):
    link, session, _layers, canvas, keys = linked
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[1]].vertexAt(7)))
    _fire_dwell(link)
    assert session.preview_key == keys[1]

    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[0]].vertexAt(11)))
    _fire_dwell(link)

    assert session.preview_key is None
    assert session.current_trace == 11


def test_hovering_away_from_every_line_clears_the_preview(linked):
    link, session, _layers, canvas, keys = linked
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[1]].vertexAt(7)))
    _fire_dwell(link)
    assert session.preview_key == keys[1]

    canvas.xyCoordinates.emit(QgsPointXY(999_999.0, 999_999.0))
    _fire_dwell(link)

    assert session.preview_key is None


def test_the_preview_waits_for_the_dwell(linked):
    link, session, _layers, canvas, keys = linked
    target = QgsPointXY(link._geometries()[keys[1]].vertexAt(7))

    canvas.xyCoordinates.emit(target)

    assert session.preview_key is None  # not yet -- the timer has not fired
    assert link._dwell.isActive()


def test_only_the_last_position_of_a_sweep_is_used(linked):
    link, session, _layers, canvas, keys = linked

    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[0]].vertexAt(2)))
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[1]].vertexAt(7)))
    _fire_dwell(link)

    assert session.preview_key == keys[1]
    assert session.preview_trace == 7


def test_the_dwell_timer_really_fires_on_its_own(linked):
    """The other hover tests drive the timer by hand; this one proves the
    timer is actually started and connected."""
    from qgis.PyQt.QtTest import QTest

    link, session, _layers, canvas, keys = linked
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[1]].vertexAt(7)))

    QTest.qWait(link.HOVER_DWELL_MS * 4)

    assert session.preview_key == keys[1]


def test_the_tolerance_is_a_distance_not_a_squared_distance(linked):
    """closestVertexWithContext returns a SQUARED distance, so the tolerance
    must be squared to match it.

    The discriminating probe is a HIT, not a miss. With mapUnitsPerPixel()
    == 1.0 the tolerance is 12 map units and 12 > sqrt(12), so comparing
    the squared distance against a RAW tolerance is *stricter* than
    correct, not looser: it rejects past 3.46 m where the correct
    comparison rejects past 12 m. A miss test therefore passes under both
    spellings and proves nothing. Hovering inside the real tolerance but
    outside sqrt(tolerance) separates them."""
    link, session, _layers, canvas, keys = linked
    tol = canvas.mapUnitsPerPixel() * link.HOVER_TOLERANCE_PX
    assert tol > 1.0, "the discriminating band exists only while tol > sqrt(tol)"
    on = link._geometries()[keys[1]].vertexAt(7)
    near = QgsPointXY(on.x() + tol * 0.8, on.y())

    canvas.xyCoordinates.emit(near)
    _fire_dwell(link)

    assert session.preview_key is not None


def test_hover_with_no_site_open_does_nothing(qgis_app, tmp_path):
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    layers = SiteLayers(session, project=project)
    canvas = QgsMapCanvas()
    link = MapLink(session, layers, canvas)

    canvas.xyCoordinates.emit(QgsPointXY(1.0, 2.0))
    link._dwell.timeout.emit()  # must not raise

    assert session.preview_key is None
    link.dispose()
    project.clear()


@needs_real_data
def test_hovering_a_real_line_previews_its_real_trace(qgis_app, tmp_path):
    """Spec §7: real data is the primary validation. The synthetic fixtures
    above all use one synthetic header; a real GSSI file has its own
    traces_per_metre and trace count, and those are what turn a pointer
    position into a trace index."""
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    line = Line.open(REAL_DZT[0], GridPlacement("A", "y", 0.0, 0.0, 1, "real"))
    session.add_lines([line])
    canvas = QgsMapCanvas()
    canvas.setDestinationCrs(layers.crs())
    link = MapLink(session, layers, canvas)
    key = session.keys()[0]
    session.open_line(key)

    want = line.n_traces // 3
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[key].vertexAt(want)))
    link._dwell.timeout.emit()

    # The working line is the only line, so the preview is a no-op on the
    # dock -- what is being asserted is that the hit test resolved a real
    # file's geometry to the right trace index.
    assert link._hit_test(QgsPointXY(link._geometries()[key].vertexAt(want))) == (key, want)
    assert session.current_key == key
    link.dispose()
    layers.detach()
    project.clear()


def test_a_previewed_line_is_requested_from_the_loader(linked, monkeypatch):
    from nsgeo_qgis.loader import LineLoader

    link, session, _layers, canvas, keys = linked
    asked: list[str] = []
    loader = LineLoader(session, on_error=lambda k, m: None)
    monkeypatch.setattr(loader, "request", asked.append)

    session.set_preview(keys[1], 7)

    assert asked == [keys[1]]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py -q -p no:xonsh -k "hover or dwell or tolerance or loader or sweep or working or real"`

Expected: FAIL — `AttributeError: 'MapLink' object has no attribute '_dwell'`.

- [ ] **Step 3: Add the hover machinery to `MapLink`**

Add the constants beside `MARKER_COLOUR`:

```python
# Sweeping the map must not thrash the renderer: a preview commits only
# once the pointer has settled for this long.
HOVER_DWELL_MS = 100
# How close the pointer must come to a line before it counts as hovering
# it, in SCREEN pixels -- converted to map units per event, so the feel
# does not change with zoom.
HOVER_TOLERANCE_PX = 12
```

Expose them on the class so tests and future callers read one name:

```python
class MapLink(QObject):
    HOVER_DWELL_MS = HOVER_DWELL_MS
    HOVER_TOLERANCE_PX = HOVER_TOLERANCE_PX
```

Extend the `QtCore` import to `from qgis.PyQt.QtCore import QObject, QTimer`.

In `__init__`, after the geometry cache is declared:

```python
        self._last_point: QgsPointXY | None = None
        self._dwell = QTimer(self)
        self._dwell.setSingleShot(True)
        self._dwell.timeout.connect(self._on_dwell)
        canvas.xyCoordinates.connect(self._on_xy)
```

And the slots:

```python
    # ---- ambient hover ----------------------------------------------------
    def _on_xy(self, point: QgsPointXY) -> None:
        """Fired on every mouse move over the canvas, whatever tool is
        active -- that is the whole reason this feature needs no tool slot.
        Cheap on purpose: it records a position and restarts the dwell."""
        try:
            self._last_point = QgsPointXY(point)
            self._dwell.start(self.HOVER_DWELL_MS)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not track the pointer: {exc}", Qgis.MessageLevel.Critical)

    def _on_dwell(self) -> None:
        try:
            point = self._last_point
            if point is None or not self.session.is_open:
                return
            hit = self._hit_test(point)
            if hit is None:
                # Clearing goes through the same dwell as previewing, so
                # crossing a gap between two lines does not flicker the
                # profile back to the working line and out again.
                self.session.clear_preview()
                return
            key, trace = hit
            if key == self.session.current_key:
                # The pointer is over the line already being worked on,
                # which is NOT a preview. The working line's cursor is
                # `current_trace`; routing it through `set_preview` would
                # give one line two sources of truth for one cursor, and
                # the map marker would then stop following a drag in the
                # profile. Any preview in progress ends here.
                self.session.clear_preview()
                self.session.set_trace(key, trace)
            else:
                self.session.set_preview(key, trace)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not preview the hovered line: {exc}", Qgis.MessageLevel.Critical)

    def _hit_test(self, point: QgsPointXY) -> tuple[str, int] | None:
        """The (line_key, trace) under `point`, or None if nothing is close
        enough. `point` is in canvas CRS, and so is the geometry cache.

        `closestVertexWithContext` returns a SQUARED distance, so the
        tolerance is squared to match rather than the distance rooted --
        getting this backwards silently widens the hit radius by 12x and
        is invisible to any test that hovers exactly on a line.

        Nearest *vertex* rather than nearest point on the segment: the
        vertex index is the trace index, which is the answer being asked
        for, and traces are centimetres apart, so the two differ by less
        than the pointer's own precision.
        """
        tolerance = self.canvas.mapUnitsPerPixel() * self.HOVER_TOLERANCE_PX
        limit = tolerance * tolerance
        best: tuple[float, str, int] | None = None
        for key, geom in self._geometries().items():
            if geom.isEmpty():
                continue
            sq_dist, index = geom.closestVertexWithContext(point)
            if index < 0 or sq_dist > limit:
                continue
            if best is None or sq_dist < best[0]:
                best = (sq_dist, key, index)
        return None if best is None else (best[1], best[2])
```

Add `self._dwell.stop()` as the first line of `dispose()` (Task 5 gives that method its final form).

- [ ] **Step 4: Let the loader load a previewed line**

In `loader.py`'s `__init__`, beside the existing `session.line_opened.connect(...)`:

```python
        session.preview_changed.connect(self._on_preview_changed)
```

And next to `_on_line_opened`:

```python
    def _on_preview_changed(self, key: str, _trace: int) -> None:
        """A previewed line needs its samples too -- the first preview of a
        line pays the async load, and the session's profile cache makes
        every later one instant. Same guarded path as an opened line: the
        empty key is the cleared sentinel and asks for nothing."""
        self._on_line_opened(key)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py packages/nsgeo-qgis/tests/qgis/test_plugin_loader.py -q -p no:xonsh`

Expected: PASS.

- [ ] **Step 6: Run both tiers and the linters, then commit**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
.venv/bin/ruff check . && .venv/bin/ruff format --check .
git add packages/nsgeo-qgis/nsgeo_qgis/map_link.py packages/nsgeo-qgis/nsgeo_qgis/loader.py packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py
git commit -m "feat: preview the line under the pointer, without a map tool

xyCoordinates fires whatever tool owns the canvas, so hovering costs no
tool slot and the user keeps pan, identify and select. A 100ms dwell keeps
a sweep from thrashing the renderer; clearing waits for the same dwell so
crossing a gap between lines does not flicker.

closestVertexWithContext returns a SQUARED distance -- the tolerance is
squared to match, with a test that fails if that is ever reversed.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

