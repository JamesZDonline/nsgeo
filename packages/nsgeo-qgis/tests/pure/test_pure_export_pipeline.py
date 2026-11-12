"""The Qt-free export pipeline: bands of a site or a grid at any cell and pixel.

The reference for most tests is the live Whole-site composition rebuilt here
from core calls the way `SiteEngine.slice_at` takes them, with the one
difference that its taps are built over the whole lattice rather than a
window, so the two cannot share a mistake in the window.
"""

from __future__ import annotations

import dataclasses
from dataclasses import replace

import numpy as np
import pytest
from nsgeo.slices import (
    CubeFrame,
    FinishSettings,
    PreparedLine,
    SiteLattice,
    SliceCube,
    ZAxis,
    bilinear_taps,
    compose_footprints,
    covered_cells,
    covered_pixels,
    find_seams,
    finish_slice,
    footprint,
    normalise,
    plan_fill,
    plan_line,
    slice_extent,
    stream_slice,
    window_on,
)
from nsgeo_qgis import export_pipeline
from nsgeo_qgis.export_pipeline import (
    TAP_BYTES_PER_PIXEL,
    ExportBand,
    ExportCancelled,
    ExportGrid,
    ExportSpec,
    estimate_export,
    run_export,
)
from nsgeo_qgis.slices_plan import (
    CURVATURE_PLAN_BYTES_PER_CELL,
    EXPORT_BUDGET_BYTES,
    WEIGHT_BYTES_PER_CELL,
    estimate_memory,
    export_refusal,
    format_bytes,
)
from plugin_testing import REAL_DZT, needs_real_data

CRS = "EPSG:32616"
Z = ZAxis.from_range(1.0, 15.0, 0.5)
SIZE = 6.0
SPACING = 0.5
KRIGING = FinishSettings("kriging", 0.5 * SPACING, 2.0 * SPACING)


def _lines(frame: CubeFrame, key: str, amp: float, seed: int) -> tuple[PreparedLine, ...]:
    """Twelve lines along the frame's y at 0.5 m, a gradient plus noise, `amp` times as bright."""
    rng = np.random.default_rng(seed)
    x_hat, y_hat = frame.axes()
    origin = np.asarray(frame.origin)
    n_traces = 80
    along = np.linspace(0.01, SIZE - 0.01, n_traces)
    out = []
    for i in range(int(SIZE / SPACING)):
        across = SPACING / 2 + i * SPACING
        coords = origin + across * x_hat + along[:, None] * y_hat
        shape = np.sin(0.8 * along)[None, :] * np.linspace(1.0, 2.0, 40)[:, None]
        data = amp * (shape + 0.3 * rng.normal(size=(40, n_traces)) + 0.2 * across)
        out.append(PreparedLine(f"{key}-{i}", data.astype(np.float32), 0.5, 0.0, coords))
    return tuple(out)


def _grid(
    grid_id: str,
    origin: tuple[float, float],
    azimuth: float,
    cell: float,
    amp: float,
    seed: int,
    finish: FinishSettings = KRIGING,
    gain: float = 1.0,
) -> ExportGrid:
    frame = CubeFrame(origin, azimuth, cell, round(SIZE / cell), round(SIZE / cell), CRS)
    return ExportGrid(grid_id, _lines(frame, grid_id, amp, seed), frame, Z, finish, SPACING, gain)


def _site(cell: float, method: str, *, finish=KRIGING, gains=(1.0, 1.0), coverage=False):
    """Two grids side by side, the second turned 20 degrees and twice as bright."""
    first = _grid("A", (500000.0, 4000000.0), 0.0, cell, 1.0, 1, finish, gains[0])
    x_hat, _ = first.frame.axes()
    origin = tuple(np.asarray(first.frame.origin) + (SIZE - 0.02) * x_hat)
    second = _grid("B", origin, 20.0, cell, 2.0, 2, finish, gains[1])
    grids = (first, second)
    extents = [slice_extent(g.frame) for g in grids]
    lattice = SiteLattice.covering(extents, cell, CRS)
    return ExportSpec(grids, lattice, ((2.0, 2.0), (6.0, 3.0)), method, coverage)


