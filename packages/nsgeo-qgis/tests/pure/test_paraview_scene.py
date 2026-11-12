from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest
from nsgeo.vtkxml import write_image_data, write_poly_data
from nsgeo_qgis.paraview_scene import SCENE_FILES, scene_record, write_scene_files

PLUGIN = Path(__file__).parents[2] / "nsgeo_qgis"

FIELDS = dict(
    grid="Grid A",
    title="Grid A  ·  depth stretched x3  ·  legend shows true depth",
    stretch=3.0,
    crs="EPSG:32633",
    origin=[500000.0, 4000000.0],
    azimuth_deg=10.0,
    cell_m=0.5,
    dz_ns=0.1,
    depth_step_m=0.02,
    max_depth_m=1.2,
    source={"preset": "p", "transform": "squared", "lines": 4, "time_base": "time_zero"},
    fill={
        "method": "idw",
        "max_distance_m": 0.5,
        "search_radius_m": 1.0,
        "smooth_x_m": 0.0,
        "smooth_y_m": 0.0,
    },
    volume={"period_ns": 2.5, "blur_m": 0.1, "trend_m": 0.15},
    amplitude_range=[0.0, 4.0],
    slices={"depth_m": 0.6, "x_m": 5.0, "y_m": 4.0, "lines_along": "y"},
    n_picks=0,
    nsgeo_version="0.0.0",
    written_utc="2026-01-01T00:00:00Z",
)


def test_write_scene_files_writes_every_file_and_the_record(tmp_path):
    write_scene_files(tmp_path, scene_record(**FIELDS), "/opt/pv/bin/paraview")
    assert {p.name for p in tmp_path.iterdir()} == {"export.json", *SCENE_FILES}
    assert "/opt/pv/bin/paraview" in (tmp_path / "open.sh").read_text()
    assert "{{PARAVIEW}}" not in (tmp_path / "open.bat").read_text()
    assert os.access(tmp_path / "open.sh", os.X_OK)
    rec = json.loads((tmp_path / "export.json").read_text())
    assert rec["iso_level"] == 2.5 and rec["cloud_ramp"] == [[1.8, 0.0], [5.0, 0.6]]
    assert rec["strength_range"] == [0.0, 5.0] and rec["paraview_checked"] == "6.2.1"


def test_an_empty_paraview_path_falls_back_to_the_command_name(tmp_path):
    write_scene_files(tmp_path, scene_record(**FIELDS), "")
    assert '"paraview"' in (tmp_path / "open.sh").read_text()


def test_scene_record_rejects_a_missing_or_unknown_field():
    fields = dict(FIELDS)
    del fields["n_picks"]
    with pytest.raises(TypeError, match="n_picks"):
        scene_record(**fields)
    with pytest.raises(TypeError, match="surprise"):
        scene_record(**FIELDS, surprise=1)


def test_scene_record_rejects_a_bad_slices_block():
    with pytest.raises(ValueError):
        scene_record(**{**FIELDS, "slices": {"depth_m": 1.0}})
    with pytest.raises(ValueError):
        scene_record(**{**FIELDS, "slices": {**FIELDS["slices"], "lines_along": "z"}})


def test_no_template_is_a_py_file():
    names = [p.name for p in (PLUGIN / "paraview").iterdir()]
    assert names and all(n.endswith(".txt") for n in names)


def test_every_scene_file_has_a_template():
    for name in SCENE_FILES:
        assert (PLUGIN / "paraview" / f"{name}.txt").is_file()


_CHECK = """
import os, sys
os.environ["NSGEO_SCENE_DIR"] = {folder!r}
src = open(os.path.join({folder!r}, "open_scene.py"), encoding="utf-8").read()
exec(compile(src, "open_scene.py", "exec"), {{"__name__": "__main__"}})  # no __file__
from paraview.simple import *
print("NAMES:" + "|".join(sorted(name for name, _ in GetSources())))
SaveScreenshot({shot!r}, GetActiveView(), ImageResolution=[400, 300])
"""


@pytest.mark.skipif(not os.environ.get("NSGEO_PVPYTHON"), reason="set NSGEO_PVPYTHON to a pvpython")
def test_the_scene_opens_in_pvpython(tmp_path):
    nx, ny, nz = 20, 16, 30
    zz, yy, xx = np.meshgrid(np.arange(nz), np.arange(ny), np.arange(nx), indexing="ij")
    blob = 5.0 * np.exp(-(((xx - 10) / 4.0) ** 2 + ((yy - 8) / 4.0) ** 2 + ((zz - 15) / 5.0) ** 2))
    blob = blob.astype(np.float32)
    depth = np.broadcast_to(np.linspace(1.2, 0.0, nz, dtype=np.float32)[:, None, None], blob.shape)
    stretch = 3.0
    chunks = lambda a: lambda: iter([a[k].ravel() for k in range(nz)])  # noqa: E731
    write_image_data(
        tmp_path / "cube.vti",
        origin=(0.25, 0.25, -1.2 * stretch),
        spacing=(0.5, 0.5, 1.2 * stretch / (nz - 1)),
        shape=(nx, ny, nz),
        arrays=[
            ("strength", chunks(blob)),
            ("amplitude", chunks(blob)),
            ("true_depth_m", chunks(np.ascontiguousarray(depth))),
        ],
    )
    write_poly_data(
        tmp_path / "picks.vtp",
        np.empty((0, 3)),
        {"true_depth_m": np.empty(0, np.float32), "line": np.empty(0, np.int32)},
    )
    write_poly_data(
        tmp_path / "lines.vtp",
        np.array([[5, 0, 0], [5, 8, 0]], dtype=np.float32),
        {},
        lines=[[0, 1]],
    )
    write_scene_files(tmp_path, scene_record(**FIELDS), "paraview")
    shot = tmp_path / "shot.png"
    check = tmp_path / "check_scene.py"
    check.write_text(_CHECK.format(folder=str(tmp_path), shot=str(shot)), encoding="utf-8")
    run = subprocess.run(
        [os.environ["NSGEO_PVPYTHON"], "--force-offscreen-rendering", str(check)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert run.returncode == 0, run.stderr
    assert "Traceback" not in run.stderr and "Traceback" not in run.stdout
    names = next(ln for ln in run.stdout.splitlines() if ln.startswith("NAMES:"))[6:].split("|")
    for want in (
        "Cloud",
        "Isosurface",
        "Isosurface inside a box",
        "Depth slice",
        "Slice along a line",
        "Slice across the lines",
        "Your picks",
        "Survey lines",
        "Box around the cube",
    ):
        assert want in names
    assert shot.stat().st_size > 10_000
    keep = os.environ.get("NSGEO_KEEP_SHOT")
    if keep:
        Path(keep).write_bytes(shot.read_bytes())
