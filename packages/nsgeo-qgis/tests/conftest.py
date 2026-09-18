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
