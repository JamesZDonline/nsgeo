"""One place to log a message under the plugin's `QgsMessageLog` tag.

`nsgeo_qgis.ui.survey_dock` (Task 9) and `nsgeo_qgis.ui.profile_view` (Task 14)
each guard Qt-invoked slots and virtual-method overrides the same way (see
either module's docstring for why): catch broadly, report through
`QgsMessageLog` rather than let PyQt swallow the exception silently. Both
had the identical two-line function inline; a third dock (Task 15) would
make three copies of the same body, so it lives here instead.
"""

from __future__ import annotations

from qgis.core import Qgis, QgsMessageLog


def log(message: str, level: Qgis.MessageLevel = Qgis.MessageLevel.Warning) -> None:
    QgsMessageLog.logMessage(message, "nsgeo", level)
