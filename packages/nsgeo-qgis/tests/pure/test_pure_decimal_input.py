from __future__ import annotations

import pytest
from nsgeo_qgis.decimal_input import parse_decimal


def test_parse_decimal_reads_a_point_and_refuses_a_comma_nan_and_inf():
    assert parse_decimal("1.5") == 1.5
    assert parse_decimal(" 2 ") == 2.0
    for bad in ["1,000", "1,5", "nan", "inf", "-inf", ""]:
        with pytest.raises(ValueError):
            parse_decimal(bad)