def _run(spec: ExportSpec, **kw) -> list[ExportBand]:
    kw.setdefault("should_stop", lambda: False)
    kw.setdefault("progress", lambda *_: None)
    return list(run_export(spec, **kw))


def _live(spec: ExportSpec) -> list[tuple[np.ndarray, dict]]:
    """`SiteEngine.slice_at` for each band, from core calls, taps over the whole lattice."""
    lattice = spec.lattice
    centres = lattice.pixel_centres()
    gathered, plans = {}, {}
    for g in spec.grids:
        taps = bilinear_taps(g.frame, centres)
        gathered[g.grid_id] = footprint(taps, lattice.height, lattice.width)
        plans[g.grid_id] = [plan_line(line, g.frame, g.z) for line in g.lines]

    def bin_(g, k0, k1):
        return stream_slice(g.lines, plans[g.grid_id], g.frame, g.z, k0, k1)

    seams = ()
    if spec.method == "edge":
        frames = {g.grid_id: g.frame for g in spec.grids}
        covers = {g.grid_id: bin_(g, 0, 1)[1] for g in spec.grids}
        seams = find_seams(frames, covers, {g.grid_id: g.spacing_m for g in spec.grids})
    out = []
    for top, thick in spec.windows:
        binned, windows = {}, {}
        for g in spec.grids:
            windows[g.grid_id] = window_on(g.z, top, thick)
            if windows[g.grid_id] is not None:
                binned[g.grid_id] = bin_(g, windows[g.grid_id].k0, windows[g.grid_id].k1)
        by_id = {g.grid_id: g for g in spec.grids}
        if spec.coverage:
            shown = {
                k: np.where(c > 0, c, np.nan).astype(np.float32) for k, (_, c) in binned.items()
            }
            factors = dict.fromkeys(binned, (1.0, 0.0))
        else:
            gains = {g.grid_id: g.gain for g in spec.grids}
            factors = normalise(spec.method, binned, seams, gains)
            shown = {}
            for k, (values, cov) in binned.items():
                g = by_id[k]
                fill = plan_fill(cov > 0, g.frame.cell, g.finish.method, g.finish.max_distance_m,
                                 g.finish.search_radius_m)  # fmt: skip
                done = finish_slice(values, fill, g.frame.cell, g.finish)
                shown[k] = factors[k][0] * done + factors[k][1]
        layers = [(gathered[k], shown[k]) for k in shown]
        out.append((compose_footprints(lattice, layers, counts=spec.coverage), factors))
    return out


def _flat(factors: dict) -> list[float]:
    """The factors as one flat list (pytest 9.2's `approx` refuses nested dicts)."""
    return [x for key in sorted(factors) for x in factors[key]]


def _same(band: ExportBand, array: np.ndarray, factors: dict) -> None:
    assert band.array.dtype == np.float32
    assert band.array.shape == array.shape
    np.testing.assert_array_equal(np.isnan(band.array), np.isnan(array))
    np.testing.assert_allclose(band.array, array, rtol=0, atol=1e-5, equal_nan=True)
    assert sorted(band.factors) == sorted(factors)
    assert _flat(band.factors) == pytest.approx(_flat(factors))


# ---- the composition --------------------------------------------------------
@pytest.mark.parametrize("method", ["edge", "none", "histogram"])
def test_export_at_the_live_cell_equals_the_live_composition(method):
    spec = _site(0.1, method)
    bands, live = _run(spec), _live(spec)
    assert len(bands) == len(live) == 2
    for band, (array, factors) in zip(bands, live):
        assert np.isfinite(array).sum() > 1000  # not comparing two blank pictures
        _same(band, array, factors)
    if method == "edge":
        assert any(a != 1.0 for a, _ in bands[0].factors.values()), "the seam moved nothing"


