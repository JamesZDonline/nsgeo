### Task 6: Persistence — the `.npz` and the survey JSON

A cube is derived, like the GeoPackage: the survey JSON records the recipe and points at the array, and a missing array is an offer to rebuild rather than an error. The core writes `.npz` because it has numpy and nothing else — GeoTIFF is the plugin's job, in M11.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/store.py`
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py`
- Modify: `packages/nsgeo-core/src/nsgeo/model/survey.py` (add `Site.cubes`)
- Modify: `packages/nsgeo-core/src/nsgeo/project.py` (persist `cubes`)
- Test: `packages/nsgeo-core/tests/test_slices_store.py`
- Test: `packages/nsgeo-core/tests/test_project.py` (append)

**Interfaces:**
- Consumes: `SliceCube`, `CubeFrame`, `ZAxis`, `Provenance`.
- Produces:
  - `save_cube(cube: SliceCube, path: str | Path) -> None`
  - `load_cube(path: str | Path) -> SliceCube`
  - `CubeStoreError(Exception)`
  - `Site.cubes: dict[str, dict[str, Any]]`, persisted under the JSON key `"cubes"`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_slices_store.py`:

```python
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
    np.testing.assert_array_equal(
        back.mean[~np.isnan(back.mean)], cube.mean[~np.isnan(cube.mean)]
    )
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
```

Append to `packages/nsgeo-core/tests/test_project.py`:

```python
def test_cubes_round_trip_through_the_survey_json(tmp_path):
    site = Site()
    site.cubes = {
        "grid-a-standard": {
            "grid_id": "A",
            "preset": "slice-standard",
            "transform": "amp_envelope",
            "cell": 0.1,
            "array": "slices/grid-a-standard.npz",
        }
    }
    path = tmp_path / "survey.nsgeo.json"
    save_site(site, path)
    assert load_site(path).cubes == site.cubes


def test_a_site_with_no_cubes_writes_no_cubes_key(tmp_path):
    """Same rule presets already follow: absent, not an empty object."""
    path = tmp_path / "survey.nsgeo.json"
    save_site(Site(), path)
    assert "cubes" not in json.loads(path.read_text())


def test_an_older_file_without_cubes_still_loads(tmp_path):
    path = tmp_path / "survey.nsgeo.json"
    path.write_text(json.dumps({"schema_version": 1, "grids": [], "lines": []}))
    assert load_site(path).cubes == {}
```

If `json` and `Site`/`save_site`/`load_site` are not already imported at the top of `test_project.py`, add them to the existing imports rather than duplicating.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest packages/nsgeo-core/tests/test_slices_store.py packages/nsgeo-core/tests/test_project.py -v`
Expected: `ModuleNotFoundError: No module named 'nsgeo.slices.store'`, and `AttributeError: 'Site' object has no attribute 'cubes'`.

- [ ] **Step 3: Implement `store.py`**

Create `packages/nsgeo-core/src/nsgeo/slices/store.py`:

```python
"""The cube on disk.

`.npz` rather than GeoTIFF because the core has numpy and nothing else --
writing a georeferenced raster needs GDAL, which lives on the plugin side.
The plugin converts on the way to the map; this is the working format a
rebuild reads.

The metadata rides as a JSON string in a 0-d array, so the file loads with
`allow_pickle=False`. Pickle in a data file is a remote-code-execution
surface in exchange for nothing here: every field is a number or a string.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Union

import numpy as np

from nsgeo.slices.cube import Provenance, SliceCube
from nsgeo.slices.frame import CubeFrame, ZAxis

STORE_VERSION = 1


class CubeStoreError(Exception):
    """Raised when a cube file is missing, unreadable, or not a cube."""


def _meta(cube: SliceCube) -> Dict[str, Any]:
    return {
        "store_version": STORE_VERSION,
        "frame": {
            "origin": list(cube.frame.origin),
            "azimuth": cube.frame.azimuth,
            "cell": cube.frame.cell,
            "nx": cube.frame.nx,
            "ny": cube.frame.ny,
            "crs": cube.frame.crs,
        },
        "z": {"t0_ns": cube.z.t0_ns, "dz_ns": cube.z.dz_ns, "nz": cube.z.nz},
        "provenance": cube.provenance.to_dict(),
    }


def save_cube(cube: SliceCube, path: Union[str, Path]) -> None:
    """Write `cube` to `path`, creating parent directories as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        mean=cube.mean.astype(np.float32, copy=False),
        count=cube.count.astype(np.int32, copy=False),
        meta=np.array(json.dumps(_meta(cube))),
    )


