"""Amplitude-to-colour mapping. Display gain is not a processing step: these
functions change how numbers become pixels, never the numbers."""

from __future__ import annotations

import warnings
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


def test_to_rgb8_matches_fancy_indexing():
    """Pins `lut.take(idx, axis=0)` to the same result as the plain
    `lut[idx]` fancy indexing it replaced for speed."""
    data = np.linspace(-3.0, 3.0, 30).reshape(5, 6)
    limit = 2.0
    lut = colormap("seismic")
    idx = to_index8(data, limit)
    fast = to_rgb8(data, limit, lut)
    naive = lut[idx]
    np.testing.assert_array_equal(fast, naive)
    assert fast.flags["C_CONTIGUOUS"]


def test_non_positive_limit_is_rejected():
    with pytest.raises(ValueError, match="limit"):
        to_index8(np.zeros((2, 2)), limit=0.0)


def test_to_index8_nan_is_neutral_not_a_reflector():
    """A NaN amplitude (e.g. an AGC divide-by-zero on an all-zero leading
    trace: rms=0, target/max(0, eps=0)=inf, 0*inf=NaN) must render as
    neutral mid-grey, not white -- indistinguishable from a strong negative
    reflector -- and must not raise a warning doing it."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        idx = to_index8(np.array([[np.nan, -5.0, 5.0]]), limit=1.0)
    assert idx.tolist() == [[128, 0, 255]]


def test_to_index8_does_not_mutate_its_input():
    data = np.array([[-2.0, -1.0, 0.0, 1.0, 2.0]])
    original = data.copy()
    to_index8(data, limit=1.0)
    np.testing.assert_array_equal(data, original)


def test_to_index8_matches_the_reference_formula():
    """Pins the in-place, reused-buffer implementation to the same result as
    the straightforward one-expression formula it replaced for speed."""
    rng = np.random.default_rng(4)
    data = rng.normal(scale=5.0, size=(40, 55))
    limit = 3.7
    fast = to_index8(data, limit)
    naive = np.round(np.clip((data / limit + 1.0) * 127.5, 0.0, 255.0)).astype(np.uint8)
    np.testing.assert_array_equal(fast, naive)


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


def test_percentile_clip_ignores_non_finite_samples():
    """A NaN or inf sample (e.g. an AGC divide-by-zero) must not be able to
    collapse the limit to the all-zero fallback: the limit is computed from
    the finite samples, same as if the non-finite ones were never there."""
    finite = np.array([1.0, 2.0, 3.0, 4.0])
    with_nan = np.concatenate([finite, [np.nan, np.inf, -np.inf]])
    lim_finite = PercentileClip(percentile=100.0).limit(finite)
    lim_with_nan = PercentileClip(percentile=100.0).limit(with_nan)
    assert lim_with_nan == lim_finite
    assert lim_with_nan != 1.0


def test_percentile_clip_on_all_nan_data_returns_one_without_warning():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        lim = PercentileClip().limit(np.full((8, 8), np.nan))
    assert lim == 1.0


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


def test_decimate_columns_does_not_mutate_its_input():
    data = np.arange(20, dtype=float).reshape(1, 20)
    original = data.copy()
    decimate_columns(data, max_width=5)
    np.testing.assert_array_equal(data, original)


def test_decimate_columns_matches_the_reference_nan_padded_mean():
    """Pins the full-blocks-plus-one-tail implementation to the same result
    as NaN-padding the whole array and taking nanmean throughout -- the
    slower, more obviously correct approach it replaced for speed."""
    rng = np.random.default_rng(5)
    data = rng.normal(size=(4, 37))
    max_width = 9
    fast = decimate_columns(data, max_width)

    block = int(np.ceil(data.shape[1] / max_width))
    n_blocks = int(np.ceil(data.shape[1] / block))
    padded = np.full((data.shape[0], n_blocks * block), np.nan)
    padded[:, : data.shape[1]] = data
    naive = np.nanmean(padded.reshape(data.shape[0], n_blocks, block), axis=2)

    np.testing.assert_allclose(fast, naive)


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
