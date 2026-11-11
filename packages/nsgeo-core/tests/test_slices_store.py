from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest
from nsgeo.slices.cube import CubeBlock, Provenance, SliceCube
from nsgeo.slices.frame import CubeFrame, ZAxis
from nsgeo.slices.store import CubeStoreError, _meta, load_cube, save_cube


def make_cube(seed=0):
    frame = CubeFrame(origin=(10.0, 20.0), azimuth=37.5, cell=0.1, nx=5, ny=4, crs="EPSG:32633")
    z = ZAxis(t0_ns=-1.5, dz_ns=0.2165, nz=6)
    rng = np.random.default_rng(seed)
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
    return SliceCube.from_dense(frame, z, mean, count, prov)


def test_round_trip_preserves_every_read(tmp_path):
    cube = make_cube()
    path = tmp_path / "grid-a.npz"
    save_cube(cube, path)
    back = load_cube(path)
    assert len(back.blocks) == len(cube.blocks)
    for got, want in zip(back.blocks, cube.blocks):
        np.testing.assert_array_equal(got.cells, want.cells)
        np.testing.assert_array_equal(got.mean, want.mean)
        np.testing.assert_array_equal(got.count, want.count)
        assert got.heading_deg == want.heading_deg
    nz = cube.z.nz
    np.testing.assert_array_equal(back.slice_levels(0, nz), cube.slice_levels(0, nz))
    np.testing.assert_array_equal(back.level(3), cube.level(3))
    np.testing.assert_array_equal(back.coverage(), cube.coverage())


def test_saved_file_holds_only_covered_cells(tmp_path):
    cube = make_cube()
    path = tmp_path / "packed.npz"
    save_cube(cube, path)
    n_covered = int((cube.coverage() > 0).sum())
    assert 0 < n_covered < cube.frame.n_cells
    with np.load(path, allow_pickle=False) as bundle:
        assert sorted(bundle.files) == ["cells_0", "count_0", "mean_0", "meta"]
        assert bundle["mean_0"].shape == (cube.z.nz, n_covered)
        meta = json.loads(str(bundle["meta"].item()))
    assert meta["store_version"] == 2
    assert meta["blocks"] == [{"heading_deg": None}]


def test_a_two_block_cube_round_trips_with_its_headings(tmp_path):
    first, second = make_cube(0), make_cube(1)
    cube = SliceCube(
        frame=first.frame,
        z=first.z,
        blocks=(
            replace(first.blocks[0], heading_deg=12.5),
            replace(second.blocks[0], heading_deg=192.5),
        ),
        provenance=first.provenance,
    )
    path = tmp_path / "two.npz"
    save_cube(cube, path)
    back = load_cube(path)
    assert [b.heading_deg for b in back.blocks] == [12.5, 192.5]
    for got, want in zip(back.blocks, cube.blocks):
        np.testing.assert_array_equal(got.cells, want.cells)
        np.testing.assert_array_equal(got.mean, want.mean)
    np.testing.assert_array_equal(back.coverage(), cube.coverage())


def test_a_version_1_file_loads_and_reads_the_same(tmp_path):
    """Cubes saved by nsgeo 0.1-0.3 stored the dense arrays."""
    cube = make_cube()
    n_cells = cube.frame.n_cells
    count = cube.coverage().ravel()
    mean = np.full((cube.z.nz, n_cells), np.nan, dtype=np.float32)
    mean[:, cube.blocks[0].cells] = cube.blocks[0].mean
    meta = _meta(cube)
    meta["store_version"] = 1
    del meta["blocks"]
    path = tmp_path / "old.npz"
    np.savez_compressed(path, mean=mean, count=count, meta=np.array(json.dumps(meta)))
    back = load_cube(path)
    assert len(back.blocks) == 1
    np.testing.assert_array_equal(back.blocks[0].cells, np.flatnonzero(count > 0))
    nz = cube.z.nz
    np.testing.assert_array_equal(
        back.slice_levels(0, nz), mean.mean(axis=0).reshape(cube.frame.ny, cube.frame.nx)
    )
    np.testing.assert_array_equal(back.coverage(), cube.coverage())


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
    (block,) = back.blocks
    assert block.cells.dtype == np.int64
    assert block.mean.dtype == np.float32
    assert block.count.dtype == np.int32


def test_loading_a_file_that_is_not_a_cube_fails_clearly(tmp_path):
    path = tmp_path / "junk.npz"
    np.savez(path, something=np.zeros(3))
    with pytest.raises(CubeStoreError, match="not a cube"):
        load_cube(path)


def test_loading_a_missing_file_fails_clearly(tmp_path):
    with pytest.raises(CubeStoreError, match="no cube file"):
        load_cube(tmp_path / "absent.npz")


@pytest.mark.parametrize("degenerate", ["", "."])
def test_loading_a_degenerate_path_fails_clearly(degenerate):
    """A hand-edited survey JSON with `"array": ""` is a realistic way to
    reach this. Path normalisation itself raises a bare ValueError for a
    name-less path -- that must come back as CubeStoreError like any other
    unusable path, not escape as an internal implementation detail."""
    with pytest.raises(CubeStoreError):
        load_cube(degenerate)


