"""Export for ParaView (M16 A): the folder, its cube at its own resolution, picks on the cube's
clock, the fill cache, cancelling and the refusals. Real DZT lines, real files on disk."""

from __future__ import annotations

import contextlib
import json
import re
import types
from pathlib import Path

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.slices import CubeFrame, VolumeSettings
from nsgeo.velocity import VelocityModel
from nsgeo_qgis import paraview_export, slices_engine
from nsgeo_qgis.paraview_export import ParaViewExport, ParaViewExportCancelled, paraview_folder
from nsgeo_qgis.paraview_scene import SCENE_FILES
from nsgeo_qgis.session import Pick, SiteSession
from nsgeo_qgis.slices_engine import SliceEngine
from nsgeo_qgis.slices_plan import Resolution, SourceChoice, VolumeChoice
from nsgeo_qgis.ui.site_scope import default_preset, source_keys
from plugin_testing import REAL_DZT, needs_real_data, spin_until, synthetic_dzt

GRID = Grid("Grid A", (0.0, 0.0), 0.0, 3.0, 12.0, "EPSG:32616", 0.5)
STEPS_ZERO = [
    {"step": "time_zero", "params": {}, "enabled": True},
    {"step": "dewow", "params": {}, "enabled": True},
    {"step": "background_mean", "params": {}, "enabled": True},
]
STEPS_RADAR = STEPS_ZERO[1:]


class Dock:
    """What the exporter reads from the Slices dock: two engines and the transform combo."""

    def __init__(self, session):
        self.engine = SliceEngine(session)
        self.site_engine = SliceEngine(session)
        self.transform_combo = types.SimpleNamespace(value=lambda: "amp_square")
        self.registered: list = []
        self.foreign_preparing = False

    @contextlib.contextmanager
    def foreign_preparation(self, engine):
        self.registered.append(engine)
        try:
            yield
        finally:
            self.registered.remove(engine)

    def dispose(self):
        self.engine.dispose()
        self.site_engine.dispose()


@pytest.fixture
def site(qgis_app, tmp_path):
    """Four real lines on a grid, in a site folder whose path has a space in it."""
    folder = tmp_path / "my site"
    folder.mkdir()
    session = SiteSession()
    session.new_site(folder)
    session.add_grid(GRID)
    lines = [
        Line.open(
            REAL_DZT[i], GridPlacement("Grid A", "y", 0.5 + i * 0.5, 0.0, 1, REAL_DZT[i].stem)
        )
        for i in range(4)
    ]
    session.add_lines(lines)
    session.site.presets["p"] = list(STEPS_ZERO)
    dock = Dock(session)
    yield session, dock, ParaViewExport(session, dock)
    dock.dispose()


@pytest.fixture
def synth_site(qgis_app, tmp_path):
    """The same site on synthetic lines: for tests that prepare nothing (they run on CI)."""
    folder = tmp_path / "my site"
    folder.mkdir()
    session = SiteSession()
    session.new_site(folder)
    session.add_grid(GRID)
    lines = []
    for i in range(2):
        path = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(path, GridPlacement("Grid A", "y", 0.5 + i, 0.0, 1, path.stem)))
    session.add_lines(lines)
    session.site.presets["p"] = list(STEPS_ZERO)
    dock = Dock(session)
    yield session, dock, ParaViewExport(session, dock)
    dock.dispose()


def _choice(session, **over):
    dt = session.line_for_key(session.keys()[0]).header.dt_ns
    fields = dict(cell=0.25, dz_ns=dt, transform="amp_square", stretch=3.0)
    fields.update(over)
    return VolumeChoice(**fields)


def _noop(done, total):
    return True


def read_vti(path: Path):
    """`(extent, origin, spacing, arrays)` of an appended-raw VTI; arrays are (nz, ny, nx)."""
    raw = path.read_bytes()
    head, _, _ = raw.partition(b'<AppendedData encoding="raw">\n_')
    text = head.decode()
    ext = [int(v) for v in re.search(r'WholeExtent="([^"]+)"', text).group(1).split()]
    origin = [float(v) for v in re.search(r'Origin="([^"]+)"', text).group(1).split()]
    spacing = [float(v) for v in re.search(r'Spacing="([^"]+)"', text).group(1).split()]
    nx, ny, nz = ext[1] + 1, ext[3] + 1, ext[5] + 1
    base = len(head) + len(b'<AppendedData encoding="raw">\n_')
    arrays = {}
    for name, offset in re.findall(
        r'Name="([^"]+)" NumberOfComponents="1" format="appended" offset="(\d+)"', text
    ):
        start = base + int(offset) + 8
        arrays[name] = np.frombuffer(raw[start : start + 4 * nx * ny * nz], "<f4").reshape(
            nz, ny, nx
        )
    return ext, origin, spacing, arrays


