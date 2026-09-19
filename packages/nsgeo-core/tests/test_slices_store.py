from __future__ import annotations

import json

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
    """`mean` and `count` alone are not a cube either -- every one of the
    three arrays is required, not just at least one of them."""
    path = tmp_path / "partial.npz"
    np.savez(path, mean=np.zeros((2, 3), dtype=np.float32), count=np.zeros(3, dtype=np.int32))
    with pytest.raises(CubeStoreError, match="not a cube"):
        load_cube(path)


def test_save_and_load_agree_on_a_path_without_the_npz_suffix(tmp_path):
    """`np.savez_compressed` appends `.npz` on its own when a path lacks
    it. If `save_cube` did not also normalise, it would write
    "grid-a.npz" while `load_cube`, given the same extensionless
    "grid-a", would look for a file named literally that and report "no
    cube file" for one sitting right next to it."""
    cube = make_cube()
    path = tmp_path / "grid-a"  # deliberately no suffix
    save_cube(cube, path)
    assert (tmp_path / "grid-a.npz").exists()
    back = load_cube(path)
    assert back.frame == cube.frame


def _good_parts(tmp_path):
    """A good cube's raw (mean, count, meta-dict) triple, for tests that
    tamper with just one part of an otherwise-valid file."""
    path = tmp_path / "seed.npz"
    save_cube(make_cube(), path)
    with np.load(path, allow_pickle=False) as bundle:
        return bundle["mean"], bundle["count"], json.loads(str(bundle["meta"].item()))


def test_loading_a_truncated_file_fails_clearly(tmp_path):
    """A half-copied file from a shared drive is the single most likely
    real-world corruption for this format. `np.load` raises
    `zipfile.BadZipFile` for it -- a plain `Exception` subclass, not an
    `OSError` or `ValueError` -- which must not escape load_cube's guard."""
    cube = make_cube()
    good = tmp_path / "good.npz"
    save_cube(cube, good)
    data = good.read_bytes()
    truncated = tmp_path / "truncated.npz"
    truncated.write_bytes(data[: len(data) // 2])
    with pytest.raises(CubeStoreError):
        load_cube(truncated)


def test_loading_a_file_with_a_zip_magic_number_but_garbage_fails_clearly(tmp_path):
    """Not every corrupt file was ever a real cube -- a file that merely
    starts with the zip signature must be refused the same way."""
    junk = tmp_path / "junk.npz"
    junk.write_bytes(b"PK\x03\x04" + b"not a real zip" * 20)
    with pytest.raises(CubeStoreError):
        load_cube(junk)


def test_loading_a_file_with_metadata_missing_a_key_fails_clearly(tmp_path):
    """Arrays present and readable, but the metadata blob itself is
    incomplete -- a bare KeyError must not escape."""
    mean, count, meta = _good_parts(tmp_path)
    del meta["z"]
    path = tmp_path / "bad-meta.npz"
    np.savez_compressed(path, mean=mean, count=count, meta=np.array(json.dumps(meta)))
    with pytest.raises(CubeStoreError):
        load_cube(path)


def test_loading_a_file_with_null_metadata_fails_clearly(tmp_path):
    """Valid arrays, but the metadata blob decodes to JSON `null` rather
    than an object -- subscripting `None` raises a bare TypeError, which
    must not escape either."""
    mean, count, _ = _good_parts(tmp_path)
    path = tmp_path / "null-meta.npz"
    np.savez_compressed(path, mean=mean, count=count, meta=np.array(json.dumps(None)))
    with pytest.raises(CubeStoreError):
        load_cube(path)


def test_loading_a_file_whose_metadata_disagrees_with_its_arrays_fails_clearly(tmp_path):
    """The metadata says a different grid shape than the `mean` array
    actually has -- SliceCube.__post_init__ raises a bare ValueError for
    the mismatch, which must come back as CubeStoreError like every other
    bad-file case, not as a construction error from deep inside."""
    mean, count, meta = _good_parts(tmp_path)
    meta["frame"]["nx"] = meta["frame"]["nx"] + 2  # no longer matches mean's cell count
    path = tmp_path / "shape-mismatch.npz"
    np.savez_compressed(path, mean=mean, count=count, meta=np.array(json.dumps(meta)))
    with pytest.raises(CubeStoreError):
        load_cube(path)


def test_loading_an_unsupported_store_version_fails_clearly(tmp_path):
    """A future format change must be detected, not parsed as if it were
    the version this build understands."""
    mean, count, meta = _good_parts(tmp_path)
    meta["store_version"] = 99
    path = tmp_path / "future-version.npz"
    np.savez_compressed(path, mean=mean, count=count, meta=np.array(json.dumps(meta)))
    with pytest.raises(CubeStoreError, match="version"):
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
