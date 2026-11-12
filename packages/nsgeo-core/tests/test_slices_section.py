"""Vertical sections along a cut: columns, crops, and the finishing (cut spec §3, §4.7)."""

from __future__ import annotations

import math
import warnings
from functools import cache

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.slices import (
    CubeFrame,
    CurvaturePlan,
    FinishSettings,
    Provenance,
    SolveStopped,
    bilinear_taps,
    build_cube,
    finish_slice,
    plan_fill,
    plan_line,
    sample,
    smooth,
)
from nsgeo.slices.section import (
    CROP_MAX_DISTANCE_SPACINGS,
    SECTION_MARGIN_SPACINGS,
    SECTION_PIECE_M,
    SectionColumns,
    column_distances,
    curvature_margin_cells,
    finish_section,
    plan_section_curvature,
    section_columns,
    section_crops,
    smoothing_reach_cells,
    solve_section_level,
    solve_section_level_whole,
    uses_crops,
)

from tests.real_lines import AXIS, SPACING, WINDOWS, needs_real_files, prepared_lines

CRS = "EPSG:32633"
GRID = Grid("G", (500000.0, 4000000.0), 10.497, 20.0, 5.0, CRS, 0.5)


def axis_frame(cell=0.2):
    return CubeFrame((0.0, 0.0), 0.0, cell, int(round(20.0 / cell)), int(round(5.0 / cell)), CRS)


def rotated_frame():
    return CubeFrame.for_grid(GRID, 0.2)


def _prov():
    return Provenance(
        line_keys=("a",),
        preset_name="p",
        steps=(),
        transform="amp_envelope",
        velocity=None,
        built_utc="2026-11-11T00:00:00Z",
        core_version="0.0.0",
    )


@cache
def cube_on(kind, cell=0.2):
    frame = axis_frame(cell) if kind == "axis" else rotated_frame()
    to_world = (lambda local: local) if kind == "axis" else GRID.to_world
    lines = prepared_lines(range(10), to_world)
    plans = [plan_line(p, frame, AXIS) for p in lines]
    return build_cube(lines, plans, frame, AXIS, _prov())


def path(*points):
    return np.array(points, dtype=float)


def straight(a, b):
    return path(a, b)


OBLIQUE = path((2.0, 0.8), (9.0, 3.9), (17.0, 1.1))


def test_columns_start_at_zero_end_at_the_length_and_step_at_half_a_cell():
    frame = axis_frame()
    columns = section_columns(frame, straight((1.0, 1.0), (4.05, 1.0)))
    d = columns.distance_m
    assert d[0] == 0.0
    assert d[-1] == pytest.approx(3.05, abs=1e-12)
    steps = np.diff(d)
    np.testing.assert_allclose(steps[:-1], 0.1, atol=1e-12)
    assert 0.0 < steps[-1] <= 0.1 + 1e-12
    assert columns.local.shape == columns.world.shape == (d.size, 2)


def test_columns_land_in_the_cells_cell_index_finds():
    frame = rotated_frame()
    local = path((2.0, 0.8), (9.0, 3.9), (17.0, 1.1))
    columns = section_columns(frame, local)
    np.testing.assert_array_equal(columns.cells, frame.cell_index(columns.world))
    assert columns.cells.dtype == np.intp
    np.testing.assert_allclose(frame.to_local(columns.world), columns.local, atol=1e-9)
    taps = bilinear_taps(frame, columns.world)
    np.testing.assert_array_equal(columns.taps.ids, taps.ids)
    np.testing.assert_array_equal(columns.taps.weights, taps.weights)
    np.testing.assert_array_equal(columns.cells, taps.nearest)
    inside = columns.cells >= 0
    np.testing.assert_array_equal(columns.tap_cells, np.unique(taps.ids[:, inside]))


def test_columns_past_the_frame_edge_are_minus_one():
    frame = axis_frame()
    columns = section_columns(frame, straight((19.0, 2.0), (23.0, 2.0)))
    beyond = columns.local[:, 0] > 20.0
    assert beyond.any() and (~beyond).any()
    assert (columns.cells[beyond] == -1).all()
    assert (columns.cells[~beyond] >= 0).all()


