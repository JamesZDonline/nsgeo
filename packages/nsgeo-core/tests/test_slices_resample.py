import numpy as np
import pytest
from nsgeo.slices import CubeFrame, bilinear_taps, sample, sample_counts
from nsgeo.slices.frame import slice_extent
from nsgeo.slices.site import SiteLattice


def frame(azimuth=0.0, nx=12, ny=10, cell=0.5):
    return CubeFrame((500_000.0, 4_000_000.0), azimuth, cell, nx, ny, "EPSG:32616")


def centres(f, pixel):
    return SiteLattice.covering([slice_extent(f)], pixel, f.crs).pixel_centres()


@pytest.mark.parametrize("azimuth", [0.0, 17.0, 30.0])
def test_cell_centres_reproduce_the_cells_exactly_and_take_the_fast_path(azimuth):
    f = frame(azimuth=azimuth, cell=0.05)
    x_hat, y_hat = f.axes()
    i, j = np.meshgrid(np.arange(f.nx), np.arange(f.ny))
    local = np.column_stack([(i.ravel() + 0.5) * f.cell, (j.ravel() + 0.5) * f.cell])
    world = np.asarray(f.origin) + local[:, :1] * x_hat + local[:, 1:] * y_hat
    values = np.arange(f.n_cells, dtype=float).reshape(f.ny, f.nx)
    taps = bilinear_taps(f, world)
    assert taps.exact
    np.testing.assert_array_equal(sample(values, taps), values.ravel().astype(np.float32))


def test_a_point_between_four_cells_is_their_bilinear_blend():
    f = frame()
    values = np.zeros((f.ny, f.nx))
    values[2, 3] = 4.0  # one bright cell
    x_hat, y_hat = f.axes()
    # a quarter cell right of and above cell (3, 2)'s centre
    local = np.array([[(3.5 + 0.25) * f.cell, (2.5 + 0.25) * f.cell]])
    world = np.asarray(f.origin) + local[:, :1] * x_hat + local[:, 1:] * y_hat
    assert sample(values, bilinear_taps(f, world))[0] == pytest.approx(4.0 * 0.75 * 0.75)


def test_a_blank_neighbour_is_dropped_and_the_rest_reweighted_not_averaged_as_zero():
    f = frame()
    values = np.full((f.ny, f.nx), 2.0)
    values[2, 4] = np.nan
    x_hat, y_hat = f.axes()
    local = np.array([[(3.5 + 0.25) * f.cell, (2.5 + 0.25) * f.cell]])  # nearest is (3, 2)
    world = np.asarray(f.origin) + local[:, :1] * x_hat + local[:, 1:] * y_hat
    assert sample(values, bilinear_taps(f, world))[0] == pytest.approx(2.0)


def test_the_outline_does_not_move_blank_exactly_where_the_nearest_cell_is_blank():
    f = frame(azimuth=17.0)
    values = np.ones((f.ny, f.nx))
    values[:, :5] = np.nan
    pts = centres(f, f.cell)
    got = sample(values, bilinear_taps(f, pts))
    ids = f.cell_index(pts)
    nearest_blank = (ids < 0) | ~np.isfinite(values.ravel()[np.clip(ids, 0, None)])
    np.testing.assert_array_equal(np.isnan(got), nearest_blank)


@pytest.mark.parametrize("azimuth", [10.497, 30.0, 45.0, 60.0, 89.9])
def test_every_cell_feeds_some_drawn_pixel_at_the_cell_pitch(azimuth):
    f = frame(azimuth=azimuth, nx=40, ny=32)
    for k in range(0, f.n_cells, 97):  # a spread of single bright cells
        values = np.zeros((f.ny, f.nx))
        values.ravel()[k] = 1.0
        got = sample(values, bilinear_taps(f, centres(f, f.cell)))
        assert np.nanmax(got) > 0.0, k


def test_counts_take_the_smallest_corner_and_never_hide_a_zero():
    f = frame(azimuth=30.0, nx=20, ny=20)
    counts = np.full((f.ny, f.nx), 3.0)
    counts[10, 10] = np.nan  # an empty cell
    got = sample_counts(counts, bilinear_taps(f, centres(f, f.cell)))
    finite = got[np.isfinite(got)]
    assert set(np.unique(finite)) == {3.0}  # whole counts, never blended
    taps = bilinear_taps(f, centres(f, f.cell))
    hits = taps.inside & ((taps.ids == 10 * f.nx + 10) & (taps.weights > 0.0)).any(axis=0)
    assert hits.any() and np.isnan(got[hits]).all()


def test_points_outside_the_frame_are_blank_and_take_keeps_alignment():
    f = frame(azimuth=30.0)
    pts = centres(f, f.cell)
    taps = bilinear_taps(f, pts)
    got = sample(np.ones((f.ny, f.nx)), taps)
    assert np.isnan(got[~taps.inside]).all()
    idx = np.flatnonzero(taps.inside)[::3]
    np.testing.assert_array_equal(sample(np.ones((f.ny, f.nx)), taps.take(idx)), got[idx])


def test_axis_aligned_counts_are_each_cells_own_count():
    f = frame(azimuth=0.0, nx=12, ny=10)
    rng = np.random.default_rng(0)
    counts = rng.integers(1, 6, size=(f.ny, f.nx)).astype(float)
    counts[5, 4] = np.nan
    pts = centres(f, f.cell)
    taps = bilinear_taps(f, pts)
    assert taps.exact
    got = sample_counts(counts, taps)
    ids = f.cell_index(pts)
    own = np.where(ids >= 0, counts.ravel()[np.clip(ids, 0, None)], np.nan)
    np.testing.assert_array_equal(got, own.astype(np.float32))
    assert np.isnan(got).sum() == (ids == 5 * f.nx + 4).sum() + (ids < 0).sum()


def test_an_infinite_nearest_cell_is_blank_on_the_exact_path():
    f = frame(azimuth=0.0, nx=6, ny=5)
    values = np.ones((f.ny, f.nx))
    values[2, 3] = np.inf
    got = sample(values, bilinear_taps(f, centres(f, f.cell)))
    assert not np.isinf(got).any() and np.isnan(got).sum() == 1