def load_cube(path: Union[str, Path]) -> SliceCube:
    """Read a cube written by `save_cube`."""
    path = Path(path)
    if not path.exists():
        raise CubeStoreError(f"no cube file at {path}")
    try:
        with np.load(path, allow_pickle=False) as bundle:
            if not {"mean", "count", "meta"} <= set(bundle.files):
                raise CubeStoreError(
                    f"{path} is not a cube: expected mean, count and meta, "
                    f"found {sorted(bundle.files)}"
                )
            mean = bundle["mean"].astype(np.float32, copy=False)
            count = bundle["count"].astype(np.int32, copy=False)
            meta = json.loads(str(bundle["meta"].item()))
    except CubeStoreError:
        raise
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise CubeStoreError(f"{path} could not be read as a cube: {exc}") from exc

    frame_doc = meta["frame"]
    z_doc = meta["z"]
    return SliceCube(
        frame=CubeFrame(
            origin=(float(frame_doc["origin"][0]), float(frame_doc["origin"][1])),
            azimuth=float(frame_doc["azimuth"]),
            cell=float(frame_doc["cell"]),
            nx=int(frame_doc["nx"]),
            ny=int(frame_doc["ny"]),
            crs=frame_doc["crs"],
        ),
        z=ZAxis(
            t0_ns=float(z_doc["t0_ns"]), dz_ns=float(z_doc["dz_ns"]), nz=int(z_doc["nz"])
        ),
        mean=mean,
        count=count,
        provenance=Provenance.from_dict(meta["provenance"]),
    )
```

Add to `packages/nsgeo-core/src/nsgeo/slices/__init__.py`:

```python
from nsgeo.slices.store import CubeStoreError, load_cube, save_cube  # noqa: F401
```

- [ ] **Step 4: Add `Site.cubes`**

In `packages/nsgeo-core/src/nsgeo/model/survey.py`, add the field to `Site` after `presets`:

```python
    #: Cube recipes, keyed by cube id, each pointing at a `.npz` beside the
    #: survey file. Plain dicts for the same reason `presets` are: the JSON
    #: is the definition, and the array it names is derived and rebuildable.
    cubes: dict[str, dict[str, Any]] = field(default_factory=dict)
```

- [ ] **Step 5: Persist `cubes`**

In `packages/nsgeo-core/src/nsgeo/project.py`, in `save_site`, after the existing `presets` block:

```python
    if site.cubes:
        doc["cubes"] = site.cubes
```

and in `load_site`, alongside where `presets` is read, add:

```python
    site.cubes = doc.get("cubes", {})
```

`SCHEMA_VERSION` stays at 1: `load_site` reads only the keys it knows, so a file with `cubes` loads in an older build (ignoring them) and a file without loads here. Bumping would force a migration for a purely additive, optional key.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest packages/nsgeo-core/tests/test_slices_store.py packages/nsgeo-core/tests/test_project.py -v`
Expected: all PASS.

- [ ] **Step 7: Add the real-data end-to-end check**

Append to `packages/nsgeo-core/tests/test_real_files.py`:

```python
def test_a_cube_binned_from_real_files_is_covered_and_finite(tmp_path):
    """End to end on real data: preset, transform, bin, slice, save, reload."""
    from nsgeo.slices.binning import PreparedLine, build_cube, plan_line, stream_slice
    from nsgeo.slices.cube import Provenance
    from nsgeo.slices.frame import CubeFrame, ZAxis
    from nsgeo.slices.store import load_cube, save_cube

    prepared = []
    for i, path in enumerate(FILES[:4]):
        header = read_header(path)
        rg = Radargram(
            data=np.asarray(read_samples(path, header)[0], dtype=float),
            dt_ns=header.dt_ns,
            t0_ns=header.position_ns,
        )
        for name in ("time_zero", "dewow", "background_mean", "gain_agc", "amp_envelope"):
            rg = build_step(name).apply(rg)
        n_traces = rg.data.shape[1]
        coords = np.column_stack(
            [np.linspace(0.0, 19.99, n_traces), np.full(n_traces, 0.25 + i * 0.5)]
        )
        prepared.append(
            PreparedLine(
                key=path.name,
                data=rg.data.astype(np.float32),
                dt_ns=rg.dt_ns,
                t0_ns=rg.t0_ns,
                coords=coords,
            )
        )

    frame = CubeFrame(origin=(0.0, 0.0), azimuth=0.0, cell=0.2, nx=100, ny=12, crs="EPSG:32633")
    z = ZAxis.from_range(1.0, 40.0, 0.2165)
    plans = [plan_line(p, frame, z) for p in prepared]
    prov = Provenance(
        line_keys=tuple(p.key for p in prepared), preset_name="test", steps=(),
        transform="amp_envelope", velocity=None, built_utc="2026-09-18T00:00:00Z",
        core_version="0.1.0.dev0",
    )
    cube = build_cube(prepared, plans, frame, z, prov)

    assert cube.coverage().sum() == sum(p.data.shape[1] for p in prepared)
    covered = cube.slice_levels(10, 28)[cube.coverage() > 0]
    assert np.isfinite(covered).all()
    assert (covered >= 0.0).all()  # the envelope is unipolar

    streamed, _ = stream_slice(prepared, plans, frame, z, 10, 28)
    np.testing.assert_allclose(
        streamed[cube.coverage() > 0], covered, rtol=1e-4, atol=1e-5
    )

    out = tmp_path / "real.npz"
    save_cube(cube, out)
    assert load_cube(out).provenance == prov
```

