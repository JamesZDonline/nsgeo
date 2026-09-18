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


def classFactory(iface: Any) -> Any:
    from nsgeo_qgis.plugin import NsgeoPlugin

    return NsgeoPlugin(iface)
