"""The Slices dock's Whole-site scope: what it shows, and the logic behind it.

Spec 4.1-4.5. Two halves:

* Plain functions that read the session and the `SiteEngine` and return
  values -- which grids are in the site, each grid's source, the grid
  list's rows, the seeded resolution, the readout text. No widgets.
* `SiteScope`, the dock's site-scope controller. The two scopes share the
  dock's Position, Resolution and Display widgets (spec 4.1); `SiteScope`
  drives them while the site shows, and the dock delegates to it. It
  declares no signals and computes nothing itself: `SiteEngine` and the
  functions above do. Kept out of `slices_dock.py` so M11's dock grows by
  composition, not by a second copy of its flow.

Every method reached from a Qt signal or timer guards its body, as every
slot in this plugin does (an exception escaping a slot aborts the CI
container). Nothing here prepares This grid's engine (ruling R-P5).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
from nsgeo.render import DEFAULT_COLORMAP, PercentileClip, UnipolarClip, colormap_names
from nsgeo.slices import (
    SliceWindow,
    ZAxis,
    limit_over_slices,
    plan_windows,
    window_depths_m,
    window_on,
    window_times_ns,
)
from nsgeo.velocity import VelocityModel
from qgis.PyQt.QtCore import QTimer

from nsgeo_qgis.log import log as _log
from nsgeo_qgis.site_engine import SiteSlice
from nsgeo_qgis.slices_plan import (
    NO_TRANSFORM,
    Resolution,
    SiteSource,
    SourceChoice,
    default_cell,
    smallest_safe_cell,
)
from nsgeo_qgis.ui.site_panel import SiteRow


@dataclass(frozen=True)
class Spins:
    """The Resolution group's geometry spins, as one scope left them.

    The two scopes share these widgets (spec 4.1) but not their values:
    This grid keeps M11's per-grid seed, the site its own (spec 4.4).
    """

    cell: float
    cell_min: float
    dz: float
    z0: float
    z1: float
    time_step: float


def transform_value(text: str) -> str:
    """A transform combo's text as a `SourceChoice.transform`."""
    return NO_TRANSFORM if text in ("", "none") else text


def keys_by_grid(session: Any) -> dict[str | None, tuple[str, ...]]:
    """Every line's key under the grid it is placed on, in survey order.

    One pass over the survey (final review M3). The grid list is refreshed
    on every progress step, so a caller that needs several grids' lines
    builds this once and passes it on, rather than walking every line per
    grid. Unplaced lines are under None.
    """
    out: dict[str | None, list[str]] = {}
    for key in session.keys():  # noqa: SIM118 -- SiteSession.keys(), not a dict
        grid_id = getattr(session.line_for_key(key).placement, "grid_id", None)
        out.setdefault(grid_id, []).append(key)
    return {grid_id: tuple(keys) for grid_id, keys in out.items()}


def grid_keys(
    session: Any, grid_id: str, by_grid: Mapping[str | None, tuple[str, ...]] | None = None
) -> tuple[str, ...]:
    """Every line placed on `grid_id`, in survey order (from `by_grid` when given)."""
    if by_grid is None:
        by_grid = keys_by_grid(session)
    return tuple(by_grid.get(grid_id, ()))


def default_preset(session: Any, grid_id: str) -> str | None:
    """The grid's remembered preset if it still exists, else the first (spec 4.2)."""
    presets = sorted(session.site.presets)
    remembered = (session.slice_source(grid_id) or {}).get("preset")
    if remembered in presets:
        return str(remembered)
    return presets[0] if presets else None


def source_keys(
    session: Any, grid_id: str, by_grid: Mapping[str | None, tuple[str, ...]] | None = None
) -> tuple[str, ...]:
    """The grid's remembered lines, still on it and in survey order; every line
    if none is remembered or they have all left the grid (#74: the reading
    `SlicesDock._restore_remembered_source` gives This grid, so both scopes agree)."""
    every = grid_keys(session, grid_id, by_grid)
    lines = (session.slice_source(grid_id) or {}).get("lines")
    if lines is None:
        return every
    wanted = set(lines)
    kept = tuple(k for k in every if k in wanted)
    return kept if kept else every


def included_grids(
    session: Any, by_grid: Mapping[str | None, tuple[str, ...]] | None = None
) -> tuple[str, ...]:
    """The remembered included grids, in site order; every grid with lines if none."""
    ids = [grid.id for grid in session.site.grids]
    stored = session.site_view().get("grids")
    if stored is None:
        wanted = set(by_grid if by_grid is not None else keys_by_grid(session))
    else:
        wanted = set(stored)
    return tuple(g for g in ids if g in wanted)


