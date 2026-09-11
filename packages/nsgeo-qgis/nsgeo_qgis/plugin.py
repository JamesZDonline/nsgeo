"""The QGIS plugin object: builds the toolbar and docks, tears them down.

Holds no survey state; that is SiteSession. Owns the file dialogs and the
save-with-prompt flow, and hands dialog requests from the docks to the
dialog classes.

Signal/slot hazard: an exception raised inside a slot connected via
`connect()` never reaches whatever emitted the signal -- PyQt prints the
traceback to stderr and `emit()` returns as if the slot had succeeded. A
`QAction.triggered` slot (every toolbar action here) and a dock's request
signal are no exception. Every slot below that does real work -- the file
actions above all -- guards its own body and reports failure through
`message()` (which itself never raises: see its docstring) rather than let
a real-world failure (a full disk, a permissions error, a corrupt survey
file) disappear into stderr while the user is left thinking nothing
happened, or worse, that it succeeded.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import nsgeo
from nsgeo.project import ProjectError
from nsgeo.velocity import VelocityModel
from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction, QDialog, QFileDialog, QMessageBox

from nsgeo_qgis import plugin_version
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.maptools.digitise_tool import DigitiseGridTool
from nsgeo_qgis.session import SURVEY_FILE, SiteSession
from nsgeo_qgis.ui.grid_dialog import GridDialog
from nsgeo_qgis.ui.survey_dock import SurveyDock

MENU = "&nsgeo"


class NsgeoPlugin:
    def __init__(self, iface: Any) -> None:
        self.iface = iface
        self.toolbar: Any = None
        # Menu actions need `iface.removePluginMenu` on unload; toolbar
        # actions live only on `self.toolbar` and just need deleteLater().
        # Keeping them apart matters: removePluginMenu on an action that
        # was never added to the menu raises, which would abort unload()
        # partway through and leak everything after it.
        self.menu_actions: list[QAction] = []
        self.toolbar_actions: list[QAction] = []
        self.docks: list[Any] = []
        self.session: SiteSession | None = None
        self.layers: SiteLayers | None = None
        self.survey_dock: SurveyDock | None = None
        self.act_new: QAction | None = None
        self.act_open: QAction | None = None
        self.act_save: QAction | None = None
        self.act_add_grid: QAction | None = None
        self.act_import: QAction | None = None

    # ---- QGIS entry points ------------------------------------------------
    def initGui(self) -> None:  # noqa: N802
        self.session = SiteSession()
        # Constructed now, before any new_site()/open_site() the user could
        # ever trigger, so it is connected before the first site_opened
        # fires (Task 8's requirement) rather than missing it.
        self.layers = SiteLayers(self.session)
        main = self.iface.mainWindow()

        self.toolbar = self.iface.addToolBar("nsgeo")
        self.toolbar.setObjectName("nsgeoToolBar")
        self.act_new = self._toolbar_action("New site…", self.new_site)
        self.act_open = self._toolbar_action("Open site…", self.open_site)
        self.act_save = self._toolbar_action("Save site", self.save_with_prompt)
        self.toolbar.addSeparator()
        self.act_add_grid = self._toolbar_action("Add grid…", lambda: self.open_grid_dialog(None))
        self.act_import = self._toolbar_action("Import DZT…", lambda: self.open_import_dialog(None))

        about = QAction("About nsgeo", main)
        about.triggered.connect(self.show_about)
        self.iface.addPluginToMenu(MENU, about)
        self.menu_actions.append(about)

        self.survey_dock = SurveyDock(self.session, main)
        self.survey_dock.add_grid_requested.connect(lambda: self.open_grid_dialog(None))
        self.survey_dock.edit_grid_requested.connect(self.open_grid_dialog)
        self.survey_dock.import_requested.connect(self.open_import_dialog)
        self.survey_dock.grid_velocity_requested.connect(self.open_grid_dialog)
        self.survey_dock.line_velocity_requested.connect(self.open_velocity_dialog)
        self.iface.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.survey_dock)
        self.docks.append(self.survey_dock)
        self._update_enabled()
        self.session.site_opened.connect(self._update_enabled)
        self.session.site_closed.connect(self._update_enabled)

    def unload(self) -> None:
        # QGIS cannot be told "no" here -- the plugin is unloading
        # regardless of what save_with_prompt() returns -- so there is no
        # Cancel option: offering one would be a button that cannot do
        # what it says (see save_with_prompt()'s docstring). Save or
        # Discard only; if the user chooses Save and it then fails, say
        # so explicitly, since save_with_prompt()'s own failure message
        # does not mention that the data is about to be lost anyway.
        if (
            self.session is not None
            and self.session.dirty
            and not self.save_with_prompt(ask_first=True, allow_cancel=False)
        ):
            self.message(
                "could not save changes before unloading; unsaved changes will be lost",
                Qgis.MessageLevel.Critical,
            )
        for dock in self.docks:
            self.iface.removeDockWidget(dock)
            dock.deleteLater()
        self.docks.clear()
        self.survey_dock = None
        for action in self.menu_actions:
            self.iface.removePluginMenu(MENU, action)
            action.deleteLater()
        self.menu_actions.clear()
        for action in self.toolbar_actions:
            action.deleteLater()
        self.toolbar_actions.clear()
        self.act_new = None
        self.act_open = None
        self.act_save = None
        self.act_add_grid = None
        self.act_import = None
        if self.toolbar is not None:
            self.toolbar.setParent(None)
            self.toolbar.deleteLater()
            self.toolbar = None
        if self.layers is not None:
            self.layers.detach()
            self.layers = None
        self.session = None

    # ---- helpers ----------------------------------------------------------
    def _toolbar_action(self, text: str, slot: Any) -> QAction:
        action = QAction(text, self.iface.mainWindow())
        action.triggered.connect(slot)
        self.toolbar.addAction(action)
        self.toolbar_actions.append(action)
        return action

    def _update_enabled(self) -> None:
        try:
            is_open = self.session is not None and self.session.is_open
            for act in (self.act_save, self.act_add_grid, self.act_import):
                if act is not None:
                    act.setEnabled(is_open)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not update the toolbar: {exc}", Qgis.MessageLevel.Warning)

    def message(self, text: str, level: Any = None, title: str = "nsgeo") -> None:
        """Tell the user something through the message bar, and log it too
        so it survives after the bar's message auto-dismisses. Deliberately
        the one silent catch in this file: this is the last resort for
        reporting every other failure, so a failure in the reporting path
        itself has nowhere further to go."""
        level = level if level is not None else Qgis.MessageLevel.Info
        try:
            QgsMessageLog.logMessage(text, "nsgeo", level)
            self.iface.messageBar().pushMessage(title, text, level, 6)
        except Exception:  # noqa: BLE001 -- see the docstring above
            pass

    def show_about(self) -> None:
        self.message(f"plugin {plugin_version()} · core {nsgeo.__version__}")

    # ---- site files -------------------------------------------------------
    def new_site(self) -> None:
        assert self.session is not None
        if self.session.dirty and not self.save_with_prompt(ask_first=True):
            return
        folder = QFileDialog.getExistingDirectory(
            self.iface.mainWindow(), "Choose an empty folder for the site"
        )
        if not folder:
            return
        try:
            self.session.new_site(Path(folder))
        except Exception as exc:  # noqa: BLE001 -- see the module docstring:
            # new_site() only installs the site after a successful write
            # (ProjectError for a bad folder, but also a plain OSError for
            # e.g. a read-only filesystem), so the session is untouched
            # either way; this is the only chance to tell the user why
            # nothing happened.
            self.message(f"could not create the new site: {exc}", Qgis.MessageLevel.Critical)

    def open_site(self) -> None:
        assert self.session is not None
        if self.session.dirty and not self.save_with_prompt(ask_first=True):
            return
        path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            "Open a survey file",
            "",
            f"nsgeo survey ({SURVEY_FILE});;All files (*)",
        )
        if not path:
            return
        try:
            self.session.open_site(Path(path))
        except Exception as exc:  # noqa: BLE001 -- see new_site() above; a
            # malformed survey file or an unreadable/corrupt referenced DZT
            # can raise ProjectError, DztError, or a plain OSError, none of
            # which install a session (open_site() only installs after
            # load_site() fully succeeds).
            self.message(f"could not open {path}: {exc}", Qgis.MessageLevel.Critical)

    def save_with_prompt(self, *, ask_first: bool = False, allow_cancel: bool = True) -> bool:
        """Save the site. Returns True when the caller may proceed (saved,
        or the user chose to discard). Handles the out-of-tree opt-in.

        Every path that can fail returns False rather than raising: this is
        a QAction.triggered slot, so an uncaught exception here would be
        swallowed by Qt (see the module docstring), and New/Open/unload all
        treat True as "safe to discard the dirty site" -- a failed save
        must never look like one that succeeded.

        `allow_cancel=False` (unload()'s case) drops Cancel from the
        button set entirely rather than showing it and ignoring the
        answer: QGIS cannot be told not to unload the plugin, so a button
        that cannot do what it says must not be offered. new_site() and
        open_site() can genuinely abort their own action, so they keep
        the default of True.
        """
        assert self.session is not None
        if not self.session.is_open:
            return True
        if ask_first:
            buttons = QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            if allow_cancel:
                buttons |= QMessageBox.StandardButton.Cancel
            answer = QMessageBox.question(
                self.iface.mainWindow(),
                "Unsaved changes",
                "Save the site before continuing?",
                buttons,
            )
            if allow_cancel and answer == QMessageBox.StandardButton.Cancel:
                return False
            if answer == QMessageBox.StandardButton.Discard:
                return True
        try:
            self.session.save()
            return True
        except ProjectError as exc:
            if "allow_absolute" not in str(exc):
                self.message(str(exc), Qgis.MessageLevel.Critical)
                return False
            answer = QMessageBox.question(
                self.iface.mainWindow(),
                "Files outside the site folder",
                "Some survey files live outside the site folder. Record them by absolute path?\n"
                "The survey file will then only open on machines with the same mount points.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
            try:
                self.session.save(allow_absolute=True)
                return True
            except Exception as exc2:  # noqa: BLE001 -- see the docstring above
                self.message(f"could not save the site: {exc2}", Qgis.MessageLevel.Critical)
                return False
        except Exception as exc:  # noqa: BLE001 -- disk full, permissions,
            # etc.; see the docstring above.
            self.message(f"could not save the site: {exc}", Qgis.MessageLevel.Critical)
            return False

    # ---- dialogs (provided by later tasks) --------------------------------
    def open_grid_dialog(self, grid_id: str | None) -> None:
        assert self.session is not None
        if not self.session.is_open:
            return
        try:
            grid = self.session.grid(grid_id) if grid_id else None
        except KeyError as exc:
            # edit_grid_requested/grid_velocity_requested carry a grid id
            # captured when a context menu was built; it is stale if the
            # grid was removed by then. This is a QAction.triggered-style
            # slot (see the module docstring), so this must not raise.
            self.message(str(exc), Qgis.MessageLevel.Critical)
            return
        suggestion = None
        if grid is None:
            lines = self.session.site.lines if self.session.site else []
            if lines:
                try:
                    suggestion = VelocityModel.from_dielectric(
                        lines[0].header.epsr
                    ).surface_velocity
                except ValueError as exc:
                    # Cosmetic only -- a bad header must not block the
                    # dialog from opening at all, just leave it unseeded.
                    self.message(
                        f"could not suggest a velocity from the header: {exc}",
                        Qgis.MessageLevel.Warning,
                    )
        dialog = GridDialog(
            self.session, grid=grid, suggested_velocity=suggestion, parent=self.iface.mainWindow()
        )
        try:
            dialog.digitise_requested.connect(lambda: self._start_digitise(dialog))
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            result = dialog.result_grid()
            try:
                if grid is None:
                    self.session.add_grid(result)
                else:
                    self.session.replace_grid(result)
            except (ValueError, KeyError) as exc:
                self.message(str(exc), Qgis.MessageLevel.Critical)
        finally:
            # Fix round 2, Finding 4: dialog.exec() can return (accept,
            # reject, or the window closed outright) while a digitise
            # pick is still in progress -- the dialog is hidden and the
            # map tool active, with neither done() nor the tool's
            # cancelled signal ever having fired to release it. Left
            # alone, that tool would later call back into show_dialog()
            # (a click, a switch to another tool) against a `dialog`
            # this method is about to delete, raising RuntimeError out
            # of a signal-connected slot.
            canvas = self.iface.mapCanvas()
            tool = canvas.mapTool()
            if isinstance(tool, DigitiseGridTool):
                # unsetMapTool() -> deactivate() -> cancelled ->
                # show_dialog() would otherwise re-show `dialog` --
                # already accepted or rejected here, and about to be
                # deleteLater()'d below regardless -- for one event-loop
                # turn before its own deletion actually runs (round 3,
                # Finding 3). blockSignals() lets deactivate()'s own
                # cleanup (releasing the rubber band) run without
                # re-triggering show_dialog().
                tool.blockSignals(True)
                canvas.unsetMapTool(tool)
            # Fix round 1, Finding 3: `dialog` is parented to the main
            # window and nothing ever deleted it, so every grid dialog
            # opened stayed alive (with its full widget tree) for the
            # life of the QGIS session -- harmless for one dialog, but a
            # segfault at interpreter shutdown once enough of them pile
            # up alongside a QgsMapCanvas/QgsRubberBand from the digitise
            # flow (verified with gdb). deleteLater() only schedules the
            # deletion; `dialog` is still perfectly usable above, before
            # this runs.
            dialog.deleteLater()

    def _start_digitise(self, dialog: GridDialog) -> None:
        canvas = self.iface.mapCanvas()
        tool = DigitiseGridTool(canvas)

        def show_dialog() -> None:
            dialog.show()
            dialog.raise_()

        def done(origin: Any, along: Any) -> None:
            # `done` is a slot on tool.points_picked (a pyqtSignal): an
            # uncaught exception here would be swallowed by Qt (see the
            # module docstring) and leave the map tool stuck active with
            # the dialog hidden and no explanation -- e.g. a fast
            # double-click that reads as two coincident canvasClicked
            # events, which set_digitised() now rejects. The finally
            # clause guarantees control always comes back to the dialog
            # regardless of what failed.
            try:
                dialog.set_digitised((origin.x(), origin.y()), (along.x(), along.y()))
                dialog.crs_widget.setCrs(canvas.mapSettings().destinationCrs())
            except Exception as exc:  # noqa: BLE001 -- see the module docstring
                self.message(
                    f"could not use the digitised points: {exc}", Qgis.MessageLevel.Critical
                )
            finally:
                canvas.unsetMapTool(tool)
                show_dialog()

        tool.points_picked.connect(done)
        # A right-click (QGIS's universal "abort this tool" gesture) or
        # switching to a different map tool entirely both abandon the
        # pick without completing it. Before, neither restored the
        # dialog: it stayed hidden with its exec() loop still running,
        # and the user's only way out was killing QGIS (Task 10 fix
        # round 1, Finding 4). DigitiseGridTool emits `cancelled` from
        # deactivate() for exactly this case, and by then the canvas has
        # already moved off this tool, so only the dialog needs restoring
        # here -- unlike `done()` above, which must still release the
        # tool itself.
        tool.cancelled.connect(show_dialog)
        dialog.hide()
        canvas.setMapTool(tool)

    def open_import_dialog(self, grid_id: str | None) -> None:
        self.message("Import dialog arrives in a later task.", Qgis.MessageLevel.Warning)

    def open_velocity_dialog(self, key: str) -> None:
        self.message("Velocity dialog arrives in a later task.", Qgis.MessageLevel.Warning)
