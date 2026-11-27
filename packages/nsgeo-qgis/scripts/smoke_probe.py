"""Smoke probe: run inside a real QGIS through ``qgis --code``.

Checks that the installed nsgeo_qgis zip loads from its own bundled core and
that QGIS's own installer accepts its metadata, then that unloading it takes
its docks and toolbar away. Writes a JSON object of named
checks to $NSGEO_SMOKE_OUT and exits 0 only when every check is true.
"""

import json
import os
import traceback

from qgis.PyQt.QtCore import QTimer

DOCKS = ("nsgeo Survey", "nsgeo Profile", "nsgeo Processing", "nsgeo Slices")


def _under(path, parent):
    path = os.path.realpath(path)
    parent = os.path.realpath(parent)
    return os.path.commonpath([path, parent]) == parent


def _run():
    out = {}
    try:
        from pyplugin_installer.installer_data import plugins as installer_plugins
        from qgis.core import Qgis, QgsApplication
        from qgis.PyQt.QtWidgets import QDockWidget, QToolBar
        from qgis.utils import iface, loadPlugin, startPlugin, unloadPlugin

        out["qgis"] = Qgis.QGIS_VERSION
        profile = QgsApplication.qgisSettingsDirPath()
        plugin_dir = os.path.join(profile, "python", "plugins", "nsgeo_qgis")

        info = installer_plugins.getInstalledPlugin("nsgeo_qgis", path=plugin_dir, readOnly=False)
        out["installer_accepts"] = info["error"] == ""
        out["installer_error_details"] = info.get("error_details", "")

        out["loads"] = loadPlugin("nsgeo_qgis") is True
        out["starts"] = startPlugin("nsgeo_qgis") is True

        import nsgeo
        import nsgeo_qgis

        out["plugin_file"] = nsgeo_qgis.__file__
        out["core_file"] = nsgeo.__file__
        out["plugin_from_profile"] = _under(nsgeo_qgis.__file__, plugin_dir)
        out["core_from_vendor"] = _under(nsgeo.__file__, os.path.join(plugin_dir, "_vendor"))
        out["build_label"] = nsgeo_qgis.build_label()
        out["stamped"] = out["build_label"].startswith("build ")

        window = iface.mainWindow()
        titles = {d.windowTitle() for d in window.findChildren(QDockWidget)}
        out["docks"] = all(t in titles for t in DOCKS)
        out["toolbar"] = any(
            t.objectName() == "nsgeoToolBar" for t in window.findChildren(QToolBar)
        )
        out["unload_returns"] = unloadPlugin("nsgeo_qgis") is True
    except Exception:
        out["error"] = traceback.format_exc()
        _finish(out)
        return
    # The docks are deleteLater()'d: look again once the event loop has run.
    QTimer.singleShot(500, lambda: _after_unload(out))


def _after_unload(out):
    try:
        from qgis.PyQt.QtWidgets import QDockWidget, QToolBar
        from qgis.utils import iface

        window = iface.mainWindow()
        titles = {d.windowTitle() for d in window.findChildren(QDockWidget)}
        out["docks_left"] = sorted(t for t in DOCKS if t in titles)
        toolbar_left = any(t.objectName() == "nsgeoToolBar" for t in window.findChildren(QToolBar))
        out["unloads"] = (
            out.get("unload_returns") is True and not out["docks_left"] and not toolbar_left
        )
    except Exception:
        out["error"] = traceback.format_exc()
    _finish(out)


def _finish(out):
    checks = (
        "installer_accepts",
        "loads",
        "starts",
        "plugin_from_profile",
        "core_from_vendor",
        "stamped",
        "docks",
        "toolbar",
        "unloads",
    )
    ok = "error" not in out and all(out.get(c) is True for c in checks)
    out["ok"] = ok
    with open(os.environ["NSGEO_SMOKE_OUT"], "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    os._exit(0 if ok else 1)


QTimer.singleShot(3000, _run)
