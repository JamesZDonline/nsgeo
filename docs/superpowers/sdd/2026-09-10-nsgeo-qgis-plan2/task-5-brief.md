### Task 5: Plugin skeleton, core path shim, boundary test, offscreen harness, CI

The first thing QGIS can load. Also the mechanical guards (plugin boundary test) and the test harness every later plugin task depends on. No docks yet.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/__init__.py`
- Create: `packages/nsgeo-qgis/nsgeo_qgis/metadata.txt`
- Create: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Create: `packages/nsgeo-qgis/nsgeo_qgis/qtcompat.py`
- Create: `packages/nsgeo-qgis/tests/conftest.py`
- Create: `packages/nsgeo-qgis/tests/plugin_testing.py`
- Create: `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py`
- Create: `packages/nsgeo-qgis/tests/pure/test_plugin_shim.py`
- Create: `packages/nsgeo-qgis/tests/qgis/conftest.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py`
- Create: `packages/nsgeo-qgis/scripts/dev_link.py`
- Create: `packages/nsgeo-qgis/README.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `.gitignore` (add `.venv-qgis/`)

**Interfaces:**
- Consumes: `nsgeo.__version__`
- Produces: `nsgeo_qgis.CORE_PATH: Path`; `nsgeo_qgis._find_core(package_dir: Path) -> Path`; `classFactory(iface)`; `NsgeoPlugin(iface)` with `initGui()`, `unload()`, `toolbar`, `session` (None until Task 6); `nsgeo_qgis.qtcompat.event_pos(event) -> QPointF`; `plugin_version() -> str`; test fixtures `qgis_app`, `fake_iface`, `REAL_DZT` (list), `synthetic_dzt(tmp_path, name, n_traces)` helper

**Test-module naming rule (matters):** the plugin `tests/` tree has **no `__init__.py`** files, so pytest imports its modules by basename. Every plugin test file must therefore have a name unique across the repo: prefix them `test_plugin_` (qgis tier) or `test_pure_`/`test_plugin_` (pure tier). Never create `packages/nsgeo-qgis/tests/test_boundary.py` — it collides with the core's. Shared helpers live in `tests/plugin_testing.py`, which the conftest puts on `sys.path`; tests import it as `from plugin_testing import ...` (relative imports do not work without packages).

- [ ] **Step 1: Write the failing pure tests**

Create `packages/nsgeo-qgis/tests/conftest.py`:

```python
"""Shared setup for the plugin tests.

Puts the plugin package, the core's test helpers, and this directory's
`plugin_testing` module on sys.path. Importing `nsgeo_qgis` runs its path
shim, which puts the core *source* on sys.path too, so these tests work in
`.venv-qgis` (no nsgeo installed) as well as in `.venv` (nsgeo editable).
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_DIR = HERE.parent  # packages/nsgeo-qgis
CORE_DIR = PLUGIN_DIR.parent / "nsgeo-core"  # for `from tests.synthetic import write_dzt`
for p in (HERE, PLUGIN_DIR, CORE_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import nsgeo_qgis  # noqa: E402,F401  (runs the core path shim)
```

Create `packages/nsgeo-qgis/tests/plugin_testing.py`:

```python
"""Helpers shared by both plugin test tiers. Imported as `plugin_testing`."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

CORE_DIR = Path(__file__).resolve().parent.parent.parent / "nsgeo-core"
LOCAL_DATA = CORE_DIR / "tests" / "data" / "local"
REAL_DZT = (
    sorted(p for p in LOCAL_DATA.rglob("*") if p.suffix.lower() == ".dzt")
    if LOCAL_DATA.exists()
    else []
)

needs_real_data = pytest.mark.skipif(not REAL_DZT, reason="no real DZT files in tests/data/local")


def synthetic_dzt(folder: Path, name: str, n_traces: int = 60, **kw) -> Path:
    """A small synthetic DZT with a visible pattern, written into `folder`."""
    from tests.synthetic import write_dzt

    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(abs(hash(name)) % (2**32))
    data = (rng.normal(size=(512, n_traces)) * 1e6).astype(np.int32)
    data[40:44, :] = 5_000_000  # a flat band, so background removal has something to remove
    path = folder / name
    write_dzt(path, data, **kw)
    return path
```