def stored_transform(session: Any, offered: Iterable[str], fallback: str) -> str:
    """The remembered transform, or `fallback` when none is stored or it is not
    offered any more (ruling T2-c: `set_site_view` does not validate it)."""
    stored = session.site_view().get("transform")
    return stored if stored in set(offered) else fallback


def stored_method(session: Any) -> str:
    """The remembered normalisation; "none" when absent (spec 4.6: off by default)."""
    return str(session.site_view().get("normalisation") or "none")


def site_source(session: Any, included: Iterable[str], transform_text: str) -> SiteSource:
    """Each included grid's own preset and lines, under the site's one transform."""
    transform = transform_value(transform_text)
    by_grid = keys_by_grid(session)
    grids = []
    for grid_id in included:
        preset = default_preset(session, grid_id)
        if preset is None:
            continue  # no preset in the survey: nothing can be prepared
        grids.append(
            SourceChoice(
                grid_id=grid_id,
                preset=preset,
                transform=transform,
                line_keys=source_keys(session, grid_id, by_grid),
            )
        )
    return SiteSource(transform=transform, grids=tuple(grids))


def state_text(site_engine: Any, grid_id: str) -> str:
    """Spec 4.2's state column: ready / preparing n of m / no lines / ..."""
    try:
        state = site_engine.grid_state(grid_id)
    except KeyError:
        return "waiting"
    if state == "preparing":
        progress = site_engine.grid_progress(grid_id)
        if progress is not None:
            return f"preparing {progress[0]} of {progress[1]}"
    return str(state)


def site_rows(
    session: Any,
    site_engine: Any,
    included: Iterable[str],
    by_grid: Mapping[str | None, tuple[str, ...]] | None = None,
) -> list[SiteRow]:
    """One row per grid in the site, in site order; one pass over the lines (M3)."""
    if by_grid is None:
        by_grid = keys_by_grid(session)
    chosen = set(included)
    rows = []
    for grid in session.site.grids:
        every = grid_keys(session, grid.id, by_grid)
        keys = source_keys(session, grid.id, by_grid)
        if not every:
            state = "no lines"
        elif grid.id not in chosen:
            state = "not included"
        else:
            state = state_text(site_engine, grid.id)
        rows.append(
            SiteRow(
                grid_id=grid.id,
                preset=default_preset(session, grid.id) or "",
                lines=f"{len(keys)} / {len(every)}",
                state=state,
                included=grid.id in chosen,
            )
        )
    return rows


def left_out_states(site_engine: Any, included: Iterable[str]) -> dict[str, str]:
    """Included grids that are in no site file, grid id to `grid_state`:
    failed, or no lines (ruling T4-a). What the file records (Ruling F-2)."""
    out = {}
    for grid_id in included:
        state = state_text(site_engine, grid_id)
        if state == "no lines" or state.startswith("failed"):
            out[grid_id] = state
    return out


def left_out(site_engine: Any, included: Iterable[str]) -> list[str]:
    """`left_out_states` as the export message names them: `C (no lines)`."""
    return [f"{g} ({state})" for g, state in left_out_states(site_engine, included).items()]


def busy(site_engine: Any, included: Iterable[str]) -> bool:
    """Whether any included grid is still queued or preparing (ruling T4-a)."""
    return any(
        state_text(site_engine, g) in ("queued", "waiting")
        or state_text(site_engine, g).startswith("preparing")
        for g in included
    )


def seed_cell(session: Any, included: Iterable[str]) -> tuple[float, float] | None:
    """`(floor, cell)`: `default_cell` for the finest-spaced included grid (spec 4.4).

    The floor is the largest of the grids' `smallest_safe_cell`, so no grid's
    own frame can be made undrawable from the arrows (walkthrough W7). The
    lattice over all of them is checked by `SiteEngine.set_resolution`.
    """
    grids = [session.grid(g) for g in included]
    if not grids:
        return None
    floor = max(0.01, *(smallest_safe_cell(g.size_x, g.size_y) for g in grids))
    finest = min(g.default_spacing for g in grids)
    return floor, default_cell(finest, floor)


