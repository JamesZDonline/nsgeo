"""The real Grad601 files (gitignored; every test skips on CI). Files are keyed by name."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.mag.grad601 import mark_missing, missing_summary, read_grad601

from tests.real_data import MAG_FILES

pytestmark = pytest.mark.skipif(not MAG_FILES, reason="no real mag files under tests/data/local")

MISSING = {
    "example1.dat": 0,
    "example2.dat": 0,
    "example3.dat": 7273,
    "example4.dat": 24,
    "example5.dat": 0,
    "example6.dat": 24,
}
KEPT_ZEROS = {
    "example1.dat": 9,
    "example2.dat": 15,
    "example3.dat": 5,
    "example4.dat": 10,
    "example5.dat": 3,
    "example6.dat": 7,
}


def raw_of(name):
    (path,) = [p for p in MAG_FILES if p.name == name]
    return read_grad601(path)


def test_real_grids_are_60_traverses_of_240_readings():
    for name in MISSING:
        assert raw_of(name).shape == (60, 240), name


def test_real_missing_data_counts():
    for name in MISSING:
        marked = mark_missing(raw_of(name))
        assert int(np.isnan(marked).sum()) == MISSING[name], name
        assert int((marked == 0.0).sum()) == KEPT_ZEROS[name], name


def test_real_missing_blocks_are_where_section_3_says():
    m4 = mark_missing(raw_of("example4.dat"))
    assert np.isnan(m4[[49, 51], 29:41]).all()
    m6 = mark_missing(raw_of("example6.dat"))
    assert np.isnan(m6[[33, 35], 20:32]).all()
    m3 = mark_missing(raw_of("example3.dat"))
    assert np.isnan(m3[:, -1]).all()


def test_real_missing_summaries():
    assert missing_summary(mark_missing(raw_of("example4.dat"))) == (
        "24 readings are missing data, on traverses 50 and 52."
    )
    assert missing_summary(mark_missing(raw_of("example6.dat"))) == (
        "24 readings are missing data, on traverses 34 and 36."
    )
    assert missing_summary(mark_missing(raw_of("example3.dat"))) == (
        "7273 readings are missing data, on traverses 1, 2, 3, 4, 5, 6 and 54 more."
    )