def test_a_step_over_half_a_cell_and_a_zero_length_path_are_refused():
    frame = axis_frame()
    line = straight((1.0, 1.0), (4.0, 1.0))
    section_columns(frame, line, step_m=0.1)
    with pytest.raises(ValueError):
        section_columns(frame, line, step_m=0.11)
    with pytest.raises(ValueError):
        section_columns(frame, line, step_m=0.0)
    with pytest.raises(ValueError):
        section_columns(frame, path((1.0, 1.0), (1.0, 1.0)))
    with pytest.raises(ValueError):
        section_columns(frame, path((1.0, 1.0)))


def test_a_hundred_vertex_cut_and_a_long_cut():
    frame = axis_frame()
    xs = np.linspace(1.0, 19.0, 100)
    ys = np.where(np.arange(100) % 2 == 0, 1.0, 4.0)
    zigzag = np.column_stack([xs, ys])
    columns = section_columns(frame, zigzag)
    length = float(np.hypot(*np.diff(zigzag, axis=0).T).sum())
    assert columns.distance_m.size == math.ceil(length / 0.1) + 1
    assert columns.distance_m[-1] == pytest.approx(length)
    long = section_columns(frame, straight((0.0, 2.0), (1000.0, 2.0)))
    assert long.distance_m.size == 10001
    assert (long.cells == -1).sum() > 0.97 * long.cells.size


def _crop_cases():
    return {
        "diagonal": straight((1.0, 0.5), (19.0, 4.5)),
        "along x": straight((0.3, 2.5), (19.7, 2.5)),
        "leaves and returns": path((1.0, 2.0), (22.0, 2.0), (22.0, 3.0), (3.0, 3.0)),
    }


@pytest.mark.parametrize("margin", [0, 5])
@pytest.mark.parametrize("case", ["diagonal", "along x", "leaves and returns"])
def test_every_inside_column_is_in_one_crop_and_crops_stay_in_the_frame(case, margin):
    frame = axis_frame()
    columns = section_columns(frame, _crop_cases()[case])
    crops = section_crops(columns, frame, margin)
    taken = np.concatenate([c.columns for c in crops])
    np.testing.assert_array_equal(np.sort(taken), np.flatnonzero(columns.cells >= 0))
    assert len(set(taken.tolist())) == taken.size
    for crop in crops:
        span = columns.distance_m[crop.columns]
        assert span.max() - span.min() <= SECTION_PIECE_M + 1e-9
        (r0, r1), (c0, c1) = crop.rows, crop.cols
        assert 0 <= r0 < r1 <= frame.ny and 0 <= c0 < c1 <= frame.nx
        assert crop.shape == (r1 - r0, c1 - c0)
        flat = crop.flat_cells(frame.nx)
        assert flat.size == (r1 - r0) * (c1 - c0)
        assert flat.min() == r0 * frame.nx + c0
        for j in crop.columns:
            iy, ix = divmod(int(columns.cells[j]), frame.nx)
            assert r0 <= max(iy - margin, 0) and r1 >= min(iy + margin + 1, frame.ny)
            assert c0 <= max(ix - margin, 0) and c1 >= min(ix + margin + 1, frame.nx)
            for k in range(4):
                if columns.taps.weights[k, j] > 0:
                    ty, tx = divmod(int(columns.taps.ids[k, j]), frame.nx)
                    assert r0 <= ty < r1 and c0 <= tx < c1


def test_smoothing_reach_follows_the_kernel_radius():
    none = FinishSettings("none", 0.1, 0.1)
    assert smoothing_reach_cells(none, 0.2) == 0
    s = FinishSettings("none", 0.1, 0.1, smooth_x_m=0.1, smooth_y_m=0.3)
    assert smoothing_reach_cells(s, 0.2) == math.ceil(4.0 * 0.3 / 0.2)


@needs_real_files
def test_a_cut_along_a_recorded_line_reads_that_lines_cells():
    cube = cube_on("axis")
    frame = cube.frame
    y = (math.floor((0.25 + 3 * 0.5) / 0.2) + 0.5) * 0.2
    columns = section_columns(frame, straight((0.1, y), (19.9, y)))
    settings = FinishSettings("none", 0.0, 0.0)
    fill = plan_fill(cube.coverage() > 0, 0.2, "none", 0.0, 0.0)
    out = finish_section(cube, fill, columns, settings)
    assert out.shape == (AXIS.nz, columns.distance_m.size) and out.dtype == np.float32
    on_centre = np.arange(0, columns.distance_m.size, 2)
    direct = cube.values_at(columns.cells)
    np.testing.assert_array_equal(out[:, on_centre], direct[:, on_centre])
    for k in range(AXIS.nz):
        np.testing.assert_array_equal(out[k], sample(cube.level(k), columns.taps))
    assert np.isfinite(out).mean() >= 0.5