def test_export_at_the_live_cell_equals_the_live_composition_with_minimum_curvature():
    finish = FinishSettings("min_curvature", 0.5 * SPACING, 2.0 * SPACING, 0.1, 0.1)
    spec = _site(0.1, "background", finish=finish)
    for band, (array, factors) in zip(_run(spec), _live(spec)):
        _same(band, array, factors)


def test_export_at_a_finer_cell_measures_normalisation_again():
    """Decision 3: the factors are measured on the cells as binned at the export
    cell, so they are the live ones at THAT cell, and not the coarse view's."""
    coarse, fine = _site(0.1, "edge"), _site(0.05, "edge")
    (coarse_band, *_) = _run(coarse)
    (fine_band, *_) = _run(fine)
    fine_live = _live(fine)[0]
    _same(fine_band, *fine_live)
    assert _flat(fine_band.factors) != pytest.approx(_flat(coarse_band.factors), rel=1e-6)


def test_manual_gains_are_carried_as_typed():
    """Decision 11: a typed multiplier is folded into the factor, not re-measured."""
    spec = _site(0.1, "none", gains=(2.0, 0.5))
    for band in _run(spec):
        assert band.factors == {"A": (2.0, 0.0), "B": (0.5, 0.0)}
    spec = _site(0.1, "histogram", gains=(2.0, 0.5))
    for band, (array, factors) in zip(_run(spec), _live(spec)):
        _same(band, array, factors)
    plain = _run(_site(0.1, "histogram"))[0].factors
    typed = _run(spec)[0].factors
    assert typed["A"][0] == pytest.approx(2.0 * plain["A"][0])
    assert typed["B"][0] == pytest.approx(0.5 * plain["B"][0])


def test_coverage_export_holds_whole_counts():
    spec = _site(0.1, "edge", coverage=True)
    bands = _run(spec)
    for band, (array, factors) in zip(bands, _live(spec)):
        _same(band, array, factors)
        counts = band.array[np.isfinite(band.array)]
        assert counts.size > 0
        np.testing.assert_array_equal(counts, np.round(counts))
        assert counts.min() >= 1
        assert band.factors == {"A": (1.0, 0.0), "B": (1.0, 0.0)}


def test_a_grid_whose_axis_misses_a_band_is_absent_from_it():
    spec = _site(0.1, "none")
    short = dataclasses.replace(spec.grids[1], z=ZAxis.from_range(1.0, 5.0, 0.5))
    spec = dataclasses.replace(spec, grids=(spec.grids[0], short))
    bands = _run(spec)
    assert set(bands[0].factors) == {"A", "B"}
    assert set(bands[1].factors) == {"A"}  # the second band starts at 6 ns
    for band, (array, factors) in zip(bands, _live(spec)):
        _same(band, array, factors)


def test_a_cube_and_a_stream_give_the_same_bands(monkeypatch):
    spec = _site(0.1, "edge")
    streamed = _run(spec)
    monkeypatch.setattr(export_pipeline, "choose_residency", lambda *a, **k: "resident")
    resident = _run(spec)
    for a, b in zip(streamed, resident):
        _same(a, b.array, b.factors)


# ---- stopping ---------------------------------------------------------------
def test_should_stop_cancels_within_one_grid():
    spec = _site(0.1, "none")
    seen: list[tuple[int, int, str]] = []
    bands = run_export(
        spec,
        should_stop=lambda: len(seen) >= 1,
        progress=lambda band, n, grid: seen.append((band, n, grid)),
    )
    with pytest.raises(ExportCancelled):
        next(bands)
    assert seen == [(0, 2, "A")]  # B never started


def test_progress_names_every_band_and_grid_in_order():
    seen: list[tuple[int, int, str]] = []
    _run(_site(0.1, "none"), progress=lambda *a: seen.append(a))
    assert seen == [(0, 2, "A"), (0, 2, "B"), (1, 2, "A"), (1, 2, "B")]


