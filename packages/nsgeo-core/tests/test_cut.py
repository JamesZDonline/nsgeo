"""A cut: a drawn path on a grid, in grid metres (cut spec §3)."""

from __future__ import annotations

import pytest
from nsgeo.model import CUT_KEY_PREFIX, Cut, cut_key, is_cut_key

L_SHAPE = [(0.0, 0.0), (3.0, 0.0), (3.0, 4.0)]


def make():
    return Cut.new("A", L_SHAPE, "Cut 1")


def test_length_and_point_at_follow_the_drawn_order():
    cut = make()
    assert cut.length_m == pytest.approx(7.0)
    assert cut.point_at(5.0) == pytest.approx((3.0, 2.0))
    assert cut.point_at(-1.0) == (0.0, 0.0)
    assert cut.point_at(99.0) == (3.0, 4.0)


def test_locate_projects_onto_the_nearest_segment():
    d, off = make().locate((4.0, 2.0))
    assert d == pytest.approx(5.0, abs=1e-12)
    assert off == pytest.approx(1.0, abs=1e-12)


def test_new_drops_consecutive_duplicates_and_refuses_too_few():
    cut = Cut.new("A", [(0, 0), (0, 0), (1, 0)], "Cut 1")
    assert cut.vertices == ((0, 0), (1, 0))
    for bad in ([(1, 1)], [(1, 1), (1, 1)], [(0, 0), (float("nan"), 1)]):
        with pytest.raises(ValueError):
            Cut.new("A", bad, "Cut 1")


def test_keys_are_prefixed_and_never_a_dzt_path():
    cut = make()
    assert CUT_KEY_PREFIX == "cut:"
    assert cut.key == "cut:" + cut.id == cut_key(cut.id)
    assert len(cut.id) == 32
    assert is_cut_key(cut.key)
    assert not is_cut_key("raw/FILE__001.DZT")
    assert make().id != cut.id


def test_a_cut_needs_a_name_and_an_id():
    with pytest.raises(ValueError):
        Cut(id="", name="x", grid_id="A", vertices=((0.0, 0.0), (1.0, 0.0)))
    with pytest.raises(ValueError):
        Cut(id="x", name="", grid_id="A", vertices=((0.0, 0.0), (1.0, 0.0)))
