from __future__ import annotations

import numpy as np
import pytest
from nsgeo.slices.cube import Provenance, SliceCube
from nsgeo.slices.frame import CubeFrame, ZAxis
from nsgeo.slices.store import CubeStoreError, load_cube, save_cube


def make_cube():
    frame = CubeFrame(origin=(10.0, 20.0), azimuth=37.5, cell=0.1, nx=5, ny=4, crs="EPSG:32633")
    z = ZAxis(t0_ns=-1.5, dz_ns=0.2165, nz=6)
    rng = np.random.default_rng(0)
    mean = rng.random((6, 20)).astype(np.float32)
    count = rng.integers(0, 3, size=20).astype(np.int32)
    mean[:, count == 0] = np.nan
    prov = Provenance(
        line_keys=("a.dzt", "b.dzt"),
        preset_name="slice-standard",
        steps=({"step": "dewow", "params": {"window_ns": 4.0}, "enabled": True},),
        transform="amp_envelope",
        velocity={"layers": [{"top_ns": 0.0, "v_m_ns": 0.08}]},
        built_utc="2026-09-18T19:12:00Z",
        core_version="0.1.0.dev0",
    )
    return SliceCube(frame=frame, z=z, mean=mean, count=count, provenance=prov)


def test_round_trip_preserves_the_arrays_exactly(tmp_path):
    cube = make_cube()
    path = tmp_path / "grid-a.npz"
    save_cube(cube, path)
    back = load_cube(path)
    np.testing.assert_array_equal(np.isnan(back.mean), np.isnan(cube.mean))
    np.testing.assert_array_equal(back.mean[~np.isnan(back.mean)], cube.mean[~np.isnan(cube.mean)])
    np.testing.assert_array_equal(back.count, cube.count)


def test_round_trip_preserves_the_frame_and_axis(tmp_path):
    cube = make_cube()
    path = tmp_path / "c.npz"
    save_cube(cube, path)
    back = load_cube(path)
    assert back.frame == cube.frame
    assert back.z == cube.z


def test_round_trip_preserves_provenance(tmp_path):
    cube = make_cube()
    path = tmp_path / "c.npz"
    save_cube(cube, path)
    assert load_cube(path).provenance == cube.provenance


def test_dtypes_survive_the_round_trip(tmp_path):
    """float64 would double a 331 MB cube for nothing."""
    cube = make_cube()
    path = tmp_path / "c.npz"
    save_cube(cube, path)
    back = load_cube(path)
    assert back.mean.dtype == np.float32
    assert back.count.dtype == np.int32


def test_loading_a_file_that_is_not_a_cube_fails_clearly(tmp_path):
    path = tmp_path / "junk.npz"
    np.savez(path, something=np.zeros(3))
    with pytest.raises(CubeStoreError, match="not a cube"):
        load_cube(path)


def test_loading_a_missing_file_fails_clearly(tmp_path):
    with pytest.raises(CubeStoreError, match="no cube file"):
        load_cube(tmp_path / "absent.npz")


def test_save_narrows_a_wider_input_dtype(tmp_path):
    """SliceCube itself does not enforce a dtype, so a caller could hand
    save_cube a float64 mean or an int64 count. The store must still not
    persist the wide form -- that would double a 331 MB cube for nothing
    -- so narrowing has to happen regardless of what came in."""
    cube = make_cube()
    wide = SliceCube(
        frame=cube.frame,
        z=cube.z,
        mean=cube.mean.astype(np.float64),
        count=cube.count.astype(np.int64),
        provenance=cube.provenance,
    )
    path = tmp_path / "wide.npz"
    save_cube(wide, path)
    # Inspect what actually landed on disk, not what load_cube hands back --
    # load_cube narrows on the way out too, so only checking its return value
    # would pass even if save_cube itself wrote the wide arrays.
    with np.load(path, allow_pickle=False) as bundle:
        assert bundle["mean"].dtype == np.float32
        assert bundle["count"].dtype == np.int32


def test_loading_a_file_missing_one_required_array_fails_clearly(tmp_path):
    """`mean` and `meta` alone are not a cube either -- every one of the
    three arrays is required, not just at least one of them."""
    path = tmp_path / "partial.npz"
    np.savez(path, mean=np.zeros((2, 3), dtype=np.float32), count=np.zeros(3, dtype=np.int32))
    with pytest.raises(CubeStoreError, match="not a cube"):
        load_cube(path)


def test_load_cube_refuses_a_pickled_object_array(tmp_path):
    """A colleague's or a shared drive's `.npz` is not a trusted input: an
    object-dtype array can only be read back through pickle, and pickle in
    a data file is a remote-code-execution surface. `allow_pickle=False`
    must be load_cube's real behaviour, not just its docstring -- so tamper
    with an otherwise-valid file's `mean` array into object dtype and
    confirm the load is refused rather than silently deserialised."""
    cube = make_cube()
    good = tmp_path / "good.npz"
    save_cube(cube, good)
    bundle = np.load(good, allow_pickle=False)
    meta = bundle["meta"]
    count = bundle["count"]
    bundle.close()

    evil = tmp_path / "evil.npz"
    np.savez_compressed(evil, mean=cube.mean.astype(object), count=count, meta=meta)
    with pytest.raises(CubeStoreError):
        load_cube(evil)