def test_a_stop_inside_the_minimum_curvature_solve_is_a_cancel():
    finish = FinishSettings("min_curvature", 0.5 * SPACING, 2.0 * SPACING)
    spec = _site(0.1, "none", finish=finish)
    asked = {"after_progress": 0, "started": False}

    def stop() -> bool:
        if asked["started"]:
            asked["after_progress"] += 1  # only the solve asks between progress and the result
        return asked["after_progress"] >= 3

    def started(*_) -> None:
        asked["started"] = True

    with pytest.raises(ExportCancelled):
        _run(spec, should_stop=stop, progress=started)
    assert asked["after_progress"] == 3  # stopped inside the solve, not before the next grid


# ---- another CRS ------------------------------------------------------------
def test_a_grid_in_another_crs_is_transformed_before_sampling():
    """The fake transform shifts the output CRS by a known offset onto the frame's.
    A grid whose frame sits at O in its own CRS lands at O + offset in the output,
    so the export equals the same grid placed there with no transform."""
    shift = np.array([1000.0, -500.0])
    own = _grid("C", (500000.0, 4000000.0), 7.0, 0.1, 1.0, 3)
    there_frame = dataclasses.replace(own.frame, origin=tuple(np.asarray(own.frame.origin) + shift))
    there_lines = tuple(dataclasses.replace(line, coords=line.coords + shift) for line in own.lines)
    placed = dataclasses.replace(own, frame=there_frame, lines=there_lines, world_to_frame=None)
    lattice = SiteLattice.covering([slice_extent(there_frame)], 0.1, "EPSG:32617")
    calls: list[int] = []

    def to_frame(points: np.ndarray) -> np.ndarray:
        calls.append(len(points))
        return points - shift

    moved = dataclasses.replace(own, world_to_frame=to_frame)
    spec = ExportSpec((moved,), lattice, ((2.0, 3.0),), "none", False)
    assert calls == []  # building the spec transformed nothing
    (got,) = _run(spec)
    assert calls  # and the taps did
    (want,) = _run(ExportSpec((placed,), lattice, ((2.0, 3.0),), "none", False))
    assert np.isfinite(want.array).sum() > 500
    _same(got, want.array, want.factors)
    again = len(calls)
    _run(spec)
    assert len(calls) == 2 * again  # once per export, never per band: the same on every run


def test_a_grid_in_another_crs_that_the_lattice_misses_is_absent():
    own = _grid("C", (500000.0, 4000000.0), 0.0, 0.1, 1.0, 3)
    far = SiteLattice(x0=0.0, y1=100.0, pixel=0.1, width=50, height=50, crs="EPSG:32617")
    moved = dataclasses.replace(own, world_to_frame=lambda p: p)
    (band,) = _run(ExportSpec((moved,), far, ((2.0, 3.0),), "none", False))
    assert np.isnan(band.array).all()


# ---- sizing -----------------------------------------------------------------
def test_the_estimate_counts_weights_taps_and_one_band():
    spec = _site(0.1, "edge")
    est = estimate_export(spec)
    cells = sum(g.frame.n_cells for g in spec.grids)
    assert est.per_band["weights"] == cells * WEIGHT_BYTES_PER_CELL
    pixels = covered_pixels([slice_extent(g.frame) for g in spec.grids], 0.1)
    assert est.per_band["taps"] == TAP_BYTES_PER_PIXEL * pixels
    assert est.per_band["cubes"] == 0  # twelve short lines stream
    assert est.per_band["solve"] == 0
    assert est.per_band["band"] >= 9 * spec.lattice.n_pixels  # the compose's accumulators
    lines = sum(line.data.size * 4 for g in spec.grids for line in g.lines)
    assert est.per_band["lines"] == lines
    parts = ("weights", "taps", "gather", "cubes", "band", "solve")
    assert est.held_bytes == sum(est.per_band[k] for k in parts)  # not the lines: already held
    assert est.file_bytes == pytest.approx(spec.lattice.n_pixels * 4 * 2 * 4 / 3, rel=0.01)


