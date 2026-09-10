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
    def initGui(self) -> None:
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