def read_points(path: Path) -> np.ndarray:
    raw = path.read_bytes()
    head, _, _ = raw.partition(b'<AppendedData encoding="raw">\n_')
    n = int(re.search(r'NumberOfPoints="(\d+)"', head.decode()).group(1))
    off = int(re.search(r'<Points>\s*<DataArray[^>]*offset="(\d+)"', head.decode()).group(1))
    start = len(head) + len(b'<AppendedData encoding="raw">\n_') + off + 8
    return np.frombuffer(raw[start : start + 12 * n], "<f4").reshape(n, 3)


def read_point_array(path: Path, name: str, dtype: str) -> np.ndarray:
    raw = path.read_bytes()
    head, _, _ = raw.partition(b'<AppendedData encoding="raw">\n_')
    text = head.decode()
    n = int(re.search(r'NumberOfPoints="(\d+)"', text).group(1))
    off = int(re.search(rf'Name="{name}"[^>]*offset="(\d+)"', text).group(1))
    start = len(head) + len(b'<AppendedData encoding="raw">\n_') + off + 8
    return np.frombuffer(raw[start:], dtype)[:n] if n else np.empty(0)


def _prepare_panel(session, dock, choice, resolution=None):
    preset = default_preset(session, "Grid A")
    dock.engine.set_source(
        SourceChoice("Grid A", preset, choice.transform, source_keys(session, "Grid A"))
    )
    assert dock.engine.wait_for_preparation(60_000)
    dock.engine.set_resolution(resolution or Resolution(0.5, 1.0, 2.0, 30.0))


@needs_real_data
def test_export_writes_the_folder_ParaView_opens(site):
    session, dock, export = site
    choice = _choice(session)
    _prepare_panel(session, dock, choice)
    before = (dock.engine.choice, dock.engine.frame, dock.engine.z)
    estimate = export.estimate("Grid A", choice)
    seen: list[tuple[int, int]] = []
    folder = export.run(
        "Grid A", choice, progress=lambda d, t: seen.append((d, t)) or True, paraview_path="pv"
    )
    assert folder == paraview_folder(session, "Grid A")
    assert folder == Path(session.root) / "paraview" / "Grid_A"
    files = {p.name for p in folder.iterdir()}
    assert files == {"cube.vti", "picks.vtp", "lines.vtp", "export.json", *SCENE_FILES}
    assert not list(folder.parent.glob("*.partial")) and not list(folder.parent.glob("*.old"))
    ext, origin, spacing, arrays = read_vti(folder / "cube.vti")
    nx, ny = 12, 48  # a 3 x 12 m grid at the 0.25 m cell
    assert ext[:4] == [0, nx - 1, 0, ny - 1]
    record = json.loads((folder / "export.json").read_text())
    assert record["cell_m"] == choice.cell and record["dz_ns"] == choice.dz_ns
    assert record["title"].startswith("Grid A") and "x3" in record["title"]
    nd = ext[5] + 1
    depths = [record["max_depth_m"] - k * record["depth_step_m"] for k in range(nd)]
    assert spacing[2] == pytest.approx(record["depth_step_m"] * 3.0)
    assert origin[2] == pytest.approx(-record["max_depth_m"] * 3.0)
    assert depths[-1] >= 0.0
    assert set(arrays) == {"strength", "amplitude", "true_depth_m"}
    assert np.isfinite(arrays["strength"]).any()
    assert arrays["true_depth_m"][0, 0, 0] == pytest.approx(record["max_depth_m"], rel=1e-5)
    assert abs(estimate - (folder / "cube.vti").stat().st_size) <= 0.05 * estimate
    assert record["slices"]["lines_along"] == "y" and record["n_picks"] == 0
    assert seen[-1][0] == seen[-1][1] and all(a <= b for a, b in seen)
    # Exporting changed nothing the Slices panel shows or holds.
    assert (dock.engine.choice, dock.engine.frame, dock.engine.z) == before
    assert not dock.engine.has_cube


