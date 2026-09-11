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

Modal-dialog hazard: QDialog.exec()'s event loop is application-modal --
it terminates the instant the dialog is hidden, from *any* cause, not only
its own Ok/Cancel buttons (verified directly: a bare QDialog.exec() with a
QTimer calling hide() returns immediately, before anything else runs). Any
dialog whose flow needs the user to interact with something else first --
GridDialog's digitise-on-map tab needs the canvas -- cannot be opened with
exec() at all: hiding it to reach the canvas would silently end the exec()
call in the same turn (Task 10 fix round 4, Finding 1 -- this shipped
undetected through three earlier review rounds because the test double for
exec(), used everywhere, does not run a real event loop and so cannot
observe this). open_grid_dialog() below is the pattern for a dialog like
that: show() instead of exec(), lifecycle (committing the result, tearing
down any state the dialog armed, deleteLater()) moved onto dialog.finished
rather than living after a blocking call, and a single `self._grid_dialog`
tracking slot so a second one isn't opened on top of the first.

Task 11's ImportDialog copies the same show()/finished pattern
(`self._import_dialog`) even though nothing in its own flow needs the
canvas or anything else mid-dialog: an application-modal exec() would have
blocked the toolbar and dock for as long as it was open, which would have
been a real (if accidental) way to avoid the races below rather than one
this plugin actually chose. Modeless is the one pattern this plugin uses
for every dialog, so a stray exec() staying modal by oversight is not a
failure mode reachable here -- and modeless does mean the site can be
closed or replaced, or the very grid an open import is targeting can be
removed (the dock's "Remove grid" has no guard against an import in
flight), before Import is clicked. ImportDialog's own accept() re-checks
all three before writing anything (see its module docstring) rather than
lean on exec() to make them unreachable.
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
from nsgeo_qgis.loader import LineLoader
from nsgeo_qgis.maptools.digitise_tool import DigitiseGridTool
from nsgeo_qgis.session import SURVEY_FILE, SiteSession
from nsgeo_qgis.ui.grid_dialog import GridDialog
from nsgeo_qgis.ui.import_dialog import ImportDialog
from nsgeo_qgis.ui.profile_dock import ProfileDock
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
        self.loader: LineLoader | None = None
        self.survey_dock: SurveyDock | None = None
        self.profile_dock: ProfileDock | None = None
        self.act_new: QAction | None = None
        self.act_open: QAction | None = None
        self.act_save: QAction | None = None
        self.act_add_grid: QAction | None = None
        self.act_import: QAction | None = None
        self._grid_dialog: GridDialog | None = None
        self._import_dialog: ImportDialog | None = None

    # ---- QGIS entry points ------------------------------------------------
    def initGui(self) -> None:  # noqa: N802
        self.session = SiteSession()
        # Constructed now, before any new_site()/open_site() the user could
        # ever trigger, so it is connected before the first site_opened
        # fires (Task 8's requirement) rather than missing it.
        self.layers = SiteLayers(self.session)
        self.loader = LineLoader(
            self.session,
            on_error=lambda key, msg: self.message(f"{key}: {msg}", Qgis.MessageLevel.Critical),
        )
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

        self.profile_dock = ProfileDock(self.session, main)
        self.profile_dock.error.connect(lambda msg: self.message(msg, Qgis.MessageLevel.Warning))
        self.iface.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.profile_dock)
        self.docks.append(self.profile_dock)

        self._update_enabled()
        self.session.site_opened.connect(self._update_enabled)
        self.session.site_closed.connect(self._update_enabled)

    def unload(self) -> None:
        # Fix round 4, Finding 1: GridDialog is modeless (see
        # open_grid_dialog()), so -- unlike the old application-modal
        # exec() it replaced -- unload() can now run while one is still
        # open. reject() runs finished()'s own cleanup (releasing a
        # still-active digitise tool, deleteLater()) via the same path
        # as a normal Cancel, rather than leaving the dialog dangling
        # with a reference to a session this method is about to tear
        # down below.
        #
        # Fix round 5, Finding 1: not close(). QDialog.closeEvent only
        # calls reject() when the dialog isVisible() -- on a hidden one
        # it just accepts the close event and finished() never fires at
        # all (verified directly: hidden + close() -> 0 finished
        # emissions; hidden + reject() -> 1). _start_digitise() hides
        # the dialog deliberately, so "hidden mid-pick" is this
        # feature's ordinary state, not an edge case -- unload() must
        # work in exactly the state its own feature creates.
        if self._grid_dialog is not None:
            self._grid_dialog.reject()
        # Same reasoning as GridDialog just above: ImportDialog is
        # modeless too, so it can still be open here, and reject() (not
        # close(), for the same hidden-dialog reason) is what runs its
        # finished-signal cleanup instead of leaving it dangling with a
        # reference to a session this method is about to tear down.
        if self._import_dialog is not None:
            self._import_dialog.reject()
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
        self.profile_dock = None
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
        # Not cancelled: a QgsTask has no way to interrupt a blocking disk
        # read partway through, and LineLoader keeps every submitted task
        # referenced (its own `_pending`) until it actually finishes, so
        # dropping this plugin's reference here does not abandon an
        # in-flight load -- it completes and reports through the same
        # finished() path as always, just with the site-identity check
        # there almost certainly finding a different (or no) site open by
        # then and declining to write anywhere (see loader.py).
        self.loader = None
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
        # Fix round 4, Finding 1 (critical): GridDialog must be
        # modeless. QDialog.exec()'s application-modal event loop
        # terminates the instant the dialog is hidden -- verified
        # directly: a bare QDialog.exec() with a QTimer calling hide()
        # returns 0 in the same turn. _start_digitise()'s dialog.hide()
        # (called from a slot that only fires *while* exec() would be
        # running) would therefore end the modal loop before the user
        # could click the canvas even once -- "digitise on map" could
        # never actually work under a real event loop. show() instead
        # of exec() means the rest of this method's old post-exec()
        # logic (commit the result, release a still-active digitise
        # tool, dispose the dialog) can no longer run synchronously
        # after a blocking call; it lives in finished() below instead,
        # which fires exactly once for accept, reject, or the window
        # closed any other way.
        assert self.session is not None
        if not self.session.is_open:
            return
        if self._grid_dialog is not None:
            # Modeless means the toolbar and dock stay clickable while
            # one is already open, unlike the old exec()'s
            # application-modal block. Only one at a time: a second
            # would fight the first over the canvas's one map tool
            # during a digitise pick.
            #
            # Fix round 5, Finding 5: show() too, not just raise_()/
            # activateWindow() -- _start_digitise() hides the dialog
            # deliberately while a pick is in progress, and raising a
            # hidden window activates nothing visible. Without this,
            # re-triggering "Add grid" mid-pick was a silent no-op: no
            # window, no message.
            self._grid_dialog.show()
            self._grid_dialog.raise_()
            self._grid_dialog.activateWindow()
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
        # Fix round 5, Finding 2: modeless means the toolbar stays
        # clickable while the dialog is open, so the site it was opened
        # against can close or be replaced by a different one before OK
        # is clicked -- impossible under the old modal exec(), which
        # blocked the toolbar entirely. json_path identifies which site
        # session.site.grids/add_grid/replace_grid would actually act on.
        opened_against = self.session.json_path

        def finished(result: int) -> None:
            # `finished` is a slot on dialog.finished (a pyqtSignal): an
            # uncaught exception here would be swallowed by Qt (see the
            # module docstring), same hazard as everywhere else in this
            # file.
            try:
                if result == QDialog.DialogCode.Accepted:
                    if not self.session.is_open:
                        # session.add_grid/replace_grid would raise
                        # ProjectError ("no site is open") here, which
                        # is not in the except below and has no outer
                        # handler -- it would escape this slot to
                        # stderr with an empty message bar, and the
                        # dialog would still close as if the grid had
                        # been saved.
                        self.message(
                            f"no site is open; grid {dialog.id_edit.text().strip()!r} "
                            "was not saved",
                            Qgis.MessageLevel.Critical,
                        )
                    elif self.session.json_path != opened_against:
                        # A *different* site opened under the dialog --
                        # not caught by the ValueError/KeyError below at
                        # all, since it is session.grids that changed
                        # meaning, not this grid's id: it could define
                        # its own grid with the same id as the one this
                        # dialog was editing, which would otherwise be
                        # silently overwritten with this dialog's
                        # geometry with no error whatsoever.
                        self.message(
                            "a different site was opened while the grid dialog was "
                            f"open; grid {dialog.id_edit.text().strip()!r} was not saved",
                            Qgis.MessageLevel.Critical,
                        )
                    else:
                        new_grid = dialog.result_grid()
                        try:
                            if grid is None:
                                self.session.add_grid(new_grid)
                            else:
                                self.session.replace_grid(new_grid)
                        except (ValueError, KeyError) as exc:
                            self.message(str(exc), Qgis.MessageLevel.Critical)
            finally:
                # Fix round 2, Finding 4 (still applies to a modeless
                # dialog): finished() can fire while a digitise pick is
                # still in progress -- the map tool active, with
                # neither done() nor the tool's cancelled signal ever
                # having fired to release it. Left alone, that tool
                # would later call back into show_dialog() (a click, a
                # switch to another tool) against a `dialog` about to
                # be deleted, raising RuntimeError out of a
                # signal-connected slot.
                canvas = self.iface.mapCanvas()
                tool = canvas.mapTool()
                if isinstance(tool, DigitiseGridTool):
                    # unsetMapTool() -> deactivate() -> cancelled ->
                    # show_dialog() would otherwise re-show `dialog` --
                    # already finished here, and about to be
                    # deleteLater()'d below regardless -- for one
                    # event-loop turn before its own deletion actually
                    # runs (round 3, Finding 3). blockSignals() lets
                    # deactivate()'s own cleanup (releasing the rubber
                    # band) run without re-triggering show_dialog().
                    tool.blockSignals(True)
                    canvas.unsetMapTool(tool)
                # Fix round 1, Finding 3: `dialog` is parented to the
                # main window and nothing else ever deleted it, so
                # every grid dialog opened stayed alive (with its full
                # widget tree) for the life of the QGIS session --
                # harmless for one dialog, but a segfault at
                # interpreter shutdown once enough of them pile up
                # alongside a QgsMapCanvas/QgsRubberBand from the
                # digitise flow (verified with gdb).
                dialog.deleteLater()
                self._grid_dialog = None

        def clear_if_current() -> None:
            # Fix round 5, Finding 6: `finished` above is the only path
            # that is *expected* to clear self._grid_dialog, but if the
            # dialog were ever destroyed some other way (probed
            # directly: setParent(None) + deleteLater() bypasses
            # finished() entirely), the tracker would stay stale --
            # unload() would then call reject() on an already-deleted
            # C++ object (RuntimeError), and every later "Add grid"
            # would wedge forever calling show()/raise_() on it (Finding
            # 5's fix above). destroyed() fires from the QObject
            # destructor itself, after the C++ side is gone, so this
            # must not touch `dialog` at all -- only compare Python
            # object identity. The `is` check matters: by the time this
            # object is actually destroyed, self._grid_dialog may
            # already point to a newer dialog opened in between (this
            # one's own deleteLater() above is itself deferred), and
            # clearing unconditionally would wedge *that* one instead.
            if self._grid_dialog is dialog:
                self._grid_dialog = None

        dialog.finished.connect(finished)
        dialog.destroyed.connect(clear_if_current)
        dialog.digitise_requested.connect(lambda: self._start_digitise(dialog))
        self._grid_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

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
        # pick without completing it. Before round 1's fix, neither
        # restored the dialog, and the user's only way out was killing
        # QGIS (Task 10 fix round 1, Finding 4). DigitiseGridTool emits
        # `cancelled` from deactivate() for exactly this case, and by
        # then the canvas has already moved off this tool, so only the
        # dialog needs restoring here -- unlike `done()` above, which
        # must still release the tool itself.
        tool.cancelled.connect(show_dialog)
        # dialog.hide() here is exactly what a modal exec() could never
        # survive (round 4, Finding 1): hiding the dialog that owns the
        # running exec() loop ends that loop immediately. GridDialog is
        # modeless now (see open_grid_dialog()), so this is an ordinary
        # hide -- the canvas stays interactive and the user can actually
        # click it.
        dialog.hide()
        canvas.setMapTool(tool)

    def open_import_dialog(self, grid_id: str | None) -> None:
        # Modeless -- see the module docstring and open_grid_dialog() above,
        # whose shape this copies: single-instance tracking on
        # self._import_dialog, lifecycle on dialog.finished rather than
        # after a blocking exec(), deleteLater() plus a destroyed() guard
        # against a dialog torn down some other way.
        assert self.session is not None
        if not self.session.is_open:
            return
        if not (self.session.site and self.session.site.grids):
            self.message("Add a grid before importing lines.", Qgis.MessageLevel.Warning)
            return
        if self._import_dialog is not None:
            self._import_dialog.show()
            self._import_dialog.raise_()
            self._import_dialog.activateWindow()
            return
        dialog = ImportDialog(self.session, grid_id=grid_id, parent=self.iface.mainWindow())

        def finished(result: int) -> None:
            # `finished` is a slot on dialog.finished (a pyqtSignal): an
            # uncaught exception here would be swallowed by Qt (see the
            # module docstring). ImportDialog.accept() already did the
            # actual session write (and its own identity/grid re-checks --
            # see its module docstring) before emitting Accepted, so there
            # is nothing left to guard here beyond reporting the count.
            try:
                if result == QDialog.DialogCode.Accepted:
                    self.message(f"imported {len(dialog.imported_keys)} line(s)")
            finally:
                dialog.deleteLater()
                self._import_dialog = None

        def clear_if_current() -> None:
            # Same reasoning as open_grid_dialog()'s clear_if_current: only
            # compare identity, never touch `dialog` (already gone by the
            # time destroyed() fires), and only clear the tracker if it
            # still points at *this* dialog.
            if self._import_dialog is dialog:
                self._import_dialog = None

        dialog.finished.connect(finished)
        dialog.destroyed.connect(clear_if_current)
        self._import_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def open_velocity_dialog(self, key: str) -> None:
        self.message("Velocity dialog arrives in a later task.", Qgis.MessageLevel.Warning)