@needs_real_files
def test_columns_blend_as_the_slice_picture_does():
    cube = cube_on("rotated")
    frame = cube.frame
    columns = section_columns(frame, OBLIQUE)
    settings = FinishSettings("kriging", 0.375, 1.0)
    fill = plan_fill(cube.coverage() > 0, 0.2, "kriging", 0.375, 1.0)
    out = finish_section(cube, fill, columns, settings)
    taps = bilinear_taps(frame, columns.world)
    for k in (10, 90, 170):
        expected = sample(finish_slice(cube.level(k), fill, 0.2, settings), taps)
        np.testing.assert_allclose(out[k], expected, rtol=0, atol=1e-6, equal_nan=True)
    # blank where the nearest cell is blank, whatever its neighbours hold
    none = plan_fill(cube.coverage() > 0, 0.2, "none", 0.0, 0.0)
    raw = finish_section(cube, none, columns, FinishSettings("none", 0.0, 0.0))
    nearest_blank = np.isnan(cube.values_at(columns.cells)[0])
    assert nearest_blank.any()
    neighbours_finite = (
        np.isfinite(cube.level(0).ravel()[columns.taps.ids]) & (columns.taps.weights > 0)
    ).any(axis=0)
    assert (nearest_blank & neighbours_finite).any()
    assert np.isnan(raw[:, nearest_blank]).all()


FINISHES = [
    ("none", (0.0, 0.0)),
    ("none", (0.0, 0.1)),
    ("idw", (0.0, 0.0)),
    ("idw", (0.0, 0.1)),
    ("kriging", (0.0, 0.0)),
    ("kriging", (0.0, 0.1)),
]


def _settings(method, smoothing):
    return FinishSettings(method, 0.375, 1.0, smooth_x_m=smoothing[0], smooth_y_m=smoothing[1])


@needs_real_files
@pytest.mark.parametrize(("method", "smoothing"), FINISHES)
def test_section_equals_the_finished_slice_at_every_level(method, smoothing):
    cube = cube_on("rotated")
    columns = section_columns(cube.frame, OBLIQUE)
    settings = _settings(method, smoothing)
    fill = plan_fill(cube.coverage() > 0, 0.2, method, 0.375, 1.0)
    out = finish_section(cube, fill, columns, settings)
    for k in range(cube.z.nz):
        expected = sample(finish_slice(cube.level(k), fill, 0.2, settings), columns.taps)
        scale = float(np.nanmax(expected) - np.nanmin(expected))
        np.testing.assert_allclose(out[k], expected, rtol=0, atol=1e-5 * scale, equal_nan=True)


@needs_real_files
@pytest.mark.parametrize(("method", "smoothing"), FINISHES)
def test_window_average_of_a_section_equals_the_slice_window(method, smoothing):
    cube = cube_on("rotated")
    columns = section_columns(cube.frame, OBLIQUE)
    settings = _settings(method, smoothing)
    fill = plan_fill(cube.coverage() > 0, 0.2, method, 0.375, 1.0)
    out = finish_section(cube, fill, columns, settings)
    for k0, k1 in WINDOWS:
        expected = sample(
            finish_slice(cube.slice_levels(k0, k1), fill, 0.2, settings), columns.taps
        )
        scale = float(np.nanmax(expected) - np.nanmin(expected))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-blank columns
            window = np.nanmean(out[k0:k1], axis=0)
        np.testing.assert_allclose(window, expected, rtol=0, atol=1e-5 * scale, equal_nan=True)


