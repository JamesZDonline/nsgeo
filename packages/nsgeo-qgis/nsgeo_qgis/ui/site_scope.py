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

Minimum curvature follows This grid's flow (interpolation spec §7, plan
calls 5 and 7; `refine_flow.RefineFlow`) on the dock's one `refiner`: a
tick that previews a slow grid starts the site's own rest, the rest queues
`SiteEngine.pending_solves` for that tick and then the stretch windows not
solved, and a landed solve redraws through `schedule_refresh()` when the
tick on screen waits for it. A tick by any other method stops the list and
the rest, as before minimum curvature came. Leaving the site stops them too.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
from nsgeo.processing import TIME_BASE_RADAR, time_base_of
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
from nsgeo_qgis.slices_engine import PendingSolve
from nsgeo_qgis.slices_plan import (
    NO_TRANSFORM,
    TIME_BASE_MIXED,
    Resolution,
    SiteSource,
    SliceFinish,
    SourceChoice,
    combined_time_base,
    default_cell,
    mixed_clock_note,
    smallest_safe_cell,
)
from nsgeo_qgis.ui.finish_panel import DISTANCE_TIP, busy_cursor
from nsgeo_qgis.ui.refine_flow import RefineFlow
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
    if none is remembered or they have all left the grid (#74, #100: the reading
    `SlicesDock._read_remembered_lines` gives This grid, so both scopes agree)."""
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


def _then(text: str, sentence: str) -> str:
    """`sentence` after `text` as its own sentence (a full stop is added if `text` has none)."""
    if text and not text.endswith((".", "!", "?")):
        text += "."
    return f"{text} {sentence}".strip()


def grid_time_bases(
    session: Any, source: SiteSource, site_engine: Any | None = None
) -> dict[str, str]:
    """Each grid's clock, as the picture and the export have it (#97, ruling R15).

    A ready grid is read from the steps its preparation captured
    (`provenance().steps`), which a later save over the preset does not
    change. A grid still queued or preparing has no cubes yet, so its live
    preset stands in. A grid with no lines or a failed preparation is not
    drawn or exported, so it is left out. Without `site_engine` every grid
    is read from its live preset.
    """
    out: dict[str, str] = {}
    for choice in source.grids:
        steps: Any = None
        if site_engine is not None:
            state = state_text(site_engine, choice.grid_id)
            engine = site_engine.engine_for(choice.grid_id)
            if state == "ready" and engine is not None:
                steps = engine.provenance().steps
            elif state in ("queued", "waiting") or state.startswith("preparing"):
                steps = None
            else:
                continue
        if steps is None:
            steps = session.site.presets.get(choice.preset, [])
        out[choice.grid_id] = time_base_of(steps)
    return out


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
    lattice over all of them can be larger than is drawn at this cell; the
    engine then draws a coarser preview and says so (`SiteEngine.preview_note`).
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


def max_distance_tooltip(session: Any, included: Iterable[str], spacings: float) -> str:
    """The Max distance control's tooltip, with each included grid's metres
    (interpolation spec §8): the one value is a multiple of every grid's own
    line spacing, so grids with different spacings are treated alike."""
    metres = [f"{g} {spacings * session.grid(g).default_spacing:.2f} m" for g in included]
    text = (
        DISTANCE_TIP + " (in each grid's own line spacings, so grids with different spacings "
        "are treated alike)"
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
    dock.site_note.setVisible(site)
    dock.grid_finish.setVisible(not site)
    dock.site_finish.setVisible(site)
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
    `dock.normalisation_panel` and `dock.site_finish` are wired here.
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
        #: Why the last resolution was refused (None when it was applied).
        self.problem: str | None = None
        #: The ready grids the last tick was set up for.
        self.ready_handled: tuple[str, ...] | None = None
        #: `(top_ns, thickness_ns)` of the last tick, as `slice_at` took them:
        #: the window its rest solves, never one re-derived from the spins.
        self.drawn_at: tuple[float, float] | None = None
        #: The included set the cell was last seeded for (spec 4.4: only when
        #: it changes). Which of dz/z0/z1 are the user's is no flag here: it
        #: is read off the remembered record each time (`seed_z`, #71).
        self.cell_seeded_for: tuple[str, ...] | None = None
        #: The site's Resolution values when the dock last left it.
        self.spins: Spins | None = None
        #: Ruling T3-g: at most one tick per event-loop pass, latest values.
        self.tick = QTimer(dock)
        self.tick.setSingleShot(True)
        self.tick.setInterval(0)
        self.tick.timeout.connect(self._run_tick)
        #: An Interpolation edit's redraw waits out This grid's pause
        #: (`dock._finish_debounce`): it re-plans every grid's weights and
        #: re-measures the shared stretch, so a keystroke or a held arrow must
        #: not pay that once a step. 0.2.0's site radius went through
        #: `dock._debounce`, the same 120 ms.
        self.finish_debounce = QTimer(dock)
        self.finish_debounce.setSingleShot(True)
        self.finish_debounce.setInterval(dock._finish_debounce.interval())
        self.finish_debounce.timeout.connect(self._on_finish_timeout)
        #: The site's side of the dock's refiner (plan calls 5 and 7): its
        #: rest, its preview, the running list's progress, and the shared
        #: stretch, `(key, limit, final)` keyed by `stretch_key`.
        self.refine = RefineFlow(dock, dock.refiner, self._on_rest)

        dock.site_panel.included_changed.connect(self._on_included_changed)
        dock.site_panel.transform_changed.connect(self._on_transform_changed)
        dock.site_panel.selected_changed.connect(self._on_selected_changed)
        dock.normalisation_panel.method_changed.connect(self._on_method_changed)
        dock.normalisation_panel.gain_changed.connect(self._on_gain_changed)
        dock.site_finish.edited.connect(self._on_finish_edited)

    @property
    def session(self) -> Any:
        return self.dock.session

    @property
    def engine(self) -> Any:
        return self.dock.site_engine

    @property
    def showing(self) -> bool:
        return self.dock.scope() == "site"

    @property
    def provisional(self) -> bool:
        """Whether the site tick on screen previews a grid, refined once the
        depth rests (plan call 5)."""
        return self.refine.provisional

    def included(self) -> tuple[str, ...]:
        return included_grids(self.session) if self.session.is_open else ()

    # ---- entering and leaving ---------------------------------------------
    def enter(self, top: float | None) -> None:
        """The dock has switched to the site: restore its view and start it."""
        dock = self.dock
        self.pending_top = top
        self.z_shown = None
        self.ready_handled = None
        self.refine.stretch = None
        panel = dock.site_panel
        panel.set_transform(
            stored_transform(
                self.session, panel.transform_combo.values(), dock.transform_combo.value()
            )
        )
        dock.normalisation_panel.set_method(stored_method(self.session))
        # #71: the finish the user chose for the site, before the rows'
        # tooltip turns the max distance into metres. Quietly: a restore never
        # writes (interpolation spec §8).
        dock.site_finish.set_value(SliceFinish().updated(self.session.site_resolution()))
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
        self.finish_debounce.stop()
        # The two scopes share the refiner: the site's list must not run on
        # under This grid, nor its rest fire there.
        self.refine.stop()
        self.engine.cancel()
        self.slice = None
        self.window = None
        self.drawn_at = None

    def forget(self) -> None:
        """A different survey: nothing the last one's site view held applies,
        the interpolation settings included (#71: a second survey inherited the first's)."""
        self.spins = None
        self.cell_seeded_for = None
        self.source_sent = None
        self.res_applied = None
        self.problem = None
        self.refine.stretch = None
        self.dock.site_finish.set_value(SliceFinish())

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
            self.refine.stretch = None
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
        """A line choice for one grid: its remembered source; only it re-prepares.
        Every line ticked is every line, now and later (#101, the user's
        ruling): remembered as `lines=None`, as This grid's `set_included` does."""
        preset = default_preset(self.session, grid_id)
        if preset is None:
            raise ValueError("the survey has no preset to prepare the grid with")
        every = set(grid_keys(self.session, grid_id))
        lines = None if set(keys) == every else tuple(keys)
        self.session.remember_slice_source(grid_id, preset=preset, lines=lines)
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
        """The grid list and the max distance tooltip, from one pass over the lines (M3)."""
        dock = self.dock
        if not self.session.is_open:
            dock.site_panel.set_rows([])
            return
        by_grid = keys_by_grid(self.session)
        included = included_grids(self.session, by_grid)
        dock.site_panel.set_rows(site_rows(self.session, self.engine, included, by_grid))
        dock.site_finish.max_distance_spin.setToolTip(
            max_distance_tooltip(self.session, included, dock.site_finish.max_distance_spin.value())
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

    def _on_finish_edited(self, field: str, value: float | str) -> None:
        """The site's Interpolation panel was edited by hand: remember it for
        the site (#71) and refresh the tooltip's metres at once, as This grid
        remembers and relabels at once, then redraw after the pause
        (`finish_debounce`). A seed or restore never gets here
        (`FinishPanel.set_value` announces nothing). Guarded: a raising
        receiver of `FinishPanel.edited` is reported by PyQt's unraisable
        hook, not by the panel's own guard."""
        try:
            if self.showing and self.session.is_open:
                self.session.remember_site_resolution(**{field: value})
                self.refresh_rows()
                self.finish_debounce.start()
        except Exception as exc:  # noqa: BLE001 -- a slot on `FinishPanel.edited`
            _log(f"could not follow the interpolation setting: {exc}")

    def _on_finish_timeout(self) -> None:
        try:
            self.schedule_refresh()
        except Exception as exc:  # noqa: BLE001 -- a QTimer.timeout slot
            _log(f"could not redraw after an interpolation edit: {exc}")

    # ---- resolution ---------------------------------------------------------------
    def seed_resolution(self, included: tuple[str, ...]) -> None:
        """Spec 4.4: the cell by M11's rule for the finest-spaced included grid,
        then dz/z0/z1 by `seed_z`, from the included grids' headers until one
        is ready.

        A cell the user chose for the site (#71) is laid over the cell seed,
        quietly, as This grid lays a grid's own over its seed; the floor just
        raised clamps it. A remembered cell leaves the z range seeded.
        """
        dock = self.dock
        is_open = self.session.is_open
        seed = seed_cell(self.session, included) if is_open else None
        if seed is not None:
            floor, cell = seed
            set_cell_floor(dock, floor)
            set_spins_quietly(dock, cell=cell)
        remembered = self.session.site_resolution() if is_open else {}
        if "cell" in remembered:
            set_spins_quietly(dock, cell=remembered["cell"])
        self.cell_seeded_for = included
        self.seed_z(included)

    def seed_z(self, included: tuple[str, ...] | None = None) -> bool:
        """dz/z0/z1, field by field (#71, Ruling 14), on every seed and every
        change to the ready grids. Whether any spin moved.

        The bounds are the union of the ready grids' prepared bounds (spec
        4.3), snapped inside them. Before any grid is ready they are the
        headers of `included`, which only `seed_resolution` passes: a tick
        with nothing ready leaves the spins alone.

        A field the user chose -- a hand edit is remembered at once, through
        `SlicesDock._on_resolution_edited` -- is read from the record, never
        from its spin: dz as remembered, and z0/z1 clamped into the bounds as
        M11's `_clamp_z_to_prepared` clamps. So a range clamped while only one
        short grid was ready widens again as the others become ready. A field
        never chosen takes the data's own value: the sample interval, or the
        bounds. Each on its own, so a remembered dz does not hold z0/z1.

        As in M11 (Review Focus 1), a range the clamp would leave empty
        (z1 <= z0), such as a remembered one wholly past the data, takes the
        bounds at both ends. The record is never written here: it stands, for
        a later crop that frees the range, until the user edits the other end
        against the range shown (Ruling 15, `SlicesDock._edited_fields`)."""
        from nsgeo_qgis.ui.slices_dock import _snap_inside  # the dock imports this module

        dock = self.dock
        if not self.session.is_open:
            return False
        bounds = ready_z_bounds(self.engine)
        if bounds is not None:
            low = _snap_inside(bounds[0], dock.z0_spin.decimals(), upper=False)
            high = _snap_inside(bounds[1], dock.z1_spin.decimals(), upper=True)
            dt = ready_dt(self.engine)
        else:
            header = header_z_seed(self.session, included) if included else None
            if header is None:
                return False
            dt, low, high = header
        remembered = self.session.site_resolution()
        z0 = max(remembered["t0_ns"], low) if "t0_ns" in remembered else low
        z1 = min(remembered["t1_ns"], high) if "t1_ns" in remembered else high
        if z1 <= z0:
            z0, z1 = low, high
        values = {"z0": z0, "z1": z1}
        if dt is not None:
            # One sample per arrow click, whatever dz the user chose.
            for spin in (dock.dz_spin, dock.z0_spin, dock.z1_spin):
                spin.setSingleStep(dt)
        if "dz_ns" in remembered:
            values["dz"] = remembered["dz_ns"]
        elif dt is not None:
            values["dz"] = dt
        return bool(set_spins_quietly(dock, **values))

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
                self.refine.stretch = None
                self.engine.set_resolution(resolution)
                self.res_applied = resolution
            self.problem = None
        except Exception as exc:  # noqa: BLE001 -- e.g. a resolution or transform the engine
            # refuses; a size never is one (a big site is drawn as a preview). The
            # reason is kept for the panel, where it outlasts the toast.
            self.problem = str(exc)
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
                # Grids became ready, or left: the axis may have changed, so
                # the stretch is measured afresh. A running list was queued
                # for the old grids and axis: cancelled here, since the tick
                # below may be a full draw, which leaves a list alone (final
                # review M-5).
                self.ready_handled = ready
                self.refine.stretch = None
                self.refine.cancel()
                if self.seed_z():
                    self.apply_resolution(refresh=False)
                self.sync_slider()
                self.update_export_button()
            # The wait cursor is the tick's own: only it knows which grids it
            # finishes, and so whether it builds anything (`refresh_slice`).
            self.refresh_slice()
        except Exception as exc:  # noqa: BLE001 -- a QTimer slot
            _log(f"could not redraw the site: {exc}")

    def refresh_slice(self) -> None:
        """One tick, now: every ready grid at the slider's window.

        With minimum curvature a grid whose solve is slow is drawn as its
        kriging preview, and the flow decides the rest and the worker from
        what the tick previewed (`RefineFlow.previewed`): a preview of a new
        window cancels a running list, a landed grid's redraw while the
        others still solve does not. A full minimum-curvature tick leaves a
        running list alone; any other method's stops it (plan call 5).

        Which grids the tick previews is known only once it has drawn them,
        but whether it builds new weights or plans is known before, from the
        grids present at its window alone (`SiteEngine.weights_cached(...,
        at=)`): a grid whose axis misses it builds nothing here. A tick that
        builds shows the wait cursor, and cancels a running list first, so
        the old list neither competes with every grid's build nor keeps the
        plans it drops alive through it (`RefineFlow.before_draw`).
        """
        dock = self.dock
        try:
            z = self.engine.site_z
            self.show_note(drawn=self.showing and z is not None and self.engine.lattice is not None)
            if not self.showing or z is None or self.engine.lattice is None:
                self.refine.stop()  # nothing drawn: no refine is owed
                self.slice = None
                self.window = None
                self.drawn_at = None
                dock.readout.setText(
                    "preparing the site…" if self.engine.is_running else "not prepared"
                )
                dock.site_depths_label.setText("")
                dock.legend_label.setText("")
                dock.status_label.setText(self.engine.status_text())
                dock.show_refine()
                dock.slice_changed.emit()
                dock.window_cleared.emit()
                return
            thickness, step = levels(z, dock.thickness_spin.value(), dock.step_spin.value())
            top = z.t0_ns + dock.slice_slider.value() * z.dz_ns
            window = window_on(z, top, thickness * z.dz_ns)
            if window is None:
                raise RuntimeError("the slider is off the site's time axis")
            finish = dock.site_finish.value()
            curvature = finish.method == "min_curvature"
            coverage = dock.coverage_check.isChecked()
            # A coverage tick finishes nothing, so builds nothing.
            builds = not coverage and not self.engine.weights_cached(
                finish, at=(top, thickness * z.dz_ns)
            )
            self.refine.before_draw(rebuilds=builds)
            # Building the weights, or the plans and their previews, takes
            # seconds at a fine cell: say so (interpolation spec §7).
            with busy_cursor() if builds else contextlib.nullcontext():
                shown = self.engine.slice_at(
                    top,
                    thickness * z.dz_ns,
                    finish=finish,
                    method=dock.normalisation_panel.method(),
                    manual=self.gains(),
                    coverage=coverage,
                    preview=curvature,
                )
            self.slice = shown
            self.window = window
            self.drawn_at = (top, thickness * z.dz_ns)
            if shown.provisional:
                self.refine.previewed((g.engine, g.key) for g in shown.previewed.values())
            else:
                self.refine.finished(stop=not curvature)
            dock.readout.setText(readout(z, window, thickness, step))
            dock.site_depths_label.setText(
                depths_text(self.engine, shown.windows, self.velocities())
            )
            self.update_legend()
            lo_ns, hi_ns = window_times_ns(z, window)
            dock.window_changed.emit(lo_ns, hi_ns)
            dock.status_label.setText(self.status_text())
            dock.show_refine()
            dock.slice_changed.emit()
        except Exception as exc:  # noqa: BLE001 -- reached from slots and timers
            # No preview stands, so no refine is owed (plan call 5).
            self.refine.stop()
            dock.status_label.setText(self.engine.status_text())
            dock.show_refine()
            self.slice = None
            self.window = None
            self.drawn_at = None
            dock.readout.setText(f"error: {exc}")
            dock.site_depths_label.setText("")
            dock.legend_label.setText("")
            dock.slice_changed.emit()
            dock.window_cleared.emit()
            dock.error.emit(str(exc))

    def show_note(self, *, drawn: bool) -> None:
        """The site note: the preview note while drawn, the reason when nothing
        is drawn and one is known, else empty. The tooltip carries the full
        text. A preview site still exports at full detail, so it says nothing
        about the export.

        When the drawn grids are not all on one clock (some have no Time zero
        step) the note ends with `mixed_clock_note`, as its own sentence, in
        the text and the tooltip alike; a site wholly on the radar clock says
        nothing, since its grids still line up."""
        note = self.dock.site_note
        engine = self.engine
        text = hint = ""
        if drawn and engine.preview_note:
            text = hint = engine.preview_note
        elif not drawn and self.problem:
            text = hint = f"Not drawn: {self.problem}"
        source = self.source_sent or self.source()
        if source is not None:
            bases = grid_time_bases(self.session, source, engine)
            radar = [g for g, base in bases.items() if base == TIME_BASE_RADAR]
            if bases and combined_time_base(bases.values()) == TIME_BASE_MIXED:
                mixed = mixed_clock_note(radar)
                text = _then(text, mixed)
                hint = _then(hint, mixed)
        note.set_hint(hint, whole=True)
        note.setText(text)

    # ---- minimum curvature's refine ---------------------------------------------------
    def status_text(self) -> str:
        """The site's status line: memory and redraw time only. Refine states
        show in the indicator on the readout's row (walkthrough round 1, W1)."""
        return self.engine.status_text()

    def _on_rest(self) -> None:
        """The depth has rested: solve, in the background, the grids the tick
        on screen previewed, then any shared-stretch window still unsolved
        (plan calls 5 and 7). The rest timer's slot, so it guards its own body.

        `pending_solves` is given the tick itself, so its slices and keys are
        reused rather than taken again. A stretch already final for what is
        drawn asks for no solves (Ruling R11): asking slices and hashes every
        grid's window of every stretch window here, on the GUI thread.

        The panel is read live, so an Interpolation edit still waiting out its
        pause (`finish_debounce`) is already in `finish`. Its plans are not
        built yet, and building them here would cost seconds in this slot,
        with no wait cursor (final review M-1). Such a rest does nothing: the
        edit's tick builds under the cursor and arms the rest again.
        """
        dock = self.dock
        try:
            z, drawn, at = self.engine.site_z, self.slice, self.drawn_at
            if (
                not self.showing
                or z is None
                or drawn is None
                or at is None
                or dock.coverage_check.isChecked()
            ):
                return
            refine = self.refine
            finish = dock.site_finish.value()
            if not self.engine.weights_cached(finish, at=at):
                return
            top, thickness_ns = at
            current: list[PendingSolve] = []
            if refine.provisional:
                current = self.engine.pending_solves(top, thickness_ns, finish, drawn=drawn)
            stretch: list[PendingSolve] = []
            if dock.stretch_combo.currentIndex() != 1 and not refine.stretch_final(
                self.stretch_key(z)
            ):
                stretch = self.engine.stretch_solves(thickness_ns, finish)
            if refine.rested(current, stretch, self._on_landed, self._on_refine_error):
                self.schedule_refresh()
            else:
                dock.show_refine()
        except Exception as exc:  # noqa: BLE001 -- a QTimer.timeout slot
            dock.error.emit(f"could not start refining the site: {exc}")

    def _on_landed(self, job: Any) -> None:
        """A background solve has finished, handed over on the GUI thread. It
        lands in its grid's engine whatever is on screen, and redraws only
        when the tick on screen waits for it, or the list has ended
        (`RefineFlow.landed`): a solve for a window left behind never draws
        over the newer one. A refine callback, so it guards its own body."""
        try:
            redraw = self.refine.landed(job)
            if not self.showing:
                return
            if redraw:
                self.schedule_refresh()
            else:
                self.dock.show_refine()
        except Exception as exc:  # noqa: BLE001 -- from the refine worker's poll timer
            self.dock.error.emit(f"could not draw the refined site: {exc}")

    def _on_refine_error(self, message: str) -> None:
        """A background solve failed: say so, and leave the preview on screen,
        blanks and all, with the site's own status line."""
        try:
            self.dock.error.emit(self.refine.failed(message))
            if self.showing:
                self.dock.show_refine()
        except Exception:  # noqa: BLE001 -- from the refine worker's poll timer
            _log(f"could not report that minimum curvature failed on the site: {message}")

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

    def stretch_key(self, z: ZAxis) -> tuple[Any, ...]:
        """Everything the site's shared stretch is measured over, and never
        the slider: it costs seconds on a large streaming site (Task 3's
        measurement). `values_key` is each ready grid's registration and
        line spacing (final review I2): a grid edit re-measures only when it
        changes the values drawn, never for a velocity edit."""
        dock = self.dock
        thickness, _ = levels(z, dock.thickness_spin.value(), dock.step_spin.value())
        return (
            thickness,
            self.source_sent,
            self.res_applied,
            self.engine.ready_grids,
            dock.normalisation_panel.method(),
            tuple(sorted(self.gains().items())),
            dock.site_finish.value(),
            self.unipolar(),
            self.engine.values_key(),
        )

    def display_limit(self) -> float:
        """Spec 4.5: shared across the site by default, measured after
        normalisation and the manual gains (`SiteEngine.shared_limit`), and
        held until `stretch_key` moves.

        Minimum curvature (plan call 7, Ruling R3): until each grid's window
        of the windows it is measured over is solved, the limit is the
        provisional one over their kriging previews (`SiteEngine.
        stretch_limit`), and it arms the site's rest while nothing is on its
        way to finish it, so the next rest queues their solves. The landing
        that ends the list drops it (`RefineFlow.stretch_limit`)."""
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
        finish = dock.site_finish.value()

        def measure() -> tuple[float, bool]:
            # The stretch finishes every grid at up to twelve windows, so it
            # builds for a grid the tick shown missed: say so too.
            waiting = (
                contextlib.nullcontext() if self.engine.weights_cached(finish) else busy_cursor()
            )
            with waiting:
                return self.engine.stretch_limit(
                    thickness * z.dz_ns, clip, finish=finish, method=method, manual=gains
                )

        return self.refine.stretch_limit(self.stretch_key(z), measure)

    def dispose(self) -> None:
        self.tick.stop()
        self.finish_debounce.stop()
        self.refine.stop()
