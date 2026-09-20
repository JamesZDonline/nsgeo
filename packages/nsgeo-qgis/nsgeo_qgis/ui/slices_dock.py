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

from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.log import log as _log
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slices_engine import SliceEngine
from nsgeo_qgis.slices_plan import (
    NO_TRANSFORM,
    SourceChoice,
    estimate_memory,
    format_bytes,
    transform_names,
)


class SlicesDock(QgsDockWidget):
    #: Ask the plugin to open `LineChoiceDialog` (spec 9.1's one dialog).
    #: A request, not the dialog itself -- the dock owns no dialogs, the
    #: same split `SurveyDock`/`ProfileDock` already use for grid/import.
    choose_lines_requested = pyqtSignal()
    error = pyqtSignal(str)

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
        # A depth counter, not a bool -- see `rebuild_source` and the
        # module docstring of `processing_dock.py`, whose reasoning this
        # copies exactly: a slot re-entering `rebuild_source` while the
        # outer call is still on the stack would otherwise have its
        # `finally` clear the guard early, for the inner call's own frame.
        self._updating = 0
        #: The included subset, in survey order. Not necessarily a subset
        #: of the selected grid's own lines -- `LineChoiceDialog` offers
        #: every line in the site, because two named grids can still share
        #: one world footprint. `_default_included` only SEEDS this set
        #: when the grid changes; it never constrains it afterwards.
        self._included: tuple[str, ...] = ()
        #: The grid id `_included` was last reset for. `None` both before
        #: any grid has been looked at and whenever no grid is selected,
        #: which is also this dock's own initial state -- so the very
        #: first `rebuild_source()` call in `__init__` reads as a "grid
        #: changed" transition exactly when a grid is actually available.
        self._last_grid_id: str | None = None

        body = QWidget(self)
        outer = QVBoxLayout(body)
        outer.setContentsMargins(4, 4, 4, 4)

        self.source_group = QGroupBox("Source")
        source_layout = QVBoxLayout(self.source_group)

        form = QFormLayout()
        self.grid_combo = QComboBox()
        self.preset_combo = QComboBox()
        self.transform_combo = QComboBox()
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
        # Task 4 appends Position/Resolution/Display group boxes here,
        # above this stretch, with no restructuring of what is above.
        outer.addStretch(1)
        self.setWidget(body)

        # `clicked` carries a `bool checked` that a direct
        # `.connect(self.choose_lines_requested.emit)` would pass straight
        # through as the signal's `str`-less argument -- `emit()` takes no
        # positional argument here, so that would actually raise. The
        # lambda drops it, the same reason `processing_dock.py`'s
        # `apply_button` uses one.
        self.choose_button.clicked.connect(lambda: self.choose_lines_requested.emit())
        self.grid_combo.currentTextChanged.connect(self._on_source_changed)
        self.preset_combo.currentTextChanged.connect(self._on_source_changed)
        self.transform_combo.currentTextChanged.connect(self._on_source_changed)
        session.site_opened.connect(self.rebuild_source)
        session.site_closed.connect(self.rebuild_source)
        session.grids_changed.connect(self.rebuild_source)
        session.lines_changed.connect(self.rebuild_source)
        session.presets_changed.connect(self.rebuild_source)

        # Filled once: `transform_names()` is the registry, not the site,
        # and does not change while this dock is alive. `grid_combo` and
        # `preset_combo` are rebuilt from the session instead, below.
        self.transform_combo.addItem("none")
        self.transform_combo.addItems(transform_names())

        self.rebuild_source()

    # ---- source group -------------------------------------------------
    def rebuild_source(self) -> None:
        """Refill `grid_combo`/`preset_combo` from the session.

        Guarded by `self._updating`: refilling a `QComboBox` emits
        `currentTextChanged` even when the text ends up unchanged (Qt
        fires it once, unconditionally, the moment a combo goes from
        empty to holding its first item), and without this guard
        `_on_source_changed` would treat that as a real choice and
        re-prepare -- on this dock's own construction, and again on
        every `grids_changed`/`lines_changed`/`presets_changed`, none of
        which is a choice the user made.
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
            self._sync_included()
            self._update_included_label()
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
        changed; otherwise just drop any key that no longer exists (a
        line removed elsewhere), keeping survey order.

        An inclusion list carried over from a different grid means
        nothing here -- the whole point of `_default_included` is to
        start from something that does.
        """
        grid_id = self.grid_combo.currentText() or None
        if grid_id != self._last_grid_id:
            self._last_grid_id = grid_id
            self._included = self._default_included(grid_id)
            return
        valid = set(self.session.keys()) if self.session.is_open else set()
        self._included = tuple(k for k in self._included if k in valid)

    def _update_included_label(self) -> None:
        """Spec 9.1: report the resulting memory before committing to the
        ~0.9 s of preparing it.

        `total` is the selected grid's own line count -- what the
        fraction is measured against -- but the estimate itself sums
        over `self._included` exactly as chosen, since a line from
        another grid the user deliberately added still costs memory.

        The sample count is read from each line's header, before
        `time_zero` crops rows -- see `slices_plan.estimate_memory` and
        this dock's own module docstring for why that is "about", not
        exact, and why that is the honest choice.
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
        self.included_label.setText(
            f"{len(included)} of {total} included · about {format_bytes(estimate.total_bytes)}"
        )

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
        Does not re-prepare on its own: like the three combos, this is a
        choice the user just made, and `plugin.py`'s dialog handler leaves
        the retry (calling `prepare()`) to whoever wants it, exactly as a
        fixed preset does through `presets_changed`."""
        self._included = tuple(keys)
        self._update_included_label()

    def prepare(self) -> None:
        """Build a `SourceChoice` from the three combos and the inclusion
        set, and hand it to the engine.

        The one place Ruling 2's refusal (a preset that already carries
        the amplitude transform) becomes visible: `set_source` raises
        `ValueError` synchronously, before any task is dispatched, and
        this is where that turns into something the user can read.
        """
        try:
            self.engine.set_source(self.source_choice())
        except ValueError as exc:
            message = str(exc)
            self.source_status.setText(message)
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
            self._sync_included()
            self._update_included_label()
            self.prepare()
        except Exception as exc:  # noqa: BLE001 -- a slot on currentTextChanged
            _log(f"could not react to a source change: {exc}")

    # ---- engine callbacks -----------------------------------------------
    def _on_progress(self, done: int, total: int) -> None:
        try:
            self.source_status.setText(f"preparing… {done} of {total}")
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not report slice-source progress: {exc}")

    def _on_prepared(self) -> None:
        try:
            self.source_status.setText(f"prepared · {self.engine.line_count} lines")
            self._update_included_label()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not report that the slice source is prepared: {exc}")

    def _on_engine_error(self, message: str) -> None:
        try:
            self.source_status.setText(message)
            self.error.emit(message)
        except Exception:  # noqa: BLE001 -- see the module docstring
            _log(f"could not report a slice engine error: {message}")