@needs_real_files
def test_blank_beyond_max_distance_and_outside_the_frame():
    cube = cube_on("axis")
    columns = section_columns(cube.frame, straight((12.0, 1.0), (23.0, 1.0)))
    inside = columns.cells >= 0
    assert inside.any() and (~inside).any()
    for max_d, finite in ((0.1, False), (0.375, True)):
        fill = plan_fill(cube.coverage() > 0, 0.2, "idw", max_d, 1.0)
        out = finish_section(cube, fill, columns, FinishSettings("idw", max_d, 1.0))
        assert np.isnan(out[:, ~inside]).all()
        assert bool(np.isfinite(out[:, inside]).all()) is finite
        if not finite:
            assert np.isnan(out[:, inside]).all()


@needs_real_files
def test_finish_section_refuses_a_curvature_plan():
    cube = cube_on("axis")
    columns = section_columns(cube.frame, straight((1.0, 1.0), (4.0, 1.0)))
    plan = plan_fill(cube.coverage() > 0, 0.2, "min_curvature", 0.25, 0.25)
    assert isinstance(plan, CurvaturePlan)
    with pytest.raises(TypeError):
        finish_section(cube, plan, columns, FinishSettings("min_curvature", 0.25, 0.25))


CURVATURE_PATHS = {
    "along x": straight((1.0, 2.5), (13.0, 2.5)),
    "along y": straight((10.2, 0.3), (10.2, 4.7)),
    "diagonal": straight((2.0, 0.5), (14.0, 4.5)),
}


def _curvature_case(name, smoothing, cell=0.05):
    cube = cube_on("axis", cell)
    columns = section_columns(cube.frame, CURVATURE_PATHS[name])
    settings = FinishSettings("min_curvature", 0.25, 0.25, smooth_x_m=0.0, smooth_y_m=smoothing)
    pop = cube.coverage() > 0
    crops = section_crops(columns, cube.frame, curvature_margin_cells(settings, cell, SPACING))
    plans = plan_section_curvature(pop, crops, cell, 0.25)
    whole = plan_fill(pop, cell, "min_curvature", 0.25, 0.25)
    return cube, columns, settings, crops, plans, whole, cell


def _crop_error(case, levels=(30, 90, 150)):
    """The worst gap between the crops' solve and the whole frame's, as a share of the range."""
    cube, columns, settings, crops, plans, whole, cell = case
    worst = 0.0
    for k in levels:
        level = cube.level(k)
        done = solve_section_level(level, columns, crops, plans, settings, cell)
        full = smooth(whole.solve(level)[0], cell, settings.smooth_x_m, settings.smooth_y_m)
        expected = sample(full, columns.taps)
        assert done.shape == expected.shape and done.dtype == np.float32
        assert np.array_equal(np.isnan(done), np.isnan(expected))
        scale = float(np.nanmax(expected) - np.nanmin(expected))
        worst = max(worst, float(np.nanmax(np.abs(done - expected))) / scale)
    return worst


def test_curvature_margin_is_the_larger_of_the_spacings_and_the_smoothing_plus_one():
    none = FinishSettings("min_curvature", 0.25, 0.25)
    assert SECTION_MARGIN_SPACINGS == 6.0
    assert curvature_margin_cells(none, 0.05, 0.5) == 60 + 1
    assert curvature_margin_cells(none, 0.2, 0.5) == 15 + 1
    assert curvature_margin_cells(none, 0.2, 0.55) == math.ceil(6 * 0.55 / 0.2) + 1
    wide = FinishSettings("min_curvature", 0.25, 0.25, smooth_y_m=2.0)  # kernel 40 cells at 0.2
    assert smoothing_reach_cells(wide, 0.2) == 40
    assert curvature_margin_cells(wide, 0.2, 0.5) == 40 + 1


@needs_real_files
@pytest.mark.parametrize("cell", [0.05, 0.2])
@pytest.mark.parametrize("name", sorted(CURVATURE_PATHS))
def test_curvature_on_crops_matches_the_whole_frame_solve(name, cell):
    case = _curvature_case(name, 0.0, cell)
    assert all(isinstance(p, CurvaturePlan) for p in case[4]) and len(case[3]) == len(case[4])
    assert _crop_error(case) <= 1e-3


@needs_real_files
@pytest.mark.parametrize("cell", [0.05, 0.2])
@pytest.mark.parametrize("name", sorted(CURVATURE_PATHS))
def test_curvature_on_crops_with_smoothing_matches_the_whole_frame(name, cell):
    assert _crop_error(_curvature_case(name, 0.1, cell)) <= 1e-3