def header_z_seed(session: Any, included: Iterable[str]) -> tuple[float, float, float] | None:
    """`(dz, z0, z1)` from the included grids' first lines' headers, before any is prepared.

    The union of what the headers record; replaced by the prepared bounds
    once a grid is ready (`ready_z_bounds`), as M11 corrects its own
    header-seeded range once its lines are prepared.
    """
    headers = []
    by_grid = keys_by_grid(session)
    for grid_id in included:
        keys = source_keys(session, grid_id, by_grid)
        if keys:
            headers.append(session.line_for_key(keys[0]).header)
    if not headers:
        return None
    lo = min(h.position_ns for h in headers)
    hi = max(h.position_ns + (h.n_samples - 1) * h.dt_ns for h in headers)
    return headers[0].dt_ns, lo, hi


def ready_z_bounds(site_engine: Any) -> tuple[float, float] | None:
    """The union of the ready grids' prepared time bounds (spec 4.3 and 4.4)."""
    spans = []
    for grid_id in site_engine.ready_grids:
        engine = site_engine.engine_for(grid_id)
        bounds = engine.prepared_z_bounds() if engine is not None else None
        if bounds is not None:
            spans.append(bounds)
    if not spans:
        return None
    return min(s[0] for s in spans), max(s[1] for s in spans)


def ready_dt(site_engine: Any) -> float | None:
    """The sample interval of the first ready grid's prepared lines."""
    for grid_id in site_engine.ready_grids:
        engine = site_engine.engine_for(grid_id)
        lines = engine.prepared_lines() if engine is not None else ()
        if lines:
            return float(lines[0].dt_ns)
    return None


def levels(z: ZAxis, thickness_ns: float, step_ns: float) -> tuple[int, int]:
    """`(thickness_levels, step_levels)` on `z`, rounded as M11 rounds them."""
    return max(1, int(round(thickness_ns / z.dz_ns))), max(1, int(round(step_ns / z.dz_ns)))