@needs_real_data
def test_export_reuses_the_dock_engines_lines_when_the_source_matches(site, monkeypatch):
    session, dock, export = site
    choice = _choice(session)
    _prepare_panel(session, dock, choice)
    calls: list[int] = []
    original = slices_engine.SliceEngine.set_source

    def spy(self, source):
        calls.append(1)
        return original(self, source)

    monkeypatch.setattr(slices_engine.SliceEngine, "set_source", spy)
    export.run("Grid A", choice, progress=_noop)
    assert calls == []
    # A different transform is a different source: the panel's lines are not used.
    export.run("Grid A", _choice(session, transform="amp_envelope"), progress=_noop)
    assert len(calls) == 1


@needs_real_data
def test_a_cancelled_export_leaves_the_previous_one_intact(site):
    session, _, export = site
    choice = _choice(session)
    folder = export.run("Grid A", choice, progress=_noop)
    snapshot = {p.name: p.read_bytes() for p in folder.iterdir()}
    calls = {"n": 0}

    def stop_after_three(done, total):
        calls["n"] += 1
        return calls["n"] <= 3

    with pytest.raises(ParaViewExportCancelled):
        export.run("Grid A", _choice(session, stretch=5.0), progress=stop_after_three)
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == snapshot
    assert not list(folder.parent.glob("*.partial")) and not list(folder.parent.glob("*.old"))
    # And a cancel during the very first fill leaves no half cache behind.
    calls["n"] = 0
    with pytest.raises(ParaViewExportCancelled):
        export.run("Grid A", _choice(session, dz_ns=0.5), progress=stop_after_three)
    assert not list((folder.parent / ".cache").glob("*.part"))
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == snapshot


@needs_real_data
def test_a_cancel_during_the_write_pass_leaves_the_previous_export_intact(site):
    session, _, export = site
    choice = _choice(session)
    folder = export.run("Grid A", choice, progress=_noop)
    snapshot = {p.name: p.read_bytes() for p in folder.iterdir()}
    partial = folder.with_name(folder.name + ".partial")
    seen = {"partial": False}

    def stop_in_the_write_pass(done, total):
        if done >= total - 1:  # the last slab of the amplitude pass
            seen["partial"] = partial.exists()
            return False
        return True

    with pytest.raises(ParaViewExportCancelled):
        export.run("Grid A", _choice(session, stretch=5.0), progress=stop_in_the_write_pass)
    assert seen["partial"], "the cancel came before .partial existed"
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == snapshot
    assert not list(folder.parent.glob("*.partial")) and not list(folder.parent.glob("*.old"))


@needs_real_data
def test_cache_bytes_states_what_the_cache_adds_then_zero(site):
    session, dock, export = site
    choice = _choice(session)
    _prepare_panel(session, dock, choice)
    before = export.cache_bytes("Grid A", choice)
    export.run("Grid A", choice, progress=_noop)
    (cache,) = (Path(session.root) / "paraview" / ".cache").glob("Grid_A-*.npy")
    assert abs(before - cache.stat().st_size) <= 0.01 * before
    assert export.cache_bytes("Grid A", choice) == 0
    assert export.cache_bytes("Grid A", _choice(session, dz_ns=0.5)) > 0
    # With nothing prepared in the panel the figure still reads the cache on disk...
    dock.engine.set_source(None)
    assert export.cache_bytes("Grid A", choice) == 0
    # ...but only for these settings: another transform writes a whole new cache.
    other = _choice(session, transform="amp_abs")
    stated = export.cache_bytes("Grid A", other)
    assert stated > 0
    export.run("Grid A", other, progress=_noop)
    (cache,) = (Path(session.root) / "paraview" / ".cache").glob("Grid_A-*.npy")
    assert abs(stated - cache.stat().st_size) <= 0.01 * stated


