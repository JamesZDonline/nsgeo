### Task 12: Background line loading and the M4 checkpoint

`Line.load()` on a `QgsTask`, so clicking a line never blocks the canvas. The session gets the profiles when the task finishes. Ends M4: real lines on the map from real files.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/loader.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (own a `LineLoader`)
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_loader.py`

**Interfaces:**
- Consumes: `SiteSession.line_opened`, `profiles_for`, `set_profiles`, `Line.load`
- Produces: `LineLoader(session, on_error=None, parent=None)` with signal `loading_changed(str, bool)`, `is_loading(key) -> bool`, `request(key)`, `wait_for(key, timeout_ms=5000) -> bool` (test helper; spins a `QEventLoop`)

- [ ] **Step 1: Write the failing test**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_loader.py`:

```python
from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt

from nsgeo_qgis.loader import LineLoader
from nsgeo_qgis.session import SiteSession

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def session(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    s.add_grid(GRID)
    return s


def test_opening_a_line_loads_it_in_the_background(session, tmp_path):
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=200)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0))])
    key = session.keys()[0]
    loader = LineLoader(session)
    states = []
    loader.loading_changed.connect(lambda k, f: states.append((k, f)))
    loaded = []
    session.line_loaded.connect(loaded.append)

    session.open_line(key)
    assert loader.is_loading(key)
    assert loader.wait_for(key)
    assert not loader.is_loading(key)
    assert states == [(key, True), (key, False)]
    assert loaded == [key]
    assert session.stack_for(key).source.n_traces == 200


def test_reopening_a_loaded_line_does_not_reload(session, tmp_path):
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    q = synthetic_dzt(tmp_path / "raw", "FILE__002.DZT")
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0)), Line.open(q, GridPlacement("A", "y", 0.5))])
    a, b = session.keys()
    loader = LineLoader(session)
    session.open_line(a)
    assert loader.wait_for(a)
    session.open_line(b)
    assert loader.wait_for(b)
    states = []
    loader.loading_changed.connect(lambda k, f: states.append((k, f)))
    session.open_line(a)
    assert states == [] and not loader.is_loading(a)


def test_a_corrupt_file_reports_instead_of_raising(session, tmp_path):
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0))])
    key = session.keys()[0]
    p.write_bytes(p.read_bytes()[:-7])  # non-integer trace count now
    errors = []
    loader = LineLoader(session, on_error=lambda k, msg: errors.append((k, msg)))
    session.open_line(key)
    assert loader.wait_for(key)
    assert errors and errors[0][0] == key and "trace count" in errors[0][1]
    assert session.profiles_for(key) is None


@needs_real_data
def test_real_line_loads(session):
    line = Line.open(REAL_DZT[0], GridPlacement("A", "y", 0.0))
    session.add_lines([line])
    key = session.keys()[0]
    loader = LineLoader(session)
    session.open_line(key)
    assert loader.wait_for(key, timeout_ms=10_000)
    src = session.stack_for(key).source
    assert src.n_samples == 512 and src.t0_ns == pytest.approx(-11.09, abs=0.01)
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_loader.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.loader'`

- [ ] **Step 3: Implement the loader**

Create `packages/nsgeo-qgis/nsgeo_qgis/loader.py`:

```python
"""Load sample arrays off the main thread.

Header reads are 1 KB and stay synchronous; Line.load() reads megabytes and
runs on a QgsTask. The session is only touched from the main thread, in the
task's finished callback.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qgis.core import QgsApplication, QgsTask
from qgis.PyQt.QtCore import QEventLoop, QObject, QTimer, pyqtSignal

from nsgeo_qgis.session import SiteSession


class LineLoader(QObject):
    loading_changed = pyqtSignal(str, bool)

    def __init__(
        self,
        session: SiteSession,
        on_error: Callable[[str, str], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.on_error = on_error
        self._tasks: dict[str, QgsTask] = {}
        session.line_opened.connect(self._on_line_opened)
        session.site_closed.connect(self._tasks.clear)

    def is_loading(self, key: str) -> bool:
        return key in self._tasks

    def _on_line_opened(self, key: str) -> None:
        if key:
            self.request(key)

    def request(self, key: str) -> None:
        if key in self._tasks or self.session.profiles_for(key) is not None:
            return
        line = self.session.line_for_key(key)

        def work(_task: QgsTask) -> Any:
            return line.load()

        def finished(exception: BaseException | None, result: Any = None) -> None:
            self._tasks.pop(key, None)
            if exception is not None:
                if self.on_error is not None:
                    self.on_error(key, str(exception))
            elif self.session.is_open and key in self.session.keys():
                self.session.set_profiles(key, result)
            self.loading_changed.emit(key, False)

        task = QgsTask.fromFunction(f"nsgeo: load {line.path.name}", work, on_finished=finished)
        self._tasks[key] = task
        self.loading_changed.emit(key, True)
        QgsApplication.taskManager().addTask(task)

    def wait_for(self, key: str, timeout_ms: int = 5000) -> bool:
        """Spin the event loop until `key` finishes loading. For tests."""
        if key not in self._tasks:
            return True
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)

        def on_change(k: str, flag: bool) -> None:
            if k == key and not flag:
                loop.quit()

        self.loading_changed.connect(on_change)
        timer.start(timeout_ms)
        loop.exec()
        self.loading_changed.disconnect(on_change)
        return key not in self._tasks
```

- [ ] **Step 4: Wire it into the plugin**

In `plugin.py` `initGui`, after creating `self.layers`:

```python
        self.loader = LineLoader(
            self.session,
            on_error=lambda key, msg: self.message(f"{key}: {msg}", Qgis.MessageLevel.Critical),
        )
```

with `from nsgeo_qgis.loader import LineLoader`, an `self.loader: LineLoader | None = None` in `__init__`, and `self.loader = None` in `unload`.

- [ ] **Step 5: Run everything, lint, commit**

Run the full verification set from Global Constraints.
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: load line samples on a QgsTask

Clicking a line never blocks the canvas: Line.load() runs in the task
pool and the session receives the profiles on the main thread. Errors
from a corrupt file reach the message bar instead of a traceback."
```

**M4 checkpoint (manual, 10 minutes).** With the dev symlink in place, reload the plugin in QGIS and:

1. Toolbar ▸ New site… ▸ pick an empty folder. The survey dock shows the folder name and `survey.nsgeo.json · ● modified` is not shown (a fresh site is clean).
2. Toolbar ▸ Add grid… ▸ GNSS corners tab. Enter four corners (any UTM numbers forming a ≈5 × 11 m rectangle), Fit, confirm the residual reads near zero, set id `A`, CRS EPSG:32616, velocity shows 0.08, OK. A dashed grid outline appears on the canvas in a group named after the site.
3. Right-click grid A ▸ Import DZT files… ▸ Add files… ▸ select the ten real files from `packages/nsgeo-core/tests/data/local/`. Check: 10 rows, FILE__008's note says it exceeds the grid, sidecar column shows ε 14 for nine files. Uncheck FILE__005, confirm FILE__006 moves to offset 2.00. Re-check it. Import 10 lines.
4. Ten coloured lines appear inside the grid outline, one mark point at the end of FILE__007. Click a line in the tree: nothing visible happens yet (no viewer), but no error appears and the QGIS task bar briefly shows a load.
5. Toolbar ▸ Save site. Open the saved `survey.nsgeo.json` in a text editor: grids carry `velocity`, lines carry placements. Open the `.nsgeo.gpkg` in QGIS's browser: four tables.
6. Digitise tab: Add grid… ▸ Digitise on map ▸ Pick on map ▸ two clicks on the canvas ▸ the dialog returns with origin and azimuth filled; enter sizes and id `B`, OK. Grid B appears.

Anything that fails here is fixed before Task 13.

---

