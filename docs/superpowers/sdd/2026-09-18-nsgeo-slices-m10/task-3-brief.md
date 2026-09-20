### Task 3: Unipolar rendering

`render.py` maps amplitude symmetrically about zero, which is right for a radargram and wrong for a slice: `to_index8` puts 0 at index 128, so an `|A|` slice uses only the top half of every table and sits on a mid-grey floor. Slices also need genuine nodata, which a 256-entry index cannot express.

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/render.py`
- Test: `packages/nsgeo-core/tests/test_render.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `UnipolarClip(percentile: float = 99.0, max_samples: int = 200_000)` with `.limit(data) -> float`
  - `to_index8_unipolar(data: np.ndarray, limit: float) -> np.ndarray`
  - `to_rgba8(data, limit, lut, *, unipolar: bool) -> np.ndarray` — `(H, W, 4)` uint8, alpha 0 where the input is not finite
  - `UNIPOLAR_COLORMAPS: frozenset[str]`, and `colormap_names(unipolar: bool | None = None)`
  - New tables `"amp_black_high"`, `"amp_white_high"`, `"amp_heat"`

- [ ] **Step 1: Write the failing tests**

Append to `packages/nsgeo-core/tests/test_render.py`:

```python
def test_unipolar_index_puts_zero_at_the_bottom_not_the_middle():
    """The whole point: a bipolar table would floor an |A| slice at grey."""
    out = render.to_index8_unipolar(np.array([[0.0, 0.5, 1.0]]), limit=1.0)
    assert list(out[0]) == [0, 128, 255]


def test_unipolar_index_clips_above_the_limit():
    out = render.to_index8_unipolar(np.array([[2.0, -1.0]]), limit=1.0)
    assert list(out[0]) == [255, 0]


def test_unipolar_clip_uses_the_percentile_of_the_values_themselves():
    """Not of their magnitudes: the data is already non-negative, so a
    percentile over |x| would be the same number computed twice."""
    data = np.concatenate([np.zeros(99), [100.0]])[None, :]
    assert render.UnipolarClip(percentile=100.0).limit(data) == pytest.approx(100.0)
    assert render.UnipolarClip(percentile=90.0).limit(data) == 1.0  # median is 0 -> fallback


def test_unipolar_clip_ignores_nan_nodata():
    data = np.array([[1.0, np.nan, 3.0]])
    assert render.UnipolarClip(percentile=100.0).limit(data) == pytest.approx(3.0)


def test_unipolar_clip_falls_back_when_everything_is_nodata():
    assert render.UnipolarClip().limit(np.full((4, 4), np.nan)) == 1.0


def test_rgba_makes_nodata_transparent_and_data_opaque():
    """A slice cell with no traces under it must not paint as a value."""
    data = np.array([[0.0, np.nan]])
    lut = render.colormap("amp_black_high")
    out = render.to_rgba8(data, limit=1.0, lut=lut, unipolar=True)
    assert out.shape == (1, 2, 4)
    assert out[0, 0, 3] == 255
    assert out[0, 1, 3] == 0


def test_rgba_bipolar_path_matches_the_existing_rgb_mapping():
    data = np.array([[-1.0, 0.0, 1.0]])
    lut = render.colormap("seismic")
    rgba = render.to_rgba8(data, limit=1.0, lut=lut, unipolar=False)
    rgb = render.to_rgb8(data, limit=1.0, lut=lut)
    np.testing.assert_array_equal(rgba[..., :3], rgb)


def test_unipolar_colormaps_are_listed_separately():
    assert set(render.colormap_names(unipolar=True)) == set(render.UNIPOLAR_COLORMAPS)
    assert "seismic" not in render.colormap_names(unipolar=True)
    assert "amp_heat" not in render.colormap_names(unipolar=False)
    assert set(render.colormap_names()) >= set(render.UNIPOLAR_COLORMAPS)


def test_every_colormap_is_a_valid_table():
    for name in render.colormap_names():
        lut = render.colormap(name)
        assert lut.shape == (256, 3)
        assert lut.dtype == np.uint8


def test_amp_black_high_runs_white_to_black():
    lut = render.colormap("amp_black_high")
    assert tuple(lut[0]) == (255, 255, 255)
    assert tuple(lut[255]) == (0, 0, 0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest packages/nsgeo-core/tests/test_render.py -v`
Expected: several FAIL with `AttributeError: module 'nsgeo.render' has no attribute 'to_index8_unipolar'`.

- [ ] **Step 3: Implement the unipolar path**

In `packages/nsgeo-core/src/nsgeo/render.py`, add after the `FixedRange` class:

```python
@dataclass(frozen=True)
class UnipolarClip:
    """Limit for data with no negative side: 0 maps to 0, limit to 255.

    Drop-in for PercentileClip, but the percentile is taken over the values
    themselves rather than their magnitudes, because they are already
    non-negative. NaN is nodata, not a value, and is excluded before the
    percentile so an unsurveyed corner cannot decide the stretch.
    """

    percentile: float = 99.0
    max_samples: int = 200_000

    def __post_init__(self) -> None:
        if not 0.0 < self.percentile <= 100.0:
            raise ValueError(f"percentile must be in (0, 100], got {self.percentile}")
        if self.max_samples < 1:
            raise ValueError(f"max_samples must be >= 1, got {self.max_samples}")

    def limit(self, data: np.ndarray) -> float:
        flat = np.asarray(data, dtype=float).ravel()
        if flat.size > self.max_samples:
            flat = flat[:: int(math.ceil(flat.size / self.max_samples))]
        finite = flat[np.isfinite(flat)]
        if finite.size == 0:
            return 1.0
        lim = float(np.percentile(finite, self.percentile))
        return lim if lim > 0.0 else 1.0
```