def readout(z: ZAxis, window: SliceWindow, thickness_levels: int, step_levels: int) -> str:
    """`slice i / N · lo–hi ns`, from the site window actually used (trap 5)."""
    windows = plan_windows(z, thickness_levels, step_levels)
    index = min(len(windows) - 1, window.k0 // step_levels)
    lo, hi = window_times_ns(z, window)
    return f"slice {index + 1} / {len(windows)} · {lo:.1f}–{hi:.1f} ns"


def grid_velocity(session: Any, engine: Any) -> VelocityModel | None:
    """A grid's velocity, resolved as M11's `_resolved_velocity` resolves it."""
    if engine is None:
        return None
    try:
        keys = engine.provenance().line_keys
    except (RuntimeError, KeyError):
        return None
    if not keys:
        return None
    try:
        return session.resolved_velocity(keys[0])
    except (KeyError, RuntimeError):
        return None


def site_velocities(session: Any, site_engine: Any) -> dict[str, VelocityModel | None]:
    """Each ready grid's resolved velocity, for the readout and the export."""
    return {g: grid_velocity(session, site_engine.engine_for(g)) for g in site_engine.ready_grids}


def depths_text(
    site_engine: Any,
    windows: Mapping[str, SliceWindow | None],
    velocities: Mapping[str, VelocityModel | None],
) -> str:
    """`A 0.60–0.80 m · B 0.52–0.70 m · C no data` (spec 4.3).

    From each grid's own window on its own axis (trap 5), through its own
    velocity; a grid whose range misses the window is named, not dropped.
    """
    parts = []
    for grid_id, window in windows.items():
        engine = site_engine.engine_for(grid_id)
        z = engine.z if engine is not None else None
        velocity = velocities.get(grid_id)
        if window is None or z is None:
            parts.append(f"{grid_id} no data")
        elif velocity is None:
            parts.append(f"{grid_id} no velocity")
        else:
            lo, hi = window_depths_m(z, window, velocity)
            parts.append(f"{grid_id} {lo:.2f}–{hi:.2f} m")
    return " · ".join(parts)


def radius_tooltip(session: Any, included: Iterable[str], radius_spacings: float) -> str:
    """The fill radius control's tooltip, with each grid's radius in metres (spec 4.4)."""
    metres = [f"{g} {radius_spacings * session.grid(g).default_spacing:.2f} m" for g in included]
    text = (
        "Fills cells no line crossed, within this many of each grid's own line "
        "spacings, so grids with different spacings are filled alike (spec 4.4)."
    )
    return text + ("\n" + " · ".join(metres) if metres else "")


# ---- the widgets the two scopes share ----------------------------------------------


def show_scope_widgets(dock: Any) -> None:
    """Show the dock's scope: Whole site swaps Source for the grid list and
    adds Normalisation (spec 4.1); Position, Resolution and Display stay."""
    site = dock.scope() == "site"
    dock.grid_scope_button.setChecked(not site)
    dock.site_scope_button.setChecked(site)
    dock.source_group.setVisible(not site)
    dock.site_panel.setVisible(site)
    dock.normalisation_panel.setVisible(site)
    dock.velocity_label.setVisible(not site)
    dock.site_depths_label.setVisible(site)
    set_row_visible(dock, dock.radius_spin, not site)
    set_row_visible(dock, dock.radius_spacing_spin, site)
    # Residency stays per grid and automatic in the site (spec 4.8).
    dock.resident_check.setVisible(not site)
    dock.save_button.setVisible(not site)
    dock.export_button.setText("Export site GeoTIFF…" if site else "Export GeoTIFF…")
    # Spec 4.5: the first stretch names what it is shared across; its index
    # meaning is unchanged. Blocked: renaming the current item emits
    # currentTextChanged.
    dock.stretch_combo.blockSignals(True)
    try:
        dock.stretch_combo.setItemText(
            0, "shared across the site" if site else "shared across the cube"
        )
    finally:
        dock.stretch_combo.blockSignals(False)


def set_row_visible(dock: Any, field: Any, visible: bool) -> None:
    """Show or hide one Resolution row, its label with it."""
    label = dock._resolution_form.labelForField(field)
    if label is not None:
        label.setVisible(visible)
    field.setVisible(visible)


def capture_spins(dock: Any) -> Spins:
    return Spins(
        cell=dock.cell_spin.value(),
        cell_min=dock.cell_spin.minimum(),
        dz=dock.dz_spin.value(),
        z0=dock.z0_spin.value(),
        z1=dock.z1_spin.value(),
        time_step=dock.dz_spin.singleStep(),
    )


def set_spins_quietly(dock: Any, **values: float) -> bool:
    """Set Resolution spins with their signals blocked (a seed or a restore,
    never the user's change); whether any moved."""
    spins = {"cell": dock.cell_spin, "dz": dock.dz_spin, "z0": dock.z0_spin}
    spins["z1"] = dock.z1_spin
    changed = False
    for name, value in values.items():
        spin = spins[name]
        before = spin.value()
        spin.blockSignals(True)
        try:
            spin.setValue(value)
        finally:
            spin.blockSignals(False)
        changed = changed or spin.value() != before
    return changed


def restore_spins(dock: Any, spins: Spins) -> None:
    set_cell_floor(dock, spins.cell_min)
    for spin in (dock.dz_spin, dock.z0_spin, dock.z1_spin):
        spin.setSingleStep(spins.time_step)
    set_spins_quietly(dock, cell=spins.cell, dz=spins.dz, z0=spins.z0, z1=spins.z1)


def set_cell_floor(dock: Any, floor: float) -> None:
    dock.cell_spin.blockSignals(True)
    try:
        dock.cell_spin.setMinimum(floor)
    finally:
        dock.cell_spin.blockSignals(False)


class SiteScope:
    """The dock's Whole-site half: its state, and what its widgets do in it.

    Built by `SlicesDock`, which owns the widgets, the `SiteEngine` and the
    scope switch, and delegates to this. `dock.site_panel`,
    `dock.normalisation_panel` and `dock.radius_spacing_spin` are wired here.
    """

    def __init__(self, dock: Any) -> None:
        self.dock = dock
        #: The site slice last drawn, and its window on the site axis.
        self.slice: SiteSlice | None = None
        self.window: SliceWindow | None = None
        #: The site axis the slider was last ranged over, and the top time
        #: carried across a scope switch until an axis exists to put it on
        #: (spec 4.1: switching keeps the window's time).
        self.z_shown: ZAxis | None = None
        self.pending_top: float | None = None
        self.source_sent: SiteSource | None = None
        self.res_applied: Resolution | None = None
        #: The ready grids the last tick was set up for.
        self.ready_handled: tuple[str, ...] | None = None
        self.limit_cache: tuple[tuple[Any, ...], float] | None = None
        #: The included set the cell was last seeded for (spec 4.4: only when
        #: it changes), and whether the user set dz/z0/z1 by hand here (then
        #: they are clamped, as M11 clamps, never re-seeded).
        self.cell_seeded_for: tuple[str, ...] | None = None
        self.z_custom = False
        #: The site's Resolution values when the dock last left it.
        self.spins: Spins | None = None
        #: Ruling T3-g: at most one tick per event-loop pass, latest values.
        self.tick = QTimer(dock)
        self.tick.setSingleShot(True)
        self.tick.setInterval(0)
        self.tick.timeout.connect(self._run_tick)

        dock.site_panel.included_changed.connect(self._on_included_changed)
        dock.site_panel.transform_changed.connect(self._on_transform_changed)
        dock.site_panel.selected_changed.connect(self._on_selected_changed)
        dock.normalisation_panel.method_changed.connect(self._on_method_changed)
        dock.normalisation_panel.gain_changed.connect(self._on_gain_changed)
        dock.radius_spacing_spin.valueChanged.connect(self._on_radius_changed)
        for spin in (dock.dz_spin, dock.z0_spin, dock.z1_spin):
            spin.valueChanged.connect(self._note_z_edit)

    @property
    def session(self) -> Any:
        return self.dock.session

    @property
    def engine(self) -> Any:
        return self.dock.site_engine

    @property
    def showing(self) -> bool:
        return self.dock.scope() == "site"

    def included(self) -> tuple[str, ...]:
        return included_grids(self.session) if self.session.is_open else ()

    # ---- entering and leaving ---------------------------------------------
    def enter(self, top: float | None) -> None:
        """The dock has switched to the site: restore its view and start it."""
        dock = self.dock
        self.pending_top = top
        self.z_shown = None
        self.ready_handled = None
        self.limit_cache = None
        panel = dock.site_panel
        panel.set_transform(
            stored_transform(
                self.session, panel.transform_combo.values(), dock.transform_combo.value()
            )
        )
        dock.normalisation_panel.set_method(stored_method(self.session))
        self.refresh_rows()
        if panel.selected_grid() is None:
            panel.select_grid(dock.grid_combo.currentText() or None)
        self._on_selected_changed(panel.selected_grid() or "")
        included = self.included()
        if self.spins is not None and included == self.cell_seeded_for:
            restore_spins(dock, self.spins)
        else:
            self.seed_resolution(included)
        self.refill_palette()
        self.send_source(force=True)
        self.apply_resolution()

    def leave(self) -> None:
        """The dock is leaving the site: keep its values, stop it (Ruling 1).

        Called after the dock's scope reads "grid": `cancel()` waits, bounded,
        in a nested event loop, and a tick firing inside it must find the
        site gone.
        """
        self.spins = capture_spins(self.dock)
        self.tick.stop()
        self.engine.cancel()
        self.slice = None
        self.window = None

    def forget(self) -> None:
        """A different survey: nothing the last one's site view held applies."""
        self.spins = None
        self.cell_seeded_for = None
        self.z_custom = False
        self.source_sent = None
        self.res_applied = None
        self.limit_cache = None

    def shown_top(self) -> float | None:
        z = self.z_shown
        if z is None:
            return self.pending_top
        return z.t0_ns + self.dock.slice_slider.value() * z.dz_ns

    # ---- source --------------------------------------------------------------
    def transform(self) -> str:
        return transform_value(self.dock.site_panel.transform())

    def source(self) -> SiteSource | None:
        """Every included grid, each with its own remembered (or first) preset
        and lines, under the site's one transform (spec 4.2)."""
        if not self.session.is_open:
            return None
        return site_source(self.session, self.included(), self.dock.site_panel.transform())

    def send_source(self, *, force: bool = False) -> None:
        """Hand the site its source when it changed, or always (`force`: the
        site resumes after `cancel()` only through `set_source`)."""
        source = self.source()
        if source is None or (not force and source == self.source_sent):
            return
        try:
            self.source_sent = source
            self.limit_cache = None
            self.engine.set_source(source)
        except Exception as exc:  # noqa: BLE001 -- reported, never raised past a slot
            self.dock.error.emit(f"could not prepare the site: {exc}")
        self.refresh_rows()

    def gains(self) -> dict[str, float]:
        """Each included grid's manual gain (spec 4.6), from the survey."""
        return {g: self.session.grid_gain(g) for g in self.included()}

    def velocities(self) -> dict[str, VelocityModel | None]:
        return site_velocities(self.session, self.engine)

    def left_out(self) -> list[str]:
        return left_out(self.engine, self.included())

    def left_out_states(self) -> dict[str, str]:
        return left_out_states(self.engine, self.included())

    def set_lines(self, grid_id: str, keys: tuple[str, ...]) -> None:
        """A line choice for one grid: its remembered source; only it re-prepares."""
        preset = default_preset(self.session, grid_id)
        if preset is None:
            raise ValueError("the survey has no preset to prepare the grid with")
        self.session.remember_slice_source(grid_id, preset=preset, lines=tuple(keys))
        self.send_source()

    def on_session_changed(self) -> None:
        """A session signal while the site shows (from `rebuild_source`).

        The cached stretch is not dropped here (final review I2): its key
        holds everything a session edit can change in the values drawn
        (`display_limit`), so a velocity edit, which only relabels depths,
        keeps it, and a spacing edit or a move does not.
        """
        self.send_source()
        self.refresh_rows()
        self.update_export_button()
        self.schedule_refresh()

    # ---- the grid list and normalisation ----------------------------------------
    def refresh_rows(self) -> None:
        """The grid list and the radius tooltip, from one pass over the lines (M3)."""
        dock = self.dock
        if not self.session.is_open:
            dock.site_panel.set_rows([])
            return
        by_grid = keys_by_grid(self.session)
        included = included_grids(self.session, by_grid)
        dock.site_panel.set_rows(site_rows(self.session, self.engine, included, by_grid))
        dock.radius_spacing_spin.setToolTip(
            radius_tooltip(self.session, included, dock.radius_spacing_spin.value())
        )

    def update_export_button(self) -> None:
        """Ruling T4-a: no export while an included grid is queued or preparing."""
        ready = bool(self.engine.ready_grids) and self.engine.lattice is not None
        self.dock.export_button.setEnabled(ready and not busy(self.engine, self.included()))

    def on_changed(self) -> None:
        """`SiteEngine.on_changed`, kept cheap: the rows, the export button, and
        a tick when the ready grids changed. It may run between the site's
        gate and its dispatch, so it never prepares This grid (R-P5)."""
        try:
            if not self.showing or not self.session.is_open:
                return
            self.refresh_rows()
            self.update_export_button()
            if self.engine.ready_grids != self.ready_handled:
                self.schedule_refresh()
        except Exception as exc:  # noqa: BLE001 -- reached from task callbacks
            _log(f"could not update the site list: {exc}")

    def _on_included_changed(self, grid_ids: object) -> None:
        try:
            included = tuple(grid_ids)  # type: ignore[call-overload]
            if included == self.included():
                return
            self.session.set_site_view(grids=included)
            if included != self.cell_seeded_for:
                self.seed_resolution(included)
            self.send_source()
            self.apply_resolution()
        except Exception as exc:  # noqa: BLE001 -- a slot on a panel signal
            self.dock.error.emit(f"could not change the site's grids: {exc}")

    def _on_transform_changed(self, text: str) -> None:
        try:
            self.session.set_site_view(transform=text)
            self.refill_palette()
            self.send_source()
            self.schedule_refresh()
        except Exception as exc:  # noqa: BLE001 -- a slot on a panel signal
            self.dock.error.emit(f"could not change the site's transform: {exc}")

    def _on_selected_changed(self, grid_id: str) -> None:
        try:
            gain = self.session.grid_gain(grid_id) if grid_id and self.session.is_open else 1.0
            self.dock.normalisation_panel.set_grid(grid_id or None, gain)
        except Exception as exc:  # noqa: BLE001 -- a slot on a panel signal
            _log(f"could not follow the selected grid: {exc}")

    def _on_method_changed(self, method: str) -> None:
        try:
            self.session.set_site_view(normalisation=method)
            self.schedule_refresh()
        except Exception as exc:  # noqa: BLE001 -- a slot on a panel signal
            self.dock.error.emit(f"could not change the normalisation: {exc}")

    def _on_gain_changed(self, grid_id: str, gain: float) -> None:
        try:
            self.session.set_grid_gain(grid_id, gain)
            self.schedule_refresh()
        except Exception as exc:  # noqa: BLE001 -- a slot on a panel signal
            self.dock.error.emit(f"could not change grid {grid_id!r}'s gain: {exc}")

    def _on_radius_changed(self, _value: float) -> None:
        try:
            if self.showing:
                self.refresh_rows()  # the tooltip's metres per grid
                self.dock._debounce.start()
        except Exception as exc:  # noqa: BLE001 -- a slot on valueChanged
            _log(f"could not follow the fill radius: {exc}")

    # ---- resolution ---------------------------------------------------------------
    def seed_resolution(self, included: tuple[str, ...]) -> None:
        """Spec 4.4: the cell by M11's rule for the finest-spaced included grid;
        dz/z0/z1 from what the grids cover -- the ready grids' prepared
        bounds when there are any, else their headers."""
        dock = self.dock
        seed = seed_cell(self.session, included) if self.session.is_open else None
        if seed is not None:
            floor, cell = seed
            set_cell_floor(dock, floor)
            set_spins_quietly(dock, cell=cell)
        self.cell_seeded_for = included
        if self.z_custom or self.seed_z_from_ready():
            return
        header = header_z_seed(self.session, included) if seed is not None else None
        if header is not None:
            dt, lo, hi = header
            for spin in (dock.dz_spin, dock.z0_spin, dock.z1_spin):
                spin.setSingleStep(dt)
            set_spins_quietly(dock, dz=dt, z0=lo, z1=hi)

    def seed_z_from_ready(self) -> bool:
        """dz/z0/z1 from the union of the ready grids' prepared bounds (spec
        4.3), or -- once the user has set them -- only clamped into it, as
        M11's `_clamp_z_to_prepared` does. Whether anything moved."""
        from nsgeo_qgis.ui.slices_dock import _snap_inside  # the dock imports this module

        dock = self.dock
        bounds = ready_z_bounds(self.engine)
        if bounds is None:
            return False
        z0 = _snap_inside(bounds[0], dock.z0_spin.decimals(), upper=False)
        z1 = _snap_inside(bounds[1], dock.z1_spin.decimals(), upper=True)
        if self.z_custom:
            return bool(
                set_spins_quietly(
                    dock, z0=max(dock.z0_spin.value(), z0), z1=min(dock.z1_spin.value(), z1)
                )
            )
        values = {"z0": z0, "z1": z1}
        dt = ready_dt(self.engine)
        if dt is not None:
            for spin in (dock.dz_spin, dock.z0_spin, dock.z1_spin):
                spin.setSingleStep(dt)
            values["dz"] = dt
        return bool(set_spins_quietly(dock, **values))

    def _note_z_edit(self, _value: float) -> None:
        """A dz/z0/z1 change while the site shows that is not a seed (seeds are
        signal-blocked) is the user's: clamped from now on, never re-seeded."""
        if self.showing and not self.dock._updating:
            self.z_custom = True

    def apply_resolution(self, *, refresh: bool = True) -> None:
        """The Resolution spins to the site, then the slider and a tick. An
        unchanged resolution is not re-sent: it would drop every gather."""
        dock = self.dock
        try:
            resolution = Resolution(
                cell=dock.cell_spin.value(),
                dz_ns=dock.dz_spin.value(),
                t0_ns=dock.z0_spin.value(),
                t1_ns=dock.z1_spin.value(),
            )
        except ValueError as exc:
            dock.error.emit(str(exc))
            return
        try:
            if resolution != self.res_applied:
                self.res_applied = None
                self.limit_cache = None
                self.engine.set_resolution(resolution)
                self.res_applied = resolution
        except Exception as exc:  # noqa: BLE001 -- e.g. a lattice too large to draw
            dock.error.emit(str(exc))
        try:
            self.sync_slider()
            if refresh:
                self.schedule_refresh()
        except Exception as exc:  # noqa: BLE001 -- reached from slots
            _log(f"could not follow the site's resolution: {exc}")

    def sync_slider(self) -> None:
        """Range the slider over the site axis, keeping the top time shown."""
        slider = self.dock.slice_slider
        z = self.engine.site_z
        top = self.shown_top()
        slider.blockSignals(True)
        try:
            if z is None:
                slider.setRange(0, 0)
                self.pending_top = top
            else:
                slider.setRange(0, max(0, z.nz - 1))
                if top is not None:
                    nearest = int(round((top - z.t0_ns) / z.dz_ns))
                    slider.setValue(max(0, min(z.nz - 1, nearest)))
                self.pending_top = None
        finally:
            slider.blockSignals(False)
        self.z_shown = z

    # ---- the tick -------------------------------------------------------------------
    def schedule_refresh(self) -> None:
        """Ruling T3-g: one tick per event-loop pass, always with the latest values."""
        if self.showing and not self.tick.isActive():
            self.tick.start()

    def _run_tick(self) -> None:
        try:
            if not self.showing:
                return
            ready = self.engine.ready_grids
            if ready != self.ready_handled:
                # Grids became ready, or left: the axis may have changed.
                self.ready_handled = ready
                self.limit_cache = None
                if self.seed_z_from_ready():
                    self.apply_resolution(refresh=False)
                self.sync_slider()
                self.update_export_button()
            self.refresh_slice()
        except Exception as exc:  # noqa: BLE001 -- a QTimer slot
            _log(f"could not redraw the site: {exc}")

    def refresh_slice(self) -> None:
        """One tick, now: every ready grid at the slider's window."""
        dock = self.dock
        try:
            z = self.engine.site_z
            if not self.showing or z is None or self.engine.lattice is None:
                self.slice = None
                self.window = None
                dock.readout.setText(
                    "preparing the site…" if self.engine.is_running else "not prepared"
                )
                dock.site_depths_label.setText("")
                dock.legend_label.setText("")
                dock.status_label.setText(self.engine.status_text())
                dock.slice_changed.emit()
                dock.window_cleared.emit()
                return
            thickness, step = levels(z, dock.thickness_spin.value(), dock.step_spin.value())
            top = z.t0_ns + dock.slice_slider.value() * z.dz_ns
            window = window_on(z, top, thickness * z.dz_ns)
            if window is None:
                raise RuntimeError("the slider is off the site's time axis")
            shown = self.engine.slice_at(
                top,
                thickness * z.dz_ns,
                radius_spacings=dock.radius_spacing_spin.value(),
                method=dock.normalisation_panel.method(),
                manual=self.gains(),
                coverage=dock.coverage_check.isChecked(),
            )
            self.slice = shown
            self.window = window
            dock.readout.setText(readout(z, window, thickness, step))
            dock.site_depths_label.setText(
                depths_text(self.engine, shown.windows, self.velocities())
            )
            self.update_legend()
            lo_ns, hi_ns = window_times_ns(z, window)
            dock.window_changed.emit(lo_ns, hi_ns)
            dock.status_label.setText(self.engine.status_text())
            dock.slice_changed.emit()
        except Exception as exc:  # noqa: BLE001 -- reached from slots and timers
            self.slice = None
            self.window = None
            dock.readout.setText(f"error: {exc}")
            dock.site_depths_label.setText("")
            dock.legend_label.setText("")
            dock.slice_changed.emit()
            dock.window_cleared.emit()
            dock.error.emit(str(exc))

    # ---- display ---------------------------------------------------------------------
    def refill_palette(self) -> None:
        """Tables for the site transform's polarity, keeping the one shown if offered."""
        combo = self.dock.palette_combo
        unipolar = self.transform() != NO_TRANSFORM
        names = colormap_names(unipolar=unipolar)
        current = combo.currentText()
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItems(names)
            fallback = "amp_black_high" if unipolar else DEFAULT_COLORMAP
            combo.setCurrentText(current if current in names else fallback)
        finally:
            combo.blockSignals(False)

    def update_legend(self) -> None:
        dock = self.dock
        limit = self.display_limit()
        if dock.coverage_check.isChecked():
            dock.legend_label.setText(f"1 – {limit:.3g} traces per cell · blank = no line crossed")
            return
        base = f"0 – {limit:.3g}" if self.unipolar() else f"−{limit:.3g} – {limit:.3g}"
        # The title the combo shows, as This grid's legend does (#82).
        dock.legend_label.setText(f"{base} ({dock.site_panel.transform_combo.currentText()})")

    def unipolar(self) -> bool:
        return self.transform() != NO_TRANSFORM

    def display_limit(self) -> float:
        """Spec 4.5: shared across the site by default, measured after
        normalisation and the manual gains (`SiteEngine.shared_limit`).
        Cached by everything it measures over and never by the slider: it
        costs seconds on a large streaming site (Task 3's measurement).
        `values_key` is each ready grid's registration and line spacing
        (final review I2): a grid edit re-measures only when it changes
        the values drawn, never for a velocity edit."""
        dock = self.dock
        shown = self.slice
        if dock.coverage_check.isChecked():
            if shown is None:
                return 1.0
            finite = shown.array[np.isfinite(shown.array)]
            return max(1.0, float(finite.max())) if finite.size else 1.0
        clip: Any = UnipolarClip() if self.unipolar() else PercentileClip()
        if dock.stretch_combo.currentIndex() == 1:  # "this slice"
            return limit_over_slices((shown.array,), clip) if shown is not None else 1.0
        z = self.engine.site_z
        if shown is None or z is None:
            return 1.0
        thickness, _ = levels(z, dock.thickness_spin.value(), dock.step_spin.value())
        gains = self.gains()
        method = dock.normalisation_panel.method()
        radius = dock.radius_spacing_spin.value()
        key = (
            thickness,
            self.source_sent,
            self.res_applied,
            self.engine.ready_grids,
            method,
            tuple(sorted(gains.items())),
            radius,
            self.unipolar(),
            self.engine.values_key(),
        )
        if self.limit_cache is None or self.limit_cache[0] != key:
            value = self.engine.shared_limit(
                thickness * z.dz_ns, clip, radius_spacings=radius, method=method, manual=gains
            )
            self.limit_cache = (key, value)
        return self.limit_cache[1]

    def dispose(self) -> None:
        self.tick.stop()