def test_save_narrows_a_wider_input_dtype(tmp_path):
    """SliceCube itself does not enforce a dtype, so a caller could hand
    save_cube a float64 mean or an int64 count. The store must still not
    persist the wide form -- that would double a 331 MB cube for nothing
    -- so narrowing has to happen regardless of what came in."""
    cube = make_cube()
    (block,) = cube.blocks
    wide = SliceCube(
        frame=cube.frame,
        z=cube.z,
        blocks=(
            CubeBlock(
                cells=block.cells.astype(np.int64),
                mean=block.mean.astype(np.float64),
                count=block.count.astype(np.int64),
            ),
        ),
        provenance=cube.provenance,
    )
    path = tmp_path / "wide.npz"
    save_cube(wide, path)
    # Inspect what actually landed on disk, not what load_cube hands back --
    # load_cube narrows on the way out too, so only checking its return value
    # would pass even if save_cube itself wrote the wide arrays.
    with np.load(path, allow_pickle=False) as bundle:
        assert bundle["cells_0"].dtype == np.int64
        assert bundle["mean_0"].dtype == np.float32
        assert bundle["count_0"].dtype == np.int32


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


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        ("grid.v2", "grid.v2.npz"),
        ("Grid A v1.2", "Grid A v1.2.npz"),
        ("2026-09-18.grid", "2026-09-18.grid.npz"),
        ("cube.tar.gz", "cube.tar.gz.npz"),
        ("cube.bin", "cube.bin.npz"),
    ],
)
def test_save_appends_npz_rather_than_replacing_a_dot_in_the_name(tmp_path, stem, expected):
    """`np.savez_compressed` APPENDS `.npz` unless the name already ends
    with it; `Path.with_suffix` REPLACES the last suffix instead. A
    version tag, a date, or a decimal in a user-typed cube name all
    contain a dot that is not an extension, and replacing it would
    silently rename the file to something the caller never asked for."""
    cube = make_cube()
    path = tmp_path / stem
    save_cube(cube, path)
    assert (tmp_path / expected).exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == [expected]
    back = load_cube(path)
    assert back.frame == cube.frame


def test_save_does_not_alias_two_dotted_names_onto_one_file(tmp_path):
    """The concrete failure mode of the `with_suffix` bug: saving
    "grid.v1" and then "grid.v2" must not collapse onto a single
    "grid.npz" -- that would make the second save silently destroy the
    first cube, with no error anywhere."""
    cube_v1 = make_cube(seed=1)
    cube_v2 = make_cube(seed=2)
    save_cube(cube_v1, tmp_path / "grid.v1")
    save_cube(cube_v2, tmp_path / "grid.v2")

    assert sorted(p.name for p in tmp_path.iterdir()) == ["grid.v1.npz", "grid.v2.npz"]

    back_v1 = load_cube(tmp_path / "grid.v1")
    back_v2 = load_cube(tmp_path / "grid.v2")
    np.testing.assert_array_equal(back_v1.blocks[0].mean, cube_v1.blocks[0].mean)
    np.testing.assert_array_equal(back_v2.blocks[0].mean, cube_v2.blocks[0].mean)
    # Compare what a reader sees (NaN where uncovered), with equal_nan=True:
    # without it np.array_equal returns False for any NaN-bearing array
    # regardless of the other array's content, so this would pass even on
    # the aliasing bug it claims to guard against (both cubes identical).
    assert not np.array_equal(
        back_v1.slice_levels(0, 6), back_v2.slice_levels(0, 6), equal_nan=True
    )  # genuinely different


def test_a_dot_in_a_directory_name_is_unaffected(tmp_path):
    """A dot belongs to a path segment other than the final name in a
    directory called e.g. "a.b" -- that must keep working exactly as
    before; only the final component's own dot was ever ambiguous."""
    cube = make_cube()
    directory = tmp_path / "a.b"
    path = directory / "cube"
    save_cube(cube, path)
    assert (directory / "cube.npz").exists()
    back = load_cube(path)
    assert back.frame == cube.frame


def _good_parts(tmp_path):
    """A good cube's raw (block arrays, meta-dict) pair, for tests that
    tamper with just one part of an otherwise-valid file."""
    path = tmp_path / "seed.npz"
    save_cube(make_cube(), path)
    with np.load(path, allow_pickle=False) as bundle:
        arrays = {k: bundle[k] for k in bundle.files if k != "meta"}
        return arrays, json.loads(str(bundle["meta"].item()))


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
    arrays, meta = _good_parts(tmp_path)
    del meta["z"]
    path = tmp_path / "bad-meta.npz"
    np.savez_compressed(path, **arrays, meta=np.array(json.dumps(meta)))
    with pytest.raises(CubeStoreError):
        load_cube(path)


def test_loading_a_file_with_null_metadata_fails_clearly(tmp_path):
    """Valid arrays, but the metadata blob decodes to JSON `null` rather
    than an object -- subscripting `None` raises a bare TypeError, which
    must not escape either."""
    arrays, _ = _good_parts(tmp_path)
    path = tmp_path / "null-meta.npz"
    np.savez_compressed(path, **arrays, meta=np.array(json.dumps(None)))
    with pytest.raises(CubeStoreError):
        load_cube(path)


