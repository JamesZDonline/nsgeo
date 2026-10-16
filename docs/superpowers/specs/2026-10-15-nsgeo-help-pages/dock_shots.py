"""Throwaway: render the real ProcessingDock with a Help button injected, two placements."""
import shutil, sys, tempfile
from pathlib import Path
sys.path.insert(0, "packages/nsgeo-qgis")
import nsgeo_qgis  # noqa: F401  core path shim
from qgis.core import QgsApplication
QgsApplication.setPrefixPath("/usr", True)
app = QgsApplication([], True)
app.initQgis()
from qgis.PyQt.QtWidgets import QPushButton
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.processing_dock import ProcessingDock

OUT = Path(".lavish/help-pages")
tmp = Path(sys.argv[1]); shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir()
src = Path("packages/nsgeo-core/tests/data/local/FILE__007.DZT")
(tmp / "raw").mkdir()
shutil.copy(src, tmp / "raw" / src.name)

def shot(where: str | None, width: int, name: str, select: int = 0) -> None:
    session = SiteSession()
    dock = ProcessingDock(session)
    (tmp / name).mkdir()
    session.new_site(tmp / name)
    session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
    line = Line.open(tmp / "raw" / src.name, GridPlacement("A", "y", 0.0))
    session.add_lines([line])
    key = session.keys()[0]
    session.set_profiles(key, line.load())
    session.open_line(key)
    for s in ("dewow", "background_mean", "gain_agc"):
        dock.add_step(s)
    body = dock.widget().layout()
    rows = [body.itemAt(i).layout() for i in range(body.count()) if body.itemAt(i).layout() is not None]
    top, bottom = rows[0], rows[-1]
    if where is not None:
        if where == "q":
            from qgis.PyQt.QtWidgets import QToolButton
            help_btn = QToolButton(); help_btn.setText("?")
        else:
            help_btn = QPushButton("Help")
        help_btn.setToolTip("Open a page explaining the selected step")
        if where in ("top", "q"):
            top.insertWidget(top.indexOf(dock.diff_button) + 1, help_btn)
        else:
            bottom.insertWidget(bottom.indexOf(dock.presets_button) + 1, help_btn)
        help_btn.setEnabled(select >= 0)
    dock.list.setCurrentRow(select)
    dock.resize(width, 470)
    dock.show()
    app.processEvents()
    print(name, "min width", dock.minimumSizeHint().width())
    dock.grab().save(str(OUT / f"{name}.png"))

shot("q", 360, "dock_q")
