"""Session S: the surfaces on the M16 walkthrough site (real data, never written to).

Its Grid1 Slices cell is the float tail 0.05000000000000002 (#204)."""

from __future__ import annotations

import types
from pathlib import Path

import pytest
from nsgeo.model.survey import Line
from nsgeo.slices import SurfaceSettings
from nsgeo_qgis import paraview_export
from nsgeo_qgis.paraview_export import ParaViewExport
from nsgeo_qgis.session import Pick
from nsgeo_qgis.ui.site_scope import source_keys
from plugin_testing import Dock, needs_walk_site, open_walk_site, reopened

pytestmark = needs_walk_site

GRID = "Grid1"


def _noop(done, total):
    return True


def _pick(key: str, trace: int, time_ns: float) -> Pick:
    return Pick(
        line_key=key,
        trace=trace,
        time_ns=time_ns,
        distance_m=None,
        depth_m=None,
        velocity_m_ns=None,
        stack_json="",
        note="",
        created="2026-11-20T00:00:00+00:00",
        zero_ns=None,
    )


@pytest.fixture
def walk(qgis_app, tmp_path):
    """`(session, dock, export, layers, surfaces)` on a copy of the walkthrough site."""
    from nsgeo_qgis.layers import SiteLayers
    from nsgeo_qgis.surfaces import Surfaces
    from qgis.core import QgsProject

    session = open_walk_site(tmp_path)
    dock = Dock(session)
    export = ParaViewExport(session, dock)
    project = QgsProject.instance()
    project.clear()
    layers = SiteLayers(session, project=project)
    layers.refresh()
    surfaces = Surfaces(session, layers, export_for=lambda: export)
    export.surfaces = surfaces
    yield session, dock, export, layers, surfaces
    layers.detach()
    project.clear()
    dock.dispose()


def test_the_walk_site_keeps_a_built_surface_fresh(walk):
    """#204: an untouched export of the float-tail cell leaves the surface fresh. #203: so does
    a reopen without Save site, whatever the Slices panel's transform then is."""
    from nsgeo_qgis.ui.paraview_dialog import ParaViewExportDialog

    session, dock, export, layers, surfaces = walk
    dock.transform_combo = types.SimpleNamespace(value=lambda: "amp_abs")
    assert session.slice_resolution(GRID)["cell"] == 0.05000000000000002
    keys = source_keys(session, GRID)
    for key, trace in zip((keys[3], keys[10], keys[20], keys[30]), (20, 60, 100, 140)):
        layers.write_pick(_pick(key, trace, 12.0 + trace / 40))
    fids = sorted(f.id() for f in layers.layers["picks"].dataProvider().getFeatures())
    record = surfaces.create("Bowl", fids, SurfaceSettings(strength=0.0))
    surfaces.build([record.feature_id], progress=_noop)
    assert surfaces.state(record.feature_id).stale == ()
    dialog = ParaViewExportDialog(
        [GRID], GRID, export.defaults, export.summary, "", hints_for=export.panel_values
    )
    try:
        choice = dialog.choice()
    finally:
        dialog.deleteLater()
    session.remember_volume(GRID, **choice.to_record())
    assert session.volume_record(GRID)["cell"] == 0.05
    assert surfaces.state(record.feature_id).stale == ()
    # A reopen of the saved copy: the round trip's record was never saved, so it is empty.
    with reopened(session, layers) as (again, dock2, _export2, again_surfaces):
        dock2.transform_combo = types.SimpleNamespace(value=lambda: "amp_square")
        assert again.volume_record(GRID) == {}
        state = again_surfaces.state(record.feature_id)
        assert state.built and state.stale == ()


def test_a_moved_line_file_is_read_once_on_the_walk_site(qgis_app, tmp_path, monkeypatch):
    """#219 on real data: a line whose file has moved is asked about once, not on every refresh."""
    link = tmp_path / "moved.DZT"

    def edit(doc):
        entry = next(e for e in doc["lines"] if (e.get("placement") or {}).get("grid_id") == GRID)
        link.symlink_to(Path(entry["path"]))
        entry["path"] = str(link)

    session = open_walk_site(tmp_path, edit=edit)
    keys = list(source_keys(session, GRID))
    moved = next(k for k in keys if session.line_for_key(k).path == link)
    other = next(k for k in keys if k != moved)
    link.unlink()
    reads: list[Path] = []
    original = Line.load

    def counting(self):
        reads.append(self.path)
        return original(self)

    monkeypatch.setattr(Line, "load", counting)
    logged: list[str] = []
    monkeypatch.setattr(paraview_export, "_log", logged.append)
    dock = Dock(session)
    try:
        export = ParaViewExport(session, dock)
        rows = [(moved, _pick(moved, 30, 12.0)), (other, _pick(other, 30, 12.0))]
        for _ in range(2):
            got = export.pick_depths(GRID, rows)
            assert got[0] is None and got[1] is not None
        assert reads.count(link) == 1
        assert len(logged) == 1 and moved in logged[0]
    finally:
        dock.dispose()