def test_loading_a_file_whose_metadata_disagrees_with_its_arrays_fails_clearly(tmp_path):
    """The metadata says a different grid shape than the `mean` array
    can hold -- SliceCube.__post_init__ raises a bare ValueError for
    the mismatch, which must come back as CubeStoreError like every other
    bad-file case, not as a construction error from deep inside."""
    arrays, meta = _good_parts(tmp_path)
    meta["frame"]["nx"] = 1  # a 1 x 4 grid: the stored cell ids no longer fit
    path = tmp_path / "shape-mismatch.npz"
    np.savez_compressed(path, **arrays, meta=np.array(json.dumps(meta)))
    with pytest.raises(CubeStoreError):
        load_cube(path)


def test_loading_an_unsupported_store_version_fails_clearly(tmp_path):
    """A future format change must be detected, not parsed as if it were
    the version this build understands."""
    arrays, meta = _good_parts(tmp_path)
    meta["store_version"] = 99
    path = tmp_path / "future-version.npz"
    np.savez_compressed(path, **arrays, meta=np.array(json.dumps(meta)))
    with pytest.raises(CubeStoreError, match="version"):
        load_cube(path)


def test_loading_a_zero_byte_file_fails_clearly(tmp_path):
    """A killed or disk-full `save_cube` can leave exactly this -- the
    limiting case of the truncated-file finding. `np.load` raises
    `EOFError` for it, not `OSError`, so it needs its own place in the
    except tuple."""
    path = tmp_path / "empty.npz"
    path.write_bytes(b"")
    with pytest.raises(CubeStoreError):
        load_cube(path)


def test_loading_a_file_with_a_too_short_origin_fails_clearly(tmp_path):
    """`origin` is unpacked as a 2-element list; a metadata blob with only
    one element raises a bare IndexError from store.py's own indexing,
    which must not escape either -- the same class of bug the `KeyError`
    case beside it already covers."""
    arrays, meta = _good_parts(tmp_path)
    meta["frame"]["origin"] = [1.0]
    path = tmp_path / "short-origin.npz"
    np.savez_compressed(path, **arrays, meta=np.array(json.dumps(meta)))
    with pytest.raises(CubeStoreError):
        load_cube(path)


def test_loading_a_file_with_a_null_crs_fails_clearly(tmp_path):
    """`CubeFrame` does not validate `crs` at all, so a hand-edited or
    corrupted survey JSON with `"crs": null` would otherwise load with
    `frame.crs is None` and no complaint -- and reach M11's GeoTIFF export
    as a silently unreferenced raster. load_cube must reject a non-string
    crs itself."""
    arrays, meta = _good_parts(tmp_path)
    meta["frame"]["crs"] = None
    path = tmp_path / "null-crs.npz"
    np.savez_compressed(path, **arrays, meta=np.array(json.dumps(meta)))
    with pytest.raises(CubeStoreError, match="crs"):
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
    arrays, meta = _good_parts(tmp_path)
    arrays["mean_0"] = arrays["mean_0"].astype(object)

    evil = tmp_path / "evil.npz"
    np.savez_compressed(evil, **arrays, meta=np.array(json.dumps(meta)))
    with pytest.raises(CubeStoreError):
        load_cube(evil)


def _damage_missing_cells(arrays, meta):
    del arrays["cells_0"]


def _damage_two_blocks_listed(arrays, meta):
    meta["blocks"] = [{"heading_deg": None}, {"heading_deg": None}]


def _damage_unsorted_cells(arrays, meta):
    arrays["cells_0"] = arrays["cells_0"][::-1].copy()


def _damage_cells_past_the_frame(arrays, meta):
    arrays["cells_0"] = arrays["cells_0"] + meta["frame"]["nx"] * meta["frame"]["ny"]


def _damage_zero_count(arrays, meta):
    arrays["count_0"] = arrays["count_0"].copy()
    arrays["count_0"][0] = 0


def _damage_wrong_mean_shape(arrays, meta):
    arrays["mean_0"] = arrays["mean_0"][:, :-1]


def _damage_object_cells(arrays, meta):
    arrays["cells_0"] = arrays["cells_0"].astype(object)


@pytest.mark.parametrize(
    "damage",
    [
        _damage_missing_cells,
        _damage_two_blocks_listed,
        _damage_unsorted_cells,
        _damage_cells_past_the_frame,
        _damage_zero_count,
        _damage_wrong_mean_shape,
        _damage_object_cells,
    ],
    ids=lambda f: f.__name__.removeprefix("_damage_"),
)
def test_a_damaged_version_2_file_fails_clearly(tmp_path, damage):
    """Never load a wrong picture: every way a packed file can disagree with
    itself is a CubeStoreError, not a ValueError from deep inside."""
    arrays, meta = _good_parts(tmp_path)
    damage(arrays, meta)
    path = tmp_path / "damaged.npz"
    np.savez_compressed(path, **arrays, meta=np.array(json.dumps(meta)))
    with pytest.raises(CubeStoreError):
        load_cube(path)
