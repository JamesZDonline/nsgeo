### Task 2: `nsgeo.render` — amplitude to colour, numpy only

The display side of spec §8 without any Qt: a `Normalizer` protocol with percentile clip, colormap lookup tables, index and RGB conversion, and column decimation. The plugin wraps the byte array in a `QImage` and does nothing else.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/render.py`
- Create: `packages/nsgeo-core/tests/test_render.py`

**Interfaces:**
- Consumes: numpy only
- Produces: `Normalizer` protocol (`limit(data) -> float`); `PercentileClip(percentile=99.0, max_samples=200_000)`; `FixedRange(limit_value)`; `DEFAULT_COLORMAP = "grey_black_high"`; `colormap_names() -> list[str]`; `colormap(name) -> np.ndarray` (256, 3) uint8; `to_index8(data, limit) -> np.ndarray` uint8 (H, W); `to_rgb8(data, limit, lut) -> np.ndarray` uint8 (H, W, 3) C-contiguous; `decimate_columns(data, max_width) -> np.ndarray`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_render.py`:

```python
"""Amplitude-to-colour mapping. Display gain is not a processing step: these
functions change how numbers become pixels, never the numbers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from nsgeo.io.dzt import read_samples
from nsgeo.render import (
    DEFAULT_COLORMAP,
    FixedRange,
    PercentileClip,
    colormap,
    colormap_names,
    decimate_columns,
    to_index8,
    to_rgb8,
)

DATA = Path(__file__).parent / "data" / "local"
FILES = sorted(p for p in DATA.rglob("*") if p.suffix.lower() == ".dzt") if DATA.exists() else []


def test_zero_maps_to_mid_grey_and_extremes_to_black_and_white():
    lut = colormap(DEFAULT_COLORMAP)
    idx = to_index8(np.array([[-2.0, -1.0, 0.0, 1.0, 2.0]]), limit=1.0)
    assert idx.tolist() == [[0, 0, 128, 255, 255]]
    rgb = lut[idx]
    assert rgb[0, 0].tolist() == [255, 255, 255]  # strong negative: white
    assert rgb[0, 4].tolist() == [0, 0, 0]  # strong positive: black
    assert 120 <= rgb[0, 2, 0] <= 135  # zero: mid grey


def test_index_is_symmetric_about_zero():
    idx = to_index8(np.array([[-0.5, 0.5]]), limit=1.0)
    assert int(idx[0, 0]) + int(idx[0, 1]) == 255


def test_to_rgb8_shape_dtype_and_contiguity():
    rgb = to_rgb8(np.zeros((4, 7)), limit=1.0, lut=colormap(DEFAULT_COLORMAP))
    assert rgb.shape == (4, 7, 3)
    assert rgb.dtype == np.uint8
    assert rgb.flags["C_CONTIGUOUS"]


def test_non_positive_limit_is_rejected():
    with pytest.raises(ValueError, match="limit"):
        to_index8(np.zeros((2, 2)), limit=0.0)


def test_every_colormap_is_a_256_by_3_uint8_table():
    assert DEFAULT_COLORMAP in colormap_names()
    for name in colormap_names():
        lut = colormap(name)
        assert lut.shape == (256, 3) and lut.dtype == np.uint8


def test_seismic_is_blue_white_red():
    lut = colormap("seismic")
    assert lut[0].tolist() == [0, 0, 255]
    assert lut[128].tolist() == [255, 255, 255]
    assert lut[255].tolist() == [255, 0, 0]


def test_unknown_colormap_names_the_options():
    with pytest.raises(KeyError, match="grey_black_high"):
        colormap("viridis")


def test_colormap_returns_a_copy():
    a = colormap(DEFAULT_COLORMAP)
    a[:] = 0
    assert colormap(DEFAULT_COLORMAP)[0, 0] == 255


def test_percentile_clip_is_symmetric_and_ignores_sign():
    data = np.concatenate([np.linspace(-10, 0, 500), np.linspace(0, 5, 500)]).reshape(10, 100)
    lim = PercentileClip(percentile=100.0).limit(data)
    assert lim == pytest.approx(10.0)


def test_percentile_clip_on_all_zero_data_returns_one():
    assert PercentileClip().limit(np.zeros((8, 8))) == 1.0


def test_percentile_clip_subsamples_large_arrays_deterministically():
    rng = np.random.default_rng(1)
    data = rng.normal(size=(512, 3000))
    clip = PercentileClip(percentile=99.0, max_samples=10_000)
    lim = clip.limit(data)
    step = int(np.ceil(data.size / 10_000))
    expected = float(np.percentile(np.abs(data.ravel()[::step]), 99.0))
    assert lim == expected
    full = float(np.percentile(np.abs(data), 99.0))
    assert abs(lim - full) / full < 0.05


def test_percentile_clip_validates_its_arguments():
    with pytest.raises(ValueError):
        PercentileClip(percentile=0.0)
    with pytest.raises(ValueError):
        PercentileClip(max_samples=0)


def test_fixed_range_is_a_drop_in_normalizer():
    assert FixedRange(3.5).limit(np.ones((2, 2))) == 3.5
    with pytest.raises(ValueError):
        FixedRange(0.0)


def test_decimate_columns_block_means_and_is_a_no_op_when_narrow():
    data = np.arange(20, dtype=float).reshape(1, 20)
    out = decimate_columns(data, max_width=5)
    assert out.shape == (1, 5)
    np.testing.assert_allclose(out[0], [1.5, 5.5, 9.5, 13.5, 17.5])
    same = decimate_columns(data, max_width=20)
    assert same is data


def test_decimate_columns_handles_a_ragged_last_block():
    data = np.arange(7, dtype=float).reshape(1, 7)
    out = decimate_columns(data, max_width=3)  # block of 3 -> widths 3, 3, 1
    np.testing.assert_allclose(out[0], [1.0, 4.0, 6.0])


@pytest.mark.skipif(not FILES, reason="no real DZT files in tests/data/local")
def test_real_file_renders_with_both_extremes_present():
    """The direct wave clips at 99 %, so a real raw render must reach both
    ends of the table; a render that does not is a broken normaliser."""
    data = read_samples(FILES[0])[0].astype(float)
    idx = to_index8(data, PercentileClip().limit(data))
    assert idx.shape == data.shape
    assert idx.min() == 0 and idx.max() == 255
    rgb = to_rgb8(data, PercentileClip().limit(data), colormap(DEFAULT_COLORMAP))
    assert rgb.shape == data.shape + (3,)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest packages/nsgeo-core/tests/test_render.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo.render'`

