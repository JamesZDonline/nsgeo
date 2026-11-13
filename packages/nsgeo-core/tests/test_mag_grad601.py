from __future__ import annotations

import numpy as np
import pytest
from nsgeo.mag.grad601 import MagFileError, mark_missing, missing_summary, read_grad601

from tests.mag_data import write_grad601

nan = np.nan


def test_reads_tabs_and_crlf_as_rows_of_readings(tmp_path):
    values = np.array([[1.5, -2.25], [0.0, 99.0]])
    raw = read_grad601(write_grad601(tmp_path / "r.dat", values))
    assert raw.dtype == np.float64 and raw.shape == (2, 2)
    np.testing.assert_array_equal(raw, values)


def test_a_ragged_file_is_refused_with_its_row(tmp_path):
    p = tmp_path / "r.dat"
    p.write_bytes(b"1.00\t2.00\r\n3.00\r\n")
    with pytest.raises(MagFileError, match=r"r\.dat: row 2 has 1 readings but row 1 has 2"):
        read_grad601(p)


def test_a_non_number_is_refused_with_its_row(tmp_path):
    p = tmp_path / "r.dat"
    p.write_text("1.00\tx\r\n")
    with pytest.raises(MagFileError, match=r"row 1 holds 'x', which is not a number"):
        read_grad601(p)


def test_an_empty_file_is_refused(tmp_path):
    p = tmp_path / "r.dat"
    p.write_text("")
    with pytest.raises(MagFileError, match=r"r\.dat holds no readings"):
        read_grad601(p)


def test_runs_of_four_zeros_are_missing_and_shorter_runs_are_readings():
    raw = np.array([[1, 0, 0, 2, 0, 0, 0, 0, 3, 0, 0, 0]], float)
    np.testing.assert_array_equal(mark_missing(raw), [[1, 0, 0, 2, nan, nan, nan, nan, 3, 0, 0, 0]])
    assert np.isnan(mark_missing(raw, min_run=3)[0, 9:]).all()
    assert (raw == 0).sum() == 9  # the input is not changed


def test_missing_summary_names_the_traverses():
    a = np.ones((6, 8))
    a[1, :5] = nan
    a[4, :5] = nan
    assert missing_summary(a) == "10 readings are missing data, on traverses 2 and 5."
    assert missing_summary(np.ones((3, 3))) == "No readings are missing data."
    b = np.ones((9, 3))
    b[:, 0] = nan
    assert missing_summary(b) == (
        "9 readings are missing data, on traverses 1, 2, 3, 4, 5, 6 and 3 more."
    )


def test_missing_summary_singular_and_three():
    a = np.ones((3, 3))
    a[2, 1] = nan
    assert missing_summary(a) == "1 reading is missing data, on traverse 3."
    a[0, 0] = nan
    a[1, 0] = nan
    assert missing_summary(a) == "3 readings are missing data, on traverses 1, 2 and 3."