@needs_real_files
def test_a_curvature_solve_can_be_stopped():
    cube, columns, settings, crops, plans, _, cell = _curvature_case("along x", 0.0)
    with pytest.raises(SolveStopped):
        solve_section_level(cube.level(30), columns, crops, plans, settings, cell, lambda: True)


def test_section_columns_are_immutable():
    columns = section_columns(axis_frame(), straight((1.0, 1.0), (4.0, 1.0)))
    assert isinstance(columns, SectionColumns)
    with pytest.raises(AttributeError):
        columns.distance_m = np.zeros(1)  # type: ignore[misc]


def test_column_distances_are_defined_once_for_the_section_and_its_callers():
    d = column_distances(3.05, 0.1)
    assert d[0] == 0.0 and d[-1] == 3.05
    np.testing.assert_allclose(np.diff(d)[:-1], 0.1, atol=1e-12)
    # A whole number of steps grows no sliver column from rounding.
    assert column_distances(30.000000000000004, 0.1).size == 301
    columns = section_columns(axis_frame(), straight((1.0, 1.0), (4.05, 1.0)))
    np.testing.assert_array_equal(columns.distance_m, column_distances(3.05, 0.1))
    with pytest.raises(ValueError):
        column_distances(0.0, 0.1)


@needs_real_files
@pytest.mark.parametrize("cell", [0.05, 0.2])
def test_window_mean_of_level_solves_equals_the_slice_view_of_the_window(cell):
    """Minimum curvature is linear for a fixed coverage (cut spec test 11): the
    mean of the per-level crop solves is the crop solve of the mean slice, and
    both are what the slice view shows for the window (whole-frame solve of
    `slice_levels`, smoothed, read at the columns)."""
    cube, columns, settings, crops, plans, whole, cell = _curvature_case("diagonal", 0.1, cell)
    for k0, k1 in WINDOWS[:3]:
        levels = [
            solve_section_level(cube.level(k), columns, crops, plans, settings, cell)
            for k in range(k0, k1)
        ]
        mean_slice = cube.slice_levels(k0, k1)
        window = solve_section_level(mean_slice, columns, crops, plans, settings, cell)
        view = sample(
            smooth(whole.solve(mean_slice)[0], cell, settings.smooth_x_m, settings.smooth_y_m),
            columns.taps,
        )
        mean = np.nanmean(np.stack(levels), axis=0)
        assert np.array_equal(np.isnan(mean), np.isnan(window))
        assert np.array_equal(np.isnan(view), np.isnan(window))
        scale = float(np.nanmax(view) - np.nanmin(view))
        assert float(np.nanmax(np.abs(mean - window))) <= 1e-3 * scale
        assert float(np.nanmax(np.abs(mean - view))) <= 1e-3 * scale


def test_the_threshold_picks_crops_or_the_whole_frame():
    assert CROP_MAX_DISTANCE_SPACINGS == 0.5
    assert uses_crops(0.25, 0.5)  # exactly 0.5 spacings
    assert uses_crops(0.1, 0.5)
    assert uses_crops(0.5 * 0.55, 0.55)  # the product rounds the same way the engine's does
    assert not uses_crops(0.26, 0.5)
    assert not uses_crops(0.375, 0.5)  # 0.75 spacings, the default
    assert not uses_crops(0.5, 0.5)  # one spacing


def _holed_cube(cell, dropped=(3, 4, 5, 6)):
    """The real lines with some dropped: `dropped` are the lines left out."""
    frame = axis_frame(cell)
    lines = prepared_lines([i for i in range(10) if i not in dropped], lambda local: local)
    plans = [plan_line(p, frame, AXIS) for p in lines]
    return build_cube(lines, plans, frame, AXIS, _prov())


HOLES = {
    "1 m": (4, 5),
    "2 m": (3, 4, 5, 6),
    "3 m": (2, 3, 4, 5, 6, 7),
}
HOLE_PATHS = {
    "across the hole, x=4.0": straight((4.0, 0.3), (4.0, 4.7)),
    "across the hole, x=10.2": straight((10.2, 0.3), (10.2, 4.7)),
    "across the hole, x=17.5": straight((17.5, 0.3), (17.5, 4.7)),
    "diagonal through the hole": straight((2.0, 0.5), (14.0, 4.5)),
    # 0.2 m inside the 2 m hole's edge, so it still sees data at 0.5 spacings (0.25 m).
    "beside the hole": straight((1.0, 1.45), (13.0, 1.45)),
}
HOLE_LEVELS = tuple(range(10, 171, 20))
_HOLED: dict = {}