Run: `python -m pytest packages/nsgeo-core/tests/test_real_files.py -v`
Expected: PASS locally where the real files are present; the module's `pytestmark` skips it in CI.

- [ ] **Step 8: Lint, type-check and commit**

```bash
python -m pytest packages/nsgeo-core/tests -q
ruff check . && ruff format --check .
mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
git add packages/nsgeo-core
git commit -m "feat(slices): persist cubes as .npz and record them in the survey JSON

The core writes .npz because it has numpy and nothing else: a GeoTIFF
needs GDAL, which lives on the plugin side. Metadata rides as a JSON
string so the file loads with allow_pickle=False.

Site.cubes holds the recipes as plain dicts, exactly as presets do, and
SCHEMA_VERSION stays at 1 because load_site reads only keys it knows --
the addition is optional in both directions.

Also adds an end-to-end test over the real GSSI files: preset, envelope,
bin, slice, stream, save and reload.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## What M10 deliberately does not do

Named here so a reviewer does not flag them as gaps:

- **No line preparation.** Loading, running a preset and transforming are the caller's; `PreparedLine` is the boundary. The cache that makes everything else interactive is M11's, because it is a session concern and the core holds no session.
- **No GeoTIFF, no GDAL, no temporal encoding.** M11.
- **No directional de-striping** (spec §6.5) and **no site mosaic** (§10). M12.
- **No on-disk residency tier.** Spec §7.4 flags it as unmeasured; the spike runs before anything commits to memory-mapping, and nothing in this plan depends on it.

## Plan Self-Review

**Spec coverage.** §5.1 `CubeFrame` → Task 1. §5.2 `ZAxis` → Task 1. §5.3 `SliceCube`, z-major layout, per-cell count and the rejection rule → Tasks 4. §5.4 `.npz` and the JSON `cubes` list → Task 6. §6.2 transforms and the no-padding rule → Task 2. §6.3 binning and the precomputed plans → Task 4. §6.4 the fill → Task 5. §6.6 `slice_levels` and `level_range` → Tasks 1 and 4. §7.4 streaming → Task 5. §8 unipolar rendering → Task 3. §6.5, §9, §10 are M11/M12 and are listed above as out of scope for this plan.

**Type consistency, checked across tasks.** `CubeFrame.cell_index` returns flat `iy * nx + ix` in Task 1 and is consumed with that meaning by `plan_line` in Task 4 and `SliceCube.coverage`'s reshape in Task 4. `ZAxis.level_range` returns the half-open pair that `slice_levels` and `stream_slice` both validate as `0 <= k0 < k1 <= nz`. `PreparedLine.data` is float32 in Tasks 4–6. `Provenance.to_dict` / `from_dict` in Task 4 are what `store.py` calls in Task 6. `is_unipolar` is defined in Task 2 and consumed by `StepStack.output_unipolar` in the same task; `to_rgba8(..., unipolar=...)` in Task 3 takes the bool that property produces.

**One thing an implementer should know.** In Task 5, `stream_slice` accumulates `count` as int64 before dividing and only narrows to int32 on return. That is deliberate: `counts * n_levels` on a 230-level cube with a dense cell overflows int32 far sooner than it looks, and the bug would surface as a negative coverage rather than as an exception.
