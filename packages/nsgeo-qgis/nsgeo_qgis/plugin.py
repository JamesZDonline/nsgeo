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
GridDialog's Pick buttons need the canvas -- cannot be opened with exec()
at all: hiding it to reach the canvas would silently end the exec() call
in the same turn (Task 10 fix round 4, Finding 1 -- this shipped
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

import contextlib
import dataclasses
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nsgeo
import numpy as np
from nsgeo.geometry import Grid
from nsgeo.model import is_cut_key
from nsgeo.processing import build_step, retime_ns, time_base_of
from nsgeo.project import ProjectError, line_key
from nsgeo.render import PercentileClip, UnipolarClip, colormap_names
from nsgeo.slices import plan_windows
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCsException,
    QgsMessageLog,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsSettings,
    QgsTemporalNavigationObject,
)
from qgis.gui import QgsMessageBarItem
from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QAction,
    QDialog,
    QFileDialog,
    QMenu,
    QMessageBox,
    QToolButton,
)

from nsgeo_qgis import build_label, own_colours, plugin_version
from nsgeo_qgis.cut_sections import CutSections
from nsgeo_qgis.export_flow import CountsClip, grid_preview, plain_export_error, site_preview
from nsgeo_qgis.export_style import write_style
from nsgeo_qgis.export_task import (
    ExportResult,
    ExportTask,
    WriterPlan,
    running_export,
    start_export,
)
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.loader import LineLoader
from nsgeo_qgis.lookup import CORNER_ROLES
from nsgeo_qgis.map_link import MapLink, crs_transform
from nsgeo_qgis.maptools.cut_tool import CutTool
from nsgeo_qgis.maptools.pick_tool import PickPointTool
from nsgeo_qgis.session import SURVEY_FILE, SiteSession
from nsgeo_qgis.site_export import (
    GeoTiffSiteWriter,
    apply_site_temporal_properties,
    band_window_ns,
    site_export_job,
)
from nsgeo_qgis.slice_export import (
    GeoTiffSliceWriter,
    apply_temporal_properties,
    coverage_path,
    cube_record,
    fit_temporal_navigation,
    grid_export_job,
    restore_band_times,
    save_cube_npz,
    window_ns,
)
from nsgeo_qgis.slice_layer import SITE_LAYER_NAME, SliceLayer, apply_smooth_resampling
from nsgeo_qgis.slices_plan import name_list, smallest_safe_cell
from nsgeo_qgis.ui.edit_lines_dialog import EditLinesDialog
from nsgeo_qgis.ui.export_dialog import ExportDialog
from nsgeo_qgis.ui.grid_dialog import GridDialog
from nsgeo_qgis.ui.import_dialog import ImportDialog
from nsgeo_qgis.ui.line_choice_dialog import LineChoiceDialog
from nsgeo_qgis.ui.processing_dock import ProcessingDock
from nsgeo_qgis.ui.profile_dock import ProfileDock, curve_param_name
from nsgeo_qgis.ui.slices_dock import CanvasDepthScroll, SlicesDock
from nsgeo_qgis.ui.survey_dock import SurveyDock
from nsgeo_qgis.ui.velocity_dialog import VelocityDialog

MENU = "&nsgeo"
VELOCITY_TIP = (
    "Velocity mode: click a diffraction hyperbola on the profile, apex first. "
    "Right-click a point to remove it."
)
VELOCITY_ON_CUT_TIP = (
    "Velocity fitting needs a recorded line: a cut at a slant widens hyperbolas "
    "and would give a wrong velocity."
)

OUTSIDE_TEXT = "Start a cut inside a grid."
TOO_FEW_TEXT = "A cut needs two different points."
CUT_HINT_TEXT = (
    "Cut: click to add points; right-click or Enter to finish; "
    "Backspace removes the last point; Esc cancels."
)
CUT_TIP = "Cut tool: draw a path on the map to see the cube's vertical section beneath it."

#: Where the one-shot "Slices has been tabbed onto Processing once" flag
#: lives, in the QGIS profile's own settings. See `_tabify_slices_dock`.
_TABIFIED_KEY = "nsgeo/slicesDockTabified"


@dataclass(frozen=True, eq=False)
class _ExportJob:
    """What an export hands the task and what it needs when the task ends."""

    spec: Any
    coverage_spec: Any
    writer_plan: WriterPlan
    n_bands: int
    #: Sets the Temporal Controller up on the added values layer.
    temporal: Callable[[Any], None]
    #: Included grids the site file does not hold, named in the success message.
    left_out: list[str]