def _hole_cases():
    """(hole, path, spacings). The set takes about a minute on one thread, so the
    1 m and 3 m holes drop the 1.5 case and the "beside" path: that path lies in
    the middle of the 3 m hole (nothing in reach) and is only 0.2 m from a line
    of the 2 m hole."""
    cases = []
    for hole in sorted(HOLES):
        for path_name in sorted(HOLE_PATHS):
            for spacings in (0.5, 0.75, 1.5):
                if hole != "2 m" and (path_name == "beside the hole" or spacings == 1.5):
                    continue
                cases.append(
                    pytest.param(hole, path_name, spacings, id=f"{hole}-{path_name}-{spacings}")
                )
    return cases


def _held_hole(name, cell=0.05):
    """The cube for each hole, built once for the whole parametrized set."""
    if (name, cell) not in _HOLED:
        _HOLED[(name, cell)] = _holed_cube(cell, HOLES[name])
    return _HOLED[(name, cell)]


def _solve_as_the_plugin_does(cube, columns, settings, spacing, plan, level):
    """What a job does: crops up to the threshold, the engine's plan above it."""
    cell = cube.frame.cell
    if uses_crops(settings.max_distance_m, spacing):
        crops = section_crops(columns, cube.frame, curvature_margin_cells(settings, cell, spacing))
        plans = plan_section_curvature(cube.coverage() > 0, crops, cell, settings.max_distance_m)
        return solve_section_level(level, columns, crops, plans, settings, cell)
    return solve_section_level_whole(level, columns, plan, settings, cell)


@needs_real_files
@pytest.mark.parametrize(("hole", "path_name", "spacings"), _hole_cases())
def test_a_cut_through_a_coverage_hole_agrees_with_the_slice(hole, path_name, spacings):
    """Cut spec tests 3 and 12 together (M15 final review, I1): holes of 1, 2 and
    3 m under minimum curvature, crops at 0.5 spacings and the whole frame at 0.75
    and 1.5, each against the slice view (whole-frame solve, smoothed, sampled),
    within 1e-3 of the range at nine levels."""
    cell = 0.05
    cube = _held_hole(hole, cell)
    columns = section_columns(cube.frame, HOLE_PATHS[path_name])
    distance = spacings * SPACING
    settings = FinishSettings("min_curvature", distance, distance, smooth_y_m=0.1)
    whole = plan_fill(cube.coverage() > 0, cell, "min_curvature", distance, distance)
    assert isinstance(whole, CurvaturePlan)
    assert uses_crops(distance, SPACING) == (spacings <= 0.5)
    for k in HOLE_LEVELS:
        level = cube.level(k)
        done = _solve_as_the_plugin_does(cube, columns, settings, SPACING, whole, level)
        full = smooth(whole.solve(level)[0], cell, settings.smooth_x_m, settings.smooth_y_m)
        expected = sample(full, columns.taps)
        assert done.dtype == np.float32 and done.shape == expected.shape
        assert np.array_equal(np.isnan(done), np.isnan(expected))
        assert np.isfinite(expected).any()
        scale = float(np.nanmax(expected) - np.nanmin(expected))
        assert float(np.nanmax(np.abs(done - expected))) <= 1e-3 * scale


@needs_real_files
def test_the_whole_frame_solve_can_be_stopped_and_shares_its_plan():
    cell = 0.2
    cube = _holed_cube(cell)
    columns = section_columns(cube.frame, HOLE_PATHS["across the hole"])
    settings = FinishSettings("min_curvature", 0.75, 0.75)
    plan = plan_fill(cube.coverage() > 0, cell, "min_curvature", 0.75, 0.75)
    with pytest.raises(SolveStopped):
        solve_section_level_whole(cube.level(30), columns, plan, settings, cell, lambda: True)
    first = solve_section_level_whole(cube.level(30), columns, plan, settings, cell)
    again = solve_section_level_whole(cube.level(30), columns, plan, settings, cell)
    np.testing.assert_array_equal(first, again)