@needs_real_data
def test_one_grids_cache_cleanup_leaves_another_grids_alone(site):
    session, dock, export = site
    other = Grid("Grid A-2", (50.0, 0.0), 0.0, 3.0, 12.0, "EPSG:32616", 0.5)
    session.add_grid(other)
    cache = Path(session.root) / "paraview" / ".cache"
    cache.mkdir(parents=True)
    neighbour = cache / "Grid_A-2-0123456789abcdef-fedcba9876543210.npy"
    neighbour.write_bytes(b"x")
    export.run("Grid A", _choice(session), progress=_noop)
    export.run("Grid A", _choice(session, dz_ns=0.5), progress=_noop)  # replaces its own
    assert neighbour.read_bytes() == b"x"
    own = [f for f in cache.glob("Grid_A-*.npy") if not f.name.startswith("Grid_A-2-")]
    assert len(own) == 1


@needs_real_data
def test_the_standalone_engine_holds_both_dock_engines_back(site, monkeypatch):
    """R12: while the export's own engine prepares, the Slices dock's grid engine and the
    site engine start nothing; what they owed runs once it has finished."""
    from nsgeo_qgis.slices_plan import SiteSource
    from nsgeo_qgis.ui.slices_dock import SlicesDock

    session, _, _ = site
    dock = SlicesDock(session)
    own = SliceEngine(session)
    started_tasks: list[int] = []
    original = slices_engine.SliceEngine._start_task

    def counting(self, *args, **kwargs):
        started_tasks.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(slices_engine.SliceEngine, "_start_task", counting)
    try:
        assert dock.engine.wait_for_preparation(60_000)
        dock.engine.set_source(None)
        choice = _choice(session)
        keys = source_keys(session, "Grid A")
        source = SourceChoice("Grid A", "p", "amp_square", keys)
        dock._grid_prepare_pending = False
        started = len(started_tasks)
        with dock.foreign_preparation(own):
            own.set_source(source)
            assert own.has_live_task
            dock.prepare()  # the grid engine's turn
            dock.site_engine.set_source(SiteSource("amp_square", (source,)))  # and the site's
            assert dock._grid_prepare_pending
            assert not dock.engine.has_live_task and not dock.site_engine.has_live_task
            assert len(started_tasks) == started + 1  # only the export's own engine started
            assert own.wait_for_preparation(60_000)
        # No deadlock: what was held runs now, and finishes.
        assert dock.site_engine.wait_until_idle(60_000)
        assert spin_until(lambda: dock.engine.is_prepared, 60_000)
        assert dock.site_engine.grid_state("Grid A") == "ready"
        assert not dock.engine.has_live_task and not dock.site_engine.has_live_task
        assert dock.refiner is not None and choice
    finally:
        own.dispose()
        dock.refiner.shutdown()
        dock.site_engine.cancel()
        dock.site_engine.wait_until_idle(20_000)
        dock.engine.wait_for_preparation(20_000)
        dock.engine.dispose()
        dock.site_engine.dispose()
        dock.deleteLater()


@needs_real_data
def test_an_engine_whose_task_outlives_its_span_still_holds_both_dock_engines_back(site):
    """R15: leaving `foreign_preparation` with a task still alive keeps it registered."""
    from nsgeo_qgis.slices_plan import SiteSource
    from nsgeo_qgis.ui.slices_dock import SlicesDock

    session, _, _ = site
    dock = SlicesDock(session)
    own = SliceEngine(session)
    try:
        assert dock.engine.wait_for_preparation(60_000)
        dock.engine.set_source(None)
        source = SourceChoice("Grid A", "p", "amp_square", source_keys(session, "Grid A"))
        dock._grid_prepare_pending = False
        with dock.foreign_preparation(own):
            own.set_source(source)
            assert own.has_live_task
        # The span is over, the task is not: both gates are still shut.
        assert own.has_live_task and own in dock._foreign
        dock.prepare()
        dock.site_engine.set_source(SiteSource("amp_square", (source,)))
        assert dock._grid_prepare_pending
        assert not dock.engine.has_live_task and not dock.site_engine.has_live_task
        assert own.wait_for_preparation(60_000)
        assert spin_until(lambda: own not in dock._foreign, 20_000)
        assert dock.site_engine.wait_until_idle(60_000)
        assert spin_until(lambda: dock.engine.is_prepared, 60_000)
    finally:
        own.dispose()
        dock.refiner.shutdown()
        dock.site_engine.cancel()
        dock.site_engine.wait_until_idle(20_000)
        dock.engine.wait_for_preparation(20_000)
        dock.engine.dispose()
        dock.site_engine.dispose()
        dock.deleteLater()