def test_a_cache_counts_each_grid_once_per_cell_and_changes_no_figure(monkeypatch):
    """The dialog asks for many pixels at one cell; the covered-cell count walks every
    trace, so it is memoised per (grid, frame, lines) and the estimate is unchanged."""
    from nsgeo_qgis import export_pipeline

    counted: list[str] = []
    real = export_pipeline.covered_cells

    def counting(frame, coords):
        counted.append("walk")
        return real(frame, coords)

    monkeypatch.setattr(export_pipeline, "covered_cells", counting)
    spec = _site(0.1, "edge")
    plain = estimate_export(spec)
    assert len(counted) == 2
    cache: dict = {}
    first = estimate_export(spec, cache)
    again = estimate_export(
        replace(
            spec,
            lattice=SiteLattice.covering([slice_extent(g.frame) for g in spec.grids], 0.05, CRS),
        ),
        cache,
    )
    assert len(counted) == 4, "two grids walked once for the first call, none for the second"
    assert first == plain
    assert again.per_band["taps"] > first.per_band["taps"]  # a finer pixel, the same cells
    other = _site(0.2, "edge")
    estimate_export(other, cache)
    assert len(counted) == 6, "another cell is another count"


def test_the_estimate_counts_a_resident_cube_by_its_covered_cells():
    """Enough traces that streaming is slower than a frame (`choose_residency`)."""
    frame = CubeFrame((0.0, 0.0), 0.0, 0.1, 60, 60, CRS)
    n = 90_000
    xy = np.column_stack([np.linspace(0.05, 5.95, n), np.full(n, 3.05)])
    line = PreparedLine("long", np.zeros((8, n), np.float32), 0.5, 0.0, xy)
    z = ZAxis.from_range(0.0, 3.0, 0.5)
    grid = ExportGrid("A", (line,), frame, z, KRIGING, SPACING, 1.0)
    lattice = SiteLattice.covering([slice_extent(frame)], 0.1, CRS)
    est = estimate_export(ExportSpec((grid,), lattice, ((0.0, 3.0),), "none", False))
    covered = covered_cells(frame, [xy])
    assert covered == 60
    assert (
        est.per_band["cubes"]
        == estimate_memory(8 * n, 3600, z.nz, covered, method="kriging").cube_bytes
        > 0
    )


def test_a_minimum_curvature_estimate_counts_the_curvature_plan_once():
    """The export holds one plan a grid; the live engine's kriging preview beside
    it (`estimate_memory(method="min_curvature")`, #148) is not built here."""
    frame = CubeFrame((0.0, 0.0), 0.0, 0.1, 60, 60, CRS)
    xy = np.array([[1.0, 1.0], [2.0, 2.0]])
    line = PreparedLine("a", np.zeros((8, 2), np.float32), 0.5, 0.0, xy)
    z = ZAxis.from_range(0.0, 3.0, 0.5)
    lattice = SiteLattice.covering([slice_extent(frame)], 0.1, CRS)
    curving = FinishSettings("min_curvature", 0.5 * SPACING, 2.0 * SPACING)
    grid = ExportGrid("A", (line,), frame, z, curving, SPACING, 1.0)
    spec = ExportSpec((grid,), lattice, ((0.0, 3.0),), "none", False)
    weights = estimate_export(spec).per_band["weights"]
    assert weights == frame.n_cells * CURVATURE_PLAN_BYTES_PER_CELL
    both = estimate_memory(0, frame.n_cells, z.nz, 2, method="min_curvature")
    assert weights < both.weights_bytes