def _norm_path(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _finish_with_pick_tool(tool: PickPointTool) -> None:
    """Release a PickPointTool nobody will use again.

    Final review, I4 (found on the two-click grid tool this one replaced):
    `unsetMapTool()` -- all any finaliser used to do -- frees neither the
    tool nor the canvas items it put in the canvas's `QGraphicsScene` (that
    tool's `QgsRubberBand` then, the snap marker now), so every pick would
    leave one more of each behind for the life of the QGIS session.
    `dispose()` takes the items back (see its docstring for why that cannot
    live in `deactivate()`); `deleteLater()` covers the tool itself, which
    `QgsMapTool` parents to the canvas.

    Idempotent and safe to call from any finaliser -- a pick's own ending
    (`_arm_pick`'s `end`) or the dialog's `finished` -- including more than
    once for the same tool: `dispose()` is idempotent on its own, and the
    `sip.isdeleted` guard is what makes a second `deleteLater()` on an
    already-destroyed C++ object a no-op rather than a RuntimeError out of
    a signal slot.

    Deliberately does not touch the canvas: `cancelled` is emitted from
    inside `deactivate()`, i.e. while the canvas is part-way through
    switching tools, so calling `unsetMapTool()` from there would
    re-enter it. Each caller unsets the tool itself, where that is the
    right thing to do.
    """
    if sip.isdeleted(tool):
        return
    tool.dispose()
    tool.deleteLater()


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
        self.map_link: Any = None
        self.survey_dock: SurveyDock | None = None
        self.profile_dock: ProfileDock | None = None
        self.processing_dock: ProcessingDock | None = None
        self.slices_dock: SlicesDock | None = None
        #: A cut's section, read from the Slices panel's cube (cut spec §4.3).
        self.cut_sections: CutSections | None = None
        #: Whether this session should still tab Slices onto Processing.
        #: Read from settings in `initGui`; see `_tabify_slices_dock`.
        self._want_tabify = False
        self.slice_layer: SliceLayer | None = None
        self.depth_scroll: CanvasDepthScroll | None = None
        self.act_new: QAction | None = None
        self.act_open: QAction | None = None
        self.act_save: QAction | None = None
        self.act_add_grid: QAction | None = None
        self.act_import: QAction | None = None
        self.act_pick: QAction | None = None
        self.act_velocity: QAction | None = None
        self.act_cut: QAction | None = None
        #: The Cut map tool while the toggle is on (cut spec §4.1).
        self._cut_tool: CutTool | None = None
        #: The toolbar's Panels button (the toolbar's own action for it)
        #: and the menu it drops down. See `_build_panels_menu`.
        self.act_panels: QAction | None = None
        self.panels_menu: QMenu | None = None
        self._grid_dialog: GridDialog | None = None
        #: The running map pick's instruction in the message bar, if any.
        #: Only one pick runs at a time (see `_arm_pick`).
        self._pick_message: QgsMessageBarItem | None = None
        self._import_dialog: ImportDialog | None = None
        self._edit_lines_dialogs: dict[str, EditLinesDialog] = {}
        self._line_choice_dialog: LineChoiceDialog | None = None
        # What the gain strip was last given, kept in lockstep with what it
        # actually displays -- the same shape ProcessingDock keeps
        # `_shown`/`_shown_step` in for the parameter form. `_gain_owner`
        # is the opaque token the strip compares (see `_sync_gain_strip`
        # for why it is (key, row, generation) and not the step itself);
        # `_gain_step` is the exact object a write must still find at that
        # row (see `_on_gain_points`).
        self._gain_owner: tuple[str, int, int] | None = None
        self._gain_step: Any = None
        self._gain_generation = 0
        #: Moves when the site closes or the plugin unloads, so an export that
        #: started on an earlier site knows it ended on another (`_finish_export`).
        self._export_epoch = 0

    # ---- QGIS entry points ------------------------------------------------
    def initGui(self) -> None:  # noqa: N802
        self.session = SiteSession()
        self._timed_layer_ids: list[str] = []
        # Every raster layer added to the project, whoever adds it (an export, a restore,
        # a project being opened, Layer > Add Raster Layer), gets its band times from its
        # own file; a project's own saved band times are whole seconds and lose bands.
        project = QgsProject.instance()
        project.layersAdded.connect(self._on_layers_added)
        project.readProject.connect(self._on_project_read)
        project.cleared.connect(self._forget_timed_layers)
        # The plugin enabled with a project already open: its layers are not "added" again.
        self._on_layers_added(list(project.mapLayers().values()))
        # Constructed now, before any new_site()/open_site() the user could
        # ever trigger, so it is connected before the first site_opened
        # fires (Task 8's requirement) rather than missing it.
        #
        # `on_info` puts the site-open report of followed picks on the message bar.
        self.layers = SiteLayers(
            self.session,
            on_info=lambda msg: self.message(msg, Qgis.MessageLevel.Info),
        )
        self.loader = LineLoader(
            self.session,
            on_error=lambda key, msg: self.message(f"{key}: {msg}", Qgis.MessageLevel.Critical),
        )
        # Constructed here, with `layers`, because it reads the `lines`
        # layer's geometry and must be connected before the first
        # site_opened fires -- same reason SiteLayers is built this early.
        self.map_link = MapLink(
            self.session,
            self.layers,
            self.iface.mapCanvas(),
            on_info=lambda msg: self.message(msg, Qgis.MessageLevel.Info),
        )
        main = self.iface.mainWindow()

        self.toolbar = self.iface.addToolBar("nsgeo")
        self.toolbar.setObjectName("nsgeoToolBar")
        self.act_new = self._toolbar_action("New site…", self.new_site)
        self.act_open = self._toolbar_action("Open site…", self.open_site)
        self.act_save = self._toolbar_action("Save site", self.save_with_prompt)
        self.toolbar.addSeparator()
        self.act_add_grid = self._toolbar_action("Add grid…", lambda: self.open_grid_dialog(None))
        self.act_import = self._toolbar_action("Import DZT…", self._import_from_toolbar)
        self.toolbar.addSeparator()
        self.act_pick = self._toolbar_action("Pick", self._toggle_pick_mode)
        self.act_pick.setCheckable(True)
        self.act_pick.setToolTip(
            "Pick mode: click the profile to author a pick. Shift+click works with this off."
        )
        self.act_velocity = self._toolbar_action("Velocity", self._toggle_velocity_fit_mode)
        self.act_velocity.setCheckable(True)
        self.act_velocity.setToolTip(VELOCITY_TIP)
        self.act_cut = self._toolbar_action("Cut", self._toggle_cut_tool)
        self.act_cut.setCheckable(True)
        self.act_cut.setToolTip(CUT_TIP)

        about = QAction("About nsgeo", main)
        about.triggered.connect(self.show_about)
        self.iface.addPluginToMenu(MENU, about)
        self.menu_actions.append(about)

        self.survey_dock = SurveyDock(self.session, main)
        self.survey_dock.add_grid_requested.connect(lambda: self.open_grid_dialog(None))
        self.survey_dock.edit_grid_requested.connect(self.open_grid_dialog)
        self.survey_dock.import_requested.connect(self.open_import_dialog)
        self.survey_dock.grid_velocity_requested.connect(self.open_grid_velocity_dialog)
        self.survey_dock.line_velocity_requested.connect(self.open_velocity_dialog)
        self.survey_dock.edit_lines_requested.connect(self.open_edit_lines_dialog)
        self.survey_dock.move_lines_requested.connect(self.move_lines)
        self.iface.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.survey_dock)
        self.docks.append(self.survey_dock)

        self.profile_dock = ProfileDock(self.session, main)
        self.profile_dock.error.connect(lambda msg: self.message(msg, Qgis.MessageLevel.Warning))
        self.profile_dock.pick_requested.connect(self._on_pick_requested)
        self.iface.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.profile_dock)
        self.docks.append(self.profile_dock)

        self.processing_dock = ProcessingDock(self.session, main)
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.processing_dock)
        self.docks.append(self.processing_dock)

        self.slices_dock = SlicesDock(self.session, main)
        self.slices_dock.error.connect(lambda msg: self.message(msg, Qgis.MessageLevel.Warning))
        self.slices_dock.choose_lines_requested.connect(self.open_line_choice_dialog)
        self.slices_dock.save_cube_requested.connect(self.save_cube)
        self.slices_dock.export_requested.connect(self.export_geotiff)
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.slices_dock)
        # Spec 9.2: tabified with Processing rather than a fourth dock
        # competing for screen space. Processing stays the raised tab --
        # this milestone adds a capability, it does not take the screen
        # away from the one people already use.
        #
        # Deferred to the event loop, and NOT done synchronously here:
        # QGIS restores its saved window layout AFTER loading plugins, so
        # a `tabifyDockWidget` called from `initGui()` is silently undone
        # before the user ever sees the window. Measured in a real QGIS
        # 3.44 on this repo's own profile: `tabifiedDockWidgets()` came
        # back empty for both docks at startup (the two panels stacked in
        # one column, as reported from the M11 walkthrough), while the
        # identical call made later, from a timer, tabbed them correctly.
        # Nothing shorter than "after the constructor returns" is
        # sufficient, and a zero-millisecond timer is exactly that.
        #
        # Once only, keyed in the profile's own settings: after the first
        # time, QGIS's restored layout IS the user's answer, and a plugin
        # that re-tabs on every start would overrule anyone who had
        # deliberately dragged the two apart.
        # Decided ONCE, here, and remembered for both attempts below: if
        # the settings flag were re-read inside the slot, the first
        # attempt would set it and the second would then decline to undo
        # QGIS's overwrite.
        self._want_tabify = not QgsSettings().value(_TABIFIED_KEY, False, type=bool)
        if self._want_tabify:
            # `initializationCompleted` is QGIS's own "startup is over"
            # signal, and restoring the saved window layout is part of
            # that startup -- measured in a real QGIS 3.44 on this repo's
            # profile: our tab was in place at 1.4 s, QGIS's restore wiped
            # it at 2.67 s (the main window resized in the same tick), and
            # `initializationCompleted` fired at 2.95 s. Hence the signal
            # and not a delay: any fixed timeout would be a guess at a
            # number that varies with the machine and the profile.
            self.iface.initializationCompleted.connect(self._tabify_slices_dock)
            # ... and the timer as well, for the OTHER way this plugin
            # gets loaded: enabled by hand from the Plugin Manager, with
            # QGIS long since initialised, `initializationCompleted` has
            # already fired and will never fire again. Nothing overwrites
            # the layout in that case, so this attempt is the one that
            # sticks.
            QTimer.singleShot(0, self._tabify_slices_dock)
        self.docks.append(self.slices_dock)
        self._build_panels_menu()

        # The active slice on the map: owned here (not by the dock) for
        # the same reason `map_link` and `layers` are -- it is a map
        # concern that outlives any one dock widget and is torn down
        # outside-in in `unload()`, before `self.layers.detach()`.
        self.slice_layer = SliceLayer(self.layers)
        # #180: the user's own colours, their edits remembered by the dock,
        # their "Current canvas" min/max read from this map view.
        self.slice_layer.own_style_changed.connect(self._on_own_style_changed)
        self.slice_layer.extent_in = self._canvas_extent_in
        self.slices_dock.symbology_requested.connect(self._open_slice_symbology)
        self.cut_sections = CutSections(self.session, self.slices_dock)
        self.profile_dock.set_cut_sections(self.cut_sections)
        self.map_link.set_sections(self.cut_sections)
        self.slices_dock.slice_changed.connect(self._on_slice_changed)
        self.slices_dock.window_changed.connect(self.profile_dock.set_slice_band)
        self.slices_dock.window_cleared.connect(self.profile_dock.clear_slice_band)
        self.profile_dock.set_cube_zero_lookup(self.slices_dock.line_zero_in_cube)
        self.depth_scroll = CanvasDepthScroll(self.iface.mapCanvas(), self.slices_dock)

        self.processing_dock.step_selected.connect(self._sync_gain_strip)
        self.processing_dock.step_selected.connect(self.profile_dock.set_selected_step)
        self.processing_dock.difference_toggled.connect(self.profile_dock.set_difference_index)
        self.profile_dock.difference_cleared.connect(
            lambda: self.processing_dock.diff_button.setChecked(False)
        )
        self.profile_dock.gain_points_changed.connect(self._on_gain_points)
        # ProcessingDock never reacts to line_loaded (only ProfileDock
        # does, to re-render), so a curve step selected before this line's
        # profiles arrive would otherwise stay exactly as
        # _sync_gain_strip last left it -- e.g. hidden for want of an axis
        # -- with nothing to re-check it once ProfileDock's own render
        # gives it one. Re-running _sync_gain_strip here on the same
        # signal ProfileDock re-renders from closes that gap.
        self.session.line_loaded.connect(self._resync_gain_strip)
        # Walkthrough round 2, W8: the same shape of gap as the gain strip
        # just above, for the profile band. The band is a property of the
        # SLICE, not of the line, but it lives in `ProfileView` state that
        # `clear()` resets on `line_opened("")` -- and `window_changed`
        # only fires when the window CHANGES, which it has not. Connected
        # AFTER `ProfileDock`'s own `line_opened` slot (that dock is built
        # earlier in this method, and Qt runs direct connections in
        # connection order), so this re-announces onto a view that has
        # already finished opening rather than one about to be cleared.
        self.session.line_opened.connect(self._resync_slice_band)

        self._update_enabled()
        self.session.site_opened.connect(self._update_enabled)
        self.session.site_closed.connect(self._update_enabled)
        # Closing the site cancels an export in flight: no layer is added to a closed site.
        self.session.site_closed.connect(self._on_site_closed_for_export)
        # The pick action follows the WORKING LINE, not merely the site
        # (see _update_enabled), so it has to be re-evaluated when that
        # changes -- line_opened carries "" when there is none.
        self.session.line_opened.connect(self._update_enabled)

        # Cut mode on the map follows QGIS's current layer (cut spec §4.3,
        # plan call 10): the cuts layer current means "work on cuts". Synced
        # when a site opens or closes too, since the layer objects are
        # replaced then.
        self.iface.currentLayerChanged.connect(self._on_current_layer_changed)
        self.session.site_opened.connect(self._sync_cut_mode)
        self.session.site_closed.connect(self._sync_cut_mode)
        self.iface.mapCanvas().mapToolSet.connect(self._on_map_tool_set)

    def _tabify_slices_dock(self) -> None:
        """Tab Slices onto Processing, once, after QGIS has restored its
        own layout.

        Called twice by design (see `initGui`) and idempotent, so the
        second call is free when the first already stuck. A slot on both
        a Qt signal and a `QTimer`: it must report rather than raise, and
        it may fire after `unload()` has already run.
        """
        try:
            dock = self.slices_dock
            processing = self.processing_dock
            if dock is None or processing is None:
                return
            if sip.isdeleted(dock) or sip.isdeleted(processing):
                return
            if not self._want_tabify:
                return
            main = self.iface.mainWindow()
            if dock not in main.tabifiedDockWidgets(processing):
                main.tabifyDockWidget(processing, dock)
            processing.raise_()
            QgsSettings().setValue(_TABIFIED_KEY, True)
        except Exception as exc:  # noqa: BLE001 -- a QTimer.timeout slot
            self.message(f"could not tab the Slices panel: {exc}", Qgis.MessageLevel.Warning)

    def _build_panels_menu(self) -> None:
        """#84: the toolbar's Panels button -- each panel by name, then
        three layouts.

        The entries are this plugin's own actions, not the docks'
        `toggleViewAction()`s: those take their text from the panel's
        title, and the Profile panel's title names the open line. Each
        entry is ticked from its dock's `toggleViewAction`, which Qt keeps
        in step however the panel is closed -- its own close button,
        View ▸ Panels, or this menu.

        A layout only opens and closes panels; Qt keeps a closed panel's
        place (its tab group, its size) for when it is opened again.
        """
        main = self.iface.mainWindow()
        menu = QMenu(main)
        named = (
            ("Survey", self.survey_dock),
            ("Profile", self.profile_dock),
            ("Processing", self.processing_dock),
            ("Slices", self.slices_dock),
        )
        for text, dock in named:
            entry = menu.addAction(text)
            entry.setCheckable(True)
            view = dock.toggleViewAction()
            entry.setChecked(view.isChecked())
            view.toggled.connect(entry.setChecked)
            entry.triggered.connect(
                lambda checked, d=dock, e=entry: self._set_panel_open(d, e, checked)
            )
        menu.addSeparator()
        profile_work = menu.addAction("Profile work")
        profile_work.triggered.connect(
            lambda: self._apply_layout((self.survey_dock, self.profile_dock))
        )
        slices_work = menu.addAction("Slices work")
        slices_work.triggered.connect(
            lambda: self._apply_layout((self.survey_dock, self.slices_dock))
        )
        menu.addAction("Show all").triggered.connect(self._show_all_panels)

        # A button of our own, not an action given a menu: the popup mode
        # belongs to the button, and QToolBar would make that button
        # itself, with a split arrow whose main half does nothing here.
        button = QToolButton(self.toolbar)
        button.setText("Panels")
        button.setToolTip("Show or hide the nsgeo panels, or switch to a layout")
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.toolbar.addSeparator()
        self.act_panels = self.toolbar.addWidget(button)
        self.toolbar_actions.append(self.act_panels)
        self.panels_menu = menu

    def _set_panel_open(self, dock: Any, entry: QAction, checked: bool) -> None:
        """A panel's entry in the Panels menu was ticked or unticked.

        Ticked: open AND in front. Qt alone reopens a tabbed panel behind
        the current tab, where the tick would look as if it did nothing.
        Unticked: `close()`, as the panel's own close button does -- not
        `setUserVisible(False)`, which does nothing to a panel that is
        open behind another tab.
        """
        try:
            if checked:
                dock.setUserVisible(True)
            else:
                dock.close()
        except Exception as exc:  # noqa: BLE001 -- a QAction.triggered slot
            verb = "open" if checked else "close"
            self.message(
                f"could not {verb} the {entry.text()} panel: {exc}", Qgis.MessageLevel.Warning
            )
            # The click has already flipped the tick; put it back to what
            # the panel actually is -- if the panel is still there to ask.
            with contextlib.suppress(Exception):
                entry.setChecked(dock.toggleViewAction().isChecked())

    def _apply_layout(self, keep: tuple[Any, ...]) -> None:
        """Profile work / Slices work: the panels in `keep` open and in
        front, every other nsgeo panel closed. QGIS's own panels are left
        as they are."""
        try:
            for dock in self.docks:
                if dock not in keep:
                    dock.close()
            for dock in keep:
                dock.setUserVisible(True)
        except Exception as exc:  # noqa: BLE001 -- a QAction.triggered slot
            self.message(f"could not change the panels: {exc}", Qgis.MessageLevel.Warning)

    def _show_all_panels(self) -> None:
        """Show all: every nsgeo panel open, and none pulled in front.

        Which of Processing and Slices ends up in front falls out of Qt
        and the order of `self.docks`: with both closed, the first one
        shown takes the front -- Processing, as at start-up; with one of
        them already open (after Slices work, say), that one stays.
        """
        try:
            for dock in self.docks:
                dock.show()
        except Exception as exc:  # noqa: BLE001 -- a QAction.triggered slot
            self.message(f"could not show the panels: {exc}", Qgis.MessageLevel.Warning)

    def unload(self) -> None:
        project = QgsProject.instance()
        for signal, slot in (
            (project.layersAdded, self._on_layers_added),
            (project.readProject, self._on_project_read),
            (project.cleared, self._forget_timed_layers),
        ):
            with contextlib.suppress(Exception):
                signal.disconnect(slot)
        # An export in flight is cancelled and waited for (bounded): a reloaded module
        # starts with no held task, while the old one could still be writing the same
        # partial file.
        self._cancel_export()
        held = running_export()
        if held is not None:
            with contextlib.suppress(Exception):
                held.waitForFinished(5000)
        # Connected in initGui() and owned by `iface`, which outlives this
        # plugin: left connected, a later startup signal would reach a
        # method on a torn-down plugin. Suppressed because the connection
        # is conditional (see `_want_tabify`) and Qt raises on
        # disconnecting what was never connected.
        with contextlib.suppress(Exception):
            self.iface.initializationCompleted.disconnect(self._tabify_slices_dock)
        with contextlib.suppress(Exception):
            self.iface.currentLayerChanged.disconnect(self._on_current_layer_changed)
        with contextlib.suppress(Exception):
            self.iface.mapCanvas().mapToolSet.disconnect(self._on_map_tool_set)
        with contextlib.suppress(Exception):
            self._drop_cut_tool()
        # Fix round 4, Finding 1: GridDialog is modeless (see
        # open_grid_dialog()), so -- unlike the old application-modal
        # exec() it replaced -- unload() can now run while one is still
        # open. reject() runs finished()'s own cleanup (releasing a
        # still-active pick tool and its message, deleteLater()) via the
        # same path as a normal Cancel, rather than leaving the dialog
        # dangling with a reference to a session this method is about to
        # tear down below.
        #
        # Fix round 5, Finding 1: not close(). QDialog.closeEvent only
        # calls reject() when the dialog isVisible() -- on a hidden one
        # it just accepts the close event and finished() never fires at
        # all (verified directly: hidden + close() -> 0 finished
        # emissions; hidden + reject() -> 1). _start_pick() hides
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
        # Same reasoning again: Edit lines tables are modeless too, one per
        # grid, and reject() (not close()) runs each one's finished-signal
        # cleanup instead of leaving it dangling with a reference to a
        # session this method is about to tear down.
        for edit_dialog in list(self._edit_lines_dialogs.values()):
            edit_dialog.reject()
        # Same reasoning again: LineChoiceDialog is modeless too, so it
        # can still be open here, and reject() (not close()) is what runs
        # its finished-signal cleanup instead of leaving it dangling with
        # a reference to a session this method is about to tear down.
        if self._line_choice_dialog is not None:
            self._line_choice_dialog.reject()
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
        if self.slices_dock is not None:
            # SliceEngine(session, ...) is built with no `parent=`, and it
            # closes over this dock's own bound methods as callbacks
            # (`on_prepared`/`on_error`/`on_progress`), which makes
            # `dock -> engine -> bound method -> dock` a reference cycle.
            # Plain refcounting cannot collect that promptly, so its
            # `session.site_closed`/`grids_changed` connections would
            # otherwise survive this method and could still fire -- against
            # a dock that is about to be deleteLater()'d -- for as long as
            # the cyclic collector happens not to have run. dispose()
            # disconnects them (and frees the kernel cache) deterministically,
            # before the session it is connected to is torn down below.
            #
            # The minimum-curvature refine worker before anything else
            # (interpolation spec §7, plan call 6): cancelled and joined, so
            # no solve is still running, or lands, once an engine is gone.
            if self.cut_sections is not None:
                self.cut_sections.dispose()
                self.cut_sections = None
            self.slices_dock.refiner.shutdown()
            # M12: the site scope first -- its timers, This grid's move hook
            # and the `SiteEngine`, which cancels and waits out its own task
            # -- so nothing it owns can start or outlive the teardown.
            self.slices_dock.dispose_site()
            self.slices_dock.engine.dispose()
        if self.depth_scroll is not None:
            self.depth_scroll.dispose()
            self.depth_scroll = None
        for dock in self.docks:
            self.iface.removeDockWidget(dock)
            dock.deleteLater()
        self.docks.clear()
        self.survey_dock = None
        self.profile_dock = None
        self.processing_dock = None
        self.slices_dock = None
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
        self.act_pick = None
        self.act_velocity = None
        self.act_cut = None
        self.act_panels = None
        if self.panels_menu is not None:
            # Parented to the main window, which outlives this plugin; its
            # entries are its children and go with it.
            self.panels_menu.deleteLater()
            self.panels_menu = None
        if self.toolbar is not None:
            self.toolbar.setParent(None)
            self.toolbar.deleteLater()
            self.toolbar = None
        if self.map_link is not None:
            # Before layers.detach(): the link holds geometry copied from
            # the `lines` layer and disposal only touches its own canvas
            # items, but ordering teardown outside-in keeps the link from
            # observing a half-dismantled layer set through the signals it
            # is still connected to.
            self.map_link.dispose()
            self.map_link = None
        if self.slice_layer is not None:
            # Same ordering as map_link just above: outside-in, before
            # layers.detach() removes the group this layer would otherwise
            # try to rejoin, and before the scratch GeoTIFF it writes to
            # is orphaned by this plugin unloading around it.
            self.slice_layer.dispose()
            self.slice_layer = None
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

    def _update_enabled(self, *_: Any) -> None:
        try:
            is_open = self.session is not None and self.session.is_open
            for act in (self.act_save, self.act_add_grid, self.act_import):
                if act is not None:
                    act.setEnabled(is_open)
            # A crosshair over an empty profile invites a click that can
            # do nothing, so this one needs a working line and not merely
            # an open site. Turning it off also has to turn the MODE off:
            # a checked-but-disabled action leaves the view in pick mode
            # with no control left to switch it back.
            has_line = is_open and self.session.current_key is not None
            if self.act_pick is not None:
                self.act_pick.setEnabled(has_line)
                if not has_line and self.act_pick.isChecked():
                    self.act_pick.setChecked(False)
                    self._toggle_pick_mode(False)
            # Cut needs a site, not a line: it draws a new one (cut spec §4.1).
            if self.act_cut is not None:
                self.act_cut.setEnabled(is_open)
                if not is_open and self.act_cut.isChecked():
                    self.act_cut.setChecked(False)
                    self._toggle_cut_tool(False)
            # A fit needs a recorded line: a cut at a slant widens hyperbolas (cut spec §4.3).
            can_fit = has_line and not is_cut_key(self.session.current_key or "")
            if self.act_velocity is not None:
                self.act_velocity.setEnabled(can_fit)
                self.act_velocity.setToolTip(
                    VELOCITY_ON_CUT_TIP if has_line and not can_fit else VELOCITY_TIP
                )
                if not can_fit and self.act_velocity.isChecked():
                    self.act_velocity.setChecked(False)
                    self._toggle_velocity_fit_mode(False)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not update the toolbar: {exc}", Qgis.MessageLevel.Warning)

    @staticmethod
    def _curve_param_name(step: Any) -> str | None:
        """The name of a step's curve-kind parameter, if it has one. Decided
        by the schema's kind, never by the step's name."""
        return curve_param_name(step)

    def _sync_gain_strip(self, row: int) -> None:
        # Slots on session/dock signals can still fire after unload() nulls
        # these -- the docks are only deleteLater()'d, not disconnected, so
        # a still-queued signal can reach here before the C++ side is
        # actually gone. An AssertionError here would die silently (see the
        # module docstring); None-guard the same way _update_enabled does.
        if self.session is None or self.profile_dock is None:
            return
        key = self.session.current_key
        if key is None or row < 0:
            self.profile_dock.show_gain_strip(None)
            return
        entries = self.session.stack_for(key).entries
        if row >= len(entries):
            self.profile_dock.show_gain_strip(None)
            return
        step = entries[row][0]
        name = self._curve_param_name(step)
        if name is None:
            self.profile_dock.show_gain_strip(None)
            return
        # The owner token the strip compares against the one already on
        # screen, so it can end a gesture that belongs to a curve no
        # longer displayed (see the gain strip module docstring's fourth
        # invariant). It cannot simply be the step object: every move of a
        # drag replaces the step, so the token has to stay stable across
        # this strip's *own* edits or the very first move would end its
        # own gesture. It cannot be (key, row) alone either: a stack
        # mutation that swaps a different step into the same row leaves
        # that pair unchanged, and the payload would then be refused
        # mid-drag while the write target had already moved -- exactly the
        # failure this fixes, one row along. So: (key, row) plus a
        # generation bumped whenever a genuinely different step object
        # arrives. `_on_gain_points` records the object it is about to
        # write *before* writing it, which is what keeps a drag's own echo
        # from reading as a different step here.
        if step is not self._gain_step:
            self._gain_generation += 1
        self._gain_owner, self._gain_step = (key, row, self._gain_generation), step
        self.profile_dock.show_gain_strip(
            step.params[name], self._gain_owner, self.profile_dock.step_input_zero_ns(row)
        )

    def _resync_gain_strip(self, key: str) -> None:
        """Re-run `_sync_gain_strip` once `key`'s profiles finish loading.
        See its own connection in `initGui` for why this is needed at all:
        `line_loaded` is the one render-triggering event `ProcessingDock`
        never reacts to, so nothing else re-checks a strip `_sync_gain_strip`
        last left hidden for want of an axis that has since arrived."""
        if self.session is None or self.processing_dock is None:
            return
        if key != self.session.current_key:
            return
        self._sync_gain_strip(self.processing_dock.current_row())

    def _resync_slice_band(self, key: str) -> None:
        """Re-announce the slice window onto a freshly opened line.
        See the connection in `initGui` for why. A slot on a
        `pyqtSignal`: it reports rather than raises."""
        if not key or self.slices_dock is None:
            # `line_opened("")` IS the clear -- re-announcing onto a view
            # with no line would draw a band across an empty panel.
            return
        try:
            self.slices_dock.reannounce_window()
        except Exception as exc:  # noqa: BLE001 -- a slot on a pyqtSignal
            self.message(f"could not redraw the slice band: {exc}", Qgis.MessageLevel.Warning)

    @staticmethod
    def _points_on_clock(points: list, from_zero_ns: float, to_zero_ns: float) -> list:
        """`[time_ns, gain_db]` points with the times moved between clocks."""
        return [[float(retime_ns(float(t), from_zero_ns, to_zero_ns)), float(g)] for t, g in points]

    def _on_gain_points(self, points: list) -> None:
        if self.session is None or self.processing_dock is None:
            return
        key = self.session.current_key
        row = self.processing_dock.current_row()
        if key is None or row < 0:
            return
        step = self.session.stack_for(key).entries[row][0]
        # The second barrier against writing one curve onto another. The
        # first is the strip's own owner check, which ends a gesture whose
        # curve has left the screen; this one refuses the write itself
        # unless the selected row still holds the very step object
        # `_sync_gain_strip` built the strip from. Identity, not name: two
        # `gain_curve` steps in one stack share a name and are not the
        # same step. Kept even though the first barrier should make it
        # unreachable, for the reason the module docstring gives for
        # `mouseMoveEvent`'s buttons() check -- this failure is silent
        # (no error, no log, no undo, and the strip goes on displaying the
        # curve it did not write), and a silent one is worth two barriers.
        # It is also the only barrier that covers `points_changed` being a
        # public signal on a public widget: an emit that never came from a
        # gesture at all never passes through the strip's owner check.
        if step is not self._gain_step:
            return
        name = self._curve_param_name(step)
        if name is None:
            return
        shown, input_zero = (
            self.profile_dock.shown_zero_ns(),
            self.profile_dock.step_input_zero_ns(row),
        )
        try:
            # Compared on the shown clock: an unmoved handle writes nothing.
            if [[float(a), float(b)] for a, b in points] == self._points_on_clock(
                step.params[name], input_zero, shown
            ):
                return
            params = dict(step.params)
            params[name] = self._points_on_clock(points, shown, input_zero)
        except (TypeError, ValueError) as exc:
            self.message(f"bad gain curve points: {exc}", Qgis.MessageLevel.Warning)
            return
        if step.params == params:
            # No actual change -- e.g. a plain click on a handle with no
            # movement, which GainStrip.mouseReleaseEvent still emits
            # unconditionally. Matches ProcessingDock._on_form_committed's
            # own no-op guard: a replace_step here would still dirty the
            # session and earn the user a save prompt for an edit they
            # never made.
            return
        try:
            new = build_step(step.name, **params)
        except ValueError as exc:
            self.message(str(exc), Qgis.MessageLevel.Warning)
            return
        # Recorded before replace_step, exactly as
        # ProcessingDock._on_form_committed records `_shown_step`: the
        # stack_changed -> rebuild() -> step_selected echo this triggers
        # runs synchronously and reports this very object back to
        # _sync_gain_strip, which must recognise it as the curve already
        # on screen rather than bump the generation and end the drag that
        # is still in progress.
        self._gain_step = new
        self.session.replace_step(key, row, new)

    def _on_slice_changed(self) -> None:
        try:
            dock, layer = self.slices_dock, self.slice_layer
            if dock is None or layer is None:
                return
            # #180: counts are always drawn in the plugin's colours. The limit
            # goes as a callable: under the user's own colours it is read only
            # to start their style from what was shown, since measuring it is a
            # pass over the cube.
            own = dock.own_colours_on() and not dock.coverage_check.isChecked()
            own_style = dock.own_style() if own else None
            limit = dock.display_limit
            if dock.scope() == "site":
                # M12 spec 4.5: one layer over every included grid, already
                # north-up on the site lattice.
                shown = dock.current_site_slice()
                if shown is None:
                    layer.clear()
                    return
                layer.update_north_up(
                    shown.array,
                    shown.lattice.geotransform,
                    shown.lattice.crs,
                    limit=limit,
                    colormap_name=dock.palette_combo.currentText(),
                    unipolar=dock.display_unipolar(),
                    subtitle=dock.readout.text(),
                    name=SITE_LAYER_NAME,
                    own=own,
                    own_style=own_style,
                )
            else:
                values, frame = dock.current_values(), dock.current_frame()
                if values is None or frame is None:
                    layer.clear()
                    return
                layer.update(
                    values,
                    frame,
                    limit=limit,
                    colormap_name=dock.palette_combo.currentText(),
                    unipolar=dock.display_unipolar(),
                    subtitle=dock.readout.text(),
                    counts=dock.coverage_check.isChecked(),
                    own=own,
                    own_style=own_style,
                )
            if own:
                dock.show_own_legend(own_colours.legend_text(layer.layer))
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not draw the slice: {exc}", Qgis.MessageLevel.Warning)

    def _on_own_style_changed(self, text: str) -> None:
        """`SliceLayer.own_style_changed`: remember the style for the scope on
        screen, and say its range on the Legend line at once, since an edit in
        Layer Properties redraws nothing in the panel (#180). A slot."""
        try:
            dock, layer = self.slices_dock, self.slice_layer
            if dock is None or layer is None:
                return
            dock.set_own_style(text)
            dock.show_own_legend(own_colours.legend_text(layer.layer))
        except Exception as exc:  # noqa: BLE001 -- a slot must never raise
            self.message(f"could not remember the slice colours: {exc}", Qgis.MessageLevel.Warning)

    def _open_slice_symbology(self) -> None:
        """`SlicesDock.symbology_requested`: the slice layer's Symbology page
        (#180). A slot: never raises."""
        try:
            layer = self.slice_layer.layer if self.slice_layer is not None else None
            if layer is None or sip.isdeleted(layer):
                self.message(
                    "show a slice first: the Symbology page belongs to the slice layer.",
                    Qgis.MessageLevel.Warning,
                )
                return
            self.iface.showLayerProperties(layer, own_colours.SYMBOLOGY_PAGE)
        except Exception as exc:  # noqa: BLE001 -- a slot must never raise
            self.message(
                f"could not open the slice's Symbology page: {exc}", Qgis.MessageLevel.Warning
            )

    def _canvas_extent_in(self, crs: QgsCoordinateReferenceSystem) -> tuple[float, ...] | None:
        """The map view as (xmin, ymin, xmax, ymax) in `crs`, for a slice style
        whose min/max is computed over the current canvas (#180)."""
        canvas = self.iface.mapCanvas()
        extent = canvas.extent()
        transform = crs_transform(canvas.mapSettings().destinationCrs(), crs, self.layers.project)
        if transform is not None:
            extent = transform.transformBoundingBox(extent)
        return (extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum())

    # ---- Task 6: what leaves the plugin -----------------------------------
    def save_cube(self) -> None:
        """`SlicesDock.save_cube_requested`: write the resident cube to
        `.npz` and record its recipe in `site.cubes`.

        `QFileDialog.getSaveFileName` defaults into `session.root /
        "slices"`, the same directory a plain "cube.npz" would land in --
        `save_cube_npz`/`save_cube` (M10) create it on demand, so this
        need not exist yet.

        Validated with `line_key` BEFORE anything is written (Task 6 fix
        round 1, "also fold in"): the earlier version called
        `save_cube_npz` first and let `cube_record`'s own `line_key` call
        raise second, which meant an out-of-tree destination built the
        whole cube and compressed it to disk before refusing -- real
        work for a save that was always going to be rejected. `root` and
        the raised `ProjectError` are identical either way; only the
        order changed.

        The cube id is `<grid_id>__<name>`, `name` being the stem of the
        file numpy ACTUALLY wrote (Important 1, same fix round) --
        `Path(npz_path).stem`, not `Path(path).stem`. `store.npz_path`'s
        own docstring names exactly this hazard: a user-typed name with a
        dot that is not an extension (a version tag, e.g. "cube.v1")
        keeps that dot in the file numpy writes ("cube.v1.npz") but the
        RAW dialog string's stem does not agree with it in general --
        and, worse, two such saves ("cube.v1", "cube.v2") used to collide
        on the SAME id ("A__cube"), so the second save silently replaced
        the first record while leaving both `.npz` files on disk, one of
        them now orphaned with no recipe pointing at it.

        A `QAction`-style guarded slot (see the module docstring): every
        failure -- a save outside the project tree, a full disk, a
        cube with no resident geometry -- is reported through
        `message()` rather than left to escape into stderr.
        """
        assert self.session is not None
        try:
            if not self.session.is_open or self.slices_dock is None:
                return
            dock = self.slices_dock
            engine = dock.engine
            if not engine.is_prepared or engine.choice is None:
                self.message(
                    "prepare a slice source before saving a cube.", Qgis.MessageLevel.Warning
                )
                return
            default_path = self.session.root / "slices" / "cube.npz"
            path, _ = QFileDialog.getSaveFileName(
                self.iface.mainWindow(), "Save cube", str(default_path), "nsgeo cube (*.npz)"
            )
            if not path:
                return
            root = self.session.root
            line_key(Path(path), root)  # raises ProjectError early; see the docstring above
            npz_path = save_cube_npz(engine, Path(path))
            # Task 7: `dock.view_settings()`, not a second, independent
            # construction of the same six values -- the dock is the one
            # place they are actually held, and it is also `restore_cube`'s
            # own inverse (`apply_view`), so the two cannot drift apart.
            record = cube_record(
                self.session,
                engine.choice,
                engine.frame,
                engine.z,
                dock.view_settings(),
                npz_path,
                line_keys=engine.provenance().line_keys,
                time_base=time_base_of(engine.provenance().steps),
            )
            cube_id = f"{engine.choice.grid_id}__{npz_path.stem}"
            self.session.record_cube(cube_id, record)
            # Task 7: the new record is a candidate `cube_combo` selection
            # the instant it exists, and `refresh_cube_combo` is the same
            # guarded refill `rebuild_source` already uses for `site_opened`
            # -- this is simply the other moment `cubes` changes.
            # Fix round 1, Minor: `select=cube_id` so the combo names the
            # record that now exactly matches what is on screen, rather
            # than sitting on "(unsaved)" immediately after a save.
            dock.refresh_cube_combo(select=cube_id)
            self.message(f"cube saved as {cube_id!r} ({record['array']!r})")
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not save the cube: {exc}", Qgis.MessageLevel.Critical)

    def export_geotiff(self) -> None:
        """`SlicesDock.export_requested`: the export dialog, then the export in the
        background, for This grid or for the whole site.

        The dialog sets the file, the export cell and the export pixel and refuses
        what does not fit; everything else comes from the panel as it is now
        (`thickness_step_levels`, `_resolved_velocity`, the finish, the
        normalisation, the gains, the coverage toggle). Nothing is solved here: a
        snapshot of the engines is taken on this thread (`grid_export_job`,
        `site_export_job`) and an `ExportTask` makes the bands off it, so the live
        view stays usable. `_finish_export` adds the layers when it ends.
        """
        assert self.session is not None
        try:
            if not self.session.is_open or self.slices_dock is None:
                return
            if running_export() is not None:
                self.message(
                    "an export is already running; wait for it to finish, "
                    "or cancel it in the task list.",
                    Qgis.MessageLevel.Warning,
                )
                return
            if self.slices_dock.scope() == "site":
                self._export_site()
            else:
                self._export_grid()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not export the GeoTIFF: {exc}", Qgis.MessageLevel.Critical)

    def _export_grid(self) -> None:
        """`export_geotiff` for This grid (see there)."""
        assert self.session is not None and self.slices_dock is not None
        dock = self.slices_dock
        engine = dock.engine
        if not engine.is_prepared or engine.frame is None or engine.z is None:
            self.message("prepare a slice source before exporting.", Qgis.MessageLevel.Warning)
            return
        thickness_levels, step_levels = dock.thickness_step_levels()
        _grid_id, velocity = dock._resolved_velocity()
        finish = dock.slice_finish()
        coverage = dock.coverage_check.isChecked()
        z = engine.z
        windows = tuple(
            window_ns(z, window) for window in plan_windows(z, thickness_levels, step_levels)
        )
        grid = self.session.grid(engine.choice.grid_id)  # type: ignore[union-attr]
        live_cell = engine.frame.cell

        def build(cell: float, pixel: float) -> _ExportJob:
            job = grid_export_job(
                engine,
                thickness_levels,
                step_levels,
                velocity,
                finish,
                cell,
                pixel,
                coverage=coverage,
            )
            return _ExportJob(
                spec=job.spec,
                coverage_spec=job.coverage_spec,
                writer_plan=WriterPlan(
                    GeoTiffSliceWriter(),
                    job.plan,
                    job.coverage_plan,
                    self._clip(dock.source_unipolar()),
                    CountsClip(),
                ),
                n_bands=len(job.plan.bands),
                temporal=lambda layer: apply_temporal_properties(layer, job.plan),
                left_out=[],
            )

        self._export_dialog(
            title="Export GeoTIFF",
            task_name="GeoTIFF",
            default=self.session.root / "slices" / "cube.tif",
            preview=grid_preview(engine, windows, finish=finish, coverage=coverage),
            floor=smallest_safe_cell(grid.size_x, grid.size_y),
            live_cell=live_cell,
            build=build,
            dock=dock,
            coverage=coverage,
        )

    def _export_site(self) -> None:
        """`export_geotiff` in site scope: one GeoTIFF over every included grid.

        Ruling T4-a: no grid is left out silently. The button is disabled while an
        included grid prepares (the dock), and the message names any included grid
        the file does not hold, and so does the file (Ruling F-2,
        `NSGEO_SITE_LEFT_OUT`). A preview site exports at full detail: the export has
        its own lattice at the export cell.
        """
        assert self.session is not None and self.slices_dock is not None
        dock = self.slices_dock
        site = dock.site_engine
        if not site.ready_grids or site.lattice is None or site.site_z is None:
            self.message("prepare the site's grids before exporting.", Qgis.MessageLevel.Warning)
            return
        thickness_levels, step_levels = dock.thickness_step_levels()
        transform = dock.site_panel.transform()
        method = dock.normalisation_panel.method()
        finish = dock.site_finish.value()
        gains = dock.site_gains()
        velocities = dock.site_velocities()
        left_out_states = dock.site_left_out_states()
        left_out = dock.site_left_out()
        coverage = dock.coverage_check.isChecked()
        site_z = site.site_z
        windows = tuple(
            band_window_ns(site_z, window)
            for window in plan_windows(site_z, thickness_levels, step_levels)
        )
        grids = [self.session.grid(g) for g in site.ready_grids]
        # The site's own picture pixel, which is the cell it is drawn at. Not the Cell size
        # box: that can still show a value a refused resolution left behind.
        full = site.full_lattice
        live_cell = full.pixel if full is not None else dock.cell_spin.value()

        def build(cell: float, pixel: float) -> _ExportJob:
            job = site_export_job(
                site,
                thickness_levels,
                step_levels,
                cell,
                pixel,
                transform=transform,
                method=method,
                finish=finish,
                gains=gains,
                velocities=velocities,
                left_out=left_out_states,
                coverage=coverage,
            )
            return _ExportJob(
                spec=job.spec,
                coverage_spec=job.coverage_spec,
                writer_plan=WriterPlan(
                    GeoTiffSiteWriter(),
                    job.plan,
                    job.coverage_plan,
                    self._clip(dock.source_unipolar()),
                    CountsClip(),
                ),
                n_bands=len(job.plan.bands),
                temporal=lambda layer: apply_site_temporal_properties(layer, job.plan),
                left_out=left_out,
            )

        self._export_dialog(
            title="Export site GeoTIFF",
            task_name="site GeoTIFF",
            default=self.session.root / "slices" / "site.tif",
            preview=site_preview(
                site,
                windows,
                method=method,
                finish=finish,
                gains=gains,
                coverage=coverage,
                normalisation=dock.normalisation_panel.method_combo.currentText().lower(),
            ),
            floor=max(smallest_safe_cell(g.size_x, g.size_y) for g in grids),
            live_cell=live_cell,
            build=build,
            dock=dock,
            coverage=coverage,
        )

    def _export_own_style(self, dock: SlicesDock) -> str | None:
        """The user's own colours for an export's style file (#180), or None
        for the plugin's: as the slice shows them now (this slice's computed
        range included), else as remembered (Show coverage is on)."""
        if not dock.own_colours_on():
            return None
        shown = self.slice_layer.own_style_now() if self.slice_layer is not None else None
        return shown if shown is not None else dock.own_style()

    @staticmethod
    def _clip(unipolar: bool) -> Any:
        """The stretch rule of the panel's own view (`display_limit`)."""
        return UnipolarClip() if unipolar else PercentileClip()

    def _export_dialog(
        self,
        *,
        title: str,
        task_name: str,
        default: Path,
        preview: Callable[[float, float], Any],
        floor: float,
        live_cell: float,
        build: Callable[[float, float], _ExportJob],
        dock: SlicesDock,
        coverage: bool,
    ) -> None:
        """Ask for the file, the export cell and the pixel; then start the task.

        Modal (`exec()`), `deleteLater` in a `finally`. A layer the target (or its
        style file or companion) is already open as is removed here, BEFORE the
        task starts (Windows locks open files) and added again by `_finish_export`.
        """
        assert self.session is not None
        dialog = ExportDialog(
            preview,
            cell_floor=floor,
            live_cell=live_cell,
            default_path=str(default),
            project=self.layers.project,
            parent=self.iface.mainWindow(),
            writes_coverage=coverage,
        )
        dialog.setWindowTitle(title)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            choice = dialog.result_settings()
            replaced = dialog.layers_to_replace()
        finally:
            dialog.deleteLater()
        target = choice.path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QgsMessageLog.logMessage(
                f"could not create {target.parent}: {exc}", "nsgeo", Qgis.MessageLevel.Warning
            )
            self.message(
                f"could not create the folder {target.parent}; choose another place to save.",
                Qgis.MessageLevel.Critical,
            )
            return
        job = build(choice.cell, choice.pixel)
        coverage_target = coverage_path(target) if job.coverage_spec is not None else None
        # Only the layers on files THIS export writes (values, companion when asked, and
        # their style files) go; the others stay. What goes is remembered by name and file
        # (never held as a layer: a held layer keeps its file open) so a cancel or a
        # failure can add it back from the unchanged file.
        written = {_norm_path(p) for p in (target, target.with_suffix(".qml"))}
        if coverage_target is not None:
            written |= {
                _norm_path(coverage_target),
                _norm_path(coverage_target.with_suffix(".qml")),
            }
        removed: list[tuple[str, Path]] = []
        for layer in replaced:
            source = layer.source().split("|")[0]
            if _norm_path(source) in written:
                removed.append((layer.name(), Path(source)))
                self.layers.project.removeMapLayer(layer.id())
        epoch = self._export_epoch
        palette = dock.palette_combo.currentText()
        unipolar = dock.source_unipolar()
        counts_palette = palette if palette in colormap_names(unipolar=True) else "amp_black_high"
        own_style = self._export_own_style(dock)

        def on_done(result: ExportResult) -> None:
            self._finish_export(
                result,
                job,
                epoch=epoch,
                cell=choice.cell,
                pixel=choice.pixel,
                palette=palette,
                unipolar=unipolar,
                counts_palette=counts_palette,
                removed=removed,
                own_style=own_style,
            )

        task = ExportTask(
            f"Export {task_name}",
            job.spec,
            job.writer_plan,
            target,
            job.coverage_spec,
            coverage_target,
            on_done,
            what=task_name,
        )
        if not start_export(task):
            note = self._restore_note(*self._restore_layers(removed))
            self.message(
                "an export is already running; wait for it to finish, "
                "or cancel it in the task list." + (f" {note}." if note else ""),
                Qgis.MessageLevel.Warning,
            )
            return
        self.message(
            f"exporting {task_name}: you can keep working; "
            "it is in the task list at the bottom right."
        )

    def _on_site_closed_for_export(self) -> None:
        try:
            self._cancel_export()
        except Exception as exc:  # noqa: BLE001 -- a slot must report, never raise
            self.message(f"could not cancel the export: {exc}", Qgis.MessageLevel.Warning)

    def _cancel_export(self) -> None:
        """Stop the export in flight: the site closed or the plugin unloads.

        The epoch moves first: cancelling a task still queued runs its `on_done`
        at once, inside this call, and it must see the site is gone.
        """
        self._export_epoch += 1
        task = running_export()
        if task is not None:
            task.cancel()

    def _finish_export(
        self,
        result: ExportResult,
        job: _ExportJob,
        *,
        epoch: int,
        cell: float,
        pixel: float,
        palette: str,
        unipolar: bool,
        counts_palette: str,
        removed: Sequence[tuple[str, Path]] = (),
        own_style: str | None = None,
    ) -> None:
        """The export task's `on_done`, on the GUI thread; it never raises.

        Re-entrant (a queued task cancelled in `_cancel_export` lands here at once)
        and re-checks that the site it started on is still open: a cancel landing
        after the task's last check still commits, and then the files stay on disk
        and nothing is added to a closed site.
        """
        try:
            if result.cancelled:
                note = self._restore_note(*self._restore_layers(removed, epoch))
                self.message(
                    "export cancelled" + (f"; {note}" if note else ""),
                    Qgis.MessageLevel.Warning if "could not" in note else Qgis.MessageLevel.Info,
                )
                return
            if not result.ok and result.values_written:
                self._finish_half_written(
                    result,
                    job,
                    epoch=epoch,
                    palette=palette,
                    unipolar=unipolar,
                    removed=removed,
                    own_style=own_style,
                )
                return
            if not result.ok:
                QgsMessageLog.logMessage(
                    f"export failed: {result.error}", "nsgeo", Qgis.MessageLevel.Warning
                )
                note = self._restore_note(*self._restore_layers(removed, epoch))
                self.message(
                    f"could not export the GeoTIFF: {plain_export_error(result.error)}"
                    + (f"; {note}" if note else ""),
                    Qgis.MessageLevel.Critical,
                )
                return
            if (
                epoch != self._export_epoch
                or self.session is None
                or not self.session.is_open
                or self.slices_dock is None
            ):
                self.message(
                    "the export finished after the site was closed; "
                    f"the file is at {result.target}",
                    Qgis.MessageLevel.Warning,
                )
                return
            parts = [
                f"exported {job.n_bands} bands to {result.target} "
                f"({cell:g} m cell, {pixel:g} m pixels)"
            ]
            style_notes: list[str] = []
            problem = self._add_export_layer(
                result.target,
                limit=float(result.limit or 1.0),
                palette=palette,
                unipolar=unipolar,
                temporal=job.temporal,
                notes=style_notes,
                own_style=own_style,
            )
            if problem is not None:
                self.message(problem, Qgis.MessageLevel.Warning)
            if result.coverage_target is not None:
                # Ruling AH: the companion in its own try, reported on its own terms.
                try:
                    problem = self._add_export_layer(
                        result.coverage_target,
                        limit=float(result.coverage_limit or 1.0),
                        palette=counts_palette,
                        unipolar=True,
                        temporal=None,
                        notes=style_notes,
                    )
                    if problem is not None:
                        raise RuntimeError(problem)
                    parts.append(f"coverage to {result.coverage_target}")
                except Exception as exc:  # noqa: BLE001 -- the values file is already added
                    self.message(
                        f"the GeoTIFF exported, but the coverage companion at "
                        f"{result.coverage_target} could not be added: {exc}",
                        Qgis.MessageLevel.Warning,
                    )
            if job.left_out:
                parts.append(f"left out {', '.join(job.left_out)}")
            text = ", ".join(parts)
            if style_notes:
                text += ". " + " ".join(style_notes)
            if job.left_out or style_notes:
                self.message(text, Qgis.MessageLevel.Warning)
            else:
                self.message(text)
        except Exception as exc:  # noqa: BLE001 -- invisible in a task's finished()
            QgsMessageLog.logMessage(
                f"could not finish the export: {exc}", "nsgeo", Qgis.MessageLevel.Critical
            )
            self.message(
                "the export was written, but could not be added to the map; "
                "the details are in the QGIS message log.",
                Qgis.MessageLevel.Critical,
            )

    def _finish_half_written(
        self,
        result: ExportResult,
        job: _ExportJob,
        *,
        epoch: int,
        palette: str,
        unipolar: bool,
        removed: Sequence[tuple[str, Path]],
        own_style: str | None = None,
    ) -> None:
        """The values file replaced its target but the companion could not be written.

        Says so. The old layer on the values file is not put back (it would read the new
        file with the old style); the new one is added. Layers on the other files, which
        are as they were, are put back.
        """
        QgsMessageLog.logMessage(
            f"export half written: {result.error}", "nsgeo", Qgis.MessageLevel.Warning
        )
        written = _norm_path(result.target)
        note = self._restore_note(
            *self._restore_layers([r for r in removed if _norm_path(r[1]) != written], epoch)
        )
        text = (
            f"the GeoTIFF was written to {result.target}, but the coverage file could not be: "
            f"{plain_export_error(result.error)}"
        )
        style_notes: list[str] = []
        if (
            epoch == self._export_epoch
            and self.session is not None
            and self.session.is_open
            and self.slices_dock is not None
        ):
            problem = self._add_export_layer(
                result.target,
                limit=float(result.limit or 1.0),
                palette=palette,
                unipolar=unipolar,
                temporal=job.temporal,
                notes=style_notes,
                own_style=own_style,
            )
            text += "; the new layer was added" if problem is None else f"; {problem}"
        if note:
            text += f"; {note}"
        # Style notes are whole sentences ending in a full stop: they go last.
        if style_notes:
            text += ". " + " ".join(style_notes)
        self.message(text, Qgis.MessageLevel.Warning)

    def _restore_layers(
        self, removed: Sequence[tuple[str, Path]], epoch: int | None = None
    ) -> tuple[list[str], list[str], list[str]]:
        """Add back the layers an export removed to replace, from their files.

        Each re-add is on its own `try`, so one failure never stops the rest. Same name; a
        style file beside the file applies as its default style, and the temporal
        properties come from the band windows the file records (`restore_band_times`);
        the layer's place in the group is not reapplied. Returns the names put back, the
        names that could not be (a file gone or unreadable, or an error, logged raw) and
        the names put back without their time slider (a file written before the windows
        were recorded). All are empty when nothing was removed or the site has closed since.
        """
        if (
            not removed
            or (epoch is not None and epoch != self._export_epoch)
            or self.session is None
            or not self.session.is_open
        ):
            return [], [], []
        back: list[str] = []
        lost: list[str] = []
        untimed: list[str] = []
        for name, path in removed:
            try:
                layer = QgsRasterLayer(str(path), name, "gdal") if path.exists() else None
                if layer is None or not layer.isValid():
                    raise OSError(f"{path} is missing or cannot be read as a layer")
                self._add_exported_layer(layer)
                back.append(name)
                restored = restore_band_times(layer, path)
                if restored == "missing":
                    untimed.append(name)
                elif restored == "set":
                    self._fit_temporal_controller(layer)
            except Exception as exc:  # noqa: BLE001 -- the others still go back
                QgsMessageLog.logMessage(
                    f"could not put the layer {name} back from {path}: {exc}",
                    "nsgeo",
                    Qgis.MessageLevel.Warning,
                )
                lost.append(name)
        return back, lost, untimed

    @staticmethod
    def _restore_note(back: Sequence[str], lost: Sequence[str], untimed: Sequence[str] = ()) -> str:
        """The words for a cancel or failure that removed layers: what is back, and what is not."""
        parts = []
        if back:
            parts.append(f"{name_list(back)} {'was' if len(back) == 1 else 'were'} put back")
        if lost:
            parts.append(f"{name_list(lost)} could not be put back; add it again from its file")
        if untimed:
            parts.append(
                f"{name_list(untimed)} {'is' if len(untimed) == 1 else 'are'} back without "
                "the time slider setting, which this older file does not record"
            )
        return "; ".join(parts)

    def _add_export_layer(
        self,
        path: Path,
        *,
        limit: float,
        palette: str,
        unipolar: bool,
        temporal: Callable[[Any], None] | None,
        notes: list[str] | None = None,
        own_style: str | None = None,
    ) -> str | None:
        """Style file, then the layer, then its temporal properties; None when it worked.

        The `.qml` is written first, so QGIS picks it up as the file's default
        style when the layer is made. The temporal properties go on after the layer
        is added (the style file stores them switched off). When the style file cannot be
        written, the previous export's one is removed (QGIS would apply its stretch to
        this file) and a sentence about it is appended to `notes`.
        """
        try:
            write_style(
                path, limit=limit, colormap_name=palette, unipolar=unipolar, own_style=own_style
            )
        except Exception as exc:  # noqa: BLE001 -- the file is good; QGIS just draws it plainly
            QgsMessageLog.logMessage(
                f"could not write the style file for {path}: {exc}",
                "nsgeo",
                Qgis.MessageLevel.Warning,
            )
            stale_gone = True
            try:
                path.with_suffix(".qml").unlink(missing_ok=True)
            except OSError as unlink_exc:
                stale_gone = False
                QgsMessageLog.logMessage(
                    f"could not remove the old style file beside {path}: {unlink_exc}",
                    "nsgeo",
                    Qgis.MessageLevel.Warning,
                )
            if notes is not None:
                notes.append(
                    f"The style file for {path.name} could not be written, so it is drawn "
                    "in QGIS's own colours."
                    + ("" if stale_gone else " An older style file beside it could not be removed.")
                )
        layer = QgsRasterLayer(str(path), path.stem, "gdal")
        if not layer.isValid():
            return f"the exported GeoTIFF at {path} could not be reopened as a layer"
        self._add_exported_layer(layer)
        if temporal is not None:
            temporal(layer)
            self._fit_temporal_controller(layer)
        return None

    def _on_layers_added(self, layers: Sequence[Any]) -> None:
        """Wire the band times of an added nsgeo export from its own file, and fit the
        Temporal Controller to it. Never raises: it is a slot, where exceptions vanish.

        Only `gdal` layers on an existing local `.tif`/`.tiff` are read (one GDAL metadata
        read each); a file with no recorded band windows, or a counts file, is left alone.
        An export or restore also wires and fits directly after adding (`_add_export_layer`,
        `_restore_layers`): the second pass gives the same result, so it is harmless.
        """
        for layer in layers:
            try:
                if not isinstance(layer, QgsRasterLayer) or layer.providerType() != "gdal":
                    continue
                path = Path(layer.source().split("|")[0])
                if path.suffix.lower() not in (".tif", ".tiff") or not path.is_file():
                    continue
                if restore_band_times(layer, path) != "set":
                    continue
                self._timed_layer_ids.append(layer.id())
                self._fit_temporal_controller(layer)
            except Exception as exc:  # noqa: BLE001 -- a slot must never raise
                QgsMessageLog.logMessage(
                    f"could not set the band times of an added layer: {exc}",
                    "nsgeo",
                    Qgis.MessageLevel.Warning,
                )

    def _forget_timed_layers(self) -> None:
        self._timed_layer_ids.clear()

    def _on_project_read(self, *_args: Any) -> None:
        """A project was opened: QGIS's Temporal Controller panel restores its own mode from
        the project once the layers are read, which undoes a fit made while they loaded.
        Fit again, after that, to the last timed nsgeo layer."""
        QTimer.singleShot(0, self._refit_after_open)

    def _refit_after_open(self) -> None:
        try:
            project = QgsProject.instance()
            for layer_id in reversed(self._timed_layer_ids):
                layer = project.mapLayer(layer_id)
                if isinstance(layer, QgsRasterLayer):
                    self._fit_temporal_controller(layer)
                    return
        except Exception as exc:  # noqa: BLE001 -- a timer slot must never raise
            QgsMessageLog.logMessage(
                f"could not set up the Temporal Controller after opening: {exc}",
                "nsgeo",
                Qgis.MessageLevel.Warning,
            )

    def _fit_temporal_controller(self, layer: QgsRasterLayer) -> None:
        """Set QGIS's Temporal Controller to step through `layer`'s bands, one per frame.

        Overrides whatever the controller held: the file was just made, put back, added or
        reopened, and a GPR project has no other timed layers. Skipped when the canvas has no
        navigation object (no canvas, or a test stub). Never raises: it runs where an exception
        would vanish, and the layer is already added.
        """
        try:
            canvas = self.iface.mapCanvas()
            navigation = canvas.temporalController() if canvas is not None else None
            if isinstance(navigation, QgsTemporalNavigationObject):
                fit_temporal_navigation(navigation, layer)
        except Exception as exc:  # noqa: BLE001 -- the layer is added; only the stepping is lost
            QgsMessageLog.logMessage(
                f"could not set up the Temporal Controller for {layer.name()}: {exc}",
                "nsgeo",
                Qgis.MessageLevel.Warning,
            )

    def _toggle_pick_mode(self, checked: bool) -> None:
        """The Pick toolbar toggle. Drives the dock, never the view
        directly: `ProfileDock` owns `ProfileView`."""
        try:
            if self.profile_dock is None:
                return
            if checked and self.act_velocity is not None and self.act_velocity.isChecked():
                # Both modes claim the left click; the one just switched on wins.
                self.act_velocity.setChecked(False)
                self._toggle_velocity_fit_mode(False)
            self.profile_dock.set_pick_mode(bool(checked))
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not change the pick mode: {exc}", Qgis.MessageLevel.Warning)

    def _toggle_velocity_fit_mode(self, checked: bool) -> None:
        """The Velocity toolbar toggle. Drives the dock, never the view."""
        try:
            if self.profile_dock is None:
                return
            if checked and self.act_pick is not None and self.act_pick.isChecked():
                self.act_pick.setChecked(False)
                self._toggle_pick_mode(False)
            self.profile_dock.set_velocity_fit_mode(bool(checked))
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not change the velocity mode: {exc}", Qgis.MessageLevel.Warning)

    # ---- the Cut tool (cut spec §4.1, decision 11) --------------------------
    def _toggle_cut_tool(self, checked: bool) -> None:
        """The Cut toolbar toggle: on sets the map tool and makes the cuts
        layer current (so the map works on cuts); off unsets the tool."""
        try:
            if self.layers is None or self.session is None:
                return
            if not checked:
                self._drop_cut_tool()
                return
            if self._cut_tool is not None:
                return
            canvas = self.iface.mapCanvas()
            tool = CutTool(canvas)
            tool.drawn.connect(self._on_cut_drawn)
            tool.failed.connect(self._on_cut_failed)
            self._cut_tool = tool  # before setMapTool: _on_map_tool_set compares against it
            canvas.setMapTool(tool)
            # Esc and Enter reach the tool only through the canvas's key events.
            canvas.setFocus()
            self._say_pick(CUT_HINT_TEXT)
            cuts = self.layers.layers.get("cuts")
            if cuts is not None and not sip.isdeleted(cuts):
                self.iface.setActiveLayer(cuts)
        except Exception as exc:  # noqa: BLE001 -- a QAction.triggered slot
            self.message(f"could not start the Cut tool: {exc}", Qgis.MessageLevel.Warning)

    def _drop_cut_tool(self) -> None:
        """Unset and release the Cut tool, if there is one. Safe to repeat."""
        tool, self._cut_tool = self._cut_tool, None
        if tool is None or sip.isdeleted(tool):
            return
        try:
            canvas = self.iface.mapCanvas()
            if not sip.isdeleted(canvas) and canvas.mapTool() is tool:
                canvas.unsetMapTool(tool)
        finally:
            self._pop_pick_message()
            tool.dispose()
            tool.deleteLater()

    def _on_map_tool_set(self, new_tool: Any, _old_tool: Any = None) -> None:
        """Another map tool took the canvas: the Cut toggle follows."""
        try:
            if self._cut_tool is None or new_tool is self._cut_tool:
                return
            if self.act_cut is not None:
                self.act_cut.setChecked(False)
            self._drop_cut_tool()
        except Exception as exc:  # noqa: BLE001 -- a signal slot: see the module docstring
            self.message(f"could not follow the map tool: {exc}", Qgis.MessageLevel.Warning)

    def _on_cut_failed(self, reason: str) -> None:
        self.message(f"drawing a cut failed: {reason}", Qgis.MessageLevel.Critical)

    def _cut_grid_and_vertices(self, points: Sequence[QgsPointXY]) -> tuple[str, list[Any]] | None:
        """The grid the FIRST point is inside (the first in survey order when
        several are), and all the points as that grid's metres; None when the
        first point is in no grid (cut spec call 6).

        Only the first point chooses the grid; the rest are transformed after,
        so a later point that will not transform cannot pass over the grid the
        first click is in (that raises, and the caller says so). Points are in
        the canvas CRS, the grid's metres are in the grid's own CRS.
        """
        assert self.session is not None and self.layers is not None
        site = self.session.site
        assert site is not None
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        first = points[0]
        for grid in site.grids:
            try:
                transform = crs_transform(
                    canvas_crs, QgsCoordinateReferenceSystem(grid.crs), self.layers.project
                )
                head = transform.transform(first) if transform else first
            except (RuntimeError, QgsCsException):
                continue  # this grid's CRS cannot be reached from the click: it is not in this grid
            x, y = grid.to_local(np.array([[head.x(), head.y()]], dtype=float))[0]
            if not (0.0 <= x <= grid.size_x and 0.0 <= y <= grid.size_y):
                continue
            try:
                mapped = [transform.transform(p) if transform else p for p in points]
            except QgsCsException as exc:
                raise RuntimeError(
                    f"part of the path cannot be placed on {grid.id}'s coordinate system: {exc}"
                ) from exc
            world = np.array([(q.x(), q.y()) for q in mapped], dtype=float)
            return grid.id, [(float(a), float(b)) for a, b in grid.to_local(world)]
        return None

    def _on_cut_drawn(self, points: list[QgsPointXY]) -> None:
        """A finished path: add the cut to the first grid its first point is
        in, and open it. The tool stays on for the next one."""
        try:
            if self.session is None or not self.session.is_open:
                return
            found = self._cut_grid_and_vertices(points)
            if found is None:
                self.message(OUTSIDE_TEXT, Qgis.MessageLevel.Warning)
                return
            grid_id, vertices = found
            try:
                key = self.session.add_cut(grid_id, vertices)
            except ValueError:
                self.message(TOO_FEW_TEXT, Qgis.MessageLevel.Warning)
                return
            self.session.open_line(key)
        except Exception as exc:  # noqa: BLE001 -- a signal slot: see the module docstring
            self.message(f"could not add the cut: {exc}", Qgis.MessageLevel.Critical)

    # ---- the current layer (plan call 10) -----------------------------------
    def _on_current_layer_changed(self, layer: Any) -> None:
        try:
            self._set_cut_mode_for(layer)
        except Exception as exc:  # noqa: BLE001 -- a signal slot: see the module docstring
            self.message(f"could not follow the current layer: {exc}", Qgis.MessageLevel.Warning)

    def _sync_cut_mode(self, *_: Any) -> None:
        try:
            self._set_cut_mode_for(self.iface.activeLayer())
        except Exception as exc:  # noqa: BLE001 -- a signal slot: see the module docstring
            self.message(f"could not follow the current layer: {exc}", Qgis.MessageLevel.Warning)

    def _set_cut_mode_for(self, layer: Any) -> None:
        """Cut mode is on exactly while the cuts layer is current. Layer ids
        are compared, not objects: a CRS rebuild replaces the layer object."""
        if self.map_link is None or self.layers is None or self.session is None:
            return
        cuts = self.layers.layers.get("cuts")
        on = (
            self.session.is_open
            and layer is not None
            and cuts is not None
            and not sip.isdeleted(cuts)
            and layer.id() == cuts.id()
        )
        self.map_link.set_cut_mode(bool(on))

    def _on_pick_requested(self, key: str, trace: int, time_ns: float) -> None:
        """Relay a pick from the profile to the session.

        `session.add_pick` is NEVER connected to a signal directly. It
        raises by design -- on a non-working line, on a non-finite time,
        on a failed provider write -- and an exception escaping a slot
        prints and passes on this build but reaches `qFatal()` in the
        `qgis/qgis:ltr` container and aborts the whole job. It also has
        somewhere better to go: a pick is authored data with no other
        source of truth, so the reason it did not land belongs on the
        message bar, not in a log the user is not reading.
        """
        try:
            if self.session is None:
                return
            if is_cut_key(key):
                self._add_cut_pick(key, trace, time_ns)
            else:
                dock = self.profile_dock
                shown = 0.0 if dock is None else dock.shown_zero_ns()
                self.session.add_pick(key, trace, time_ns, zero_ns=shown)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not author the pick: {exc}", Qgis.MessageLevel.Critical)

    def _add_cut_pick(self, key: str, column: int, time_ns: float) -> None:
        """A pick on the open cut: its distance and provenance come from the
        section on screen (cut spec §4.5). No section means no column to
        click, so the reason it has none goes on the message bar."""
        assert self.session is not None
        section = None if self.profile_dock is None else self.profile_dock.shown_cut_section(key)
        if section is None:
            raise RuntimeError("the profile shows no section for this cut, so there is no column")
        distances = section.columns.distance_m
        index = max(0, min(int(column), distances.size - 1))
        self.session.add_cut_pick(
            key, index, float(distances[index]), time_ns, section.provenance_json
        )

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
        self.message(f"plugin {plugin_version()} · core {nsgeo.__version__} · {build_label()}")

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
        # returns 0 in the same turn. _start_pick()'s dialog.hide()
        # (called from a slot that only fires *while* exec() would be
        # running) would therefore end the modal loop before the user
        # could click the canvas even once -- a map pick could never
        # actually work under a real event loop. show() instead of
        # exec() means the rest of this method's old post-exec() logic
        # (commit the result, release a still-active pick tool, dispose
        # the dialog) can no longer run synchronously
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
            # during a map pick.
            #
            # Fix round 5, Finding 5: show() too, not just raise_()/
            # activateWindow() -- _start_pick() hides the dialog
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
            # edit_grid_requested carries a grid id captured when a context
            # menu was built; it is stale if the grid was removed by then.
            # This is a QAction.triggered-style
            # slot (see the module docstring), so this must not raise.
            self.message(str(exc), Qgis.MessageLevel.Critical)
            return
        dialog = GridDialog(
            self.session,
            grid=grid,
            parent=self.iface.mainWindow(),
            canvas=self.iface.mapCanvas(),
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
                                new_grid = self._edited_grid_velocity(dialog, new_grid)
                                report = self.session.replace_grid(new_grid)
                                if report.message():
                                    self.message(
                                        report.message(),
                                        Qgis.MessageLevel.Warning
                                        if report.outside
                                        else Qgis.MessageLevel.Info,
                                    )
                        except (ValueError, KeyError) as exc:
                            self.message(str(exc), Qgis.MessageLevel.Critical)
            finally:
                # Fix round 2, Finding 4 (still applies to a modeless
                # dialog): finished() can fire while a map pick is still
                # in progress -- the map tool active, with neither a
                # click nor the tool's cancelled signal ever having fired
                # to release it. Left alone, that tool would later call
                # back into the pick's ending (a click, a switch to
                # another tool) against a `dialog` about to be deleted,
                # raising RuntimeError out of a signal-connected slot.
                canvas = self.iface.mapCanvas()
                tool = canvas.mapTool()
                if isinstance(tool, PickPointTool):
                    # unsetMapTool() -> deactivate() -> cancelled -> the
                    # pick's end() would otherwise re-show `dialog` --
                    # already finished here, and about to be
                    # deleteLater()'d below regardless -- for one
                    # event-loop turn before its own deletion actually
                    # runs (round 3, Finding 3). blockSignals() lets
                    # deactivate()'s own cleanup (clearing the snap
                    # marker) run without re-triggering that.
                    tool.blockSignals(True)
                    canvas.unsetMapTool(tool)
                    # blockSignals() above is exactly why this cannot
                    # lean on the pick's own ending for the disposal or
                    # the message: those are suppressed here on purpose.
                    _finish_with_pick_tool(tool)
                self._pop_pick_message()
                # Fix round 1, Finding 3: `dialog` is parented to the
                # main window and nothing else ever deleted it, so
                # every grid dialog opened stayed alive (with its full
                # widget tree) for the life of the QGIS session --
                # harmless for one dialog, but a segfault at
                # interpreter shutdown once enough of them pile up
                # alongside a QgsMapCanvas and the canvas items a map
                # tool left in its scene (verified with gdb).
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
            # The overlay's canvas item belongs to the canvas, not the
            # dialog, so a dialog destroyed without finished() must still
            # give it back (dispose() is idempotent). Held by a local
            # reference: `dialog` is already gone here.
            if overlay is not None:
                overlay.dispose()

        overlay = dialog.overlay
        dialog.finished.connect(finished)
        dialog.destroyed.connect(clear_if_current)
        dialog.pick_requested.connect(lambda row: self._start_pick(dialog, [row]))
        dialog.pick_all_requested.connect(
            lambda: self._start_pick(dialog, list(range(len(CORNER_ROLES))))
        )
        dialog.pick_polygon_requested.connect(lambda: self._start_pick_polygon(dialog))
        self._grid_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    # ---- picking on the map (#63, spec §4.7) -------------------------------
    def _start_pick(self, dialog: GridDialog, rows: list[int]) -> None:
        """Pick corners on the map: one row, or Pick all's walk over `rows`.

        The dialog hides while the canvas is clicked, and the message bar
        names the corner to click (C3). Each click fills the current row
        through `set_corner`, converting from the canvas CRS. A single
        pick's right-click cancels it; Pick all's skips the corner and
        leaves its row as it was, and Esc stops it, keeping what was
        picked. A conversion `set_corner` refuses ends the pick too: the
        dialog comes back with the reason in its status line. Picks never
        fit (C1).
        """
        armed: Callable[[], None] | None = None
        try:
            canvas = self.iface.mapCanvas()
            tool = PickPointTool(canvas)
            queue = list(rows)

            def prompt() -> str:
                role = CORNER_ROLES[queue[0]]
                if len(rows) == 1:
                    return f"Click the {role} corner. Right-click or Esc cancels."
                k = len(rows) - len(queue) + 1
                return (
                    f"Pick corners: click the {role} corner ({k} of {len(rows)}). "
                    "Right-click skips it, Esc stops."
                )

            end = armed = self._arm_pick(dialog, tool, prompt())

            def next_corner() -> None:
                queue.pop(0)
                if queue:
                    self._say_pick(prompt())
                else:
                    end()

            def picked(point: QgsPointXY, label: str) -> None:
                # A slot on tool.picked: guarded, and a failure ends the pick.
                try:
                    crs = canvas.mapSettings().destinationCrs()
                    if dialog.set_corner(queue[0], point, crs, label):
                        next_corner()
                    else:
                        end()  # set_corner wrote the reason in the status line
                except Exception as exc:  # noqa: BLE001 -- a slot: see the module docstring
                    self.message(
                        f"could not use the picked point: {exc}", Qgis.MessageLevel.Critical
                    )
                    end()

            def skipped() -> None:
                # A slot on tool.skipped (a right-click): guarded, as above.
                # Pick all moves on; a single pick has no next corner, so
                # skipping its one corner is its cancel.
                try:
                    next_corner()
                except Exception as exc:  # noqa: BLE001 -- a slot: see the module docstring
                    self.message(f"could not skip the corner: {exc}", Qgis.MessageLevel.Critical)
                    end()

            tool.picked.connect(picked)
            tool.skipped.connect(skipped)
        except Exception as exc:  # noqa: BLE001 -- a slot: see the module docstring
            self.message(f"could not start picking: {exc}", Qgis.MessageLevel.Critical)
            if armed is not None:
                armed()

    def _start_pick_polygon(self, dialog: GridDialog) -> None:
        """Pick the polygon to fill the corners from (C5, #28): one click
        chooses the topmost polygon feature under it in the dialog's layer
        and feature lists. Right-click or Esc cancels."""
        armed: Callable[[], None] | None = None
        try:
            tool = PickPointTool(self.iface.mapCanvas(), mode="polygon")
            text = "Click the polygon to use. Right-click or Esc cancels."
            end = armed = self._arm_pick(dialog, tool, text)

            def polygon_picked(layer: Any, fid: int) -> None:
                # A slot on tool.polygon_picked: guarded, and the pick ends
                # however it went. A layer the dialog's list refuses is
                # reported in its status line by set_polygon_feature.
                try:
                    dialog.set_polygon_feature(layer, fid)
                except Exception as exc:  # noqa: BLE001 -- a slot: see the module docstring
                    self.message(
                        f"could not choose the picked polygon: {exc}", Qgis.MessageLevel.Critical
                    )
                finally:
                    end()

            tool.polygon_picked.connect(polygon_picked)
            tool.skipped.connect(lambda: end())
        except Exception as exc:  # noqa: BLE001 -- a slot: see the module docstring
            self.message(f"could not start picking: {exc}", Qgis.MessageLevel.Critical)
            if armed is not None:
                armed()

    def _arm_pick(self, dialog: GridDialog, tool: PickPointTool, text: str) -> Callable[[], None]:
        """Hand the canvas to `tool` for `dialog`, and return the pick's `end`.

        Hides the dialog (C3 -- possible only because it is modeless: see
        open_grid_dialog()), sets the tool and says `text` in the message
        bar. `end()` is the one way a pick finishes, however it finishes --
        the last corner, a right-click, Esc, a switch to another map tool,
        an exception -- and each of those is wired to it here or by the
        caller. It finishes and unsets the tool, releases it and its canvas
        items, pops the message and shows the dialog again; the dialog
        comes back even if a step before it failed. Calling it twice is
        harmless.

        The one finisher that does not come through here is the dialog's
        own `finished` (closed mid-pick): see open_grid_dialog().
        """
        canvas = self.iface.mapCanvas()
        ended = False

        def end(unset: bool = True) -> None:
            nonlocal ended
            if ended:
                return
            ended = True
            try:
                try:
                    tool.finish()
                    if unset and canvas.mapTool() is tool:
                        canvas.unsetMapTool(tool)
                finally:
                    self._pop_pick_message()
                    _finish_with_pick_tool(tool)
            except Exception as exc:  # noqa: BLE001 -- reached from slots: see the module docstring
                self.message(f"could not finish picking cleanly: {exc}", Qgis.MessageLevel.Warning)
            finally:
                if not sip.isdeleted(dialog):
                    dialog.show()
                    dialog.raise_()

        def cancelled() -> None:
            # Emitted from inside the tool's deactivate(), while the canvas
            # is part-way through switching to another tool: there is
            # nothing to unset, and unsetting would re-enter the switch.
            end(unset=False)

        def failed(reason: str) -> None:
            # The tool caught an exception in a method Qt called (see
            # pick_tool.py's module docstring): say so, and end the pick.
            self.message(f"picking on the map failed: {reason}", Qgis.MessageLevel.Critical)
            end()

        tool.cancelled.connect(cancelled)
        tool.stopped.connect(lambda: end())
        tool.failed.connect(failed)
        try:
            running = canvas.mapTool()
            if isinstance(running, PickPointTool):
                # A pick is already running: the dialog was re-shown mid-pick
                # (Add grid again) and a Pick pressed. That pick ends first,
                # through its own cancelled path, so its dialog.show() and
                # its message's removal happen before this one starts.
                canvas.unsetMapTool(running)
            # Modeless, so an ordinary hide: the canvas stays interactive
            # (round 4, Finding 1 -- this is what exec() could not survive).
            dialog.hide()
            canvas.setMapTool(tool)
            # Esc reaches the tool only through the canvas's key events.
            canvas.setFocus()
            self._say_pick(text)
        except Exception:
            end()
            raise
        return end

    def _say_pick(self, text: str) -> None:
        """Show `text` as the running pick's instruction, replacing the last.

        One message for the whole pick, its text updated corner by corner.
        If the user closed it, a fresh one is pushed.
        """
        bar = self.iface.messageBar()
        item = self._pick_message
        if item is not None and not sip.isdeleted(item) and item in bar.items():
            item.setText(text)
            return
        item = bar.createMessage("nsgeo", text)
        bar.pushWidget(item, Qgis.MessageLevel.Info)
        self._pick_message = item

    def _pop_pick_message(self) -> None:
        """Take the running pick's instruction off the message bar, if it is
        still there. Safe to call with no pick running."""
        item, self._pick_message = self._pick_message, None
        if item is None or sip.isdeleted(item):
            return
        bar = self.iface.messageBar()
        if item in bar.items():
            bar.popWidget(item)

    def _add_exported_layer(self, layer: Any) -> None:
        """Show an exported GeoTIFF in the site's group, below its tables.
        With the group deleted by the user, on top of the Layers panel
        instead: never in the project with no place in the panel (#68)."""
        apply_smooth_resampling(layer)
        self.layers.project.addMapLayer(layer, False)
        group = self.layers.group
        if group is not None:
            group.addLayer(layer)
        else:
            self.layers.project.layerTreeRoot().insertLayer(0, layer)

    def _import_from_toolbar(self) -> None:
        # #61: into the grid the Survey panel points at, not always the
        # first one. None when it points at none, and the dialog then
        # falls back to the first grid.
        dock = self.survey_dock
        self.open_import_dialog(dock.target_grid_id() if dock is not None else None)

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
            if grid_id is not None:
                self._import_dialog.retarget(grid_id)
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

    def open_edit_lines_dialog(self, grid_id: str, keys: Sequence[str] = ()) -> None:
        # A slot of the Survey panel's edit_lines_requested: guarded, so a
        # failure reaches the message bar and never the swallowing signal.
        try:
            self._open_edit_lines_dialog(grid_id, keys)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not open Edit lines: {exc}", Qgis.MessageLevel.Critical)

    def _open_edit_lines_dialog(self, grid_id: str, keys: Sequence[str] = ()) -> None:
        # Modeless, one table per grid -- open_import_dialog()'s shape: a
        # second request for the same grid raises the open table and selects
        # the lines asked for (line editing spec §4.1).
        assert self.session is not None
        if not self.session.is_open:
            return
        existing = self._edit_lines_dialogs.get(grid_id)
        if existing is not None and existing.opened_against != self.session.json_path:
            # Tables are keyed by grid id, and "A" or "Grid1" recur from site
            # to site: a table opened against the old site would only be
            # refused at OK and lose its edits (line editing spec §3 call 14).
            # reject() runs `finished`, which drops it from the dict.
            existing.reject()
            existing = self._edit_lines_dialogs.get(grid_id)
        if existing is not None:
            existing.select_keys(keys)
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return
        dialog = EditLinesDialog(self.session, grid_id, select=keys, parent=self.iface.mainWindow())

        def finished(result: int) -> None:
            # A pyqtSignal slot: must not raise (module docstring). The write
            # was done, and re-checked, by EditLinesDialog.accept().
            try:
                if result == QDialog.DialogCode.Accepted and dialog.outcome is not None:
                    self.message(
                        f"Edit lines · {grid_id}: {dialog.outcome.message()}",
                        Qgis.MessageLevel.Warning
                        if dialog.outcome.skipped
                        else Qgis.MessageLevel.Info,
                    )
            finally:
                dialog.deleteLater()
                if self._edit_lines_dialogs.get(grid_id) is dialog:
                    del self._edit_lines_dialogs[grid_id]

        def clear_if_current() -> None:
            # Identity only, never touching `dialog` (already gone).
            if self._edit_lines_dialogs.get(grid_id) is dialog:
                del self._edit_lines_dialogs[grid_id]

        dialog.finished.connect(finished)
        dialog.destroyed.connect(clear_if_current)
        self._edit_lines_dialogs[grid_id] = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def move_lines(self, keys: list[str], grid_id: str) -> None:
        """Move lines to another grid, from the Survey panel's Move to grid.

        A slot: it never raises, and reports on the message bar (line editing
        spec §3 call 7). Lines already on the grid are left alone."""
        try:
            assert self.session is not None
            outcome = self.session.move_lines(keys, grid_id)
        except (KeyError, ProjectError) as exc:
            # str(KeyError) is repr(arg): quotes inside the bar's own quotes.
            what = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
            self.message(f"Move to {grid_id}: {what}", Qgis.MessageLevel.Critical)
            return
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not move the lines: {exc}", Qgis.MessageLevel.Critical)
            return
        self.message(
            f"Move to {grid_id}: {outcome.message()}",
            Qgis.MessageLevel.Warning if outcome.skipped else Qgis.MessageLevel.Info,
        )

    def _edited_grid_velocity(self, dialog: GridDialog, edited: Grid) -> Grid:
        """Edit grid's velocity at OK (grid velocity spec §7.2). The dialog is
        modeless and holds the grid as it opened, so its box is compared with
        the value it opened with. Unchanged: the grid's velocity and record as
        they are NOW, so a velocity set meanwhile (the grid velocity dialog,
        the strip's Apply to grid) is neither put back nor paired with the
        wrong record. Changed: the box's number, with no record."""
        if dialog.velocity_unchanged():
            now = self.session.grid(edited.id)
            return dataclasses.replace(
                edited, velocity=now.velocity, velocity_source=now.velocity_source
            )
        return dataclasses.replace(edited, velocity_source=None)

    def open_velocity_dialog(self, key: str) -> None:
        """Set or clear the line's velocity override, from a typed number or a
        saved fit. Modal: it is a short question about one line, and the answer
        is applied the moment it closes.

        The line's velocity source says which fits produced the override, so
        every route here keeps it true (grid velocity spec §7.2): applying a
        fit or an average records them, a typed number drops the record, and
        clearing the override clears both."""
        try:
            dialog = VelocityDialog(self.session, key, parent=self.iface.mainWindow())
        except (KeyError, ProjectError) as exc:
            # The key was captured when a context menu was built; the line
            # may be gone by now.
            self.message(str(exc), Qgis.MessageLevel.Critical)
            return
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            # e.g. ValueError from a header with a non-positive epsr, which
            # loads fine and fails when its velocity is resolved.
            self.message(f"could not open the velocity dialog: {exc}", Qgis.MessageLevel.Critical)
            return
        self._run_velocity_dialog(
            dialog,
            lambda: self.session.apply_line_velocity(
                key, dialog.velocity(), dialog.chosen_source()
            ),
        )

    def open_grid_velocity_dialog(self, grid_id: str) -> None:
        """Set or clear a grid's velocity, from a typed number, one fit on its
        lines, or the average of the fits ticked (grid velocity spec §4). The
        Survey panel's grid Set velocity... opens this; Edit grid stays on its
        own menu item. Modal, like the line's dialog.

        The grid's velocity source records the fits behind the number, as
        `open_velocity_dialog` does for a line. Line overrides are left alone."""
        try:
            dialog = VelocityDialog(self.session, grid_id=grid_id, parent=self.iface.mainWindow())
        except (KeyError, ProjectError) as exc:
            # The id was captured when a context menu was built; the grid may
            # be gone by now.
            self.message(str(exc), Qgis.MessageLevel.Critical)
            return
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not open the velocity dialog: {exc}", Qgis.MessageLevel.Critical)
            return
        self._run_velocity_dialog(
            dialog,
            lambda: self.session.apply_grid_velocity(
                grid_id, dialog.velocity(), dialog.chosen_source()
            ),
        )

    def _run_velocity_dialog(self, dialog: VelocityDialog, apply: Callable[[], None]) -> None:
        """Show a velocity dialog, `apply` its answer if accepted, and dispose
        of it. The selected fit is lit on the profile while the dialog is open,
        so its row can be matched to its curve; the profile lights it only when
        its line is the one shown."""
        dock = self.profile_dock

        def light(ref: tuple[str, str] | None) -> None:
            if dock is not None:
                dock.highlight_saved_fit(*(ref if ref is not None else ("", None)))

        try:
            dialog.fit_highlighted.connect(light)
            light(dialog.highlighted_ref())
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            apply()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not set the velocity: {exc}", Qgis.MessageLevel.Critical)
        finally:
            light(None)
            dialog.deleteLater()

    def open_line_choice_dialog(self) -> None:
        """Spec 9.1's one dialog. Modeless, like every dialog here.

        A single tracking slot, so a second `Choose...` does not stack a
        dialog on top of the first; the result is committed on `finished`
        rather than after a blocking call, and the dock is re-read then
        rather than captured now, because the site can change while this
        is open. Follows `open_import_dialog` exactly -- fix round 1, M4:
        an earlier version of this method omitted `destroyed.connect(...)`
        (a dialog destroyed some other way then leaves
        `self._line_choice_dialog` pointing at a dead wrapper, wedging the
        re-open branch below and making `unload()`'s own `reject()` raise
        mid-teardown -- see `open_grid_dialog`'s `clear_if_current` for the
        same reasoning) and the `show()`/`raise_()`/`activateWindow()` set
        both other dialogs here use on every path, not just some of them.

        M12: the grid is `dock.line_choice_grid()` -- This grid's, or the
        site list's selected row -- and the result is committed through
        `dock.set_included_for`, which in site scope re-prepares that grid
        only.

        `finished` re-checks the dock's CURRENT grid against `grid_id`
        (fix round 3, Ruling Z): the dialog is modeless and binds
        `grid_id` once, at open time, but nothing stops the user from
        changing the Source group's own grid combo while it sits open.
        Without this check, accepting after such a change commits the
        OLD grid's keys against the NEW grid's frame -- bringing back
        both `6 of 3 included` and the silent trace drop Ruling U's own
        scoping exists to remove, just reached one step later than a
        cross-grid pick in the dialog itself would have.

        In This grid scope only (M12 final review M1). In site scope the
        choice is the grid's own remembered source, which
        `set_included_for` addresses by id, and the dialog names the grid
        it is for: a row selected meanwhile is no reason to throw the
        choice away, so it is applied to the grid it was opened for.
        """
        try:
            if self.session is None or not self.session.is_open or self.slices_dock is None:
                return
            # M12: This grid's grid, or the site list's selected row.
            grid_id = self.slices_dock.line_choice_grid()
            if not grid_id:
                self.message("Choose a grid before choosing lines.", Qgis.MessageLevel.Warning)
                return
            if self._line_choice_dialog is not None:
                self._line_choice_dialog.show()
                self._line_choice_dialog.raise_()
                self._line_choice_dialog.activateWindow()
                return
            dock = self.slices_dock
            dialog = LineChoiceDialog(
                self.session, grid_id, dock.line_choice_keys(grid_id), self.iface.mainWindow()
            )

            def finished(result: int) -> None:
                try:
                    if result == QDialog.DialogCode.Accepted and self.slices_dock is not None:
                        if (
                            self.slices_dock.scope() == "grid"
                            and self.slices_dock.line_choice_grid() != grid_id
                        ):
                            self.message(
                                "the grid changed while choosing lines; "
                                "the line choice was not applied",
                                Qgis.MessageLevel.Warning,
                            )
                        else:
                            self.slices_dock.set_included_for(grid_id, dialog.included_keys())
                except Exception as exc:  # noqa: BLE001 -- a slot on finished
                    self.message(
                        f"could not apply the line choice: {exc}", Qgis.MessageLevel.Warning
                    )
                finally:
                    dialog.deleteLater()
                    self._line_choice_dialog = None

            def clear_if_current() -> None:
                # Same reasoning as open_grid_dialog()/open_import_dialog()'s
                # own clear_if_current: only compare identity, never touch
                # `dialog` (already gone by the time destroyed() fires), and
                # only clear the tracker if it still points at THIS dialog.
                if self._line_choice_dialog is dialog:
                    self._line_choice_dialog = None

            dialog.finished.connect(finished)
            dialog.destroyed.connect(clear_if_current)
            self._line_choice_dialog = dialog
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not open the line chooser: {exc}", Qgis.MessageLevel.Critical)
