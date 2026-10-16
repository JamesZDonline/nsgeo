"""The figures subpackage. Runs under .venv-qgis only, where matplotlib lives."""

from __future__ import annotations

from dataclasses import replace

import pytest

pytest.importorskip("matplotlib")

from help_tools.figures import common, make_figures, recipes  # noqa: E402
from help_tools.figures import dewow as dewow_recipe  # noqa: E402
from help_tools.figures.common import antenna_mhz  # noqa: E402
from nsgeo.io.dzt import read_header  # noqa: E402
from nsgeo.processing import available_steps, build_step  # noqa: E402
from plugin_testing import synthetic_dzt  # noqa: E402


@pytest.fixture(scope="module")
def header(tmp_path_factory):
    return read_header(synthetic_dzt(tmp_path_factory.mktemp("hdr"), "H.DZT"))


def test_dewow_measure_matches_the_design_measurements():  # spec section 8, campus dt
    rows = {r["window_ns"]: r for r in dewow_recipe.measure(0.21653111279010773)}
    assert rows[4.0]["samples"] == 18 and rows[4.0]["used_ns"] == pytest.approx(3.898, abs=1e-3)
    assert rows[4.0]["half_power_mhz"] == pytest.approx(193, abs=4)
    assert rows[4.0]["peak_gain"] == pytest.approx(1.214, abs=0.01)
    assert rows[4.0]["peak_mhz"] == pytest.approx(366, abs=6)
    assert rows[2.0]["samples"] == 9 and rows[8.0]["samples"] == 37


def test_make_figures_writes_three_pngs_for_dewow(tmp_path):
    dzt = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    paths = make_figures(dzt, tmp_path / "img", ["dewow"])
    assert sorted(p.name for p in paths) == [
        "dewow_panels.png",
        "dewow_response.png",
        "dewow_trace.png",
    ]
    assert all(p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" for p in paths)
    assert {p.parent for p in paths} == {tmp_path / "img"}


def test_unknown_step_is_refused(tmp_path):
    with pytest.raises(KeyError, match="time_zero"):
        make_figures(synthetic_dzt(tmp_path, "F.DZT"), tmp_path, ["time_zero"])


def test_recipes_are_discovered_and_named_for_registered_steps():
    found = recipes()
    assert "dewow" in found and "common" not in found
    assert set(found) <= set(available_steps())


def test_antenna_mhz(header):
    assert antenna_mhz(replace(header, antenna="HS350US")) == 350
    assert antenna_mhz(replace(header, antenna="")) is None


def test_saved_figures_are_palette_pngs(tmp_path):
    from PIL import Image

    rg, hdr = common.load_radargram(synthetic_dzt(tmp_path / "raw", "P.DZT"))
    stack = common.stack_of(rg, [build_step("dewow")])
    out = common.panels(stack, 0, tmp_path / "p.png", "After", "Removed", hdr)
    with Image.open(out) as im:
        assert im.format == "PNG" and im.mode in ("P", "L")


def test_panels_full_depth_when_t_max_is_none(tmp_path):
    rg, hdr = common.load_radargram(synthetic_dzt(tmp_path / "raw", "T.DZT"))
    stack = common.stack_of(rg, [build_step("dewow")])
    out = common.panels(stack, 0, tmp_path / "p.png", "A", "R", hdr, t_max_ns=None)
    assert out.is_file()


def test_response_is_a_real_magnitude():
    # A complex spectrum (no abs) compares and argmaxes lexicographically, which can
    # still land near the right numbers; the magnitude must be real and non-negative.
    f, h = dewow_recipe._response(0.21653111279010773, 4.0)
    assert h.dtype.kind == "f" and (h >= 0).all() and f.shape == h.shape