Create `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py`:

```python
"""The plugin must contain no signal processing and no direct PyQt imports.

Direct `PyQt5`/`PyQt6` imports break on the other Qt major version; the
`qgis.PyQt` shim works on both. Importing processing internals would let
maths creep into widgets, which is the boundary the whole design rests on.
"""

from __future__ import annotations

import ast
from pathlib import Path

import nsgeo_qgis

SRC = Path(nsgeo_qgis.__file__).parent

FORBIDDEN_ROOTS = {"PyQt5", "PyQt6", "PySide2", "PySide6", "matplotlib", "scipy"}
ALLOWED_FROM_PROCESSING = {
    "StepStack",
    "build_step",
    "available_steps",
    "get_step",
    "Radargram",
    "ParamSpec",
    "REQUIRED",
    "default_params",
    "required_params",
}


def _py_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "_vendor" not in p.parts)


def test_src_tree_is_actually_being_scanned() -> None:
    assert len(_py_files()) >= 2


def test_no_direct_qt_or_forbidden_imports() -> None:
    offenders = []
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module.split(".")[0]]
            bad = set(names) & FORBIDDEN_ROOTS
            if bad:
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}: {sorted(bad)}")
    assert not offenders, "forbidden imports:\n" + "\n".join(offenders)


def test_processing_is_used_only_through_its_public_surface() -> None:
    offenders = []
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "nsgeo.processing":
                    bad = {a.name for a in node.names} - ALLOWED_FROM_PROCESSING
                    if bad:
                        offenders.append(f"{path.relative_to(SRC)}:{node.lineno}: {sorted(bad)}")
                elif node.module.startswith("nsgeo.processing."):
                    offenders.append(f"{path.relative_to(SRC)}:{node.lineno}: {node.module}")
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("nsgeo.processing"):
                        offenders.append(f"{path.relative_to(SRC)}:{node.lineno}: import {a.name}")
    assert not offenders, "processing internals imported by the plugin:\n" + "\n".join(offenders)


def test_package_init_imports_no_qgis_at_module_level() -> None:
    """The pure test tier and the zip's shim both import the package without
    a QGIS runtime. classFactory imports qgis lazily."""
    tree = ast.parse((SRC / "__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Import):
            assert not any(a.name.split(".")[0] == "qgis" for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("qgis")
```

Create `packages/nsgeo-qgis/tests/pure/test_plugin_shim.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

import nsgeo_qgis
from nsgeo_qgis import _find_core, plugin_version


def test_core_path_points_at_a_real_nsgeo_package():
    assert (nsgeo_qgis.CORE_PATH / "nsgeo" / "__init__.py").is_file()
    import nsgeo

    assert Path(nsgeo.__file__).resolve().parent == (nsgeo_qgis.CORE_PATH / "nsgeo").resolve()


def test_vendored_core_wins_when_present(tmp_path):
    pkg = tmp_path / "packages" / "nsgeo-qgis" / "nsgeo_qgis"
    (pkg / "_vendor" / "nsgeo").mkdir(parents=True)
    (pkg / "_vendor" / "nsgeo" / "__init__.py").write_text("")
    assert _find_core(pkg) == pkg / "_vendor"


def test_sibling_source_tree_is_the_development_fallback(tmp_path):
    pkg = tmp_path / "packages" / "nsgeo-qgis" / "nsgeo_qgis"
    pkg.mkdir(parents=True)
    src = tmp_path / "packages" / "nsgeo-core" / "src"
    (src / "nsgeo").mkdir(parents=True)
    (src / "nsgeo" / "__init__.py").write_text("")
    assert _find_core(pkg) == src


def test_missing_core_names_both_places_it_looked(tmp_path):
    pkg = tmp_path / "packages" / "nsgeo-qgis" / "nsgeo_qgis"
    pkg.mkdir(parents=True)
    with pytest.raises(ImportError) as exc:
        _find_core(pkg)
    msg = str(exc.value)
    assert "_vendor" in msg and "nsgeo-core" in msg


def test_plugin_version_comes_from_metadata():
    v = plugin_version()
    assert v and v[0].isdigit()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis'`

- [ ] **Step 3: Create the package**

