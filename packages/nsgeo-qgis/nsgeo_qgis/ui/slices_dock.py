"""The Slices dock: choosing a source, then navigating the slices it makes.

Tabified with the Processing dock rather than competing for screen space
(spec 9.2) -- a sub-ten-step stack leaves room below it. A separate widget
rather than a tab inside `processing_dock.py`, so it can be torn off to
see both at once, and because issue #21 already records that file as
overloaded.

Four groups, ordered by how often they are touched and what each costs:
Source (~0.9 s, a task), Position (0.6-4 ms), Resolution (44 ms) and
Display (free). This module builds them; it computes nothing. Every number
on screen comes from `slices_plan` or from the engine.

Signal/slot hazard, same as every other dock in this plugin (see
`plugin.py`'s module docstring): an exception raised inside a slot
connected via `connect()` never reaches whatever emitted the signal -- it
is swallowed locally and turns into `qFatal()` in the CI container. Every
slot below guards its own body and reports through `error` or
`nsgeo_qgis.log.log`.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from nsgeo.render import DEFAULT_COLORMAP, PercentileClip, UnipolarClip, colormap_names
from nsgeo.slices import (
    CubeFrame,
    SliceWindow,
    fill,
    limit_over_slices,
    plan_windows,
    window_label,
    window_times_ns,
)
from nsgeo.velocity import VelocityModel
from qgis.gui import QgsDockWidget
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.log import log as _log
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.site_engine import SiteEngine, SiteSlice
from nsgeo_qgis.slice_export import ViewSettings, recipe_from_record
from nsgeo_qgis.slices_engine import SliceEngine
from nsgeo_qgis.slices_plan import (
    DEFAULT_BUDGET_BYTES,
    DEFAULT_CELL_M,
    DEFAULT_RADIUS_SPACINGS,
    DEFAULT_TRANSFORM,
    MAX_FRAME_CELLS,
    NO_TRANSFORM,
    Resolution,
    SiteSource,
    SourceChoice,
    default_cell,
    depth_scroll_delta,
    estimate_memory,
    format_bytes,
    frame_cells,
    smallest_safe_cell,
    transform_names,
)
from nsgeo_qgis.ui import site_scope
from nsgeo_qgis.ui.profile_dock import velocity_source
from nsgeo_qgis.ui.site_panel import NormalisationPanel, SiteSourcePanel


def _snap_inside(value: float, decimals: int, *, upper: bool) -> float:
    """`value` rounded to `decimals`, never ESCAPING the bound it describes.

    A plain `round()` is wrong at a boundary: `QDoubleSpinBox.setValue`
    rounds to the box's own precision, and rounding a lower bound DOWN (or
    an upper bound UP) puts the spin a few ten-thousandths of a nanosecond
    outside the range every prepared line actually covers -- which is
    exactly the `CoverageError` the caller is clamping to avoid, now made
    intermittent and dependent on the fourth decimal place of a header.
    Rounds away from the forbidden side instead.
    """
    step = 10.0**-decimals
    snapped = round(value, decimals)
    if upper and snapped > value:
        snapped -= step
    elif not upper and snapped < value:
        snapped += step
    return round(snapped, decimals)


class SlicesDock(QgsDockWidget):
    #: Ask the plugin to open `LineChoiceDialog` (spec 9.1's one dialog).
    #: A request, not the dialog itself -- the dock owns no dialogs, the
    #: same split `SurveyDock`/`ProfileDock` already use for grid/import.
    choose_lines_requested = pyqtSignal()
    error = pyqtSignal(str)
    #: Emitted at the end of `refresh_slice()`, whenever `current_values()`
    #: /`current_frame()`/`display_limit()` are worth reading again --
    #: `plugin.py` connects this to redraw `SliceLayer` (Task 4).
    slice_changed = pyqtSignal()
    window_changed = pyqtSignal(float, float)  # (lo_ns, hi_ns) of the averaged window
    window_cleared = pyqtSignal()
    #: Requests for `plugin.py`'s two file dialogs (Task 6, spec 9.6). This
    #: dock owns no dialogs of its own -- the same split `choose_lines_
    #: requested` already uses for `LineChoiceDialog`.
    save_cube_requested = pyqtSignal()
    export_requested = pyqtSignal()

    def __init__(self, session: SiteSession, parent: QWidget | None = None) -> None:
        super().__init__("nsgeo Slices", parent)
        self.setObjectName("nsgeoSlicesDock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.session = session
        self.engine = SliceEngine(
            session,
            on_prepared=self._on_prepared,
            on_error=self._on_engine_error,
            on_progress=self._on_progress,
        )
        # ---- M12: the Whole site scope (spec 4.1-4.5) ---------------------
        #: "grid" (M11's This grid) or "site". Never persisted (plan Ruling
        #: 5): the dock always opens in This grid.
        self._scope = "grid"
        #: Built here, after `engine` and before this dock connects to the
        #: session: its `grids_changed` slot must run before `rebuild_source`
        #: (see `site_engine.py`'s slot-order note). This grid's engine is its
        #: `exclusive_with` peer (Ruling 1); R-P5 closes the other direction.
        self.site_engine = SiteEngine(
            session,
            on_changed=self._on_site_changed,
            on_error=self._on_site_error,
            exclusive_with=[self.engine],
            parent=self,
        )
        #: This grid's values while the site shows: its Resolution spins,
        #: palette and remembered source, and the top time carried back.
        self._grid_spins: site_scope.Spins | None = None
        self._grid_palette = ""
        self._grid_record_at_entry: tuple[Any, Any] | None = None
        self._pending_top_ns: float | None = None
        #: R-P5: a This-grid preparation owed once the site has stopped, and
        #: This grid's `_on_prepared` arriving while the site showed.
        self._grid_prepare_pending = False
        self._grid_prepared_away = False
        #: The survey the site scope's memory belongs to.
        self._site_seen: Any = None
        #: R-P5: retries the owed This-grid preparation every 50 ms until no
        #: site task is live. Never blocks.
        self._grid_retry = QTimer(self)
        self._grid_retry.setSingleShot(True)
        self._grid_retry.setInterval(50)
        self._grid_retry.timeout.connect(self._run_pending_grid_prepare)
        # A depth counter, not a bool -- see `rebuild_source` and the
        # module docstring of `processing_dock.py`, whose reasoning this
        # copies exactly: a slot re-entering `rebuild_source` while the
        # outer call is still on the stack would otherwise have its
        # `finally` clear the guard early, for the inner call's own frame.
        self._updating = 0
        #: The included subset, in survey order. Always a subset of the
        #: selected grid's own lines (fix round 3, Ruling Y corrects what
        #: this used to say): `_default_included` seeds it from the grid,
        #: and `LineChoiceDialog` (Ruling U, fix round 1) now lists only
        #: that same grid's lines, so nothing can widen this to a line
        #: from elsewhere.
        self._included: tuple[str, ...] = ()
        #: The grid id `_included` was last reset for. `None` both before
        #: any grid has been looked at and whenever no grid is selected,
        #: which is also this dock's own initial state -- so the very
        #: first `rebuild_source()` call in `__init__` reads as a "grid
        #: changed" transition exactly when a grid is actually available.
        self._last_grid_id: str | None = None
        #: The grid id `dz_spin`/`z0_spin`/`z1_spin` were last successfully
        #: seeded FROM A REAL LINE for -- `None` reset on every genuine
        #: grid change; see `_seed_dz_z_defaults` for why a grid change
        #: alone is not enough to know these three are done being seeded.
        self._dz_z_seeded_for: str | None = None
        #: Whether `_included` is still the SEEDED default for
        #: `_last_grid_id`, as opposed to a subset the user chose through
        #: `LineChoiceDialog` (fix round 1, Important 1 / Ruling S).
        #: `plugin.py` constructs this dock at `initGui`, before any site
        #: exists: the first `grids_changed` after `add_grid` seeds `()`
        #: (the grid has no lines yet), which used to latch there --
        #: `_sync_included`'s "grid unchanged" branch only pruned stale
        #: keys, it never looked again at what `_default_included` would
        #: now say. A LATER `lines_changed`, with the grid still selected,
        #: must still pick up the lines that arrive after the seed -- this
        #: flag is what tells `_sync_included` it is still allowed to
        #: re-seed rather than merely prune. Cleared the moment the user
        #: makes an explicit choice (`set_included`), and set again only by
        #: an actual grid change.
        self._included_is_default = True
        #: The current slice's own values (post coverage/fill) and the
        #: `SliceWindow` they came from, as `refresh_slice()` last left
        #: them -- `None` before anything has been prepared. `display_limit()`
        #: reads both: the array for "this slice"'s own clip, `_window
        #: .n_levels` as half the shared-limit cache's key.
        self._values: np.ndarray | None = None
        self._window: SliceWindow | None = None
        #: `(key, limit)` from the last `shared_limit()` call, where `key`
        #: is `(n_levels, engine.choice, engine.mode, radius_cells)` --
        #: everything `engine.shared_limit` actually measures over (fix
        #: round: `radius_cells` joined the other three once `shared_limit`
        #: started filling each window before measuring it -- see its own
        #: docstring). Recomputing it is a pass over every window in the
        #: cube (tens of them), not a per-tick cost, so `display_limit()`
        #: only pays for it again when one of those four actually changed
        #: -- and `_on_prepared` also clears it unconditionally on every
        #: successful preparation, because `_on_grids_changed` can
        #: re-prepare against the SAME `SourceChoice` (a grid move), which
        #: changes what was measured without moving any of these four.
        self._shared_limit_cache: tuple[tuple[Any, ...], float] | None = None
        #: Task 7: a palette name `restore_cube` still owes `palette_combo`
        #: once the preparation it just dispatched finishes. `_on_prepared`
        #: always calls `_refill_palette_combo()`, which resets the combo
        #: to a computed default regardless of what was selected before
        #: (by design -- see that method's own docstring) -- so a palette
        #: applied by `apply_view` before `prepare()` would otherwise be
        #: silently overwritten the moment the async preparation completes.
        #: Consumed and cleared by `_on_prepared` every time it runs
        #: (restore-triggered or not), and cleared early by
        #: `_on_source_changed`/`set_included` too, so a manual change made
        #: while a restore is still preparing cannot inherit its palette.
        #: Fix round 1, Minor: ALSO cleared right after `restore_cube`'s
        #: own `prepare()` call when that call turns out to have been a
        #: no-op (`self.engine.is_running` still `False` afterwards) --
        #: `prepare()`'s own guard skips dispatching, and therefore skips
        #: `_on_prepared`, whenever the computed choice already equals
        #: `engine.choice` and the preset's steps still match (reachable
        #: by restoring a cube, changing only e.g. the cell size, then
        #: reselecting the SAME cube). Without this, a value stashed here
        #: would sit unconsumed until some LATER, unrelated preparation's
        #: `_on_prepared` fires and applies a palette that restore no
        #: longer has anything to do with.
        self._pending_palette: str | None = None

        body = QWidget(self)
        outer = QVBoxLayout(body)
        outer.setContentsMargins(4, 4, 4, 4)

        # M12 spec 4.1: the scope is stated where the eye lands first.
        scope_row = QHBoxLayout()
        self.grid_scope_button = QPushButton("This grid")
        self.site_scope_button = QPushButton("Whole site")
        self._scope_buttons = QButtonGroup(self)
        self._scope_buttons.setExclusive(True)
        for button in (self.grid_scope_button, self.site_scope_button):
            button.setCheckable(True)
            self._scope_buttons.addButton(button)
            scope_row.addWidget(button)
        self.grid_scope_button.setChecked(True)
        self.site_scope_button.setEnabled(False)
        outer.addLayout(scope_row)

        self.source_group = QGroupBox("Source")
        source_layout = QVBoxLayout(self.source_group)

        form = QFormLayout()
        # Cube sits above Grid (Task 7): it is the control that sets all
        # three of the others (and the inclusion set, and Resolution), so
        # it reads first. `refresh_cube_combo()` fills it; see that
        # method's own docstring for why it starts empty here.
        self.cube_combo = QComboBox()
        self.grid_combo = QComboBox()
        self.preset_combo = QComboBox()
        self.transform_combo = QComboBox()
        form.addRow("Cube", self.cube_combo)
        form.addRow("Grid", self.grid_combo)
        form.addRow("Preset", self.preset_combo)
        form.addRow("Transform", self.transform_combo)
        source_layout.addLayout(form)

        included_row = QHBoxLayout()
        self.included_label = QLabel("")
        self.choose_button = QPushButton("Choose…")
        included_row.addWidget(self.included_label, 1)
        included_row.addWidget(self.choose_button)
        source_layout.addLayout(included_row)

        self.source_status = QLabel("")
        self.source_status.setWordWrap(True)
        source_layout.addWidget(self.source_status)

        outer.addWidget(self.source_group)
        self.site_panel = SiteSourcePanel()
        self.site_panel.setVisible(False)
        outer.addWidget(self.site_panel)

        # ---- Position: the slider IS the top of the window (spec 9.2) --
        # there is no separate "Top" field. The readout sits directly
        # beneath it with nothing between them, because the control that
        # moves the window and the statement of where it now is are read
        # together on every tick; `velocity_label` is one line further
        # down, in a smaller and dimmer face, because a velocity is
        # provenance about the source, not state this control changes.
        self.position_group = QGroupBox("Position")
        position_layout = QVBoxLayout(self.position_group)

        self.slice_slider = QSlider(Qt.Orientation.Horizontal)
        self.slice_slider.setRange(0, 0)
        position_layout.addWidget(self.slice_slider)

        self.readout = QLabel("not prepared")
        position_layout.addWidget(self.readout)

        self.velocity_label = QLabel("")
        velocity_font = self.velocity_label.font()
        velocity_font.setPointSizeF(max(1.0, velocity_font.pointSizeF() * 0.85))
        self.velocity_label.setFont(velocity_font)
        self.velocity_label.setStyleSheet("color: palette(mid);")
        position_layout.addWidget(self.velocity_label)

        # M12 spec 4.3: each grid's depth through its own velocity, in the
        # same quieter face as `velocity_label`, which it replaces in site scope.
        self.site_depths_label = QLabel("")
        self.site_depths_label.setFont(velocity_font)
        self.site_depths_label.setStyleSheet("color: palette(mid);")
        self.site_depths_label.setWordWrap(True)
        self.site_depths_label.setVisible(False)
        position_layout.addWidget(self.site_depths_label)

        thickness_form = QFormLayout()
        self.thickness_spin = QDoubleSpinBox()
        self.thickness_spin.setRange(0.01, 100_000.0)
        self.thickness_spin.setDecimals(2)
        self.thickness_spin.setSuffix(" ns")
        self.thickness_spin.setValue(5.0)
        # In ns, over a ~110 ns window: Qt's 1.0 default is a fifth of
        # the default thickness in a single click (round 2, W5/W7).
        self.thickness_spin.setSingleStep(0.25)
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(0.01, 100_000.0)
        self.step_spin.setDecimals(2)
        self.step_spin.setSuffix(" ns")
        # Spec 6.6's 50% overlap default: a reflector sitting on a window
        # boundary is halved in both neighbours rather than lost from one
        # of them, which a step equal to the thickness (no overlap) would
        # do at every boundary in the stack.
        self.step_spin.setValue(self.thickness_spin.value() / 2.0)
        self.step_spin.setSingleStep(0.25)
        thickness_form.addRow("Thickness", self.thickness_spin)
        thickness_form.addRow("Step", self.step_spin)
        position_layout.addLayout(thickness_form)

        outer.addWidget(self.position_group)

        # ---- Resolution: the binning geometry, debounced (44 ms a
        # rebuild, spec 7.2 and trap 4) so a slider dragged through five
        # cell sizes in a second rebuilds once, not five times.
        self.resolution_group = QGroupBox("Resolution")
        resolution_form = QFormLayout(self.resolution_group)

        self.cell_spin = QDoubleSpinBox()
        self.cell_spin.setRange(0.01, 5.0)
        self.cell_spin.setDecimals(3)
        self.cell_spin.setSuffix(" m")
        self.cell_spin.setValue(DEFAULT_CELL_M)
        # Qt defaults `singleStep` to 1.0 whatever the range or the
        # decimals. On a control spanning 0.01-5.0 m that made ONE press
        # of the down-arrow clamp 0.5 m straight to the 0.01 m minimum --
        # and cell count goes as 1/cell**2, so on a 300 m grid that is a
        # 30000 x 30000 frame and a dead QGIS (walkthrough round 2, W7).
        # The minimum itself is raised per grid in `_seed_resolution_
        # defaults`; this is what stops the arrows being a cliff.
        self.cell_spin.setSingleStep(0.05)
        self.cell_spin.setToolTip(
            "Width of one cube cell on the ground.\n"
            "Spec 4 (Conyers): no smaller than the trace spacing -- below that "
            "there is no new information to resolve -- and no larger than half "
            "the line spacing."
        )
        resolution_form.addRow("Cell size", self.cell_spin)

        self.dz_spin = QDoubleSpinBox()
        self.dz_spin.setRange(0.001, 100.0)
        self.dz_spin.setDecimals(4)
        self.dz_spin.setSuffix(" ns")
        self.dz_spin.setValue(1.0)
        # Re-set from the file's own `dt_ns` in `_seed_dz_z_defaults`:
        # one sample per click is the only increment that means anything
        # on a time axis. 1.0 ns -- Qt's default -- was five samples at
        # this repo's own 0.2165 ns sampling.
        self.dz_spin.setSingleStep(0.05)
        self.dz_spin.setToolTip(
            "Vertical spacing of the cube's levels, in two-way time.\n"
            "Defaults to the file's own sample interval; §7.2 measured that "
            "decimating buys nothing, so there is rarely a reason to coarsen it."
        )
        resolution_form.addRow("dz", self.dz_spin)

        self.z0_spin = QDoubleSpinBox()
        self.z0_spin.setRange(-1_000.0, 100_000.0)
        self.z0_spin.setDecimals(3)
        self.z0_spin.setSuffix(" ns")
        self.z0_spin.setValue(0.0)
        self.z0_spin.setSingleStep(0.05)
        self.z0_spin.setToolTip(
            "Top of the cube in two-way time. Clamped to what every included "
            "line actually covers once they are prepared."
        )
        resolution_form.addRow("z0", self.z0_spin)

        self.z1_spin = QDoubleSpinBox()
        self.z1_spin.setRange(-1_000.0, 100_000.0)
        # Fix round 1, Ruling AJ: 4, not 3, and deliberately NOT matching
        # `z0_spin`'s 3. A record's `t1_ns` is `z.t_end_ns = t0_ns + (nz -
        # 1) * dz_ns` (Task 6, so the record round-trips `nz` exactly
        # rather than the requested-but-possibly-fractional `t1_ns`) --
        # with `z0_ns` at 3 dp and `dz_ns` at 4 dp, that sum is a genuine
        # 4-dp quantity about half the time over plausible GSSI headers
        # (43 of 90 swept combinations). `setValue()` rounds to a spin
        # box's own `decimals()` (verified directly: `QDoubleSpinBox`
        # does not merely format the display), so at 3 dp `restore_cube`
        # was silently flooring `t1_ns` below its own level boundary,
        # which `ZAxis.from_range` then floors a whole level off -- a
        # shorter slider range and a missing deepest slice, with nothing
        # raised. `z0_spin` stays at 3: it is where the 3-dp precision in
        # `z.t0_ns` originates (every `t0_ns` this dock ever produces
        # passed through THIS spin box's own `setValue()` first, whether
        # seeded from a header or typed by hand), so restoring a record's
        # `t0_ns` into it is always lossless -- there is no fourth decimal
        # for it to lose. `z1_spin` has no such origin story: its value is
        # DERIVED (`t_end_ns`), not sourced from this widget, so it needs
        # the extra digit the arithmetic can actually produce.
        self.z1_spin.setDecimals(4)
        self.z1_spin.setSuffix(" ns")
        self.z1_spin.setValue(100.0)
        self.z1_spin.setSingleStep(0.05)
        self.z1_spin.setToolTip(
            "Bottom of the cube in two-way time. Clamped to what every included "
            "line actually covers once they are prepared."
        )
        resolution_form.addRow("z1", self.z1_spin)

        self.radius_spin = QDoubleSpinBox()
        self.radius_spin.setRange(0.0, 50.0)
        self.radius_spin.setDecimals(3)
        self.radius_spin.setSuffix(" m")
        self.radius_spin.setValue(0.0)
        # 1.0 m -- Qt's default -- moved the seeded 0.75 m radius to 1.75
        # in one click, past anything spec 6.4's 1.5x-line-spacing rule
        # would ever suggest (walkthrough round 2, W5).
        self.radius_spin.setSingleStep(0.05)
        self.radius_spin.setToolTip(
            "Fills cells that no line crossed from their neighbours within "
            "this distance (spec 6.4).\n"
            "Default is 0.5 x the line spacing. The binned truth is kept "
            "underneath either way -- tick Show coverage to see it, and set "
            "this to 0 to display it unfilled."
        )
        resolution_form.addRow("Fill radius", self.radius_spin)

        # M12 spec 4.4: in site scope the radius is a multiple of each grid's
        # own line spacing; the tooltip gives the metres per grid.
        self.radius_spacing_spin = QDoubleSpinBox()
        self.radius_spacing_spin.setRange(0.0, 10.0)
        self.radius_spacing_spin.setDecimals(2)
        self.radius_spacing_spin.setSingleStep(0.25)
        self.radius_spacing_spin.setSuffix(" × line spacing")
        self.radius_spacing_spin.setValue(DEFAULT_RADIUS_SPACINGS)
        resolution_form.addRow("Fill radius", self.radius_spacing_spin)
        self._resolution_form = resolution_form
        site_scope.set_row_visible(self, self.radius_spacing_spin, False)

        outer.addWidget(self.resolution_group)
        self.normalisation_panel = NormalisationPanel()
        self.normalisation_panel.setVisible(False)
        outer.addWidget(self.normalisation_panel)

        # One debounce for all five Resolution widgets: `flush_debounce()`
        # stops the timer and applies immediately, for tests and for
        # anything that needs the current geometry right away.
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self._apply_resolution)

        # ---- Display: how the slice is coloured and stretched, never
        # what it contains -- spec 8's comparability-by-default,
        # legibility-on-demand split.
        self.display_group = QGroupBox("Display")
        display_form = QFormLayout(self.display_group)

        self.stretch_combo = QComboBox()
        self.stretch_combo.addItems(["shared across the cube", "this slice"])
        display_form.addRow("Stretch", self.stretch_combo)

        self.palette_combo = QComboBox()
        display_form.addRow("Palette", self.palette_combo)

        self.coverage_check = QCheckBox("Show coverage")
        # Round 2, W6: "Don't know what this is doing." The view is the
        # whole reason the cube stores a count alongside the mean (spec
        # 6.2), and it is unreadable without being told what the numbers
        # are.
        self.coverage_check.setToolTip(
            "Shows how many traces fell in each cell instead of the amplitude.\n"
            "Cells no line crossed are left blank, so an empty bin is "
            "distinguishable from a real zero reflection -- which is the "
            "whole point of recording a count."
        )
        display_form.addRow(self.coverage_check)

        # Ruling AN (M11 final review): the settings override spec 9.2
        # itself describes ("keep the whole volume in memory for faster
        # dragging") lives here, in the Display group, rather than in
        # settings -- this plugin has none, and building one was ruled
        # beyond this milestone's scope. Wired to `SliceEngine.
        # set_always_resident`, which existed but had no caller anywhere
        # but tests. `_update_resident_check_label` fills in the real
        # text (spec 9.2's own wording, with the cost it names) once an
        # engine estimate exists; the placeholder here is never shown.
        self.resident_check = QCheckBox("Keep the volume in memory")
        display_form.addRow(self.resident_check)

        self.legend_label = QLabel("")
        # Wraps, because a QLabel's minimum width is its text width and a
        # dock's minimum width is a hard floor on the QGIS main window's
        # -- the same mechanism that made this dock force a 556 px window
        # in round 1. The coverage legend is the longest string here.
        self.legend_label.setWordWrap(True)
        display_form.addRow("Legend", self.legend_label)

        outer.addWidget(self.display_group)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        # Spec 9.2: the status line sits ABOVE the export buttons, so a
        # person reading "stale · the grid changed" sees why before
        # reaching for either button below it. Both start disabled --
        # `_refresh_source_status` is the one place that state is kept
        # current, alongside everything else that line already reports.
        button_row = QHBoxLayout()
        self.save_button = QPushButton("Save cube…")
        self.export_button = QPushButton("Export GeoTIFF…")
        self.save_button.setEnabled(False)
        self.export_button.setEnabled(False)
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.export_button)
        outer.addLayout(button_row)

        outer.addStretch(1)
        # Inside a scroll area, not set as the dock's widget directly.
        # Four group boxes stacked give `body` a ~1019 px MINIMUM height
        # (measured), and a dock widget's minimum is a hard floor on the
        # main window: QGIS could not shrink its right dock area below it,
        # so opening this dock resized the whole QGIS window -- reported
        # from the M11 walkthrough as "it messes up the width/height of
        # the window". A scroll area's own minimum is small, so the dock
        # can be any size the user wants and scrolls to the rest.
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        self.setWidget(scroll)

        # A palette is always offered, even before any source is chosen
        # (bipolar, `engine.output_unipolar`'s own default) -- `_on_prepared`
        # refills it with the real answer once a source actually exists.
        self._refill_palette_combo()
        self._update_resident_check_label()

        # Filled once, and BEFORE the connects just below: `transform_names()`
        # is the registry, not the site, and does not change while this dock
        # is alive. Filling an empty combo auto-selects its first item and
        # fires `currentTextChanged` unconditionally (fix round 1, M2) -- with
        # this above the connect block, that happens with nothing listening
        # yet; the earlier order fired `_on_source_changed('none')` with
        # `_updating == 0` right here in `__init__`, harmless only by luck
        # (grid_combo was still empty, so `source_choice()` was `None`).
        # `grid_combo`/`preset_combo` are rebuilt from the session instead,
        # in `rebuild_source` below.
        self.transform_combo.addItem("none")
        self.transform_combo.addItems(transform_names())
        # #81: start on Square. Set here, above the connect block, for the
        # same reason as the items: nothing is listening yet.
        if self.transform_combo.findText(DEFAULT_TRANSFORM) >= 0:
            self.transform_combo.setCurrentText(DEFAULT_TRANSFORM)

        # `clicked` carries a `bool checked` that a direct
        # `.connect(self.choose_lines_requested.emit)` would pass straight
        # through as the signal's `str`-less argument -- `emit()` takes no
        # positional argument here, so that would actually raise. The
        # lambda drops it, the same reason `processing_dock.py`'s
        # `apply_button` uses one.
        self.choose_button.clicked.connect(lambda: self.choose_lines_requested.emit())
        self.save_button.clicked.connect(lambda: self.save_cube_requested.emit())
        self.export_button.clicked.connect(lambda: self.export_requested.emit())
        self.cube_combo.currentTextChanged.connect(self._on_cube_changed)
        self.grid_combo.currentTextChanged.connect(self._on_source_changed)
        self.preset_combo.currentTextChanged.connect(self._on_source_changed)
        self.transform_combo.currentTextChanged.connect(self._on_source_changed)
        session.site_opened.connect(self.rebuild_source)
        session.site_closed.connect(self.rebuild_source)
        session.grids_changed.connect(self.rebuild_source)
        session.lines_changed.connect(self.rebuild_source)
        session.presets_changed.connect(self.rebuild_source)

        # Position is cheap (0.6-4 ms, the module docstring's own figure):
        # every tick redraws directly, with no debounce.
        self.slice_slider.valueChanged.connect(lambda _value: self.refresh_slice())
        self.thickness_spin.valueChanged.connect(lambda _value: self.refresh_slice())
        self.step_spin.valueChanged.connect(lambda _value: self.refresh_slice())

        # Resolution is not: every one of these five widgets only starts
        # the shared debounce (see its own construction above for why).
        for _spin in (
            self.cell_spin,
            self.dz_spin,
            self.z0_spin,
            self.z1_spin,
            self.radius_spin,
        ):
            _spin.valueChanged.connect(lambda _value: self._debounce.start())

        # Task 7: `cube_combo` falls back to "(unsaved)" the moment one of
        # the four fields that decide what the cube IS (spec 5.4's split,
        # `cube_record`'s own docstring) moves -- `cell`/`dz_ns`/`t0_ns`/
        # `t1_ns`, i.e. the `Resolution` dataclass's own fields. Deliberately
        # NOT `radius_spin`: the fill radius is a `ViewSettings` field (it
        # changes no pixel in the array, only how it is displayed -- see
        # `Resolution`'s own docstring), so moving it alone leaves the
        # combo's claim about the array still true.
        for _spin in (self.cell_spin, self.dz_spin, self.z0_spin, self.z1_spin):
            _spin.valueChanged.connect(lambda _value: self._mark_cube_unsaved())

        # Display changes no value `refresh_slice()` fetches from the
        # engine, but each still changes what the map ought to show --
        # a new palette, a different stretch, coverage instead of
        # amplitude -- so each still funnels through the one path that
        # recomputes `_values` and re-emits `slice_changed`.
        self.stretch_combo.currentTextChanged.connect(lambda _text: self.refresh_slice())
        self.palette_combo.currentTextChanged.connect(lambda _text: self.refresh_slice())
        self.coverage_check.toggled.connect(lambda _checked: self.refresh_slice())
        # Not wired straight to refresh_slice(): the residency override
        # changes no pixel (spec 11's own property -- streaming and
        # resident agree exactly), only how fast the NEXT slice redraws,
        # so `_on_resident_toggled` reaches the engine directly.
        self.resident_check.toggled.connect(self._on_resident_toggled)

        # M12: the scope switch; `SiteScope` wires the two site groups.
        self.grid_scope_button.clicked.connect(lambda: self._on_scope_clicked("grid"))
        self.site_scope_button.clicked.connect(lambda: self._on_scope_clicked("site"))
        self.site_panel.choose_lines_requested.connect(
            lambda _grid: self.choose_lines_requested.emit()
        )
        self._site = site_scope.SiteScope(self)

        self.rebuild_source()

    # ---- source group -------------------------------------------------
    def rebuild_source(self) -> None:
        """Refill `grid_combo`/`preset_combo` from the session, then bring
        the status line and (fix round 1, Important 2) the engine itself
        up to date with whatever that refill left selected.

        Guarded by `self._updating`: refilling a `QComboBox` emits
        `currentTextChanged` even when the text ends up unchanged (Qt
        fires it once, unconditionally, the moment a combo goes from
        empty to holding its first item), and without this guard
        `_on_source_changed` would treat that as a real choice and
        re-prepare -- on this dock's own construction, and again on
        every `grids_changed`/`lines_changed`/`presets_changed`, none of
        which is a choice the user made.

        That guard has a cost this method has to pay itself: with one
        grid, one preset and transform `none` already selected, no combo
        can ever change again, so `_on_source_changed` -- the only other
        caller of `prepare()` before a `Choose...` is even possible -- can
        never fire either. Without the check below, nothing in this dock
        can ever reach `prepared` (fix round 1, Important 2). Gating it on
        `not self.engine.is_prepared and not self.engine.is_running` makes
        it a FIRST computation, never a recomputation: once a source has
        been prepared (or is being prepared), every later call here -- on
        an unrelated `presets_changed`/`lines_changed`, say -- leaves it
        alone, exactly like `_updating` already leaves the combos alone.
        This is deliberately not a `Prepare` button; see `_on_source_changed`
        for why one was rejected.
        """
        try:
            self._updating += 1
            try:
                site = self.session.site
                grid_ids = [g.id for g in site.grids] if site is not None else []
                preset_names = sorted(site.presets) if site is not None else []
                self._refill(self.grid_combo, grid_ids)
                self._refill(self.preset_combo, preset_names)
            finally:
                self._updating -= 1
            self.refresh_cube_combo()
            self._sync_included()
            self._update_included_label()
            self._refresh_source_status()
            # Cheap cluster (final review): the established pattern
            # (`processing_dock.py`'s own `has_line` loop) -- there is
            # nothing to choose lines FROM without a site open.
            self.choose_button.setEnabled(self.session.is_open)
            self.site_scope_button.setEnabled(self.session.is_open)
            if (
                self.source_choice() is not None
                and not self.engine.is_prepared
                and not self.engine.is_running
            ):
                self.prepare()
            # M12: the site scope follows the same five signals, and a
            # different survey forgets what the last one's site view held.
            if self._scope == "site":
                if self.session.is_open:
                    self._site.on_session_changed()
                else:
                    self.set_scope("grid")  # the survey closed under the site
            if self.session.site is not self._site_seen:
                self._site_seen = self.session.site
                self._site.forget()
        except Exception as exc:  # noqa: BLE001 -- a slot on five session signals
            _log(f"could not rebuild the slice source controls: {exc}")

    @staticmethod
    def _refill(combo: QComboBox, items: list[str]) -> None:
        """Replace `combo`'s items, keeping the current selection if it
        still exists among the new ones."""
        current = combo.currentText()
        combo.clear()
        combo.addItems(items)
        if current in items:
            combo.setCurrentText(current)

    def refresh_cube_combo(self, *, select: str | None = None) -> None:
        """Refill `cube_combo` from `session.site.cubes`, `"(unsaved)"`
        first -- called from `rebuild_source` (so a fresh `site_opened`
        picks up whatever `cubes` the reopened survey carries, alongside
        every other session signal `rebuild_source` already answers) and
        directly by `plugin.py`'s save handler, the moment a new record
        exists.

        Guarded by `_updating`, the same reason `rebuild_source` guards
        `grid_combo`/`preset_combo` (see its own docstring): refilling
        emits `currentTextChanged` even when the selection ends up
        unchanged, and without this guard that would read as the user
        picking a cube and fire `_on_cube_changed`/`restore_cube`.

        `select`, when given and present among the refreshed items, is
        set as the current text -- still inside this same `_updating`
        guard. Fix round 1, Minor: `plugin.save_cube` passes the id it
        just wrote, so `cube_combo` names the record that now exactly
        matches what is on screen, rather than sitting on "(unsaved)"
        despite nothing having changed since the save. Set this way
        rather than by a plain `self.cube_combo.setCurrentText(cube_id)`
        afterwards, which -- outside the guard -- would read as the user
        picking that very cube and dispatch a whole redundant
        `restore_cube` (and its ~0.9 s re-preparation) of the state that
        is already on screen.
        """
        try:
            self._updating += 1
            site = self.session.site
            cube_ids = sorted(site.cubes) if site is not None else []
            items = ["(unsaved)", *cube_ids]
            self._refill(self.cube_combo, items)
            if select is not None and select in items:
                self.cube_combo.setCurrentText(select)
        finally:
            self._updating -= 1

    def _default_included(self, grid_id: str | None) -> tuple[str, ...]:
        """Every line placed on `grid_id`, in survey order -- the default
        `LineChoiceDialog` starts from whenever the grid changes."""
        if grid_id is None or not self.session.is_open:
            return ()
        return tuple(
            key
            for key in self.session.keys()  # noqa: SIM118 -- SiteSession.keys(), not a dict
            if getattr(self.session.line_for_key(key).placement, "grid_id", None) == grid_id
        )

    def _sync_included(self) -> None:
        """Reset the inclusion set when the selected grid actually
        changed; otherwise, while it is still a seeded default (fix round
        1, Important 1), re-seed it -- more lines may have arrived under
        this same grid since it was last seeded -- and only once the user
        has made an explicit choice does this fall back to pruning stale
        keys, keeping survey order.

        An inclusion list carried over from a different grid means
        nothing here -- the whole point of `_default_included` is to
        start from something that does. And a default that stops tracking
        the grid's own line count is just as wrong: `plugin.py` builds
        this dock before any site exists, so the grid can go from
        nonexistent to empty to populated across three separate signals
        (`grids_changed` then `lines_changed`) before the user ever
        touches a combo, and the seed from the FIRST of those must not
        outlive the other two.

        An actual grid change is also the one moment `_seed_resolution_
        defaults` re-seeds `cell_spin`/`radius_spin` from `grid_id`'s own
        `default_spacing` (spec 4, spec 6.4) -- tied to this branch and
        not to every call here, for the same reason `_included_is_default`
        exists at all: reseeding on every `presets_changed` would silently
        overwrite a cell size the user picked for THIS grid.

        `dz_spin`/`z0_spin`/`z1_spin` are different: they need a LINE, not
        just a grid, and `plugin.py` builds this dock before any site
        exists -- new site, then add a grid, then import lines under it is
        the ordinary flow, not an edge case, and it fires `grids_changed`
        (this method's grid-changed branch) before any `lines_changed`
        that could seed them. `_seed_dz_z_defaults` is therefore also
        retried from the "still default" branch below, exactly where
        `_included` itself is already retried for the same reason -- once
        successfully seeded for a grid it does not re-run for that grid
        again, so a value the user later chooses is never clobbered.
        """
        grid_id = self.grid_combo.currentText() or None
        if grid_id != self._last_grid_id:
            self._last_grid_id = grid_id
            self._included = self._default_included(grid_id)
            self._included_is_default = True
            self._dz_z_seeded_for = None
            self._seed_resolution_defaults(grid_id)
            self._restore_remembered_source(grid_id)
            return
        if self._included_is_default:
            self._included = self._default_included(grid_id)
            self._seed_dz_z_defaults(grid_id)
            return
        valid = set(self.session.keys()) if self.session.is_open else set()
        self._included = tuple(k for k in self._included if k in valid)

    def _restore_remembered_source(self, grid_id: str | None) -> None:
        """M12 spec 4.2: bring back the preset and lines the user chose for
        `grid_id` the last time (`SiteSession.slice_source`). A restore, not
        a choice: the preset is selected inside the `_updating` guard so it
        does not read as a user change, and nothing is remembered here. A
        remembered preset that no longer exists is skipped; remembered line
        keys are filtered to the ones still on the grid, in survey order. A
        remembered `lines` of None means "every line", so it stays a
        default and a line imported later is still picked up. So does one
        that filters to nothing -- an empty choice, or lines that have all
        left the grid (final review D4): an empty inclusion set would leave
        This grid with nothing to prepare and no way back to the default."""
        entry = self.session.slice_source(grid_id) if grid_id and self.session.is_open else None
        if entry is None:
            return
        preset = entry.get("preset")
        if (
            preset
            and preset != self.preset_combo.currentText()
            and self.preset_combo.findText(preset) >= 0
        ):
            self._updating += 1
            try:
                self.preset_combo.setCurrentText(preset)
            finally:
                self._updating -= 1
        lines = entry.get("lines")
        if lines is not None:
            wanted = set(lines)
            every = self._default_included(grid_id)
            kept = tuple(k for k in every if k in wanted)
            self._included = kept if kept else every
            self._included_is_default = not kept

    def _remember_source(self, *, every_line: bool = False) -> None:
        """Record the user's own choice for the selected grid. Called only
        from a real user change (`_on_source_changed`, `set_included`),
        never from `rebuild_source`'s first computation: opening a site
        must not mark it dirty. `every_line` remembers `lines=None` whatever
        the inclusion set is: a cube record that names no line list (D4)."""
        grid_id = self.grid_combo.currentText()
        preset = self.preset_combo.currentText()
        if not grid_id or not preset or not self.session.is_open:
            return
        lines = None if every_line or self._included_is_default else self._included
        self.session.remember_slice_source(grid_id, preset=preset, lines=lines)

    def _update_included_label(self) -> None:
        """Spec 9.1: report the resulting memory before committing to the
        ~0.9 s of preparing it.

        `total` is the selected grid's own line count, and `included` is
        always a subset of it (fix round 3, Ruling Y corrects what this
        used to say: `LineChoiceDialog` now lists only the selected
        grid's own lines -- Ruling U, fix round 1 -- so there is no longer
        a way to include a line from elsewhere).

        The sample count is read from each line's header, before
        `time_zero` crops rows -- see `slices_plan.estimate_memory` and
        this dock's own module docstring for why that is "about", not
        exact, and why that is the honest choice.

        Ruling AN (M11 final review): also where the over-budget WARNING
        spec 9.1/7.4 asks for lives -- "warns and requires confirmation
        above the budget rather than hard-caps" was entirely unimplemented
        before this; this label reported "about N MB" and never compared
        it to anything. Warns, never blocks: spec 7.4 is explicit that an
        over-budget cube degrades to streaming rather than failing, so the
        estimate going over the budget changes nothing about what happens
        next -- only what the label says about it.
        """
        grid_id = self.grid_combo.currentText() or None
        total = len(self._default_included(grid_id))
        included = self._included
        samples = 0
        if self.session.is_open:
            for key in included:
                line = self.session.line_for_key(key)
                samples += line.n_traces * line.header.n_samples
        frame = self.engine.frame
        z = self.engine.z
        n_cells = frame.n_cells if frame is not None else 0
        nz = z.nz if z is not None else 0
        estimate = estimate_memory(samples, n_cells, nz)
        text = f"{len(included)} of {total} included · about {format_bytes(estimate.total_bytes)}"
        if estimate.total_bytes > DEFAULT_BUDGET_BYTES:
            text += " -- over the default budget; slices will stream rather than hold it all"
        self.included_label.setText(text)
        self._update_resident_check_label()

    def _update_resident_check_label(self) -> None:
        """Spec 9.2's own wording for the residency override, with the
        cost it names filled in: `engine.estimate.cube_bytes` is what
        turning it on actually adds -- the prepared lines are already held
        in memory in EITHER mode, so the whole-volume checkbox's own cost
        is the cube alone, not the total. Called from `_update_included_
        label` (every place that estimate could have changed) and from
        `_apply_resolution` (a resolution change moves `frame`/`z`, and so
        `engine.estimate`, without necessarily touching `_included`)."""
        mb = format_bytes(self.engine.estimate.cube_bytes)
        # Short on the face, the full wording in the tooltip. A QCheckBox
        # cannot elide or wrap its own text, so its minimum width is the
        # width of that text -- "Keep the whole volume in memory for
        # faster dragging (uses 118 MB)" measured a 555 px floor on this
        # dock, and a dock's minimum width is a hard floor on the main
        # window's. The cost stays on the face because spec 9.2 asks the
        # control to name what it costs.
        self.resident_check.setText(f"Keep the volume in memory ({mb})")
        self.resident_check.setToolTip(
            f"Keep the whole volume in memory for faster dragging.\n"
            f"Uses {mb} on top of the prepared lines, which are held either way."
        )

    def _on_resident_toggled(self, checked: bool) -> None:
        try:
            self.engine.set_always_resident(checked)
            # Spec 11: streaming and resident agree on every pixel, so
            # nothing on screen needs to change -- only the status line's
            # own "held in memory"/"redraws in" figures, which only
            # `refresh_slice()` recomputes.
            self.refresh_slice()
        except Exception as exc:  # noqa: BLE001 -- a slot on QCheckBox.toggled
            _log(f"could not toggle whole-volume residency: {exc}")

    def source_choice(self) -> SourceChoice | None:
        """What the three combos and the inclusion set currently say,
        or `None` when there is nothing to choose yet (no grid, or no
        preset)."""
        grid_id = self.grid_combo.currentText()
        preset = self.preset_combo.currentText()
        if not grid_id or not preset:
            return None
        transform_text = self.transform_combo.currentText()
        transform = NO_TRANSFORM if transform_text in ("", "none") else transform_text
        return SourceChoice(
            grid_id=grid_id, preset=preset, transform=transform, line_keys=self._included
        )

    def included_keys(self) -> tuple[str, ...]:
        return self._included

    def set_included(self, keys: tuple[str, ...]) -> None:
        """Replace the inclusion set outright -- the `Choose...` dialog's
        result, committed on `finished` by `plugin.open_line_choice_dialog`.

        Fix round 1, Important 2: DOES re-prepare, when the set actually
        changed -- accepting the line chooser is a choice made in this
        dock, the same test spec 9.1 applies to a combo change, and spec
        9.2's status line has no way to say "stale" usefully if nothing
        here ever notices the choice changed. Living here rather than in
        `plugin.open_line_choice_dialog`'s `finished` handler keeps the
        "changing what the user chose here re-prepares" rule in exactly
        one place (`_on_source_changed` is the other half of it), instead
        of pushing it onto every caller that could ever change the
        inclusion set. The equality check is the same no-op guard
        `ProcessingDock._on_form_committed` uses: clicking OK without
        actually changing anything must not spend another ~0.9 s.

        Cheap cluster (final review): `_included_is_default` is cleared
        only for a NON-EMPTY `keys` -- clearing it unconditionally meant
        accepting the line chooser on a grid that is still EMPTY (`keys ==
        ()`, `self._included` already `()` too, so `changed` is `False`
        and nothing else here would otherwise notice) permanently latched
        it `False`, disabling `_sync_included`'s "still default" retry
        branch for this grid forever. `_seed_dz_z_defaults` depends on
        that retry to seed `dz`/`z0`/`z1` once lines actually arrive
        (`plugin.py` builds this dock before any site exists, so "grid
        added, then empty" is the ordinary flow, not an edge case) -- with
        the flag latched, lines imported afterwards left `z0 = 0.0`
        standing on a SIR-4000 file with a negative `position_ns`, giving
        `CoverageError` on every slice with no visible route back to a
        working default.
        """
        keys = tuple(keys)
        changed = keys != self._included
        self._included = keys
        if keys:
            self._included_is_default = False
        # Task 7: an explicit line-chooser choice is not a restore, and
        # must not inherit one still in flight -- see `_pending_palette`'s
        # own docstring for why a manual change clears it here and in
        # `_on_source_changed` rather than leaving `_on_prepared` to apply
        # a palette this choice has nothing to do with.
        self._pending_palette = None
        self._mark_cube_unsaved()
        self._update_included_label()
        self._refresh_source_status()
        if changed:
            self._remember_source()
            self.prepare()

    def _live_preset_steps(self, preset_name: str) -> list[dict]:
        return list(self.session.site.presets.get(preset_name, [])) if self.session.is_open else []

    def _prepared_steps_match(self, preset_name: str) -> bool:
        """Whether `preset_name`'s steps, as they stand RIGHT NOW, are the
        same recipe `engine.provenance()` says was actually captured at
        dispatch time (Ruling K) -- `False` after an in-place edit to the
        selected preset, even though the three combos and the inclusion
        set show no change at all. Shared by `prepare()`'s no-op guard
        (Ruling X) and `_refresh_source_status()` (Ruling R), so the two
        never drift apart on what "nothing has changed" means."""
        try:
            prepared_steps = list(self.engine.provenance().steps)
        except (RuntimeError, KeyError):
            # RuntimeError: provenance() raises when no source is chosen.
            # Both callers already know `engine.choice` is not None before
            # reaching here, so this is unreachable today -- guarded
            # anyway, since this method's whole job is being the one place
            # this question is answered, not assuming its callers can
            # never change.
            #
            # KeyError (final review, Minor 6): provenance() also raises
            # this once the FIRST prepared line has been removed from the
            # session -- see `_resolved_velocity`'s own docstring, which
            # widens the identical catch for the identical reason. A
            # "does not match" answer here is conservative and safe either
            # way: both callers already treat a mismatch as "stale, not
            # unprepared".
            return False
        return self._live_preset_steps(preset_name) == prepared_steps

    def prepare(self) -> None:
        """Build a `SourceChoice` from the three combos and the inclusion
        set, and hand it to the engine.

        The one place Ruling 2's refusal (a preset that already carries
        the amplitude transform) becomes visible: `set_source` raises
        `ValueError` synchronously, before any task is dispatched, and
        this is where that turns into something the user can read.

        Catches `Exception`, not just `ValueError` (fix round 1, M3): a
        preset naming a step the registry no longer has raises `KeyError`
        from `_start_task`'s own main-thread validation, and a bare
        `except ValueError` here let that escape to `_on_source_changed`'s
        log-only guard instead of the one place a refusal is meant to
        become visible.

        A no-op when the computed choice already equals `engine.choice`
        AND the selected preset's live steps still match what was
        actually captured at dispatch time (`_prepared_steps_match`).

        This is now an EFFICIENCY guard, not a safety one (fix round 3,
        Ruling X corrects what this docstring used to claim):
        `SliceEngine.set_source` itself cancels and confirms any
        in-flight preparation before dispatching a new one (Ruling V,
        then Ruling W for the reentrant case `set_source`'s own guard
        closes), so calling it again for an identical choice would only
        repeat ~0.9 s of identical work, not risk the concurrency this
        guard was once the only thing preventing.

        Comparing the steps, not just the combos, is what makes the
        no-op guard correct rather than merely convenient: an in-place
        edit to the SELECTED preset changes nothing the three combos or
        the inclusion set can see. Before this comparison existed, the
        documented retry path -- calling `prepare()` again -- silently
        did nothing after such an edit, and with one grid and one preset
        there was no OTHER combo left to toggle: the source stayed
        "stale" permanently, with the only escape being to toggle the
        transform away and back, paying for two preparations and showing
        the wrong transform in between.

        Task 6 fix round 1, Important 2: refreshes `save_button`/
        `export_button` (and the status line/text) immediately after a
        successful dispatch, not just in `_on_prepared`/`_on_engine_error`
        once the ~0.9 s task finishes. `set_source` clears `engine._lines`
        SYNCHRONOUSLY before returning here, so `engine.is_prepared` is
        already `False` the moment this call returns -- without this,
        both buttons stayed visibly enabled for the whole re-preparation
        window, and a click on either during it reached the engine with a
        stale response (see `SliceEngine.cube()`'s own new guard, this
        same fix round, for what "Save cube..." did there before that
        guard existed). Deliberately not in a blanket `finally`: the
        `except` branch below already writes a specific, readable refusal
        (e.g. Ruling 2's preset-transform-conflict message) straight into
        `source_status`, and recomputing it there would immediately
        overwrite that message with the generic "not prepared" this
        method would otherwise compute.
        """
        # M12, ruling R-P5: This grid's engine never prepares while the site
        # is showing, nor while a site task may still run (a cancel whose
        # bounded wait gave up): two preparations at once segfault (trap 1).
        # The preparation is owed, and run by `_run_pending_grid_prepare`.
        if self._scope == "site" or self.site_engine.has_live_task:
            self._grid_prepare_pending = True
            if self._scope == "grid":
                self._grid_retry.start()
            return
        choice = self.source_choice()
        if (
            choice is not None
            and choice == self.engine.choice
            and self._prepared_steps_match(choice.preset)
        ):
            return
        try:
            self.engine.set_source(choice)
            self._refresh_source_status()
        except Exception as exc:  # noqa: BLE001 -- see the docstring above
            message = str(exc)
            self.source_status.setText(message)
            # Buttons only, not the full `_refresh_source_status()` call
            # above -- see the docstring: that would overwrite `message`
            # (a specific refusal) with a generic "not prepared". `_lines`
            # is already cleared by `set_source` even on this path (it
            # runs before the conflict check that raises), so this is
            # never stale.
            self.save_button.setEnabled(self.engine.is_prepared)
            self.export_button.setEnabled(self.engine.is_prepared)
            self.error.emit(message)

    def _on_source_changed(self, _text: str = "") -> None:
        """Changing the grid, preset or transform re-runs preparation as
        a `QgsTask` (spec 9.1) -- not a violation of "nothing runs
        automatically": the user chose it, and preparation is the
        execution of that choice, not an inference about it.

        Returns immediately while `self._updating` is non-zero: see
        `rebuild_source`'s docstring for why refilling a combo must not
        read as this kind of choice. No `Prepare` button either --
        `SliceEngine._generation` discards every stale result, so three
        rapid combo changes are safe without debouncing, and a button
        would just be a second way to do what the combos already do
        (spec 9.1 rejected exactly that shape once, for `Edit...`).
        """
        if self._updating:
            return
        try:
            # Task 7: a manual combo change, not a restore -- see
            # `_pending_palette`'s own docstring for why this must not
            # inherit a palette a still-preparing `restore_cube` owes a
            # DIFFERENT preparation.
            self._pending_palette = None
            self._mark_cube_unsaved()
            self._sync_included()
            self._remember_source()
            self._update_included_label()
            self.prepare()
        except Exception as exc:  # noqa: BLE001 -- a slot on currentTextChanged
            _log(f"could not react to a source change: {exc}")

    # ---- status ----------------------------------------------------------
    def _refresh_source_status(self) -> None:
        """The one place spec 9.2's three states get computed (fix round
        1, Ruling R): `not prepared`, `stale · ...`, or `prepared · N
        lines`. Called from `rebuild_source`, `set_included`, and the
        engine callbacks below -- everywhere the truth this reports could
        have just changed.

        "Stale" covers more than the in-place-preset-edit question this
        dock's design already settled (no auto re-prepare there -- see
        `prepare`'s docstring): it is also what accepting the line chooser
        leaves behind until a re-prepare finishes (`source_choice()` now
        differs from `engine.choice` in `line_keys`), and what a DELETED
        selected preset leaves behind -- `_refill` cannot restore a name
        that no longer exists, so the combo silently jumps to a fallback
        while `_updating` suppresses `_on_source_changed`, and without
        this check the status line would keep naming a preset the engine
        never actually prepared. Names what diverged specifically -- the
        grid, the preset (by name or by an in-place edit to its steps),
        the transform, or the lines -- rather than blaming "the preset"
        for all four (fix round 3, Ruling Y: the review found every
        non-`line_keys` mismatch printing the same preset-flavoured
        wording, which a grid or transform change had no business doing).

        Left untouched while a task is running: `_on_progress` already
        owns the status line for that duration, and `engine.line_count`
        would otherwise report last time's count under this time's claim.

        The "otherwise" branch is not simply `prepared · N lines` (fix
        round 3, Ruling Y): after `_on_engine_error` -- a failed `addTask`,
        say -- `engine.choice` still names the attempted choice and every
        structural check above still passes, so without this the
        recomputed line read `prepared · 0 lines`, a claim that something
        succeeded when scheduling itself failed. A genuinely EMPTY
        selection (`choice.line_keys == ()`) is excluded from that check
        on purpose: `0 of 0` legitimately prepares, and is not the failure
        this guards against.
        """
        # Task 6: mirrors `engine.is_prepared` on every call here,
        # regardless of the early `is_running` return just below -- a
        # preparation in flight must disable both buttons just as
        # cleanly as no source chosen at all does, and this is the one
        # place spec 9.2's "the status could have just changed" already
        # gets recomputed everywhere it matters (rebuild_source,
        # set_included, and both engine callbacks).
        if self._scope == "site":
            self._site.update_export_button()
        else:
            self.save_button.setEnabled(self.engine.is_prepared)
            self.export_button.setEnabled(self.engine.is_prepared)
        if self.engine.is_running:
            return
        choice = self.engine.choice
        if choice is None:
            self.source_status.setText("not prepared")
            return
        current = self.source_choice()
        if current is None or current.grid_id != choice.grid_id:
            self.source_status.setText("stale · the grid changed since this was prepared")
            return
        if current.preset != choice.preset:
            self.source_status.setText("stale · the preset changed since this was prepared")
            return
        if current.transform != choice.transform:
            self.source_status.setText("stale · the transform changed since this was prepared")
            return
        if current.line_keys != choice.line_keys:
            self.source_status.setText("stale · the lines changed since this was prepared")
            return
        if not self._prepared_steps_match(choice.preset):
            self.source_status.setText("stale · the preset changed since this was prepared")
            return
        if not self.engine.is_prepared and choice.line_keys:
            self.source_status.setText("not prepared · every line failed")
            return
        self.source_status.setText(f"prepared · {self.engine.line_count} lines")

    # ---- engine callbacks -----------------------------------------------
    def _on_progress(self, done: int, total: int) -> None:
        try:
            self.source_status.setText(f"preparing… {done} of {total}")
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not report slice-source progress: {exc}")

    def _clamp_z_to_prepared(self) -> bool:
        """Pull `z0`/`z1` inside the range every PREPARED line covers.

        Returns whether anything moved, because the caller must then push
        the corrected geometry at the engine before asking it for a slice.

        `_seed_dz_z_defaults` seeds these two from the chosen line's raw
        DZT header, which is the best estimate available before a
        preparation has run but is only right for a preset that leaves the
        sample axis alone. `time_zero` -- first in the ordinary preset,
        not an exotic one -- crops rows off the FRONT, and on this repo's
        own real files drops 49 of 512, moving the start from -11.086 ns
        to -0.476 while the header still says -11.086. The cube then asked
        for 10.6 ns of two-way time that no prepared line has, and the
        first slice raised `CoverageError` naming the line. Correcting it
        here, against `engine.prepared_z_bounds()`, is the only point
        where the processed extent is actually known.

        Deliberately a clamp and not a re-seed: a range the user has
        narrowed by hand is still theirs, and `CoverageError` still
        reaches them for lines that genuinely disagree with each other
        (spec 9.1 wants that acted on, not hidden). Only a range reaching
        OUTSIDE what the data can supply is corrected.
        """
        bounds = self.engine.prepared_z_bounds()
        if bounds is None:
            return False
        low, high = bounds
        changed = False
        self._updating += 1
        try:
            for spin, bound, upper in (
                (self.z0_spin, low, False),
                (self.z1_spin, high, True),
            ):
                value = spin.value()
                if (value > bound) if upper else (value < bound):
                    spin.blockSignals(True)
                    try:
                        spin.setValue(_snap_inside(bound, spin.decimals(), upper=upper))
                    finally:
                        spin.blockSignals(False)
                    changed = True
        finally:
            self._updating -= 1
        return changed

    def _on_prepared(self) -> None:
        try:
            if self._scope == "site":
                # M12: the Resolution and Display widgets are the site's
                # now; This grid's clamp and redraw run on the way back.
                self._shared_limit_cache = None
                self._grid_prepared_away = True
                return
            # Before anything asks the engine for a slice: the seeded z
            # range was read off a raw DZT header, and a preset that crops
            # the sample axis makes that range uncoverable. See the method.
            clamped = self._clamp_z_to_prepared()
            # Final review, Important 1 (part 3): the cache's key
            # (`n_levels`, `engine.choice`, `engine.mode`, `radius_cells`)
            # cannot always tell a re-preparation happened -- `_on_grids_
            # changed` re-prepares with the SAME `SourceChoice` object
            # after a grid move, so none of those four values need to
            # change even though the prepared lines' own coordinates just
            # did. Every successful preparation lands here, so clearing
            # unconditionally here is what actually keeps the cache from
            # outliving the data it was measured over.
            self._shared_limit_cache = None
            self._update_included_label()
            self._refresh_source_status()
            # Spec 8's rule enforced here, not just described: the combo
            # only ever lists tables that suit the source's OWN polarity
            # (`engine.output_unipolar`), which can only be known once a
            # preparation has actually run.
            self._refill_palette_combo()
            # Task 7: reapply a palette `restore_cube` owed this
            # preparation -- `_refill_palette_combo` just reset the combo
            # to a computed default regardless of what was there before
            # (its own docstring explains why), which would otherwise
            # silently discard a restored palette the instant this async
            # preparation finished. Consumed (and cleared) every time this
            # runs, restore-triggered or not, so a stale value from an
            # earlier, unrelated restore can never outlive the next
            # `_on_prepared`; a palette not currently offered (the wrong
            # polarity, say) is simply skipped, not raised.
            pending, self._pending_palette = self._pending_palette, None
            if pending is not None:
                names = [self.palette_combo.itemText(i) for i in range(self.palette_combo.count())]
                if pending in names:
                    self.palette_combo.blockSignals(True)
                    try:
                        self.palette_combo.setCurrentText(pending)
                    finally:
                        self.palette_combo.blockSignals(False)
            # Without this, a source that finishes preparing while the
            # Position/Resolution controls have not themselves changed
            # since (the ordinary case: their debounce already applied a
            # seeded default while the ~0.9 s preparation was still
            # in flight) would leave the map and `current_values()`
            # exactly as `refresh_slice()`'s own early return last left
            # them -- `None` -- until the user happens to touch a control.
            #
            # `_apply_resolution()` rather than `refresh_slice()` when the
            # clamp moved a spin: the engine is still holding the ZAxis
            # built from the UNcorrected range, and the spins' own
            # debounce was blocked along with their signals, so nothing
            # else would ever push the correction through.
            if clamped:
                self._apply_resolution()
            else:
                self.refresh_slice()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not report that the slice source is prepared: {exc}")

    def _on_engine_error(self, message: str) -> None:
        try:
            self.error.emit(message)
            self._refresh_source_status()
        except Exception:  # noqa: BLE001 -- see the module docstring
            _log(f"could not report a slice engine error: {message}")

    # ---- cube combo (Task 7: reproducing a saved cube) --------------------
    def _mark_cube_unsaved(self) -> None:
        """Fall back to `"(unsaved)"` the moment a widget that decides
        what the cube IS moves away from a just-restored cube's own
        values -- a `view` field (Display, Position, the fill radius) does
        not change the array, so moving only those leaves the combo's
        claim still true; the Source combos and the four `Resolution`
        geometry spins do, and are wired to call this (see their own
        connections and `_on_source_changed`/`set_included`).

        Gated on `self._updating` for the same reason `_on_source_changed`
        is: `restore_cube` sets these same widgets itself while restoring,
        and without this guard restoring a cube would immediately
        un-restore its own combo selection.
        """
        try:
            if self._updating or self._scope == "site":
                return
            if self.cube_combo.currentText() != "(unsaved)":
                self.cube_combo.setCurrentText("(unsaved)")
        except Exception as exc:  # noqa: BLE001 -- reached directly from valueChanged
            _log(f"could not update the cube combo: {exc}")

    def _on_cube_changed(self, text: str) -> None:
        """`cube_combo.currentTextChanged`: `"(unsaved)"` is a label, not
        an action (see the class's own module docstring for the dock's
        general "nothing runs automatically" rule -- picking a name that
        means "nothing chosen" is not choosing something); any real cube
        id restores it."""
        if self._updating:
            return
        if not text or text == "(unsaved)":
            return
        try:
            self.restore_cube(text)
        except Exception as exc:  # noqa: BLE001 -- a slot on currentTextChanged
            _log(f"could not restore the cube {text!r}: {exc}")

    def view_settings(self) -> ViewSettings:
        """The six values `cube_record`'s `view` half carries, read off
        the widgets that hold them right now. `plugin.save_cube` calls
        this so a saved record carries what was actually on screen at the
        moment of saving, not a value re-derived some other way."""
        return ViewSettings(
            thickness_ns=self.thickness_spin.value(),
            step_ns=self.step_spin.value(),
            radius_m=self.radius_spin.value(),
            palette=self.palette_combo.currentText(),
            stretch=self.stretch_combo.currentText(),
            coverage=self.coverage_check.isChecked(),
        )

    def apply_view(self, view: ViewSettings) -> None:
        """The inverse of `view_settings()`: write `view`'s six fields
        back onto their widgets, signals blocked throughout.

        `thickness_spin`/`step_spin`/`stretch_combo`/`palette_combo`/
        `coverage_check` are wired straight to `refresh_slice()`,
        unconditionally -- unlike the Source combos, which check
        `self._updating` themselves -- so setting all of them without
        blocking would fire that many redundant redraws before
        `restore_cube`'s own single `prepare()` produces the real
        picture. `radius_spin` only ever restarts the Resolution
        debounce (harmless to retrigger, and `flush_debounce()` applies
        it deliberately, once, right after `restore_cube` finishes
        setting every widget), but is blocked here too so this method is
        a complete, self-contained inverse of `view_settings()` regardless
        of what a future caller does after it.

        `palette` and `stretch` are each set only if currently offered --
        both are non-editable combos, and Qt's `setCurrentText` on one is
        a silent no-op for a value not among its items (fix round 1,
        Minor: the same failure class Ruling AK's `restore_cube` check
        refuses loudly for the three Source combos; `stretch_combo`'s own
        two items are fixed today, so this is a defensive match for that
        method's own membership check rather than a reachable bug yet).
        `palette_combo` specifically still lists whatever polarity the
        PREVIOUS source prepared under, since this runs before
        `restore_cube` even sets the three source combos -- `restore_cube`
        stashes the palette in `_pending_palette` for `_on_prepared` to
        try again once the new source's own polarity is known (see that
        field's own docstring); neither combo's mismatch raises here,
        since `view` is display-only and a display field silently keeping
        its prior value is not the "different picture under this cube's
        name" failure Ruling AK's Source-combo check exists to prevent.
        """
        widgets = (
            self.thickness_spin,
            self.step_spin,
            self.radius_spin,
            self.palette_combo,
            self.stretch_combo,
            self.coverage_check,
        )
        for widget in widgets:
            widget.blockSignals(True)
        try:
            self.thickness_spin.setValue(view.thickness_ns)
            self.step_spin.setValue(view.step_ns)
            self.radius_spin.setValue(view.radius_m)
            palette_names = [
                self.palette_combo.itemText(i) for i in range(self.palette_combo.count())
            ]
            if view.palette in palette_names:
                self.palette_combo.setCurrentText(view.palette)
            stretch_names = [
                self.stretch_combo.itemText(i) for i in range(self.stretch_combo.count())
            ]
            if view.stretch in stretch_names:
                self.stretch_combo.setCurrentText(view.stretch)
            self.coverage_check.setChecked(view.coverage)
        finally:
            for widget in widgets:
                widget.blockSignals(False)

    def restore_cube(self, cube_id: str) -> None:
        """Bring every control back to the state that produced `cube_id`'s
        saved cube (`session.site.cubes[cube_id]`, read through
        `recipe_from_record`), then re-prepare.

        Guards its whole body -- this runs from `_on_cube_changed`, a slot
        on `currentTextChanged`, and is itself a public entry point -- and
        reports a refused record (`recipe_from_record`'s `ValueError` for
        a field that is PRESENT and wrong, an unknown `cube_id`, or a
        grid/preset/transform this site no longer has -- see the next
        paragraph) through `error`/`source_status`, exactly as `prepare()`
        already reports Ruling 2's preset-transform conflict: a
        caller-visible refusal, not a `_log` only a developer would ever
        see. Fix round 1, Minor: the refusal also resets `cube_combo`
        itself to "(unsaved)" -- `currentTextChanged` does not re-fire for
        the same text, so without this a user could not even retry a
        refused selection without picking something else first.

        Fix round 1, Ruling AK: `grid_combo`/`preset_combo`/
        `transform_combo` are all non-editable, and Qt's `setCurrentText`
        on a non-editable combo silently does nothing when the text is
        not among its items -- a preset renamed or a grid removed since
        this cube was saved would otherwise leave the PREVIOUS selection
        in place, `prepare()` would go on to succeed against it, and both
        the status line and `cube_combo` would keep naming this cube over
        a different picture. Checked with `findText` for all three,
        together, BEFORE any widget is touched, so a refusal names every
        missing field at once and leaves the dock entirely as it was
        (partial restore is not an acceptable middle ground here: a user
        can act on "preset 'x' no longer exists", not on a picture that
        is quietly wrong).

        `_updating` is raised around every widget this sets: the three
        Source combos are already gated on it (`_on_source_changed`), and
        so is `_mark_cube_unsaved` -- without this, restoring a cube would
        immediately fall back to "(unsaved)" the moment it set the very
        combos and Resolution spins it just restored. `apply_view` (called
        first, per the brief's own ordering: it is what the Display/
        Position widgets need before anything else touches them) blocks
        signals on top of that for the widgets `_updating` alone does not
        cover.

        `_last_grid_id`/`_dz_z_seeded_for` are updated to the restored
        grid so a later, unrelated Source change does not read this as a
        genuine grid change and silently widen `_included` back to every
        line on the grid, or re-seed Resolution from the grid's generic
        defaults (`_sync_included`'s job, for a transition this is not).

        `recipe.choice.line_keys` is set unconditionally, even for a
        record with no `lines` key at all -- `recipe_from_record` cannot
        tell "the key was missing" from "the key was an empty list" (both
        read back as `()`), so restoring an old-format record leaves the
        inclusion set empty rather than guessing the whole grid was meant.

        `recipe.resolution`/`recipe.view` being `None` leaves the
        corresponding widgets exactly where they were -- `CubeRecipe`'s
        own contract for an old-format record.
        """
        try:
            record = self.session.site.cubes[cube_id]
            recipe = recipe_from_record(record)
            transform_text = (
                "none" if recipe.choice.transform == NO_TRANSFORM else recipe.choice.transform
            )
            # Fix round 1, Ruling AK: checked -- and refused BEFORE any
            # widget is touched -- rather than handed straight to
            # `setCurrentText`. All three combos are non-editable, and Qt
            # makes `setCurrentText` on a non-editable combo a silent
            # no-op when the text is not among its items: a preset
            # renamed or a grid removed since the cube was saved would
            # otherwise leave the PREVIOUS selection in place, `prepare()`
            # would go on to succeed against it, and the status line and
            # `cube_combo` would both go on claiming this cube's name over
            # a different picture. Missing lines are already named
            # individually by `set_source` through `_report`; a missing
            # grid/preset/transform deserves the same treatment, not a
            # silent substitution -- `recipe_from_record`'s own docstring
            # names exactly this as the one failure a reproducibility
            # feature must not have. Checked here, together, so a refusal
            # names every field that is missing, not just the first.
            missing = [
                f"{label} {text!r}"
                for label, combo, text in (
                    ("grid", self.grid_combo, recipe.choice.grid_id),
                    ("preset", self.preset_combo, recipe.choice.preset),
                    ("transform", self.transform_combo, transform_text),
                )
                if combo.findText(text) < 0
            ]
            if missing:
                raise ValueError(
                    f"cube {cube_id!r} refers to {', '.join(missing)}, "
                    "no longer present in this site"
                )
            self._updating += 1
            try:
                if recipe.view is not None:
                    self.apply_view(recipe.view)
                self._pending_palette = recipe.view.palette if recipe.view is not None else None
                self._included = recipe.choice.line_keys
                self._included_is_default = False
                self._last_grid_id = recipe.choice.grid_id
                self._dz_z_seeded_for = recipe.choice.grid_id
                self.grid_combo.setCurrentText(recipe.choice.grid_id)
                self.preset_combo.setCurrentText(recipe.choice.preset)
                self.transform_combo.setCurrentText(transform_text)
                if recipe.resolution is not None:
                    self.cell_spin.setValue(recipe.resolution.cell)
                    self.dz_spin.setValue(recipe.resolution.dz_ns)
                    self.z0_spin.setValue(recipe.resolution.t0_ns)
                    self.z1_spin.setValue(recipe.resolution.t1_ns)
            finally:
                self._updating -= 1
            # M12 spec 4.2 (controller ruling T2-b): picking a saved cube is
            # a user choice, so its preset and lines become this grid's
            # remembered source. `restore_cube` is reached only from
            # `_on_cube_changed`, which returns early under `_updating`, so
            # no automatic path (opening a site) remembers through here. A
            # record with no `lines` key names no line list: it is remembered
            # as every line, not as an empty choice (final review D4).
            self._remember_source(every_line="lines" not in record)
            self._update_included_label()
            self.flush_debounce()
            self.prepare()
            # Fix round 1, Minor: `prepare()` is a no-op (its own guard)
            # when the computed choice already equals `engine.choice` and
            # the preset's live steps still match -- reachable by
            # restoring a cube, changing only e.g. the cell size, then
            # reselecting the SAME cube from the combo. Without this, a
            # `_pending_palette` stashed just above would sit unconsumed
            # until some LATER, unrelated preparation's `_on_prepared`
            # fires and applies a palette that restore no longer has
            # anything to do with -- exactly the staleness this field's
            # own docstring otherwise claims cannot happen.
            if not self.engine.is_running:
                self._pending_palette = None
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            message = f"could not restore cube {cube_id!r}: {exc}"
            self.source_status.setText(message)
            self.error.emit(message)
            # Fix round 1, Minor: a refused restore must not leave
            # `cube_combo` naming a cube the dock did not actually
            # restore -- `currentTextChanged` does not re-fire for the
            # same text, so without this the user could not even retry
            # the same (still-broken) selection without picking something
            # else first. `_updating` because this IS a widget set that
            # must not itself read as a fresh choice.
            self._updating += 1
            try:
                self.cube_combo.setCurrentText("(unsaved)")
            finally:
                self._updating -= 1

    # ---- Position/Resolution/Display -------------------------------------
    def _seed_resolution_defaults(self, grid_id: str | None) -> None:
        """Re-seed `cell_spin`/`radius_spin` from the grid that was just
        selected -- called only from `_sync_included`'s grid-changed
        branch, so an unrelated session signal never overwrites a value
        the user picked for the grid that is still selected. Spec 4's "no
        smaller than the trace spacing, no larger than half the line
        spacing", and #81's 0.2 m cell and half-spacing fill radius -- both
        need only the grid itself. `dz_spin`/`z0_spin`/`z1_spin` are seeded
        separately, by `_seed_dz_z_defaults`: see its own docstring for
        why a grid change is not the only moment that needs to try them.
        """
        if grid_id is None or not self.session.is_open:
            return
        try:
            grid = self.session.grid(grid_id)
        except KeyError:
            return
        # The floor is raised BEFORE the value is set, so the seeded
        # value is clamped into the affordable range rather than sitting
        # below a minimum that arrives afterwards. On any ordinary grid
        # `smallest_safe_cell` is well under the spin's own 0.01 m and
        # this changes nothing; it only bites where the arithmetic really
        # does run away (walkthrough round 2, W7).
        floor = max(0.01, smallest_safe_cell(grid.size_x, grid.size_y))
        self.cell_spin.setMinimum(floor)
        self.cell_spin.setValue(default_cell(grid.default_spacing, floor))
        self.radius_spin.setValue(DEFAULT_RADIUS_SPACINGS * grid.default_spacing)
        self._seed_dz_z_defaults(grid_id)

    def _seed_dz_z_defaults(self, grid_id: str | None) -> None:
        """Re-seed `dz_spin`/`z0_spin`/`z1_spin` from `grid_id`'s first
        included line's own header, at most once per grid.

        These three need a LINE, not just a grid -- there is no such
        thing as a grid's own native sample interval -- and `plugin.py`
        builds this dock before any site exists: new site, then add a
        grid, then import lines under it is the ORDINARY flow, not an
        edge case, and it fires `grids_changed` (which is when
        `_seed_resolution_defaults` runs) before any line exists to read.
        Seeding these only from the grid-changed branch left them stuck
        at their generic fallback construction-time values
        (`dz=1.0, z0=0.0, z1=100.0`) forever in that flow -- which not
        only states the wrong numbers, it silently asks for two-way times
        `plan_line` cannot cover: `z0=0.0` on a line whose own recording
        starts at a negative `position_ns` (as real SIR-4000 files do)
        raises `CoverageError` the moment anything tries to slice it.
        `_sync_included` therefore also retries this from its "still
        default" branch. `_dz_z_seeded_for` is what keeps a retry from
        re-running once it has genuinely succeeded for this grid: without
        it, every `rebuild_source()` (an unrelated `presets_changed`,
        say) would re-seed over a value the user has since changed by
        hand.
        """
        if self._dz_z_seeded_for == grid_id:
            return
        included = self._default_included(grid_id)
        if not included:
            return
        header = self.session.line_for_key(included[0]).header
        # One sample per arrow click, on all three of the time spins: on
        # a time axis nothing else is a meaningful increment, and Qt's
        # 1.0 ns default was five samples at this repo's own sampling
        # (walkthrough round 2, W7).
        for _spin in (self.dz_spin, self.z0_spin, self.z1_spin):
            _spin.setSingleStep(header.dt_ns)
        self.dz_spin.setValue(header.dt_ns)
        self.z0_spin.setValue(header.position_ns)
        self.z1_spin.setValue(header.position_ns + (header.n_samples - 1) * header.dt_ns)
        self._dz_z_seeded_for = grid_id

    def _refill_palette_combo(self) -> None:
        """Spec 8's rule made concrete: only tables that suit the
        source's actual polarity are ever offered, defaulting to the one
        named for that polarity rather than preserving whatever the combo
        happened to show for a differently-polarised source before.

        Fix round 1, M2: signals blocked around the refill. Unblocked,
        `currentTextChanged` -- wired to `refresh_slice()` -- fires once
        going from empty to whatever Qt auto-selects as the first item
        (itself, on the very first call, an "unknown colormap ''" error
        logged from `refresh_slice()`'s own broad guard) and again if
        `setCurrentText(default)` picks something else, each a spurious
        full rebuild on top of the one `_on_prepared()` already calls
        explicitly right after this returns.
        """
        unipolar = self.engine.output_unipolar
        names = colormap_names(unipolar=unipolar)
        default = "amp_black_high" if unipolar else DEFAULT_COLORMAP
        self.palette_combo.blockSignals(True)
        try:
            self.palette_combo.clear()
            self.palette_combo.addItems(names)
            if default in names:
                self.palette_combo.setCurrentText(default)
        finally:
            self.palette_combo.blockSignals(False)

    def current_window(self) -> SliceWindow | None:
        z = self.engine.z
        if z is None:
            return None
        top_ns = z.t0_ns + self.slice_slider.value() * z.dz_ns
        k0, k1 = z.level_range(top_ns, max(z.dz_ns, self.thickness_spin.value()))
        return SliceWindow(k0, k1)

    def current_frame(self) -> CubeFrame | None:
        return self.engine.frame

    def current_values(self) -> np.ndarray | None:
        return self._values

    def radius_cells(self) -> int:
        return max(0, int(round(self.radius_spin.value() / self.cell_spin.value())))

    def _step_levels(self, z: Any) -> int:
        """`step_spin`'s nanoseconds, in levels of `z` -- at least 1, so a
        step spin box smaller than `dz_ns` still advances by something
        rather than stalling `step_slice`/the readout's index forever."""
        return max(1, int(round(self.step_spin.value() / z.dz_ns)))

    def thickness_step_levels(self) -> tuple[int, int]:
        """`(thickness_levels, step_levels)`, in levels of the current z
        axis -- the same rounding rule `current_window()` and
        `_step_levels()` already apply, exposed here so Task 6's export
        (`plugin.py`) derives them once, the same way, rather than
        re-deriving the formula and risking a mismatch between what the
        dock is currently showing and what a GeoTIFF actually gets."""
        if self._scope == "site":
            site_z = self.site_engine.site_z
            if site_z is None:
                raise RuntimeError("no site geometry: prepare the grids and set a resolution")
            return site_scope.levels(site_z, self.thickness_spin.value(), self.step_spin.value())
        z = self.engine.z
        if z is None:
            raise RuntimeError("no slice geometry: choose a source and a resolution first")
        thickness_levels = max(1, int(round(self.thickness_spin.value() / z.dz_ns)))
        return thickness_levels, self._step_levels(z)

    def step_slice(self, delta: int) -> None:
        """Move the slider by `delta` STEPS, not levels -- the unit a
        person navigating overlapping slices actually thinks in."""
        z = self.site_engine.site_z if self._scope == "site" else self.engine.z
        step_levels = self._step_levels(z) if z is not None else 1
        target = self.slice_slider.value() + delta * step_levels
        target = max(self.slice_slider.minimum(), min(self.slice_slider.maximum(), target))
        self.slice_slider.setValue(target)

    def flush_debounce(self) -> None:
        """Apply a pending Resolution change immediately. Used by tests,
        and by anything else that needs the current geometry right now
        rather than up to 120 ms from now."""
        self._debounce.stop()
        self._apply_resolution()

    def _apply_resolution(self) -> None:
        try:
            if self._scope == "site":
                self._apply_site_resolution()
                return
            choice = self.engine.choice
            previous_time: float | None = None
            old_z = self.engine.z
            if old_z is not None:
                previous_time = old_z.t0_ns + self.slice_slider.value() * old_z.dz_ns
            try:
                resolution = Resolution(
                    cell=self.cell_spin.value(),
                    dz_ns=self.dz_spin.value(),
                    t0_ns=self.z0_spin.value(),
                    t1_ns=self.z1_spin.value(),
                )
            except ValueError as exc:
                # __post_init__'s own validation (e.g. z1 <= z0) -- a
                # refusal the user can read, not a crash from a QTimer slot.
                self.error.emit(str(exc))
                return
            # Defence in depth behind `cell_spin`'s own floor: a
            # `Resolution` can also arrive from a saved cube record
            # (`restore_cube`), which never passed through this spin box
            # and may have been written against a different grid.
            # Refused rather than warned-and-allowed: spec 7.4's
            # "warn, do not hard-cap" is about MEMORY BUDGETS, where the
            # fallback is to degrade to streaming. There is no degraded
            # mode for a frame this size -- the per-slice array alone is
            # what cannot be allocated -- so the honest answer is to say
            # so, and to say what would work.
            grid_now = self.session.grid(choice.grid_id) if choice is not None else None
            if grid_now is not None:
                cells = frame_cells(grid_now.size_x, grid_now.size_y, resolution.cell)
                if cells > MAX_FRAME_CELLS:
                    safe = smallest_safe_cell(grid_now.size_x, grid_now.size_y)
                    self.error.emit(
                        f"a {resolution.cell:g} m cell over grid "
                        f"{grid_now.id!r} is {cells:,} cells, too many to "
                        f"draw; use {safe:g} m or coarser"
                    )
                    return
            self.engine.set_resolution(resolution)
            # Keyed on `(n_levels, choice, mode, radius_cells)` -- see the
            # field's own docstring -- and a geometry change can only have
            # moved `n_levels` (the axis it is measured against changed),
            # so there is no cheaper way to know the old cache is still
            # good.
            self._shared_limit_cache = None
            # `engine.estimate.cube_bytes` depends on `frame`/`z`, both of
            # which `set_resolution` may just have moved.
            self._update_resident_check_label()
            new_z = self.engine.z
            nz = new_z.nz if new_z is not None else 1
            # Fix round 1, M3: blocked. `setRange` and `setValue` can each
            # emit `valueChanged` -- wired to `refresh_slice()` -- on top
            # of the explicit call below; a `dz`/`z0`/`z1` change (unlike
            # a cell-only change) generally moves the slider's own clamped
            # value, so this was invisible to a debounce test that only
            # ever varies `cell_spin`.
            self.slice_slider.blockSignals(True)
            try:
                self.slice_slider.setRange(0, max(0, nz - 1))
                if new_z is not None and previous_time is not None:
                    nearest = int(round((previous_time - new_z.t0_ns) / new_z.dz_ns))
                    self.slice_slider.setValue(max(0, min(new_z.nz - 1, nearest)))
            finally:
                self.slice_slider.blockSignals(False)
            self.refresh_slice()
        except Exception as exc:  # noqa: BLE001 -- a QTimer.timeout slot
            self.error.emit(str(exc))

    def refresh_slice(self) -> None:
        if self._scope == "site":
            self._site.schedule_refresh()  # ruling T3-g; This grid is not coalesced
            return
        try:
            window = self.current_window()
            if window is None or not self.engine.is_prepared:
                self._values = None
                # Fix round 1, Important 4: emitted here too. `set_source`
                # empties the engine's lines SYNCHRONOUSLY, before any
                # re-preparation even starts, so this is the only path
                # that can tell `plugin._on_slice_changed` to `clear()`
                # the map for a source that just stopped being prepared --
                # without it the map kept showing the PREVIOUS source's
                # slice, indefinitely if the new one never prepares.
                self.slice_changed.emit()
                self.window_cleared.emit()
                return
            values, coverage = self.engine.slice_at(window)
            if self.coverage_check.isChecked():
                shown = coverage.astype(float)
                shown[coverage == 0] = np.nan
            else:
                shown = fill(values, coverage, self.radius_cells())
            self._values = shown
            self._window = window
            self._update_readout(window)
            lo_ns, hi_ns = window_times_ns(self.engine.z, window)
            self.window_changed.emit(lo_ns, hi_ns)
            self.status_label.setText(self._grid_status_text())
            self.slice_changed.emit()
        except Exception as exc:  # noqa: BLE001 -- reached from slider slots; an
            # escape passes locally and aborts the CI container.
            # Fix round 1, M4: state reset here too, not just reported --
            # otherwise `current_values()`/`current_window()`/the readout
            # keep describing the tick before this one (e.g. an out-of-
            # range `z1` that a prepared line no longer covers), and a
            # message bar warning appears beside a map and readout that
            # both still claim the OLD window is what is on screen.
            #
            # Task 5: the profile band is exactly the same kind of stale
            # state -- left pointing at the tick before this one, on a
            # radargram that may not even cover it any more -- so it is
            # cleared here for the same reason `_values`/`_window` are,
            # not left to the brief's one call site alone.
            #
            # Cheap cluster (final review): `legend_label` too -- without
            # this it kept showing the PREVIOUS tick's number beside
            # "error: ...", the exact same stale-state failure `_values`/
            # `_window`/`readout` are already reset here to avoid.
            self._values = None
            self._window = None
            self.readout.setText(f"error: {exc}")
            self.legend_label.setText("")
            self.slice_changed.emit()
            self.window_cleared.emit()
            self.error.emit(str(exc))

    def reannounce_window(self) -> None:
        """Re-emit the CURRENT window without recomputing the slice.

        For listeners whose own state was reset underneath them and who
        have no way to ask. The profile band is the case that needs it:
        it is a property of the slice -- one window, identical on every
        line -- but it lives in per-line view state that
        `ProfileView.clear()` resets, and `window_changed` only fires
        when the window CHANGES, which it has not. Walkthrough round 2,
        W8: once the view had been cleared, every line opened afterwards
        showed no band until the slider was nudged.

        Deliberately does NOT re-slice: nothing about the data changed,
        and `refresh_slice()` here would spend a redraw (and, in resident
        mode, possibly a cube build) to announce a number this dock is
        already holding.
        """
        if self._scope == "site":
            z, window = self.site_engine.site_z, self._site.window
        else:
            z, window = self.engine.z, self._window
        if window is None or z is None:
            self.window_cleared.emit()
            return
        lo_ns, hi_ns = window_times_ns(z, window)
        self.window_changed.emit(lo_ns, hi_ns)

    def _update_readout(self, window: SliceWindow) -> None:
        """Spec 6.6: derived from `(k0, k1)` -- what `ZAxis.level_range`
        actually returned -- and NEVER rebuilt from `self.slice_slider
        .value()`/`self.thickness_spin.value()`, which can disagree with
        it at either end of the axis (trap 3). `velocity_label` and
        `legend_label` are refreshed alongside it, on the same tick, for
        the same "read together" reason spec 9.2 puts them in one group.

        Fix round 1, Important 1: spec 9.2 fixes the readout's text as
        BOTH units (`slice 14 / 40 · 12.0-16.0 ns · 0.60-0.80 m`), and
        `window_label` already does that when given a velocity -- the
        two-argument call here had simply never passed one, so the
        readout stated ns only. `_resolved_velocity()` is the one place
        that resolves it, shared with `velocity_label` so the two always
        describe the same line's velocity.

        Final review, Minor 5: `plan_windows` is called with `thickness_
        step_levels()[0]` (the SAME unclamped thickness `export_geotiff`
        plans its bands from), never `window.n_levels` -- `window` comes
        from `current_window()`, and `ZAxis.level_range` CLAMPS its
        returned `n_levels` to a genuinely thinner value at either end of
        the axis (trap 3). Passing that clamped count into `plan_windows`
        here recomputed a DIFFERENT (smaller) band total than the export
        actually writes, so at nz=181/thickness=23/step=11 the readout
        read "slice 15 / 15", "16 / 16", "17 / 17" at sliders 158/170/180
        while the export wrote 15 bands throughout -- three disagreeing
        totals for a source `plan_windows`'s own docstring says has one,
        by construction.
        """
        z = self.engine.z
        assert z is not None  # refresh_slice() already checked current_window()
        thickness_levels, step_levels = self.thickness_step_levels()
        windows = plan_windows(z, thickness_levels, step_levels)
        # `windows` tiles from level 0 in steps of `step_levels`; a window
        # this thin only at an axis end (trap 3) need not be a member of
        # that tiling at all, so this is arithmetic, not a search -- and
        # it degrades gracefully to "the last slice" there rather than
        # raising.
        index = min(len(windows) - 1, window.k0 // step_levels)
        key, velocity = self._resolved_velocity()
        label = window_label(z, window, velocity)  # falls back to ns-only when velocity is None
        self.readout.setText(f"slice {index + 1} / {len(windows)} · {label}")
        self._update_velocity_label(key, velocity)
        self._update_legend_label()

    def _resolved_velocity(self) -> tuple[str | None, VelocityModel | None]:
        """The line key and the velocity resolved against it, shared by
        the readout (spec 9.2's ns-and-m format) and `velocity_label`
        (spec 9.2's "provenance, not state") so the two never describe
        two different lines. `None, None` before anything is prepared.

        Final review, Minor 6: also `None, None` when `engine.provenance()`
        raises `KeyError`, not just `RuntimeError` -- `provenance()`
        resolves velocity against the FIRST prepared line's key, and that
        raises `KeyError` once that line has been removed from the session
        (a contributing line can be deleted while a source stays prepared;
        the cube's own arrays are still entirely correct). Before this,
        deleting any such line blanked an otherwise still-valid slice --
        `refresh_slice()`'s broad `except` caught the `KeyError` escaping
        from here, reported `error: '<key>'`, and cleared the map -- for a
        reason that has nothing to do with whether the slice itself is
        still good.
        """
        try:
            keys = self.engine.provenance().line_keys
        except (RuntimeError, KeyError):
            return None, None
        if not keys:
            return None, None
        key = keys[0]
        try:
            return key, self.session.resolved_velocity(key)
        except (KeyError, RuntimeError):
            return None, None

    def _update_velocity_label(self, key: str | None, velocity: VelocityModel | None) -> None:
        if key is None or velocity is None:
            self.velocity_label.setText("")
            return
        source = velocity_source(self.session, key)
        self.velocity_label.setText(f"v = {velocity.surface_velocity:.3f} m/ns ({source})")

    def _update_legend_label(self) -> None:
        limit = self.display_limit()
        if self.coverage_check.isChecked():
            # Ruling AB: a count map's legend states a count scale, not
            # an amplitude range with a transform name that does not
            # apply to it.
            #
            # Round 2, W6: and it starts at ONE, not zero. Zero is the one
            # value this view never draws -- `refresh_slice` turns a
            # coverage of 0 into NaN, so a cell no line crossed is left
            # blank rather than coloured at the bottom of the ramp. A
            # legend reading "0 - 15" described a scale the picture did
            # not use, on the one view whose whole job is to be read
            # literally. Saying what blank means is the rest of that job.
            self.legend_label.setText(f"1 – {limit:.3g} traces per cell · blank = no line crossed")
            return
        base = f"0 – {limit:.3g}" if self.engine.output_unipolar else f"−{limit:.3g} – {limit:.3g}"
        transform_label = self.transform_combo.currentText() or "none"
        self.legend_label.setText(f"{base} ({transform_label})")

    def display_limit(self) -> float:
        """Spec 8: one limit for the whole cube by default, so depths stay
        comparable; a limit measured on just this slice, on demand, for
        legibility when a deep, dim window would otherwise wash out.

        The shared branch is cached (`_shared_limit_cache`) because it is
        a pass over every window in the cube, not a per-tick cost, and is
        only recomputed when the key it is measured over -- `(n_levels,
        engine.choice, engine.mode, radius_cells)` -- actually changed;
        see that field's own docstring for why those four and nothing
        else.

        Fix round 1, Important 2 (Ruling AB): the coverage view measures
        its OWN limit -- the greatest trace count actually on screen,
        floored at 1 -- regardless of the stretch combo. The shared
        stretch exists so DEPTHS stay amplitude-comparable (spec 8); that
        is not a property trace counts have at all, and `_values` here
        holds counts (1..a few), not amplitudes, whenever coverage is
        checked. Measured before this fix: `engine.shared_limit(...)`
        (the "shared" branch) returned ~7.0e4 on the synthetic fixture,
        so every count mapped to the shader's bottom stop and the whole
        coverage view rendered as one flat colour.

        Final review, Important 1 + Minor 9: BOTH remaining branches now
        measure exactly what `refresh_slice()` displays (`fill(values,
        coverage, radius_cells())`), never the raw unfilled array --
        `engine.shared_limit` takes `radius_cells()` and fills every
        window itself (see its own docstring for the measured before/after
        numbers, on this repo's four real DZT files); "this slice" is
        routed through `limit_over_slices` instead of calling
        `clip.limit(self._values)` raw, because the clips stride-subsample
        BEFORE filtering non-finite values and `limit_over_slices` is the
        function that exists specifically to filter first (see its own
        docstring) -- the two branches now differ only in WHICH slices
        they measure, never in HOW.
        """
        if self._scope == "site":
            return self._site.display_limit()
        if self.coverage_check.isChecked():
            if self._values is None:
                return 1.0
            finite = self._values[np.isfinite(self._values)]
            return max(1.0, float(np.nanmax(finite))) if finite.size else 1.0
        clip: Any = UnipolarClip() if self.engine.output_unipolar else PercentileClip()
        if self.stretch_combo.currentText() == "this slice":
            if self._values is None:
                return 1.0
            return limit_over_slices((self._values,), clip)
        window = self._window
        if window is None:
            return 1.0
        radius_cells = self.radius_cells()
        key = (window.n_levels, self.engine.choice, self.engine.mode, radius_cells)
        if self._shared_limit_cache is None or self._shared_limit_cache[0] != key:
            value = self.engine.shared_limit(window.n_levels, clip, radius_cells)
            self._shared_limit_cache = (key, value)
        return self._shared_limit_cache[1]

    def display_unipolar(self) -> bool:
        """Whether `current_values()` has no negative side, for the LUT
        `plugin.py` builds the map layer's shader with. Always `True` for
        the coverage view -- a trace count is never negative regardless
        of `engine.output_unipolar`, which describes the SOURCE, not what
        `refresh_slice()` currently has `_values` holding -- so a bipolar
        source's coverage view is not drawn on a bipolar ramp with half
        the table addressing counts that cannot occur (Ruling AB, the same
        reasoning `display_limit()`'s own coverage branch applies to the
        number rather than the colour)."""
        if self.coverage_check.isChecked():
            return True
        if self._scope == "site":
            return self._site.unipolar()
        return self.engine.output_unipolar

    # ---- M12: the scope switch (spec 4.1) ----------------------------------
    #
    # Whole site drives the same Position, Resolution and Display widgets
    # for every included grid. Its logic lives in `site_scope.SiteScope`
    # (`self._site`); the M11 methods above branch to it in site scope and
    # are otherwise unchanged. What stays here is the switch itself, the
    # widgets both scopes share, and ruling R-P5's guard on This grid.
    def scope(self) -> str:
        """`"grid"` (This grid, M11's dock) or `"site"` (Whole site)."""
        return self._scope

    def set_scope(self, scope: str) -> None:
        """Switch scope, keeping the window's time (spec 4.1).

        Leaving the site cancels its preparation (Ruling 1), then runs any
        This-grid preparation owed meanwhile once no site task is live
        (R-P5). Entering it builds a `SiteSource` from the survey's site view.
        """
        if scope not in ("grid", "site"):
            raise ValueError(f"scope must be 'grid' or 'site', got {scope!r}")
        if scope == self._scope:
            site_scope.show_scope_widgets(self)
            return
        if scope == "site" and not self.session.is_open:
            site_scope.show_scope_widgets(self)
            raise RuntimeError("open a survey before showing the whole site")
        if self._debounce.isActive():
            # The scope being left applies its own pending change first.
            self._debounce.stop()
            self._apply_resolution()
        if self._scope == "site":
            top = self._site.shown_top()
        else:
            z = self.engine.z
            top = (
                self._pending_top_ns if z is None else z.t0_ns + self.slice_slider.value() * z.dz_ns
            )
        if scope == "site":
            self._grid_spins = site_scope.capture_spins(self)
            self._grid_palette = self.palette_combo.currentText()
            self._grid_record_at_entry = self._grid_record()
            self._scope = "site"
            # R-P5: a moved grid's This-grid engine clears itself and owes a
            # preparation, rather than re-preparing beside the site's.
            self.engine.on_grid_moved = self._mark_grid_stale
            site_scope.show_scope_widgets(self)
            self._site.enter(top)
        else:
            self._scope = "grid"  # first: the site's cancel spins the event loop
            self._site.leave()
            # Final review D2: `on_grid_moved` stays `_mark_grid_stale` until
            # `_run_pending_grid_prepare` sees no site task live. A cancel
            # whose bounded wait gave up leaves the site's task reading, and
            # M11's self re-preparation on a move would start beside it.
            site_scope.show_scope_widgets(self)
            self._resume_grid(top)

    def _on_scope_clicked(self, scope: str) -> None:
        try:
            self.set_scope(scope)
        except Exception as exc:  # noqa: BLE001 -- a slot on QPushButton.clicked
            site_scope.show_scope_widgets(self)
            self.error.emit(f"could not switch the slice scope: {exc}")

    def _resume_grid(self, top: float | None) -> None:
        """Back to This grid exactly as it was left, at the site's window time."""
        if self._grid_spins is not None:
            site_scope.restore_spins(self, self._grid_spins)
        self._refill_palette_combo()
        if self.palette_combo.findText(self._grid_palette) >= 0:
            self.palette_combo.blockSignals(True)
            try:
                self.palette_combo.setCurrentText(self._grid_palette)
            finally:
                self.palette_combo.blockSignals(False)
        self._follow_record_changed_in_site()
        self._pending_top_ns = top
        self._sync_grid_slider()
        self._refresh_source_status()
        if self._grid_prepared_away:
            self._grid_prepared_away = False
            self._on_prepared()
        else:
            self.refresh_slice()
        # Always: it also hands This grid's moves back to its engine (D2).
        self._run_pending_grid_prepare()

    def _grid_record(self) -> tuple[Any, Any] | None:
        grid_id = self.grid_combo.currentText()
        if not grid_id or not self.session.is_open:
            return None
        entry = self.session.slice_source(grid_id) or {}
        # The preset and lines only: a gain edit is not a source change.
        return entry.get("preset"), entry.get("lines")

    def _follow_record_changed_in_site(self) -> None:
        """Spec 4.2: This grid reads the record the site writes. Lines chosen
        for This grid's own grid while the site showed are picked up here,
        and owe a preparation."""
        record = self._grid_record()
        if record is None or record == self._grid_record_at_entry:
            return
        grid_id = self.grid_combo.currentText()
        self._restore_remembered_source(grid_id)
        if record[1] is None:
            self._included = self._default_included(grid_id)
            self._included_is_default = True
        self._update_included_label()
        self._grid_prepare_pending = True

    def _grid_status_text(self) -> str:
        """This grid's status line, and what the site view still holds.

        Final review M2: leaving Whole site keeps every prepared site grid
        (Ruling 1), memory This grid's own line would otherwise hide. The
        figure is `SiteEngine.held_bytes`, the site's own accounting.
        """
        text = self.engine.status_text()
        held = self.site_engine.held_bytes
        if held > 0:
            text += f" · +{format_bytes(held)} held by the site view"
        return text

    # ---- R-P5: This grid never prepares while the site shows ---------------
    def _mark_grid_stale(self) -> None:
        """This grid's engine's `on_grid_moved` while the site shows, or while a
        site task outlives leaving it (D2). The engine has cleared its lines
        (R-P2); preparing them again waits for This grid and a stopped site.
        In This grid scope `_resume_grid` has already started the retry that
        runs it: the hook is only still installed while that retry runs."""
        try:
            self._grid_prepare_pending = True
        except Exception as exc:  # noqa: BLE001 -- called from a grids_changed slot
            _log(f"could not mark the slice source stale: {exc}")

    def _run_pending_grid_prepare(self) -> None:
        """Run the owed This-grid preparation once no site task is live, else
        retry in 50 ms. Never blocks. Also the retry timer's slot.

        Final review D2: only here, once no site task is live, does This
        grid's engine get M11's self re-preparation on a move back
        (`on_grid_moved = None`). Until then a move is `_mark_grid_stale`'s.
        """
        try:
            if self._scope != "grid":
                return
            if self.site_engine.has_live_task:
                self._grid_retry.start()
                return
            self.engine.on_grid_moved = None  # R-P5: M11's self re-preparation again
            if not self._grid_prepare_pending:
                return
            self._grid_prepare_pending = False
            self.prepare()
            if self.engine.z is None and self.engine.choice is not None:
                # A moved grid's engine was cleared, resolution and all.
                self._apply_resolution()
            self._sync_grid_slider()
        except Exception as exc:  # noqa: BLE001 -- a QTimer slot
            _log(f"could not prepare the slice source: {exc}")

    def _sync_grid_slider(self) -> None:
        """Put the carried-over top time on This grid's axis, once it has one."""
        z, top = self.engine.z, self._pending_top_ns
        if z is None or top is None:
            return
        nearest = int(round((top - z.t0_ns) / z.dz_ns))
        self.slice_slider.blockSignals(True)
        try:
            self.slice_slider.setRange(0, max(0, z.nz - 1))
            self.slice_slider.setValue(max(0, min(z.nz - 1, nearest)))
        finally:
            self.slice_slider.blockSignals(False)
        self._pending_top_ns = None

    # ---- the site, delegated to `SiteScope` ---------------------------------
    def _site_source(self) -> SiteSource | None:
        return self._site.source()

    def _site_transform(self) -> str:
        return self._site.transform()

    def _on_site_changed(self) -> None:
        self._site.on_changed()  # guards itself

    def _on_site_error(self, message: str) -> None:
        try:
            self.error.emit(message)
        except Exception:  # noqa: BLE001 -- see the module docstring
            _log(f"could not report a site error: {message}")

    def _apply_site_resolution(self) -> None:
        self._site.apply_resolution()

    def _refresh_site_slice(self) -> None:
        self._site.refresh_slice()

    def current_site_slice(self) -> SiteSlice | None:
        """The site slice last drawn, or None (not in site scope, or none ready)."""
        return self._site.slice if self._scope == "site" else None

    def site_gains(self) -> dict[str, float]:
        """Each included grid's manual gain (spec 4.6)."""
        return self._site.gains() if self.session.is_open else {}

    def site_velocities(self) -> dict[str, VelocityModel | None]:
        """Each ready grid's velocity, resolved as the This-grid readout does."""
        return self._site.velocities()

    def site_left_out(self) -> list[str]:
        """Included grids no site file will hold: failed, or no lines (T4-a)."""
        return self._site.left_out() if self.session.is_open else []

    def site_left_out_states(self) -> dict[str, str]:
        """`site_left_out`, grid id to state, as the site file records it (F-2)."""
        return self._site.left_out_states() if self.session.is_open else {}

    def line_choice_grid(self) -> str | None:
        """The grid the line chooser acts on: This grid's, or the selected row's."""
        if self._scope == "site":
            return self.site_panel.selected_grid()
        return self.grid_combo.currentText() or None

    def line_choice_keys(self, grid_id: str) -> tuple[str, ...]:
        """The lines the chooser starts from for `grid_id`."""
        if self._scope == "site":
            return site_scope.source_keys(self.session, grid_id)
        return self.included_keys()

    def set_included_for(self, grid_id: str, keys: tuple[str, ...]) -> None:
        """Commit a line choice for `grid_id`. In site scope it becomes that
        grid's remembered source (spec 4.2) and only that grid re-prepares;
        This grid's own inclusion set is not touched."""
        if self._scope == "site":
            self._site.set_lines(grid_id, tuple(keys))
            return
        if grid_id != (self.grid_combo.currentText() or None):
            raise ValueError(f"lines for {grid_id!r} offered while This grid shows another")
        self.set_included(tuple(keys))

    def dispose_site(self) -> None:
        """Stop the site scope for good (`plugin.unload`): its timers, This
        grid's hook, and the site engine, which cancels and waits, bounded."""
        self._site.dispose()
        self._grid_retry.stop()
        self._grid_prepare_pending = False
        self.engine.on_grid_moved = None
        self.site_engine.dispose()


class CanvasDepthScroll(QObject):
    """Shift + scroll on the map canvas cycles depth (spec 9.2).

    An event filter rather than a map tool: spec 9.3 is explicit that the
    slice introduces no new tool, and taking over the canvas would break
    the ambient hover and the Select-to-promote gesture M7 already built.
    Without shift the event is not consumed, so plain scrolling remains
    the map's zoom.

    `eventFilter` is a Qt-invoked virtual, the same hazard class as
    `paintEvent`: an exception escaping it is swallowed locally and
    reaches `qFatal()` in the CI container, so the body is guarded.
    """

    def __init__(self, canvas: Any, dock: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self._dock = dock
        canvas.viewport().installEventFilter(self)

    def eventFilter(self, obj: Any, event: Any) -> bool:  # noqa: N802
        try:
            if event.type() != QEvent.Type.Wheel:
                return False
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            delta = depth_scroll_delta(int(event.angleDelta().y()), shift)
            if delta == 0:
                return False
            self._dock.step_slice(delta)
            return True  # consumed: the map must not also zoom
        except Exception as exc:  # noqa: BLE001 -- see the class docstring
            _log(f"could not step the slice from the canvas: {exc}")
            return False

    def dispose(self) -> None:
        try:
            if self._canvas is not None and not sip.isdeleted(self._canvas):
                self._canvas.viewport().removeEventFilter(self)
        except (RuntimeError, AttributeError):
            pass
        self._canvas = None
        self._dock = None
