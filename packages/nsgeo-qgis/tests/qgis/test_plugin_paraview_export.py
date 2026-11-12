"""Export for ParaView (M16 A): the folder, its cube at its own resolution, picks on the cube's
clock, the fill cache, cancelling and the refusals. Real DZT lines, real files on disk."""

from __future__ import annotations

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
from plugin_testing import REAL_DZT, needs_real_data

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
        self.transform_combo = types.SimpleNamespace(currentText=lambda: "amp_square")

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


def test_a_second_preparation_is_refused_while_the_dock_is_preparing(site, monkeypatch):
    session, dock, export = site
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


def test_a_too_fine_cell_is_refused_before_anything_is_prepared_or_written(site, monkeypatch):
    session, dock, export = site
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