@needs_real_data
def test_a_version_bump_states_the_full_cache_then_writes_it(site, monkeypatch):
    session, dock, export = site
    choice = _choice(session)
    export.run("Grid A", choice, progress=_noop)
    assert export.cache_bytes("Grid A", choice) == 0
    monkeypatch.setattr(paraview_export.nsgeo, "__version__", "99.0.0")
    stated = export.cache_bytes("Grid A", choice)
    assert stated > 0
    export.run("Grid A", choice, progress=_noop)
    (cache,) = (Path(session.root) / "paraview" / ".cache").glob("Grid_A-*.npy")
    assert abs(stated - cache.stat().st_size) <= 0.01 * stated


@needs_real_data
def test_a_second_export_is_refused_while_the_first_exports_engine_is_live(site, monkeypatch):
    from nsgeo_qgis.ui.slices_dock import SlicesDock

    session, _, _ = site
    dock = SlicesDock(session)
    export = ParaViewExport(session, dock)
    own = SliceEngine(session)
    try:
        assert dock.engine.wait_for_preparation(60_000)
        dock.engine.set_source(None)
        source = SourceChoice("Grid A", "p", "amp_square", source_keys(session, "Grid A"))
        with dock.foreign_preparation(own):
            own.set_source(source)
        assert own.has_live_task and dock.foreign_preparing  # the first export's span is over
        started: list[int] = []
        monkeypatch.setattr(slices_engine.SliceEngine, "set_source", lambda s, c: started.append(1))
        with pytest.raises(RuntimeError, match="Slices are still preparing"):
            export.run("Grid A", _choice(session), progress=_noop)
        assert started == []
        monkeypatch.undo()
        assert own.wait_for_preparation(60_000)
        assert spin_until(lambda: not dock.foreign_preparing, 20_000)
    finally:
        own.dispose()
        dock.refiner.shutdown()
        dock.site_engine.cancel()
        dock.site_engine.wait_until_idle(20_000)
        dock.engine.wait_for_preparation(20_000)
        dock.engine.dispose()
        dock.site_engine.dispose()
        dock.deleteLater()


@needs_real_data
def test_the_export_registers_its_engine_and_waits_without_user_input(site, monkeypatch):
    from qgis.PyQt.QtCore import QEventLoop

    session, dock, export = site
    seen: list[tuple[int, object]] = []
    original = slices_engine.SliceEngine.wait_for_preparation

    def spy(self, timeout_ms=20_000, flags=QEventLoop.ProcessEventsFlag.AllEvents):
        if self is not dock.engine and self is not dock.site_engine:
            seen.append((len(dock.registered), flags))
        return original(self, timeout_ms, flags)

    monkeypatch.setattr(slices_engine.SliceEngine, "wait_for_preparation", spy)
    export.run("Grid A", _choice(session), progress=_noop)
    assert seen and all(n == 1 for n, _ in seen)  # registered for the whole wait
    assert all(f == QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents for _, f in seen)
    assert dock.registered == []


def test_a_site_engine_with_grids_queued_refuses_the_export(synth_site, monkeypatch):
    session, dock, export = synth_site
    started: list[int] = []
    monkeypatch.setattr(slices_engine.SliceEngine, "set_source", lambda s, c: started.append(1))
    monkeypatch.setattr(
        type(dock.site_engine), "is_running", property(lambda self: self is dock.site_engine)
    )
    with pytest.raises(RuntimeError, match="Slices are still preparing"):
        export.run("Grid A", _choice(session), progress=_noop)
    assert started == []


