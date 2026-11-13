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
@pytest.mark.parametrize("n_picks", [0, 3])
def test_the_scene_opens_in_pvpython(tmp_path, n_picks):
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
    picks_at = np.array([[2.0, 3.0, -1.0], [4.0, 3.0, -2.0], [6.0, 3.0, -3.0]])[:n_picks]
    write_poly_data(
        tmp_path / "picks.vtp",
        picks_at.reshape(-1, 3),
        {
            "true_depth_m": np.array([0.3, 0.6, 0.9], np.float32)[:n_picks],
            "line": np.zeros(n_picks, np.int32),
        },
        verts=[[i] for i in range(n_picks)],
    )
    write_poly_data(
        tmp_path / "lines.vtp",
        np.array([[5, 0, 0], [5, 8, 0]], dtype=np.float32),
        {},
        lines=[[0, 1]],
    )
    write_scene_files(tmp_path, scene_record(**{**FIELDS, "n_picks": n_picks}), "paraview")
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
    # ParaView logs a warning (and may open its Output Messages window) when a colour range
    # cannot be read, as from an empty picks file; the scene prints "open_scene:" for a
    # setting this ParaView lacks.
    assert "WARN|" not in run.stderr and "ERR|" not in run.stderr, run.stderr
    assert "open_scene:" not in run.stdout, run.stdout
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


def test_scene_title_names_the_grid_and_states_the_stretch():
    from nsgeo_qgis.paraview_scene import scene_title

    assert scene_title("Grid A", 3.0) == "Grid A  ·  depth stretched x3  ·  legend shows true depth"
    assert "x2.5" in scene_title("G", 2.5)


# ---- the export dialog's wording ----------------------------------------------------------


def _summary(**over):
    from nsgeo_qgis.paraview_scene import ExportSummary

    fields = dict(
        folder=Path("/site/paraview/Grid A"),
        replaces=False,
        nx=120,
        ny=48,
        nd=300,
        max_depth_m=2.4,
        fill_method="min_curvature",
        n_picks=1,
        n_lines=4,
        export_bytes=1_500_000_000,
        cache_bytes=800_000_000,
        free_bytes=50_000_000_000,
    )
    fields.update(over)
    return ExportSummary(**fields)


def test_summary_rows_say_what_will_be_written():
    from nsgeo_qgis.paraview_scene import summary_rows

    rows = dict(summary_rows(_summary()))
    assert list(rows) == ["Folder", "Volume", "Fill", "Also", "Size", "Disk"]
    assert rows["Volume"] == "120 × 48 cells × 300 depths, 0 – 2.40 m"
    assert rows["Fill"] == "Minimum curvature"
    assert rows["Also"] == "1 pick, 4 lines"
    assert rows["Size"] == "about 1.5 GB, plus 800 MB fill kept for quick re-exports"
    assert rows["Disk"] == "50.0 GB free"
    assert "replaces" not in rows["Folder"] and "Grid A" in rows["Folder"]


def test_a_replaced_export_and_a_kept_fill_are_said():
    from nsgeo_qgis.paraview_scene import summary_rows

    rows = dict(summary_rows(_summary(replaces=True, cache_bytes=0)))
    assert rows["Folder"].endswith("(replaces the last export)")
    assert rows["Size"] == "about 1.5 GB; fill already kept"


def test_the_disk_row_warns_below_files_plus_fill_plus_headroom():
    from nsgeo_qgis.paraview_scene import disk_is_short, disk_text

    need = 1_500_000_000 + 800_000_000 + 500_000_000
    assert not disk_is_short(_summary(free_bytes=need))
    short = _summary(free_bytes=need - 1)
    assert disk_is_short(short)
    text = disk_text(short)
    assert text.startswith("only 2.8 GB free") and "needs about 2.8 GB" in text
    assert "needs about 2.8 GB" in disk_text(_summary(free_bytes=2_500_000_000))


def test_messages_name_the_folder_and_the_script():
    from nsgeo_qgis.paraview_scene import (
        CANCELLED_MESSAGE,
        exported_message,
        how_to_open_message,
        launch_failed_message,
    )

    folder = Path("/site/paraview/A")
    assert exported_message("A", folder) == f"Exported A for ParaView to {folder}"
    assert "run open.sh there" in how_to_open_message("A", folder)
    assert "run open.bat there" in how_to_open_message("A", folder, windows=True)
    assert launch_failed_message("A", folder, "/usr/bin/pv") == (
        f"Exported A for ParaView to {folder}. ParaView could not be started from "
        "/usr/bin/pv. Run open.sh there, or fix the ParaView path in the export dialog."
    )
    skipped = launch_failed_message("A", folder, "/usr/bin/pv", skipped=["x"])
    assert skipped == (
        f"Exported A for ParaView to {folder}. 1 line could not be prepared: x. "
        "ParaView could not be started from /usr/bin/pv. Run open.sh there, "
        "or fix the ParaView path in the export dialog."
    )
    assert CANCELLED_MESSAGE == "ParaView export cancelled"


