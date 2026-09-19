## Task 3: `MapLink` — the profile drawn onto the map

Marker and band only. Hover comes in Task 4, promotion in Task 5, so this task ends with a link that is already useful: drag a selection in the profile and watch it light up on the map.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/map_link.py`
- Test: create `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`

**Interfaces:**
- Consumes (Tasks 1-2): `session.trace_changed`, `session.selection_changed`, `session.preview_changed`, `session.line_opened`, `session.lines_changed`, `session.grids_changed`, `session.site_closed`, `session.display_key`, `session.preview_key`, `session.preview_trace`, `session.current_trace`, `session.selection`; `SiteLayers.layers` (a `dict[str, QgsVectorLayer]`, key `"lines"`).
- Produces:
  - `MapLink(session: SiteSession, layers: SiteLayers, canvas: QgsMapCanvas, parent: QObject | None = None)`
  - `MapLink.dispose() -> None` — idempotent
  - `MapLink._geometries() -> dict[str, QgsGeometry]` — line geometries **in canvas CRS**, keyed by `line_key` (Task 4 hit-tests against these)
  - `MapLink._invalidate() -> None`
  - Module constants `MARKER_COLOUR`, `BAND_COLOUR`

**Verified API facts** (probed against QGIS 3.44.7 in this worktree — do not re-derive):
- `QgsGeometry.closestVertexWithContext(pt)` returns `(sqrDist, vertexIndex)`. The distance is **squared**.
- `QgsGeometry.vertexAt(i)` returns a `QgsPoint`, **not** a `QgsPointXY` — wrap it: `QgsPointXY(geom.vertexAt(i))`.
- `QgsVertexMarker.setCenter(pt)` takes map (canvas CRS) coordinates.
- `QgsRubberBand.setToGeometry(geom, layer)` — passing `None` for `layer` means "already in canvas CRS, do not transform".
- Constructing a `QgsVertexMarker(canvas)` or `QgsRubberBand(canvas, ...)` adds exactly one item to `canvas.scene()`; `scene().removeItem(item)` takes it back off. An empty canvas's scene already holds 1 item, so assert on deltas, never absolutes.
- `refill_lines` writes one geometry vertex per trace (`_line_points` → `Line.trace_coords`), so **vertex index == trace index**. That equality is the whole reason this module needs no coordinate maths of its own.

**Deviation from spec §3.1, deliberate.** The spec says a trace's world position is `Line.trace_coords(frames)[index]` transformed to the canvas CRS. This module reads the `lines` layer's own geometry vertex instead. It is the *same value by a cheaper route* — `refill_lines` computed it with exactly that call — and it is strictly better in two ways: the marker is guaranteed to sit on the line as drawn rather than on a recomputation that could drift from it, and an unplaceable line (a time-triggered acquisition, which `trace_coords` raises `ValueError` for) is simply absent from the layer and therefore absent here, with no second error path to handle.

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`:

```python
"""MapLink: the map <-> profile link (M7, spec §3)."""

from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.map_link import MapLink
from nsgeo_qgis.session import SiteSession
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt
from qgis.core import QgsGeometry, QgsPointXY, QgsProject
from qgis.gui import QgsMapCanvas

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def linked(qgis_app, tmp_path):
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    lines = []
    for i in range(2):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", i * 2.0, 0.0, 1, p.stem)))
    session.add_lines(lines)
    canvas = QgsMapCanvas()
    canvas.setDestinationCrs(layers.crs())
    link = MapLink(session, layers, canvas)
    keys = session.keys()
    session.open_line(keys[0])
    yield link, session, layers, canvas, keys
    link.dispose()
    layers.detach()
    project.clear()


def _vertex(link, key, i):
    return QgsPointXY(link._geometries()[key].vertexAt(i))


def test_the_marker_sits_on_the_traces_own_vertex(linked):
    link, session, _layers, _canvas, keys = linked

    session.set_trace(keys[0], 10)

    want = _vertex(link, keys[0], 10)
    assert link._marker.isVisible()
    assert link._marker.center().distance(want) < 1e-6


def test_the_band_spans_the_selected_traces(linked):
    link, session, _layers, _canvas, keys = linked

    session.set_selection(keys[0], 4, 9)

    assert link._band.numberOfVertices() == 6  # 4..9 inclusive


def test_clearing_the_selection_empties_the_band(linked):
    link, session, _layers, _canvas, keys = linked
    session.set_selection(keys[0], 4, 9)

    session.clear_selection()

    assert link._band.numberOfVertices() == 0


def test_the_marker_follows_the_preview_not_the_working_line(linked):
    link, session, _layers, _canvas, keys = linked
    session.set_trace(keys[0], 10)

    session.set_preview(keys[1], 3)

    want = _vertex(link, keys[1], 3)
    assert link._marker.center().distance(want) < 1e-6


def test_hovering_the_working_line_keeps_its_own_selection_band(linked):
    """`preview_key == current_key` is reachable and emits, and it means
    the pointer is over the line already being worked on -- not a preview.
    Testing `preview_key is not None` alone blanks that line's own band."""
    link, session, _layers, _canvas, keys = linked
    session.set_selection(keys[0], 4, 9)

    session.set_preview(keys[0], 3)

    assert link._band.numberOfVertices() == 6
    assert link._marker.isVisible()


def test_a_preview_shows_no_selection_band(linked):
    link, session, _layers, _canvas, keys = linked
    session.set_selection(keys[0], 4, 9)

    session.set_preview(keys[1], 3)

    assert link._band.numberOfVertices() == 0


def test_snapping_back_restores_the_working_lines_marker_and_band(linked):
    link, session, _layers, _canvas, keys = linked
    session.set_trace(keys[0], 10)
    session.set_selection(keys[0], 4, 9)

    session.set_preview(keys[1], 3)
    session.clear_preview()

    assert link._marker.center().distance(_vertex(link, keys[0], 10)) < 1e-6
    assert link._band.numberOfVertices() == 6


def test_closing_the_site_hides_both_items(linked):
    link, session, _layers, _canvas, keys = linked
    session.set_trace(keys[0], 10)
    session.set_selection(keys[0], 4, 9)

    session.close_site()

    assert not link._marker.isVisible()
    assert link._band.numberOfVertices() == 0


def test_dispose_takes_both_items_off_the_scene_and_is_idempotent(qgis_app, tmp_path):
    """I4's lesson: a QgsMapCanvasItem is owned by the canvas SCENE, and
    nothing removes it when the Python wrapper goes away."""
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    canvas = QgsMapCanvas()
    before = len(canvas.scene().items())

    link = MapLink(session, layers, canvas)
    assert len(canvas.scene().items()) == before + 2

    link.dispose()
    assert len(canvas.scene().items()) == before

    link.dispose()  # must not raise
    assert len(canvas.scene().items()) == before
    layers.detach()
    project.clear()


def test_the_geometry_cache_is_rebuilt_after_the_lines_change(linked):
    link, session, _layers, _canvas, keys = linked
    link._geometries()  # populate
    assert link._geoms is not None

    session.remove_line(keys[1])

    assert link._geoms is None
    assert keys[1] not in link._geometries()


def test_geometries_are_transformed_into_canvas_crs(linked):
    """Hit testing (Task 4) measures its tolerance in canvas units, so the
    cache must already be transformed -- not left in the layer's CRS.

    Asserting against a DIFFERENT canvas CRS is the only version of this
    test that can fail: with the canvas on the layer's own CRS the
    transform is a no-op and an untransformed cache looks identical."""
    from qgis.core import QgsCoordinateReferenceSystem

    link, _session, layers, canvas, keys = linked
    in_layer_crs = QgsPointXY(link._geometries()[keys[0]].vertexAt(0))

    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    link._invalidate()
    in_wgs84 = QgsPointXY(link._geometries()[keys[0]].vertexAt(0))

    assert abs(in_wgs84.x()) <= 180.0 and abs(in_wgs84.y()) <= 90.0
    assert in_wgs84.distance(in_layer_crs) > 1.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py -q -p no:xonsh`

Expected: FAIL at collection — `ModuleNotFoundError: No module named 'nsgeo_qgis.map_link'`.

- [ ] **Step 3: Write `map_link.py`**

Create `packages/nsgeo-qgis/nsgeo_qgis/map_link.py`:

```python
"""MapLink: the map <-> profile link.

Deliberately NOT a QgsMapTool, which is why this module does not live in
`maptools/`. A map tool claims the canvas: while it is active the user
loses pan, identify and select, which is the wrong trade for an always-on
feature. `QgsMapCanvas.xyCoordinates` fires on mouse move regardless of
the active tool (verified against QGIS 3.44 with no tool set and with
QgsMapToolPan active), and a QgsVertexMarker attaches to the canvas scene
without owning the tool -- so the whole link coexists with whatever the
user is already doing.

Clicks are deliberately not intercepted. Catching one ambiently means an
event filter on the canvas viewport adjudicating every click in QGIS
against the active tool -- the same shape as the Plan 2 bug where a
right-click committed a left-drag selection in the profile. Selection
gives us a deliberate gesture for free instead (see `_on_selection`).

Every slot here catches its own exceptions: PyQt cannot propagate an
exception out of a slot invoked from C++, this build prints it and carries
on, and the CI container routes it to qFatal(). See `session.py`.
"""

from __future__ import annotations

from typing import Any

from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsMessageLog,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapCanvas, QgsRubberBand, QgsVertexMarker
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtGui import QColor

from .layers import SiteLayers
from .session import SiteSession

MARKER_COLOUR = QColor("#e67e22")
BAND_COLOUR = QColor("#e67e22")
MARKER_SIZE_PX = 9
BAND_WIDTH_PX = 3


def _log(message: str, level: Qgis.MessageLevel = Qgis.MessageLevel.Warning) -> None:
    QgsMessageLog.logMessage(message, "nsgeo", level)


class MapLink(QObject):
    def __init__(
        self,
        session: SiteSession,
        layers: SiteLayers,
        canvas: QgsMapCanvas,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.layers = layers
        self.canvas = canvas

        self._marker: QgsVertexMarker | None = QgsVertexMarker(canvas)
        self._marker.setIconType(QgsVertexMarker.ICON_CROSS)
        self._marker.setColor(MARKER_COLOUR)
        self._marker.setIconSize(MARKER_SIZE_PX)
        self._marker.setPenWidth(2)
        self._marker.setVisible(False)

        self._band: QgsRubberBand | None = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self._band.setColor(BAND_COLOUR)
        self._band.setWidth(BAND_WIDTH_PX)

        # None means "not built". Holds every line's geometry already
        # transformed into the CANVAS's CRS, so neither the marker nor the
        # hit test has to transform anything per mouse move, and the hover
        # tolerance -- which is a pixel count times mapUnitsPerPixel -- is
        # in the same units as the distances it is compared against.
        self._geoms: dict[str, QgsGeometry] | None = None

        for signal in (
            session.trace_changed,
            session.selection_changed,
            session.preview_changed,
            session.line_opened,
        ):
            signal.connect(self._on_session_changed)
        for signal in (session.lines_changed, session.grids_changed, session.site_opened):
            signal.connect(self._on_lines_changed)
        session.site_closed.connect(self._on_lines_changed)
        canvas.destinationCrsChanged.connect(self._on_lines_changed)

    # ---- cache ------------------------------------------------------------
    def _invalidate(self) -> None:
        self._geoms = None

    def _geometries(self) -> dict[str, QgsGeometry]:
        if self._geoms is not None:
            return self._geoms
        geoms: dict[str, QgsGeometry] = {}
        layer = self._lines_layer()
        if layer is not None:
            tr = self._transform(layer)
            for feature in layer.getFeatures():
                # A copy: the QgsFeature the iterator yields is reused, so
                # its geometry must not be held by reference.
                geom = QgsGeometry(feature.geometry())
                if tr is not None:
                    geom.transform(tr)
                geoms[str(feature["line_key"])] = geom
        self._geoms = geoms
        return geoms

    def _lines_layer(self) -> QgsVectorLayer | None:
        layer = self.layers.layers.get("lines")
        if layer is None or sip.isdeleted(layer):
            return None
        return layer

    def _transform(self, layer: QgsVectorLayer) -> QgsCoordinateTransform | None:
        dest = self.canvas.mapSettings().destinationCrs()
        source = layer.crs()
        if not dest.isValid() or not source.isValid() or source == dest:
            return None
        return QgsCoordinateTransform(source, dest, QgsProject.instance())

    # ---- drawing ----------------------------------------------------------
    def _on_lines_changed(self, *_: Any) -> None:
        try:
            self._invalidate()
            self._refresh()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not rebuild the map link: {exc}", Qgis.MessageLevel.Critical)

    def _on_session_changed(self, *_: Any) -> None:
        try:
            self._refresh()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not update the map link: {exc}", Qgis.MessageLevel.Critical)

    def _refresh(self) -> None:
        """Redraw both items from the session, whatever changed.

        Every signal lands here rather than each one updating its own item:
        the marker and the band both depend on which line is displayed AND
        on whether that line is a preview, so per-signal updates would have
        to re-derive the same answer in four places and could disagree.
        """
        if self._marker is None or self._band is None:
            return  # disposed
        key = self.session.display_key if self.session.is_open else None
        if key is None:
            self._marker.setVisible(False)
            self._band.reset(QgsWkbTypes.LineGeometry)
            return
        # `preview_key == current_key` is reachable -- the session allows
        # it and emits for it -- and it means the pointer is over the line
        # already being worked on, which is not a preview at all. Testing
        # `preview_key is not None` alone would blank that line's own
        # selection band the moment the pointer crossed it. ProfileDock
        # draws the same distinction in `_on_preview_changed`; the two must
        # agree or the map and the profile disagree about what is showing.
        previewing = self.session.preview_key not in (None, self.session.current_key)
        if previewing:
            self._set_marker(key, self.session.preview_trace)
            # A preview has no selection of its own, and the working
            # line's selection belongs to a line that is not on screen.
            self._band.reset(QgsWkbTypes.LineGeometry)
            return
        self._set_marker(key, self.session.current_trace)
        self._set_band(key, *self.session.selection)

    def _set_marker(self, key: str, trace: int) -> None:
        assert self._marker is not None
        geom = self._geometries().get(key)
        if geom is None or trace < 0 or trace >= self._n_vertices(geom):
            self._marker.setVisible(False)
            return
        self._marker.setCenter(QgsPointXY(geom.vertexAt(trace)))
        self._marker.setVisible(True)

    def _set_band(self, key: str, start: int, end: int) -> None:
        assert self._band is not None
        geom = self._geometries().get(key)
        if geom is None or start < 0 or end < 0:
            self._band.reset(QgsWkbTypes.LineGeometry)
            return
        n = self._n_vertices(geom)
        lo = max(0, min(start, end))
        hi = min(n - 1, max(start, end))
        if lo > hi:
            self._band.reset(QgsWkbTypes.LineGeometry)
            return
        points = [QgsPointXY(geom.vertexAt(i)) for i in range(lo, hi + 1)]
        # layer=None: the cache is already in canvas CRS, so asking for a
        # transform here would apply one twice.
        self._band.setToGeometry(QgsGeometry.fromPolylineXY(points), None)

    @staticmethod
    def _n_vertices(geom: QgsGeometry) -> int:
        part = geom.constGet()
        return 0 if part is None else int(part.numPoints())

    # ---- teardown ---------------------------------------------------------
    def dispose(self) -> None:
        """Take both canvas items back off the scene, for good.

        Item I4 in Plan 2's final fix round: a QgsMapCanvasItem is owned by
        the canvas's QGraphicsScene, not by the Python wrapper, so dropping
        the reference leaks the item for the life of the QGIS session --
        the objects implicated in a shutdown segfault "once enough of them
        pile up alongside a QgsMapCanvas".

        Idempotent, because more than one finaliser can reach the same
        link. `item.scene()` rather than `self.canvas.scene()`: it removes
        the item from whatever scene actually holds it, and does not
        assume the canvas is still alive.
        """
        items, self._marker, self._band = (self._marker, self._band), None, None
        for item in items:
            if item is None or sip.isdeleted(item):
                continue
            scene = item.scene()
            if scene is not None:
                # removeItem() hands ownership back to us, so dropping the
                # last reference (done above) is what actually frees it.
                scene.removeItem(item)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py -q -p no:xonsh`

Expected: PASS, 11 tests.

- [ ] **Step 5: Verify the boundary test still passes**

`packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py` asserts the plugin never imports `nsgeo.processing` internals. `map_link.py` imports none, but run it explicitly — the test enumerates plugin modules, so a new file is newly in scope:

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q -p no:xonsh`

Expected: PASS.

- [ ] **Step 6: Run both tiers and the linters, then commit**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
.venv/bin/ruff check . && .venv/bin/ruff format --check .
git add packages/nsgeo-qgis/nsgeo_qgis/map_link.py packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py
git commit -m "feat: draw the profile's cursor and selection on the map

MapLink owns a vertex marker and a rubber band and redraws both from the
session. refill_lines writes one geometry vertex per trace, so the vertex
index IS the trace index and this module needs no coordinate maths.

Geometries are cached already transformed into canvas CRS: the hover
tolerance in Task 4 is a pixel count times mapUnitsPerPixel, and it has to
be compared against distances in the same units.

dispose() takes both items off the scene. I4 showed that nothing else will.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