def _picks_case(session, export, monkeypatch, steps, pick_zero):
    """Find where the cube's strength peaks over a line, store a pick there on another clock,
    export again: the pick must land on that peak (a clock slip of a few ns is 20+ levels)."""
    session.site.presets["p"] = list(steps)
    choice = _choice(session)
    monkeypatch.setattr(session, "picks_for", lambda key: [])
    probe = SliceEngine(session)
    try:
        probe.set_source(
            SourceChoice("Grid A", "p", choice.transform, source_keys(session, "Grid A"))
        )
        assert probe.wait_for_preparation(60_000)
        line = sorted(probe.prepared_lines(), key=lambda ln: ln.key)[1]
    finally:
        probe.dispose()
    trace = line.data.shape[1] // 2
    x, y = CubeFrame.for_grid(GRID, choice.cell).to_local(line.coords[trace : trace + 1])[0]
    ix, iy = int(x / choice.cell), int(y / choice.cell)
    folder = export.run("Grid A", choice, progress=_noop)
    _, origin, spacing, arrays = read_vti(folder / "cube.vti")
    depth_col = arrays["true_depth_m"][:, 0, 0]
    column = np.where(depth_col > 0.3, arrays["strength"][:, iy, ix], -np.inf)
    column = np.where(np.isfinite(column), column, -np.inf)
    peak = int(np.argmax(column))
    peak_depth = float(depth_col[peak])
    velocity = session.resolved_velocity(line.key)
    times = np.linspace(0.0, 150.0, 6001)
    t_cube = float(np.interp(peak_depth, velocity.depth_at(times), times))
    time_ns = t_cube + line.zero_ns - pick_zero
    pick = Pick(line.key, trace, time_ns, None, None, None, "", "", "", zero_ns=pick_zero)
    monkeypatch.setattr(session, "picks_for", lambda key: [pick] if key == line.key else [])
    folder = export.run("Grid A", choice, progress=_noop)
    points = read_points(folder / "picks.vtp")
    assert points.shape == (1, 3)
    at_pick = (points[0, 2] - origin[2]) / spacing[2]
    assert abs(at_pick - peak) <= 2, (at_pick, peak)
    assert points[0, 0] == pytest.approx(x, abs=1e-4) and points[0, 1] == pytest.approx(y, abs=1e-4)
    ids = read_point_array(folder / "picks.vtp", "line", "<i4")
    assert list(ids) == [1]
    assert read_point_array(folder / "picks.vtp", "true_depth_m", "<f4")[0] == pytest.approx(
        peak_depth, abs=2 * spacing[2] / choice.stretch
    )


@needs_real_data
def test_picks_land_on_the_cube_clock_with_and_without_time_zero(site, monkeypatch):
    session, _, export = site
    # With time zero: the pick is stored on the radar clock, the cube on the line's own zero.
    _picks_case(session, export, monkeypatch, STEPS_ZERO, 0.0)
    # Without it, the cube is on the radar clock; the pick row carries a zero of its own.
    _picks_case(session, export, monkeypatch, STEPS_RADAR, 7.0)


@needs_real_data
def test_pick_depths_use_the_volume_velocity(site, monkeypatch):
    session, _, export = site
    session.set_grid_velocity("Grid A", VelocityModel([(0.0, 0.1), (20.0, 0.06)]))
    choice = _choice(session)
    key = sorted(session.keys())[0]
    picks = [
        Pick(key, 30, t, None, None, None, "", "", "", zero_ns=None) for t in (10.0, 30.0, 55.0)
    ]
    monkeypatch.setattr(session, "picks_for", lambda k: list(picks) if k == key else [])
    folder = export.run("Grid A", choice, progress=_noop)
    depth = read_point_array(folder / "picks.vtp", "true_depth_m", "<f4")
    zs = read_points(folder / "picks.vtp")[:, 2]
    # Picks with no zero are on the radar clock, the preset's cube is on the line's zero.
    probe = SliceEngine(session)
    try:
        probe.set_source(SourceChoice("Grid A", "p", "amp_square", source_keys(session, "Grid A")))
        assert probe.wait_for_preparation(60_000)
        zero = {ln.key: ln.zero_ns for ln in probe.prepared_lines()}[key]
    finally:
        probe.dispose()
    velocity = session.resolved_velocity(key)
    expected = velocity.depth_at(np.array([10.0, 30.0, 55.0]) - zero)
    assert depth == pytest.approx(expected, rel=1e-4)
    assert zs == pytest.approx(-expected * choice.stretch, rel=1e-4)
    # The cube's own depth array is the same conversion.
    _, origin, spacing, arrays = read_vti(folder / "cube.vti")
    for z, d in zip(zs, depth):
        k = int(round((z - origin[2]) / spacing[2]))
        assert arrays["true_depth_m"][k, 0, 0] == pytest.approx(
            float(d), abs=spacing[2] / 3.0 * 1.01
        )