Add the unipolar tables next to `_seismic`:

```python
def _amp_grey(black_high: bool) -> np.ndarray:
    ramp = np.linspace(255.0, 0.0, 256) if black_high else np.linspace(0.0, 255.0, 256)
    g = np.round(ramp).astype(np.uint8)
    return np.stack([g, g, g], axis=1)


def _amp_heat() -> np.ndarray:
    """Black through red and orange to white: the unipolar table that reads
    as intensity rather than as a signed deviation."""
    t = np.linspace(0.0, 1.0, 256)
    r = np.clip(t * 3.0, 0.0, 1.0)
    g = np.clip(t * 3.0 - 1.0, 0.0, 1.0)
    b = np.clip(t * 3.0 - 2.0, 0.0, 1.0)
    return np.round(np.stack([r, g, b], axis=1) * 255.0).astype(np.uint8)
```

Extend the registry and the listing (replacing the existing `_COLORMAPS` dict and `colormap_names`):

```python
_COLORMAPS: dict[str, np.ndarray] = {
    "grey_black_high": _grey(black_high=True),
    "grey_white_high": _grey(black_high=False),
    "seismic": _seismic(),
    "amp_black_high": _amp_grey(black_high=True),
    "amp_white_high": _amp_grey(black_high=False),
    "amp_heat": _amp_heat(),
}

#: Tables meant for data with no negative side. Putting a bipolar table on
#: unipolar data is a configuration error, not a style choice: half of it
#: addresses values that cannot occur.
UNIPOLAR_COLORMAPS = frozenset({"amp_black_high", "amp_white_high", "amp_heat"})


def colormap_names(unipolar: bool | None = None) -> list[str]:
    """Table names; `unipolar` filters to (or away from) the slice tables."""
    if unipolar is None:
        return list(_COLORMAPS)
    if unipolar:
        return [n for n in _COLORMAPS if n in UNIPOLAR_COLORMAPS]
    return [n for n in _COLORMAPS if n not in UNIPOLAR_COLORMAPS]
```

Add the index and RGBA functions after `to_rgb8`:

```python
def to_index8_unipolar(data: np.ndarray, limit: float) -> np.ndarray:
    """Map 0..limit to 0..255, clipping outside.

    Non-finite samples land at 0 here and are handled properly by
    `to_rgba8`, which makes them transparent -- index 8 has no spare
    entry to mean "no data", so nodata is an alpha question.
    """
    if not limit > 0.0:
        raise ValueError(f"limit must be positive, got {limit}")
    scaled = np.asarray(data, dtype=np.float64) / limit
    scaled *= 255.0
    np.nan_to_num(scaled, copy=False, nan=0.0, posinf=255.0, neginf=0.0)
    np.clip(scaled, 0.0, 255.0, out=scaled)
    np.rint(scaled, out=scaled)
    return scaled.astype(np.uint8)


def to_rgba8(data: np.ndarray, limit: float, lut: np.ndarray, *, unipolar: bool) -> np.ndarray:
    """(H, W, 4) uint8 with alpha 0 where `data` is not finite.

    Slices need real nodata: a cell with no traces under it must not paint
    as an amplitude, and zero is a perfectly ordinary amplitude. A
    radargram has no nodata, so `unipolar=False` simply reproduces
    `to_rgb8` with a fully opaque alpha channel.
    """
    lut = np.asarray(lut)
    if lut.shape != (256, 3) or lut.dtype != np.uint8:
        raise ValueError(f"lut must be a (256, 3) uint8 table, got {lut.shape} {lut.dtype}")
    values = np.asarray(data, dtype=float)
    index = to_index8_unipolar(values, limit) if unipolar else to_index8(values, limit)
    rgb = lut.take(index, axis=0)
    alpha = np.where(np.isfinite(values), 255, 0).astype(np.uint8)
    return np.ascontiguousarray(np.concatenate([rgb, alpha[..., None]], axis=-1))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest packages/nsgeo-core/tests/test_render.py -v`
Expected: all PASS, existing tests included.

- [ ] **Step 5: Lint, type-check and commit**

```bash
python -m pytest packages/nsgeo-core/tests -q
ruff check . && ruff format --check .
mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
git add packages/nsgeo-core/src/nsgeo/render.py packages/nsgeo-core/tests/test_render.py
git commit -m "feat(render): unipolar normaliser, tables and an RGBA path

to_index8 maps symmetrically about zero, which floors an |A| slice at
mid-grey and spends half the table on values that cannot occur. Adds
UnipolarClip, three unipolar tables, and to_rgba8 -- slices need genuine
nodata, and zero is an ordinary amplitude, so absence has to be alpha
rather than a reserved index.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