Create `packages/nsgeo-qgis/nsgeo_qgis/__init__.py`:

```python
"""nsgeo QGIS plugin entry point.

Two jobs, both before any qgis import: find the nsgeo core and put it on
sys.path, and expose classFactory for QGIS. The core is found in the
release zip's `_vendor/` first, then in the sibling development checkout
(`packages/nsgeo-core/src`, reached through the dev symlink's real path).
No `pip install` into the QGIS interpreter is ever needed.
"""

from __future__ import annotations

import configparser
import sys
from pathlib import Path
from typing import Any


def _find_core(package_dir: Path) -> Path:
    """The directory to put on sys.path so `import nsgeo` works."""
    vendored = package_dir / "_vendor"
    if (vendored / "nsgeo" / "__init__.py").is_file():
        return vendored
    sibling = package_dir.parent.parent / "nsgeo-core" / "src"
    if (sibling / "nsgeo" / "__init__.py").is_file():
        return sibling
    raise ImportError(
        "nsgeo core library not found. Looked in "
        f"{vendored} (release zip) and {sibling} (development checkout)."
    )


CORE_PATH = _find_core(Path(__file__).resolve().parent)
if str(CORE_PATH) not in sys.path:
    sys.path.insert(0, str(CORE_PATH))


def plugin_version() -> str:
    cfg = configparser.ConfigParser()
    cfg.read(Path(__file__).resolve().parent / "metadata.txt", encoding="utf-8")
    return cfg["general"]["version"]


def classFactory(iface: Any) -> Any:  # noqa: N802  (QGIS API name)
    from nsgeo_qgis.plugin import NsgeoPlugin

    return NsgeoPlugin(iface)
```

Create `packages/nsgeo-qgis/nsgeo_qgis/metadata.txt`:

```ini
[general]
name=nsgeo
qgisMinimumVersion=3.40
supportsQt6=True
description=Near-surface geophysics: GPR profiles in map context
about=Load GSSI DZT files, organise them into georeferenced grids, view and process radargrams, and navigate them from the QGIS map. Core library is numpy-only and vendored into this plugin.
version=0.1.0
author=James Zimmer-Dauphinee
email=james.r.zimmer-dauphinee@vanderbilt.edu
repository=https://github.com/JamesZDonline/nsgeo
tracker=https://github.com/JamesZDonline/nsgeo/issues
homepage=https://github.com/JamesZDonline/nsgeo
category=Plugins
tags=gpr,geophysics,archaeology,radar,near-surface
hasProcessingProvider=no
experimental=True
```

Create `packages/nsgeo-qgis/nsgeo_qgis/qtcompat.py`:

```python
"""The few places Qt5 and Qt6 differ for this plugin.

Everything else is handled by importing through `qgis.PyQt` and using
scoped enums. Keep this file tiny; if it grows, the design is leaking.
"""

from __future__ import annotations

from typing import Any

from qgis.PyQt.QtCore import QPointF


def event_pos(event: Any) -> QPointF:
    """Local position of a mouse or wheel event on both Qt majors."""
    if hasattr(event, "position"):
        return QPointF(event.position())
    return QPointF(event.pos())
```

Create `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`:

```python
"""The QGIS plugin object: builds the toolbar and docks, tears them down.

Holds no survey state. That lives in SiteSession (Task 6); widgets read
from it and never from each other.
"""

from __future__ import annotations

from typing import Any

import nsgeo
from qgis.core import Qgis
from qgis.PyQt.QtWidgets import QAction

from nsgeo_qgis import plugin_version

MENU = "&nsgeo"


class NsgeoPlugin:
    def __init__(self, iface: Any) -> None:
        self.iface = iface
        self.toolbar: Any = None
        self.actions: list[QAction] = []
        self.docks: list[Any] = []
        self.session: Any = None

    # QGIS calls these two.
    def initGui(self) -> None:  # noqa: N802
        self.toolbar = self.iface.addToolBar("nsgeo")
        self.toolbar.setObjectName("nsgeoToolBar")
        about = QAction("About nsgeo", self.iface.mainWindow())
        about.triggered.connect(self.show_about)
        self.iface.addPluginToMenu(MENU, about)
        self.actions.append(about)

    def unload(self) -> None:
        for dock in self.docks:
            self.iface.removeDockWidget(dock)
            dock.deleteLater()
        self.docks.clear()
        for action in self.actions:
            self.iface.removePluginMenu(MENU, action)
        self.actions.clear()
        if self.toolbar is not None:
            self.toolbar.setParent(None)
            self.toolbar.deleteLater()
            self.toolbar = None

    def show_about(self) -> None:
        self.iface.messageBar().pushMessage(
            "nsgeo",
            f"plugin {plugin_version()} · core {nsgeo.__version__}",
            Qgis.MessageLevel.Info,
            5,
        )
```