@needs_real_data
def test_the_fill_cache_is_reused_and_replaced(site, monkeypatch):
    session, _, export = site
    spy: list[int] = []
    original = paraview_export.fill_levels

    def counting(*args, **kwargs):
        spy.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(paraview_export, "fill_levels", counting)
    export.run("Grid A", _choice(session), progress=_noop)
    assert spy == [1]
    export.run("Grid A", _choice(session, stretch=5.0), progress=_noop)
    export.run("Grid A", _choice(session, settings=VolumeSettings(blur_m=0.0)), progress=_noop)
    assert spy == [1]
    cache = Path(session.root) / "paraview" / ".cache"
    assert len(list(cache.glob("Grid_A-*.npy"))) == 1
    old = list(cache.glob("Grid_A-*.npy"))[0].name
    export.run("Grid A", _choice(session, dz_ns=0.5), progress=_noop)
    assert spy == [1, 1]
    now = list(cache.glob("Grid_A-*.npy"))
    assert len(now) == 1 and now[0].name != old


def test_a_second_preparation_is_refused_while_the_dock_is_preparing(synth_site, monkeypatch):
    session, dock, export = synth_site
    started: list[int] = []
    monkeypatch.setattr(
        slices_engine.SliceEngine, "set_source", lambda self, source: started.append(1)
    )
    monkeypatch.setattr(
        type(dock.engine), "has_live_task", property(lambda self: self is dock.engine)
    )
    with pytest.raises(RuntimeError, match="Slices are still preparing"):
        export.run("Grid A", _choice(session), progress=_noop)
    assert started == []
    assert not (Path(session.root) / "paraview").exists()


def test_a_too_fine_cell_is_refused_before_anything_is_prepared_or_written(synth_site, monkeypatch):
    session, dock, export = synth_site
    started: list[int] = []
    monkeypatch.setattr(slices_engine.SliceEngine, "set_source", lambda s, c: started.append(1))
    fine = _choice(session, cell=0.001)  # 3 x 12 m at 1 mm: 36 million cells
    with pytest.raises(ValueError, match="too fine"):
        export.estimate("Grid A", fine)
    with pytest.raises(ValueError, match="too fine"):
        export.run("Grid A", fine, progress=_noop)
    assert started == []
    assert not (Path(session.root) / "paraview").exists()


@needs_real_data
def test_defaults_take_the_panel_values_then_the_record(site):
    session, dock, export = site
    first = export.defaults("Grid A")
    assert first.transform == "amp_square" and first.stretch == 3.0
    assert first.dz_ns == session.line_for_key(session.keys()[0]).header.dt_ns
    assert first.cell == 0.2  # default_cell(0.5 m spacing)
    session.remember_slice_resolution("Grid A", cell=0.4)
    session.remember_volume("Grid A", dz_ns=0.3, stretch=2.0)
    again = export.defaults("Grid A")
    assert (again.cell, again.dz_ns, again.stretch) == (0.4, 0.3, 2.0)
    assert session.volume_record("Grid A") == {"dz_ns": 0.3, "stretch": 2.0}


# ---- the dialog's summary --------------------------------------------------------------------


def test_summary_describes_the_export_without_preparing_anything(synth_site):
    session, dock, export = synth_site
    choice = _choice(session)
    s = export.summary("Grid A", choice)
    assert s.nx > 0 and s.ny > 0
    assert s.n_lines == 2 and s.n_picks == 0
    assert s.export_bytes == export.estimate("Grid A", choice)
    assert s.cache_bytes == export.cache_bytes("Grid A", choice) > 0
    assert s.max_depth_m > 0 and s.nd >= 2 and s.free_bytes > 0
    assert s.folder == paraview_folder(session, "Grid A") and not s.replaces
    assert not dock.engine.is_prepared  # nothing was prepared to answer


def test_summary_refuses_a_too_fine_cell_like_estimate(synth_site):
    session, _dock, export = synth_site
    with pytest.raises(ValueError, match="too fine"):
        export.summary("Grid A", _choice(session, cell=0.002))


def test_summary_counts_the_picks_and_sees_a_previous_export(synth_site, monkeypatch):
    session, _dock, export = synth_site
    key = source_keys(session, "Grid A")[0]
    pick = Pick(key, 5, 12.0, None, None, None, "", "", "", zero_ns=None)
    monkeypatch.setattr(session, "picks_for", lambda k: [pick] if k == key else [])
    paraview_folder(session, "Grid A").mkdir(parents=True)
    s = export.summary("Grid A", _choice(session))
    assert s.n_picks == 1 and s.replaces
