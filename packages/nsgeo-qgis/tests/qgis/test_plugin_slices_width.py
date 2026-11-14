"""The Slices panel's width (#121, #50).

The rule (spec 8.2): the Slices contents are never wider than the Processing
panel's minimum at the same font, with the data's own text (a long cube name,
the longest slice readout, the memory label in GB, a long velocity source) in
the panel. And the panel opens at least as wide as its contents, so it never
opens scrolling sideways."""

from __future__ import annotations

import contextlib

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.processing_dock import ProcessingDock
from nsgeo_qgis.ui.slices_dock import SlicesDock, _OpensWideScrollArea
from nsgeo_qgis.ui.warnings_panel import WARNING, Entry
from plugin_testing import REAL_DZT, needs_real_data
from qgis.gui import QgsCollapsibleGroupBox
from qgis.PyQt.QtCore import QCoreApplication, QEvent
from qgis.PyQt.QtWidgets import QApplication, QScrollArea

LONG_NAME = "a name long enough to widen any combo box at all, 60 c"
LONG_CUBE = LONG_NAME
LONG_WARNING = (
    "Too many levels: a long warning with one unbroken token "
    + "x" * 40
    + " that must wrap or be cut off, never widen the panel."
)
LONG_MEMORY = (
    "12 of 12 included · about 12.3 GB"
    " -- over the default budget; slices will stream rather than hold it all"
)
LONG_VELOCITY = "v = 0.100 m/ns (a long source label from a cube, a preset or the survey itself)"


@contextlib.contextmanager
def width_fonts(points: float):
    """The application font at `points`, restored on exit. Build the docks inside it."""
    app = QApplication.instance()
    old = app.font()
    font = QApplication.font()
    font.setPointSizeF(points)
    app.setFont(font)
    try:
        yield
    finally:
        app.setFont(old)


def _events(n: int = 5) -> None:
    for _ in range(n):
        QCoreApplication.processEvents()


def _carry_data_text(dock) -> None:
    """The data's longest labels. A late preparation rewrites them, so the guard
    sets them again once the dock is shown."""
    dock.included_label.setText(LONG_MEMORY)
    dock.velocity_label.setText(LONG_VELOCITY)


@contextlib.contextmanager
def _loaded_dock(session: SiteSession, scope: str):
    """A Slices dock on `session`, prepared, carrying the data's longest texts,
    every section unfolded, in `scope` and settled."""
    dock = SlicesDock(session)
    try:
        assert dock.engine.wait_for_preparation(60_000)
        dock.flush_debounce()
        for combo in (dock.cube_combo, dock.grid_combo, dock.preset_combo):
            combo.addItem(LONG_NAME)
            # A combo keeps the minimum width it worked out before the item came;
            # a theme change (this event) makes it measure the long name.
            QCoreApplication.sendEvent(combo, QEvent(QEvent.Type.StyleChange))
        dock.slice_slider.setValue(dock.slice_slider.maximum())  # the longest readout
        for box in dock.findChildren(QgsCollapsibleGroupBox):
            box.setCollapsed(False)
        if scope == "site":
            dock.site_scope_button.click()
            assert dock.scope() == "site"
            assert dock.site_engine.wait_until_idle(60_000)
        _events()
        _carry_data_text(dock)
        dock.warnings_panel.set_entries([Entry(WARNING, LONG_WARNING)])
        _events()
        yield dock
    finally:
        dock.refiner.shutdown()
        dock.dispose_site()
        dock.engine.wait_for_preparation(20_000)
        dock.engine.dispose()
        dock.deleteLater()


def _assert_fits_the_processing_minimum(session: SiteSession, scope: str) -> None:
    limit = ProcessingDock(session).minimumSizeHint().width()
    with _loaded_dock(session, scope) as dock:
        dock.setFloating(True)
        dock.resize(limit, 500)
        dock.show()
        _events()
        _carry_data_text(dock)
        _events()
        scroll = dock.findChild(QScrollArea)
        content = scroll.widget()
        assert scroll.verticalScrollBar().isVisible()
        assert scroll.verticalScrollBar().maximum() > 0, "the vertical bar must be showing"
        assert dock.cube_combo.findText(LONG_CUBE) >= 0
        assert dock.warnings_panel.isVisible(), "the long Warnings entry is in the panel"
        assert dock.included_label.text() == LONG_MEMORY, "the long data text is in the panel"
        assert dock.width() == limit
        assert content.minimumSizeHint().width() <= limit
        assert scroll.horizontalScrollBar().maximum() == 0, (
            f"scrolls sideways at {limit} px; content wants {content.minimumSizeHint().width()}"
        )


@pytest.mark.parametrize("points", [9.0, 14.0])
@pytest.mark.parametrize("scope", ["grid", "site"])
def test_the_slices_panel_fits_the_processing_panels_minimum(qgis_app, site3, points, scope):
    with width_fonts(points):
        _assert_fits_the_processing_minimum(site3.session, scope)


@needs_real_data
@pytest.mark.parametrize("points", [9.0, 14.0])
@pytest.mark.parametrize("scope", ["grid", "site"])
def test_a_real_site_fits_the_processing_panels_minimum(qgis_app, tmp_path, points, scope):
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(Grid("A", (500.0, 700.0), 0.0, 20.0, 20.0, "EPSG:32616", 1.0))
    session.add_lines(
        [
            Line.open(path, GridPlacement("A", "y", 1.0 + i, 0.0, 1, path.stem))
            for i, path in enumerate(REAL_DZT[:4])
        ]
    )
    with width_fonts(points):
        _assert_fits_the_processing_minimum(session, scope)


@pytest.mark.parametrize("scope", ["grid", "site"])
def test_the_panel_opens_at_least_as_wide_as_its_contents(qgis_app, site3, scope):
    """#50: opening at `sizeHint` (as a dock does) must not scroll sideways."""
    with _loaded_dock(site3.session, scope) as dock:
        dock.setFloating(True)
        dock.resize(dock.sizeHint())
        dock.show()
        _events()
        scroll = dock.findChild(QScrollArea)
        assert scroll.verticalScrollBar().isVisible(), "the bar is what the hint must make room for"
        assert scroll.horizontalScrollBar().maximum() == 0


def test_the_opens_wide_scroll_area_makes_room_for_its_bar(qgis_app):
    """#50, directly: content whose hint equals its minimum and is taller than
    the viewport. A stock QScrollArea opens at the content's width, shows the
    bar, and scrolls sideways by the bar's width."""
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtWidgets import QWidget

    class Fixed(QWidget):
        def sizeHint(self):  # noqa: N802
            return QSize(300, 2000)

        def minimumSizeHint(self):  # noqa: N802
            return QSize(300, 2000)

    def sideways(scroll_class) -> int:
        scroll = scroll_class()
        scroll.setWidgetResizable(True)
        scroll.setWidget(Fixed())
        scroll.resize(scroll.sizeHint().width(), 400)
        scroll.show()
        _events()
        assert scroll.verticalScrollBar().isVisible()
        result = scroll.horizontalScrollBar().maximum()
        scroll.deleteLater()
        return result

    assert sideways(QScrollArea) > 0, "the premise: a stock scroll area scrolls sideways"
    assert sideways(_OpensWideScrollArea) == 0
