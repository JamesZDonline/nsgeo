"""The packed cube (#113): it must read exactly as the dense layout did."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.slices.binning import (
    PreparedLine,
    build_cube,
    covered_cells,
    plan_line,
    resample_window,
)
from nsgeo.slices.cube import CubeBlock, Provenance, SliceCube
from nsgeo.slices.frame import CubeFrame, ZAxis

from tests.real_lines import AXIS, WINDOWS, needs_real_files, prepared_lines


def _prov():
    return Provenance(
        line_keys=("a",),
        preset_name="p",
        steps=(),
        transform="amp_abs",
        velocity=None,
        built_utc="2026-11-10T00:00:00Z",
        core_version="0.1.0.dev0",
    )


def _dense_reference(lines, plans, frame, z):
    """Today's (pre-#113) algorithm: a dense total and count, then a divide."""
    total = np.zeros((z.nz, frame.n_cells), dtype=np.float32)
    count = np.zeros(frame.n_cells, dtype=np.int32)
    for line, plan in zip(lines, plans):
        block = resample_window(line, plan, 0, z.nz)
        total[:, plan.cells] += np.add.reduceat(block, plan.starts, axis=1)
        count[plan.cells] += plan.counts
    mean = np.divide(total, count, out=np.full_like(total, np.nan), where=count > 0)
    return mean, count


def _build(lines, frame, z):
    plans = [plan_line(ln, frame, z) for ln in lines]
    return build_cube(lines, plans, frame, z, _prov()), plans


def _synthetic_lines(n=10, along="x", seed=0, n_traces=100, extent=19.9):
    """Lines 0.5 m apart, offset by 0.25 m, with positive random data."""
    rng = np.random.default_rng(seed)
    lines = []
    for i in range(n):
        t = np.linspace(0.05, extent, n_traces)
        across = np.full(n_traces, 0.25 + 0.5 * i)
        xy = [t, across] if along == "x" else [across, t]
        lines.append(
            PreparedLine(
                key=f"{along}{i}",
                data=(rng.random((30, n_traces)) + 0.5).astype(np.float32),
                dt_ns=1.0,
                t0_ns=0.0,
                coords=np.column_stack(xy),
            )
        )
    return lines


def _frame(nx, ny, cell):
    return CubeFrame(origin=(0.0, 0.0), azimuth=0.0, cell=cell, nx=nx, ny=ny, crs="EPSG:32633")


Z = ZAxis(t0_ns=0.0, dz_ns=1.0, nz=24)


def test_build_cube_stores_only_covered_cells():
    frame = _frame(100, 125, 0.2)
    lines = _synthetic_lines()
    cube, plans = _build(lines, frame, Z)
    _, dense_count = _dense_reference(lines, plans, frame, Z)
    (block,) = cube.blocks
    np.testing.assert_array_equal(block.cells, np.flatnonzero(dense_count > 0))
    assert block.mean.shape == (Z.nz, block.cells.size) and block.mean.dtype == np.float32
    assert block.cells.dtype == np.int64 and block.count.dtype == np.int32
    assert block.heading_deg is None


def _assert_matches_dense(cube, lines, frame, z, windows):
    plans = [plan_line(ln, frame, z) for ln in lines]
    dense_mean, dense_count = _dense_reference(lines, plans, frame, z)
    for k0, k1 in windows:
        np.testing.assert_array_equal(
            cube.slice_levels(k0, k1),
            dense_mean[k0:k1].mean(axis=0).reshape(frame.ny, frame.nx),
        )
    np.testing.assert_array_equal(cube.coverage(), dense_count.reshape(frame.ny, frame.nx))


@needs_real_files
@pytest.mark.parametrize("cell", [0.2, 0.05])
@pytest.mark.parametrize("rotated", [False, True], ids=["axis-aligned", "rotated-utm"])
def test_slices_match_the_dense_layout_bit_for_bit(cell, rotated):
    nx, ny = round(20.0 / cell), round(5.0 / cell)
    if rotated:
        frame = CubeFrame(
            origin=(500000.0, 4500000.0), azimuth=33.0, cell=cell, nx=nx, ny=ny, crs="EPSG:32617"
        )
        x_hat, y_hat = frame.axes()

        def to_world(local):
            return np.asarray(frame.origin) + local[:, [0]] * x_hat + local[:, [1]] * y_hat
    else:
        frame = _frame(nx, ny, cell)

        def to_world(local):
            return local

    lines = prepared_lines(range(10), to_world)
    cube, _ = _build(lines, frame, AXIS)
    _assert_matches_dense(cube, lines, frame, AXIS, WINDOWS)