def test_the_deepest_time_hint_gives_the_depth_and_where_the_record_ends():
    from nsgeo_qgis.paraview_scene import t1_hint

    assert t1_hint(1.42, 100.0) == "1.42 m; the record ends at 100.0 ns"
    assert t1_hint(None, 99.5) == "the record ends at 99.5 ns"


def test_the_too_shallow_message_says_what_to_change():
    from nsgeo_qgis.paraview_scene import shallow_t1_message

    text = shallow_t1_message(0.0)
    assert "Down to must be deeper than time zero" in text and "0.0 ns" in text


def test_the_hints_name_the_panels_cell_and_the_files_step():
    from nsgeo_qgis.paraview_scene import cell_hint, dt_hint

    assert cell_hint(0.25) == "Slices panel: 0.25 m"
    assert "not set" in cell_hint(None)
    assert dt_hint(0.4) == "files: 0.4 ns"


def test_the_disk_refuses_only_what_cannot_fit_with_its_margin():
    from nsgeo_qgis.paraview_scene import (
        disk_is_short,
        disk_refusal,
        disk_text,
        export_margin_bytes,
        fill_margin_bytes,
    )

    assert fill_margin_bytes(800_000_000) == 500_000_000  # half a gigabyte...
    assert fill_margin_bytes(20_000_000_000) == 2_000_000_000  # ...or a tenth of the fill
    assert export_margin_bytes(1_500_000_000) == 150_000_000
    # Tight (under files + fill + half a gigabyte) but it fits: a warning, no refusal.
    tight = _summary(free_bytes=2_500_000_000)
    assert disk_is_short(tight) and disk_refusal(tight) == ""
    # The fill alone needs 800 MB + 500 MB; one byte less is refused, and says how much.
    fill_short = _summary(free_bytes=1_299_999_999)
    assert "fill" in disk_refusal(fill_short) and "1.3 GB" in disk_refusal(fill_short)
    assert disk_refusal(fill_short) in disk_text(fill_short)
    # The fill fits but the export's files do not fit after it.
    after = _summary(free_bytes=800_000_000 + 1_650_000_000 - 1)
    assert "export" in disk_refusal(after) and "fill" not in disk_refusal(after)
    assert disk_refusal(_summary(free_bytes=800_000_000 + 1_650_000_000)) == ""
    # A kept fill asks nothing of the disk.
    assert disk_refusal(_summary(cache_bytes=0, free_bytes=1_650_000_000)) == ""


def test_skipped_lines_are_named_with_a_count_when_many():
    from nsgeo_qgis.paraview_scene import exported_message, skipped_text

    assert skipped_text([]) == ""
    assert skipped_text(["a"]) == "1 line could not be prepared: a"
    assert skipped_text(["a", "b"]) == "2 lines could not be prepared: a, b"
    assert skipped_text(list("abcde")) == "5 lines could not be prepared: a, b, c, and 2 more"
    folder = Path("/s/p/A")
    assert exported_message("A", folder) == f"Exported A for ParaView to {folder}"
    assert exported_message("A", folder, ["x"]).endswith(". 1 line could not be prepared: x")


def test_the_windows_launcher_does_not_hold_the_folder_and_keeps_crlf(tmp_path):
    write_scene_files(tmp_path, scene_record(**FIELDS), "C:\\pv\\paraview.exe")
    raw = (tmp_path / "open.bat").read_bytes()
    text = raw.decode()
    assert "cd " not in text and "\n" not in text.replace("\r\n", "")
    assert text.count("\r\n") == len(text.splitlines())
    assert 'start "" /D "%HERE%.." "C:\\pv\\paraview.exe" --script="%HERE%open_scene.py"' in text
    assert 'set "NSGEO_SCENE_DIR=%HERE%"' in text


def test_skipped_lines_are_recorded_in_the_scene_record():
    assert scene_record(**FIELDS)["skipped_lines"] == []
    assert scene_record(**FIELDS, skipped_lines=["a"])["skipped_lines"] == ["a"]