- [ ] **Step 3: Implement `render.py`**

Create `packages/nsgeo-core/src/nsgeo/render.py`:

```python
"""Amplitude-to-colour mapping for front ends. numpy only.

Display gain is not a processing step. Clip percentile, colour range, and
colormap alter how amplitude maps to colour, not the data, so dragging them
remaps a lookup table and repaints with no recomputation, and none of it is
recorded in a stack. Front ends wrap the byte arrays produced here in their
own image type (QImage, PIL, ...) and do nothing else.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import numpy as np

DEFAULT_COLORMAP = "grey_black_high"


class Normalizer(Protocol):
    """Chooses the symmetric amplitude limit that maps to the ends of the
    colour table. Bipolar data is always mapped symmetrically about zero."""

    def limit(self, data: np.ndarray) -> float: ...


@dataclass(frozen=True)
class PercentileClip:
    """Limit = the given percentile of |data|.

    Above `max_samples` values, a strided subsample is used. On a 512 x 6301
    radargram the full percentile costs about 120 ms; the subsample keeps a
    display-gain drag interactive and is deterministic for a given array.
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
        if flat.size == 0:
            return 1.0
        lim = float(np.percentile(np.abs(flat), self.percentile))
        return lim if lim > 0.0 else 1.0


@dataclass(frozen=True)
class FixedRange:
    """A user-chosen limit. Drop-in for PercentileClip."""

    limit_value: float

    def __post_init__(self) -> None:
        if not self.limit_value > 0.0:
            raise ValueError(f"limit_value must be positive, got {self.limit_value}")

    def limit(self, data: np.ndarray) -> float:
        return float(self.limit_value)


def _grey(black_high: bool) -> np.ndarray:
    ramp = np.linspace(255.0, 0.0, 256) if black_high else np.linspace(0.0, 255.0, 256)
    g = np.round(ramp).astype(np.uint8)
    return np.stack([g, g, g], axis=1)


def _seismic() -> np.ndarray:
    """Blue for negative, white at zero, red for positive."""
    t = np.linspace(-1.0, 1.0, 256)
    r = np.where(t < 0, 1.0 + t, 1.0)
    g = 1.0 - np.abs(t)
    b = np.where(t > 0, 1.0 - t, 1.0)
    return np.round(np.stack([r, g, b], axis=1) * 255.0).astype(np.uint8)


_COLORMAPS: dict[str, np.ndarray] = {
    "grey_black_high": _grey(black_high=True),
    "grey_white_high": _grey(black_high=False),
    "seismic": _seismic(),
}


def colormap_names() -> list[str]:
    return list(_COLORMAPS)


def colormap(name: str) -> np.ndarray:
    """A (256, 3) uint8 lookup table. Returns a copy."""
    try:
        return _COLORMAPS[name].copy()
    except KeyError:
        raise KeyError(f"unknown colormap {name!r}; available: {colormap_names()}") from None


def to_index8(data: np.ndarray, limit: float) -> np.ndarray:
    """Map amplitudes to 0..255 with -limit -> 0, 0 -> 128, +limit -> 255."""
    if not limit > 0.0:
        raise ValueError(f"limit must be positive, got {limit}")
    scaled = (np.asarray(data, dtype=float) / limit + 1.0) * 127.5
    return np.round(np.clip(scaled, 0.0, 255.0)).astype(np.uint8)


def to_rgb8(data: np.ndarray, limit: float, lut: np.ndarray) -> np.ndarray:
    """(H, W, 3) uint8, C-contiguous, ready to wrap as an RGB888 image."""
    lut = np.asarray(lut)
    if lut.shape != (256, 3) or lut.dtype != np.uint8:
        raise ValueError(f"lut must be a (256, 3) uint8 table, got {lut.shape} {lut.dtype}")
    return np.ascontiguousarray(lut[to_index8(data, limit)])


def decimate_columns(data: np.ndarray, max_width: int) -> np.ndarray:
    """Block-mean along the trace axis until there are at most `max_width`
    columns. Happens after processing, never before, so the view is a
    downsampled real result. Returns `data` itself when already narrow."""
    if max_width < 1:
        raise ValueError(f"max_width must be >= 1, got {max_width}")
    n = data.shape[1]
    if n <= max_width:
        return data
    block = int(math.ceil(n / max_width))
    n_blocks = int(math.ceil(n / block))
    padded = np.full((data.shape[0], n_blocks * block), np.nan)
    padded[:, :n] = data
    return np.nanmean(padded.reshape(data.shape[0], n_blocks, block), axis=2)
```

- [ ] **Step 4: Run tests, lint, mypy**

Run: `.venv/bin/python -m pytest packages/nsgeo-core/tests/test_render.py packages/nsgeo-core/tests/test_boundary.py -q && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo`
Expected: all PASS, clean.

- [ ] **Step 5: Commit**

```bash
git add packages/nsgeo-core
git commit -m "feat: add nsgeo.render, numpy-only amplitude-to-colour mapping

Normaliser protocol with percentile clip (strided subsample above 200k
values so a display-gain drag stays interactive), colormap lookup tables
with greyscale black-high as the bipolar default, index/RGB conversion,
and column decimation after processing. Lives in the MIT core so a
future standalone front end can use it verbatim; the plugin only wraps
the byte array in a QImage."
```

---