def test_crossing_lines_match_the_dense_layout():
    """A cell on both a row and a column, and a cell wider than the spacing,
    is one covered cell: the union, never a sum."""
    frame = _frame(27, 27, 0.75)
    lines = _synthetic_lines(5, "x", seed=1, extent=4.9) + _synthetic_lines(
        5, "y", seed=2, extent=4.9
    )
    cube, plans = _build(lines, frame, Z)
    _assert_matches_dense(cube, lines, frame, Z, [(0, 24), (3, 11), (23, 24)])
    covered = np.unique(np.concatenate([p.cells for p in plans]))
    assert cube.blocks[0].cells.size == covered.size


def test_level_is_a_one_level_window():
    frame = _frame(100, 125, 0.2)
    cube, _ = _build(_synthetic_lines(), frame, Z)
    for k in (0, Z.nz // 2, Z.nz - 1):
        np.testing.assert_array_equal(cube.level(k), cube.slice_levels(k, k + 1))


def _small_cube():
    frame = _frame(100, 125, 0.2)
    cube, _ = _build(_synthetic_lines(), frame, Z)
    return frame, cube


def test_values_at_reads_levels_at_chosen_cells():
    frame, cube = _small_cube()
    covered = cube.blocks[0].cells
    empty = np.setdiff1d(np.arange(frame.n_cells), covered)
    ids = np.array([covered[0], covered[10], covered[-1], empty[0], empty[-1], -1])
    out = cube.values_at(ids)
    assert out.shape == (Z.nz, ids.size) and out.dtype == np.float32
    for k in (0, 7):
        np.testing.assert_array_equal(
            out[k], np.where(ids >= 0, cube.level(k).ravel()[ids], np.nan)
        )
    assert cube.values_at(ids, 2, 5).shape == (3, ids.size)
    np.testing.assert_array_equal(cube.values_at(ids, 2, 5), out[2:5])


@pytest.mark.parametrize("bad", [[100 * 125], [-2]])
def test_values_at_rejects_ids_outside_the_frame(bad):
    frame, cube = _small_cube()
    assert frame.n_cells == 100 * 125
    with pytest.raises(ValueError):
        cube.values_at(np.array(bad))


def _assert_blocks_combine(frame, first, second, reference):
    both = SliceCube(frame=frame, z=Z, blocks=first.blocks + second.blocks, provenance=_prov())
    for k0, k1 in [(0, 24), (4, 9), (23, 24)]:
        np.testing.assert_allclose(
            both.slice_levels(k0, k1), reference.slice_levels(k0, k1), rtol=1e-6, equal_nan=True
        )
    ids = np.arange(frame.n_cells)
    np.testing.assert_allclose(
        both.values_at(ids, 3, 8), reference.values_at(ids, 3, 8), rtol=1e-6, equal_nan=True
    )
    np.testing.assert_array_equal(both.coverage(), reference.coverage())


@pytest.mark.parametrize("overlap", [False, True], ids=["disjoint", "overlapping"])
def test_two_blocks_read_as_the_count_weighted_mean(overlap):
    frame = _frame(100, 125, 0.2)
    lines = _synthetic_lines(6)
    out_idx, back_idx = ([0, 1, 2, 3], [2, 3, 4, 5]) if overlap else ([0, 2, 4], [1, 3, 5])
    outward, _ = _build([lines[i] for i in out_idx], frame, Z)
    back, _ = _build([lines[i] for i in back_idx], frame, Z)
    # Lines in both blocks count twice, as they would if built twice.
    reference, _ = _build([lines[i] for i in out_idx + back_idx], frame, Z)
    _assert_blocks_combine(frame, outward, back, reference)


def test_blocks_sharing_cells_with_different_means_and_counts_are_count_weighted():
    """The two cases above cannot tell a count-weighted read from a plain mean
    of the blocks' means: shared cells there hold the same mean in both. Here
    X and Y lines share 16 cells with different data and different counts."""
    frame = _frame(27, 27, 0.75)
    xs = _synthetic_lines(5, "x", seed=1, extent=4.9)
    ys = _synthetic_lines(5, "y", seed=2, n_traces=37, extent=4.9)
    first, _ = _build(xs, frame, Z)
    second, _ = _build(ys, frame, Z)
    shared = np.intersect1d(first.blocks[0].cells, second.blocks[0].cells)
    assert shared.size > 0
    reference, _ = _build(xs + ys, frame, Z)
    _assert_blocks_combine(frame, first, second, reference)


def _block(cells=(1, 4, 9), nz=24, count=None, mean=None):
    cells = np.asarray(cells, dtype=np.int64)
    return CubeBlock(
        cells=cells,
        mean=np.ones((nz, cells.size), np.float32) if mean is None else mean,
        count=np.ones(cells.size, np.int32) if count is None else count,
    )


_MALFORMED = {
    "unsorted cells": lambda: _block(cells=(4, 1, 9)),
    "duplicate cell": lambda: _block(cells=(1, 4, 4)),
    "cell equal to n_cells": lambda: _block(cells=(1, 4, 100 * 125)),
    "negative cell": lambda: _block(cells=(-1, 4, 9)),
    "mean of the wrong shape": lambda: _block(mean=np.ones((24, 2), np.float32)),
    "mean nz differs from z": lambda: _block(nz=23),
    "non-float mean": lambda: _block(mean=np.ones((24, 3), np.int32)),
    "float count": lambda: _block(count=np.ones(3, np.float32)),
    "zero count": lambda: _block(count=np.array([1, 0, 1], np.int32)),
}


@pytest.mark.parametrize("case", sorted(_MALFORMED))
def test_a_malformed_block_is_refused(case):
    frame = _frame(100, 125, 0.2)
    with pytest.raises(ValueError):
        SliceCube(frame=frame, z=Z, blocks=(_MALFORMED[case](),), provenance=_prov())


def test_a_cube_with_no_blocks_is_refused():
    with pytest.raises(ValueError):
        SliceCube(frame=_frame(100, 125, 0.2), z=Z, blocks=(), provenance=_prov())


def test_from_dense_keeps_only_covered_columns():
    frame = _frame(5, 4, 1.0)
    z = ZAxis(t0_ns=0.0, dz_ns=1.0, nz=6)
    rng = np.random.default_rng(3)
    dense_mean = rng.random((6, 20)).astype(np.float32)
    dense_count = rng.integers(0, 3, size=20).astype(np.int32)
    dense_mean[:, dense_count == 0] = np.nan
    cube = SliceCube.from_dense(frame, z, dense_mean, dense_count, _prov())
    np.testing.assert_array_equal(cube.blocks[0].cells, np.flatnonzero(dense_count > 0))
    np.testing.assert_array_equal(
        cube.slice_levels(1, 5), dense_mean[1:5].mean(axis=0).reshape(4, 5)
    )
    np.testing.assert_array_equal(cube.coverage(), dense_count.reshape(4, 5))
    with pytest.raises(ValueError, match="mean must be"):
        SliceCube.from_dense(frame, z, dense_mean[:, :5], dense_count, _prov())
    with pytest.raises(ValueError, match="count must be"):
        SliceCube.from_dense(frame, z, dense_mean, dense_count[:5], _prov())


def test_nbytes_counts_the_packed_arrays():
    _, cube = _small_cube()
    block = cube.blocks[0]
    assert cube.nbytes == block.cells.nbytes + block.mean.nbytes + block.count.nbytes
    n = block.cells.size
    assert cube.nbytes == Z.nz * n * 4 + n * 4 + n * 8


def test_covered_cells_counts_a_shared_cell_once():
    frame = _frame(10, 10, 1.0)
    # Two traces in cell (1, 1); an X line along y=5.5 crossing a Y line
    # along x=3.5 (one shared cell at (3, 5)); one trace outside the frame.
    pair = np.array([[1.2, 1.3], [1.7, 1.8]])
    x_line = np.column_stack([np.array([0.5, 1.5, 2.5, 3.5, 4.5]), np.full(5, 5.5)])
    y_line = np.column_stack([np.full(5, 3.5), np.array([3.5, 4.5, 5.5, 6.5, 7.5])])
    outside = np.array([[-40.0, 99.0]])
    # pair 1 + X line 5 + Y line 5 - 1 shared = 10
    assert covered_cells(frame, [pair, x_line, y_line, outside]) == 10
    assert covered_cells(frame, []) == 0
    assert covered_cells(frame, [outside]) == 0


@needs_real_files
@pytest.mark.parametrize("cell", [0.2, 0.05])
def test_covered_cells_equals_the_cubes_cell_count(cell):
    nx, ny = round(20.0 / cell), round(5.0 / cell)
    frame = CubeFrame(
        origin=(500000.0, 4500000.0), azimuth=33.0, cell=cell, nx=nx, ny=ny, crs="EPSG:32617"
    )
    x_hat, y_hat = frame.axes()

    def to_world(local):
        return np.asarray(frame.origin) + local[:, [0]] * x_hat + local[:, [1]] * y_hat

    lines = prepared_lines(range(10), to_world)
    cube, _ = _build(lines, frame, AXIS)
    assert covered_cells(frame, (ln.coords for ln in lines)) == cube.blocks[0].cells.size