- [ ] **Step 4: Run the pure tests**

Run: `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q`
Expected: all PASS.

- [ ] **Step 5: Write the failing QGIS-tier test and its fixtures**

Create `packages/nsgeo-qgis/tests/qgis/conftest.py`:

```python
"""Offscreen QGIS for tests that construct widgets and layers.

Skips the whole directory when `qgis` is not importable, so the normal CI
matrix (no QGIS) stays green while `.venv-qgis` and the Docker job run it.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
qgis_core = pytest.importorskip("qgis.core")


@pytest.fixture(scope="session")
def qgis_app():
    from qgis.core import QgsApplication

    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/usr"), True)
    app = QgsApplication([], False)
    app.initQgis()
    yield app
    app.exitQgis()


class FakeIface:
    """The parts of QgisInterface the plugin touches."""

    def __init__(self) -> None:
        from qgis.gui import QgsMapCanvas, QgsMessageBar
        from qgis.PyQt.QtWidgets import QMainWindow

        self._main = QMainWindow()
        self._canvas = QgsMapCanvas(self._main)
        self._main.setCentralWidget(self._canvas)
        self._bar = QgsMessageBar(self._main)
        self.docks: list = []
        self.toolbars: list = []
        self.menu_actions: list = []

    def mainWindow(self):  # noqa: N802
        return self._main

    def mapCanvas(self):  # noqa: N802
        return self._canvas

    def messageBar(self):  # noqa: N802
        return self._bar

    def addToolBar(self, name):  # noqa: N802
        from qgis.PyQt.QtWidgets import QToolBar

        tb = QToolBar(name, self._main)
        self._main.addToolBar(tb)
        self.toolbars.append(tb)
        return tb

    def addDockWidget(self, area, dock):  # noqa: N802
        self._main.addDockWidget(area, dock)
        self.docks.append(dock)

    def removeDockWidget(self, dock):  # noqa: N802
        self._main.removeDockWidget(dock)
        if dock in self.docks:
            self.docks.remove(dock)

    def addPluginToMenu(self, name, action):  # noqa: N802
        self.menu_actions.append((name, action))

    def removePluginMenu(self, name, action):  # noqa: N802
        self.menu_actions.remove((name, action))


@pytest.fixture
def fake_iface(qgis_app):
    return FakeIface()
```

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py`:

```python
from __future__ import annotations

import nsgeo_qgis


def test_class_factory_builds_a_plugin_that_adds_and_removes_its_ui(fake_iface):
    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    assert plugin.toolbar is not None
    assert plugin.toolbar.objectName() == "nsgeoToolBar"
    assert [name for name, _ in fake_iface.menu_actions] == ["&nsgeo"]

    plugin.show_about()
    item = fake_iface.messageBar().currentItem()
    assert item is not None and "core" in item.text()

    plugin.unload()
    assert plugin.toolbar is None
    assert fake_iface.menu_actions == []
```

- [ ] **Step 6: Run the QGIS tier**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q`
Expected: pure tests PASS; `test_plugin_loads` PASS. Then confirm the skip path: `.venv/bin/python -m pytest packages/nsgeo-qgis/tests -q` (no qgis) → the `qgis/` directory is skipped, pure tests pass.

- [ ] **Step 7: Dev link script and README**

Create `packages/nsgeo-qgis/scripts/dev_link.py`:

```python
"""Symlink nsgeo_qgis/ into the active QGIS profile's plugin directory.

Usage: python packages/nsgeo-qgis/scripts/dev_link.py [--profile NAME] [--remove]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PLUGIN_SRC = Path(__file__).resolve().parent.parent / "nsgeo_qgis"


def profile_plugins_dir(profile: str) -> Path:
    home = Path.home()
    if sys.platform.startswith("win"):
        base = Path(os.environ["APPDATA"]) / "QGIS" / "QGIS3"
    elif sys.platform == "darwin":
        base = home / "Library" / "Application Support" / "QGIS" / "QGIS3"
    else:
        base = home / ".local" / "share" / "QGIS" / "QGIS3"
    return base / "profiles" / profile / "python" / "plugins"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", default="default")
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()

    target = profile_plugins_dir(args.profile) / "nsgeo_qgis"
    if args.remove:
        if target.is_symlink():
            target.unlink()
            print(f"removed {target}")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not target.is_symlink():
        print(f"refusing: {target} exists and is not a symlink", file=sys.stderr)
        return 1
    if target.is_symlink():
        target.unlink()
    os.symlink(PLUGIN_SRC, target, target_is_directory=True)
    print(f"{target} -> {PLUGIN_SRC}")
    print("Enable 'nsgeo' in QGIS: Plugins > Manage and Install Plugins > Installed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `packages/nsgeo-qgis/README.md`:

````markdown
# nsgeo QGIS plugin

GPL-2.0-or-later. Consumes the MIT `nsgeo` core from `../nsgeo-core`; contains no
signal processing (a test enforces it).

## Development install

```bash
python packages/nsgeo-qgis/scripts/dev_link.py      # symlink into the QGIS profile
```

Then enable **nsgeo** in QGIS's plugin manager. The plugin finds the core source
through the symlink's real path; no `pip install` into QGIS's Python is needed.
Use the Plugin Reloader plugin after edits.

## Tests

Two tiers. `tests/pure` needs no QGIS and runs in the normal `.venv`. `tests/qgis`
needs the QGIS Python bindings and an offscreen display:

```bash
python3 -m venv --system-site-packages .venv-qgis     # from the interpreter QGIS uses
.venv-qgis/bin/pip install pytest
QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q
```

The `qgis/` directory skips itself when `qgis` is not importable.
````

Add `.venv-qgis/` to `.gitignore` under the Python section (next to `.venv/`).

- [ ] **Step 8: CI**

In `.github/workflows/ci.yml`, add to the `test` job after the core pytest line:

```yaml
      - run: python -m pytest packages/nsgeo-qgis/tests/pure -v
```

and add a new job:

```yaml
  plugin-qgis:
    runs-on: ubuntu-latest
    container: qgis/qgis:ltr
    env:
      QT_QPA_PLATFORM: offscreen
      QGIS_PREFIX_PATH: /usr
    steps:
      - uses: actions/checkout@v4
      - run: |
          python3 -m pip --version || (apt-get update && apt-get install -y python3-pip)
          python3 -m pip install --break-system-packages pytest
      - run: python3 -m pytest packages/nsgeo-qgis/tests -v
```

- [ ] **Step 9: Lint and commit**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: clean (accept `ruff format .` reflows). ruff's `N` rules are not enabled, so `initGui`/`classFactory` need no `noqa` — remove the `# noqa: N802` comments if ruff reports them as unused (`RUF100` is not enabled either, so either way is fine; be consistent and drop them).

```bash
git add packages/nsgeo-qgis .github/workflows/ci.yml .gitignore
git commit -m "feat: QGIS plugin skeleton with core path shim and offscreen test harness

classFactory plus a shim that finds the core in _vendor/ (release zip) or
the sibling source tree (dev symlink), so nothing is pip-installed into
QGIS's Python. A plugin boundary test forbids direct PyQt imports and any
use of nsgeo.processing beyond its public surface. Tests run in two
tiers: pure (normal matrix) and offscreen QGIS (.venv-qgis locally,
qgis/qgis:ltr container in CI)."
```

**Manual checkpoint (2 minutes):** `.venv/bin/python packages/nsgeo-qgis/scripts/dev_link.py`, start QGIS, enable nsgeo, confirm the toolbar appears and Plugins ▸ nsgeo ▸ About pushes a message naming both versions. If QGIS refuses to load the plugin, the error dialog shows the shim's message or a traceback; fix before continuing.

---

