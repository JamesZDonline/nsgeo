"""The real Grad601 files (gitignored; every test skips on CI). Files are keyed by name."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.mag import MagFile, MagSetup
from nsgeo.mag.grad601 import mark_missing, missing_summary, read_grad601
from nsgeo.mag.map import DEFAULT_CELL_M, grid_map, mosaic
from nsgeo.slices import FinishSettings, bilinear_taps, sample

from tests.real_data import MAG_FILES

pytestmark = pytest.mark.skipif(not MAG_FILES, reason="no real mag files under tests/data/local")

MISSING = {
    "example1.dat": 0,
    "example2.dat": 0,
    "example3.dat": 7273,
    "example4.dat": 24,
    "example5.dat": 0,
    "example6.dat": 24,
}
KEPT_ZEROS = {
    "example1.dat": 9,
    "example2.dat": 15,
    "example3.dat": 5,
    "example4.dat": 10,
    "example5.dat": 3,
    "example6.dat": 7,
}


def raw_of(name):
    (path,) = [p for p in MAG_FILES if p.name == name]
    return read_grad601(path)


def test_real_grids_are_60_traverses_of_240_readings():
    for name in MISSING:
        assert raw_of(name).shape == (60, 240), name


def test_real_missing_data_counts():
    for name in MISSING:
        marked = mark_missing(raw_of(name))
        assert int(np.isnan(marked).sum()) == MISSING[name], name
        assert int((marked == 0.0).sum()) == KEPT_ZEROS[name], name


def test_real_missing_blocks_are_where_section_3_says():
    m4 = mark_missing(raw_of("example4.dat"))
    assert np.isnan(m4[[49, 51], 29:41]).all()
    m6 = mark_missing(raw_of("example6.dat"))
    assert np.isnan(m6[[33, 35], 20:32]).all()
    m3 = mark_missing(raw_of("example3.dat"))
    assert np.isnan(m3[:, -1]).all()


def test_real_missing_summaries():
    assert missing_summary(mark_missing(raw_of("example4.dat"))) == (
        "24 readings are missing data, on traverses 50 and 52."
    )
    assert missing_summary(mark_missing(raw_of("example6.dat"))) == (
        "24 readings are missing data, on traverses 34 and 36."
    )
    assert missing_summary(mark_missing(raw_of("example3.dat"))) == (
        "7273 readings are missing data, on traverses 1, 2, 3, 4, 5, 6 and 54 more."
    )


def test_real_points_fill_the_grid():
    grid = Grid("M", (0.0, 0.0), 0.0, 30.0, 30.0, "EPSG:32616", 0.5, instrument="mag")
    for name in MISSING:
        (path,) = [p for p in MAG_FILES if p.name == name]
        xy, values = MagFile.open(path, "M", MagSetup()).points(grid)
        assert xy.shape == (14400 - MISSING[name], 2), name
        assert values.shape == (14400 - MISSING[name],), name
        assert np.isfinite(values).all(), name
        assert xy.min() >= 0.0 and xy.max() <= 30.0, name


FINISH = FinishSettings("kriging", 0.375, 1.0)
CRS = "EPSG:32616"
LAYOUT = {
    "example5.dat": (0.0, 30.0),
    "example2.dat": (30.0, 30.0),
    "example3.dat": (60.0, 30.0),
    "example4.dat": (0.0, 60.0),
    "example1.dat": (30.0, 60.0),
    "example6.dat": (60.0, 0.0),
}


def _map_of(name, origin, setup=None):
    (path,) = [p for p in MAG_FILES if p.name == name]
    grid = Grid(name, origin, 0.0, 30.0, 30.0, CRS, 0.5, instrument="mag")
    setup = setup or MagSetup(axis="x", far_y=True, far_x=False)
    return grid_map(MagFile.open(path, name, setup), grid, DEFAULT_CELL_M, FINISH)


def test_a_real_grid_map_covers_its_grid():
    _, one = _map_of("example1.dat", (0.0, 0.0), MagSetup())
    _, three = _map_of("example3.dat", (0.0, 0.0), MagSetup())
    assert np.isfinite(one).mean() >= 0.98
    assert 0.45 <= np.isfinite(three).mean() <= 0.55
    # Traverses run along Y, so the missing far end of each is the grid's far half in Y.
    half = three.shape[0] // 2
    assert np.isfinite(three[:half]).mean() > 0.75
    assert np.isfinite(three[half:]).mean() < 0.25


def _six():
    maps = {name: _map_of(name, origin) for name, origin in LAYOUT.items()}
    lattice, out = mosaic(
        list(maps.values()), DEFAULT_CELL_M, CRS, max_pixels=10**7, max_covered=10**7
    )
    return maps, lattice, out


def test_the_six_real_grids_land_where_the_layout_puts_them():
    maps, lattice, out = _six()
    centres = lattice.pixel_centres()
    x, y = centres[:, 0], centres[:, 1]
    flat = out.ravel()
    assert np.isnan(flat[(x > 0) & (x < 60) & (y > 0) & (y < 30)]).all()
    for name, (ox, oy) in LAYOUT.items():
        frame, values = maps[name]
        inside = (x >= ox + 0.5) & (x <= ox + 29.5) & (y >= oy + 0.5) & (y <= oy + 29.5)
        want = sample(values, bilinear_taps(frame, centres[inside]))
        got = flat[inside]
        np.testing.assert_allclose(got, want, atol=1e-4, equal_nan=True, err_msg=name)


def test_real_neighbours_join_along_their_traverses():
    _, lattice, out = _six()
    col = lambda x: int(round((x - lattice.x0) / lattice.pixel))  # noqa: E731
    row = lambda y: int(round((lattice.y1 - y) / lattice.pixel))  # noqa: E731
    seams = {"ex4|ex1": (30.0, 60.0), "ex5|ex2": (30.0, 30.0), "ex2|ex3": (60.0, 30.0)}
    for label, (sx, oy) in seams.items():
        rows = slice(row(oy + 30.0), row(oy))
        left = out[rows, col(sx) - 1]
        right = out[rows, col(sx)]
        ok = np.isfinite(left) & np.isfinite(right)
        assert ok.sum() > 100, label
        r = float(np.corrcoef(left[ok], right[ok])[0, 1])
        assert r >= 0.8, f"{label}: r={r:.3f}"
