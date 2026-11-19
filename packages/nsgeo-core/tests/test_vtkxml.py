from __future__ import annotations

import numpy as np
import pytest
from nsgeo.vtkxml import (
    image_data_bytes,
    structured_grid_bytes,
    write_image_data,
    write_poly_data,
    write_structured_grid,
)

from tests.vtk_reader import read_vtk_xml


def _vol():
    return np.arange(4 * 3 * 2, dtype=np.float32).reshape(2, 3, 4)  # (nz, ny, nx)


def test_image_data_round_trips_in_vtk_order(tmp_path):
    vol = _vol()
    chunks = lambda: iter([vol[0].ravel(), vol[1].ravel()])  # noqa: E731
    n = write_image_data(
        tmp_path / "c.vti",
        origin=(0.025, 0.025, -1.0),
        spacing=(0.05, 0.05, 0.01),
        shape=(4, 3, 2),
        arrays=[("strength", chunks), ("amplitude", chunks)],
    )
    doc = read_vtk_xml(tmp_path / "c.vti")
    assert doc["WholeExtent"] == (0, 3, 0, 2, 0, 1) and doc["Spacing"] == (0.05, 0.05, 0.01)
    assert doc["Origin"] == (0.025, 0.025, -1.0) and doc["Scalars"] == "strength"
    np.testing.assert_array_equal(doc["point_data"]["strength"], vol.ravel())
    np.testing.assert_array_equal(doc["point_data"]["amplitude"], vol.ravel())
    assert n == (tmp_path / "c.vti").stat().st_size
    assert not (tmp_path / "c.vti.part").exists()


@pytest.mark.parametrize("n_values", [23, 25])
def test_a_wrong_length_array_raises_and_leaves_no_file(tmp_path, n_values):
    bad = lambda: iter([np.zeros(n_values, np.float32)])  # noqa: E731
    with pytest.raises(ValueError):
        write_image_data(
            tmp_path / "c.vti",
            origin=(0, 0, 0),
            spacing=(1, 1, 1),
            shape=(4, 3, 2),
            arrays=[("strength", bad)],
        )
    assert list(tmp_path.iterdir()) == []


def test_poly_data_round_trips_points_verts_lines_and_polys(tmp_path):
    pts = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 1], [2, 2, -1]], dtype=np.float32)
    data = {
        "true_depth_m": np.array([0.1, 0.2, 0.3, 0.4, 0.5], np.float32),
        "line": np.array([1, 2, 3, 4, 5], np.int32),
    }
    write_poly_data(
        tmp_path / "p.vtp", pts, data, verts=[[4]], lines=[[0, 1, 2]], polys=[[1, 2, 3]]
    )
    doc = read_vtk_xml(tmp_path / "p.vtp")
    assert doc["NumberOfPoints"] == 5
    np.testing.assert_array_equal(doc["points"], pts)
    np.testing.assert_array_equal(doc["Verts_connectivity"], [4])
    np.testing.assert_array_equal(doc["Verts_offsets"], [1])
    np.testing.assert_array_equal(doc["Lines_connectivity"], [0, 1, 2])
    np.testing.assert_array_equal(doc["Lines_offsets"], [3])
    np.testing.assert_array_equal(doc["Polys_connectivity"], [1, 2, 3])
    np.testing.assert_array_equal(doc["Polys_offsets"], [3])
    for name, a in data.items():
        np.testing.assert_array_equal(doc["point_data"][name], a)
        assert doc["point_data"][name].dtype == a.dtype


def test_an_empty_point_set_is_a_valid_file(tmp_path):
    write_poly_data(tmp_path / "p.vtp", np.empty((0, 3)), {"true_depth_m": np.empty(0, np.float32)})
    doc = read_vtk_xml(tmp_path / "p.vtp")
    assert doc["NumberOfPoints"] == 0 and len(doc["Verts_offsets"]) == 0


def test_image_data_bytes_is_within_the_header_allowance_of_the_file(tmp_path):
    vol = _vol()
    chunks = lambda: iter([vol.ravel()])  # noqa: E731
    write_image_data(
        tmp_path / "c.vti",
        origin=(0, 0, 0),
        spacing=(1, 1, 1),
        shape=(4, 3, 2),
        arrays=[("a", chunks), ("b", chunks)],
    )
    size = (tmp_path / "c.vti").stat().st_size
    bound = image_data_bytes((4, 3, 2), 2)
    assert bound - 4096 <= size <= bound


def test_structured_grid_round_trips_and_its_size_is_exact(tmp_path):
    pts = np.random.default_rng(0).random((4, 5, 3))
    amp = np.arange(20.0).reshape(4, 5)
    n = write_structured_grid(tmp_path / "w.vts", pts, {"amplitude": amp})
    doc = read_vtk_xml(tmp_path / "w.vts")
    assert np.allclose(doc["points"].reshape(4, 5, 3), pts, atol=1e-6)
    assert np.allclose(doc["point_data"]["amplitude"].reshape(4, 5), amp)
    assert doc["WholeExtent"] == (0, 4, 0, 3, 0, 0)
    assert doc["points"].dtype == np.float32 and doc["point_data"]["amplitude"].dtype == np.float32
    size = (tmp_path / "w.vts").stat().st_size
    assert n == size
    # the estimate is the payload plus the header allowance (as image_data_bytes is):
    # never short, and never off by more than the allowance
    est = structured_grid_bytes(20, 1)
    assert est == (8 + 12 * 20) + (8 + 4 * 20) + 4096
    assert size <= est and est - size < 4096
    assert not (tmp_path / "w.vts.part").exists()


def test_a_structured_grid_array_of_the_wrong_size_is_refused_and_leaves_no_file(tmp_path):
    pts = np.zeros((4, 5, 3))
    with pytest.raises(ValueError):
        write_structured_grid(tmp_path / "w.vts", pts, {"amplitude": np.zeros((5, 4))})
    with pytest.raises(ValueError):
        write_structured_grid(tmp_path / "w.vts", np.zeros((4, 5, 2)), {})
    assert list(tmp_path.iterdir()) == []