def test_an_export_over_budget_is_refused_with_the_finest_fit():
    frame = CubeFrame((0.0, 0.0), 0.0, 0.005, 20_000, 20_000, CRS)  # 400 M cells
    xy = np.array([[1.0, 1.0], [2.0, 2.0]])
    line = PreparedLine("a", np.zeros((8, 2), np.float32), 0.5, 0.0, xy)
    grid = ExportGrid("A", (line,), frame, ZAxis.from_range(0.0, 3.0, 0.5), KRIGING, SPACING, 1.0)
    lattice = SiteLattice(0.0, 100.0, 0.005, 20_000, 20_000, CRS)
    est = estimate_export(ExportSpec((grid,), lattice, ((0.0, 3.0),), "none", False))
    assert est.held_bytes > EXPORT_BUDGET_BYTES
    held = f"{format_bytes(est.held_bytes)}"
    budget = f"{format_bytes(EXPORT_BUDGET_BYTES)}"
    base = f"This export would hold about {held} in memory, more than the {budget} it is allowed."
    assert export_refusal(est.held_bytes, EXPORT_BUDGET_BYTES, None, None) == base
    assert export_refusal(est.held_bytes, EXPORT_BUDGET_BYTES, 0.025, None) == (
        base + " A 0.025 m export cell would fit."
    )
    assert export_refusal(est.held_bytes, EXPORT_BUDGET_BYTES, None, 0.0125) == (
        base + " A 0.0125 m export pixel would fit."
    )
    assert export_refusal(est.held_bytes, EXPORT_BUDGET_BYTES, 0.05, 0.025) == (
        base + " A 0.05 m export cell would fit. A 0.025 m export pixel would fit."
    )
    assert export_refusal(3_400_000_000, 1_500_000_000, 0.05, None) == (
        "This export would hold about 3.4 GB in memory, more than the 1.5 GB it is allowed."
        " A 0.05 m export cell would fit."
    )


# ---- the cube interface -----------------------------------------------------
def test_the_pipeline_never_reads_cube_mean(monkeypatch):
    """Decision 5: a cube is read through `slice_levels` and `coverage` only."""

    class Guarded(SliceCube):
        @property
        def mean(self):
            raise AssertionError("the export read cube.mean")

    real = export_pipeline.build_cube

    def build(*args, **kwargs):
        cube = real(*args, **kwargs)
        return Guarded(cube.frame, cube.z, cube.blocks, cube.provenance)

    monkeypatch.setattr(export_pipeline, "build_cube", build)
    monkeypatch.setattr(export_pipeline, "choose_residency", lambda *a, **k: "resident")
    spec = _site(0.1, "edge")
    got = _run(spec)
    for band, (array, factors) in zip(got, _live(spec)):
        _same(band, array, factors)


def test_the_module_imports_without_qt():
    """The pure tier has no QGIS: the pipeline must import with none loaded."""
    import os
    import subprocess
    import sys

    code = (
        "import sys; import nsgeo_qgis.export_pipeline; "
        "assert 'qgis' not in sys.modules and 'PyQt5' not in sys.modules"
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr


# ---- real data --------------------------------------------------------------
@needs_real_data
@pytest.mark.parametrize("cell", [0.05, 0.025])
def test_the_ten_real_lines_export_at_a_fine_cell(cell):
    """The ten local lines as one grid, at 0.05 m and 0.025 m, kriged: every cell the lines
    cover is a finite pixel, and the fill reaches into the blanks between them."""
    from tests.real_lines import AXIS, prepared_lines
    from tests.real_lines import SPACING as REAL_SPACING

    frame = CubeFrame((0.0, 0.0), 0.0, cell, round(20.0 / cell), round(5.0 / cell), CRS)
    lines = tuple(prepared_lines(range(10), lambda local: np.asarray(local, dtype=float)))
    finish = FinishSettings("kriging", 0.5 * REAL_SPACING, 2.0 * REAL_SPACING)
    grid = ExportGrid("A", lines, frame, AXIS, finish, REAL_SPACING, 1.0)
    lattice = SiteLattice.covering([slice_extent(frame)], cell / 2, CRS)
    windows = ((10.0, 5.0), (20.0, 5.0))
    amplitudes = _run(ExportSpec((grid,), lattice, windows, "none", False))
    counts = _run(ExportSpec((grid,), lattice, windows, "none", True))
    assert len(amplitudes) == 2
    for amp, cnt in zip(amplitudes, counts):
        assert amp.array.shape == (lattice.height, lattice.width)
        data = np.isfinite(cnt.array)
        assert data.any()
        filled = np.isfinite(amp.array)
        assert filled[data].mean() > 0.95  # a cell the lines cover is drawn
        assert filled.sum() > 3 * data.sum()  # and the kriging fills between the lines
        assert np.isfinite(amp.array[filled]).all()
    assert REAL_DZT  # the skip guard and this test read the same list
