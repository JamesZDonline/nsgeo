"""Cuts in the session (cut spec §4.2): add, rename, remove, and the velocity a cut uses."""

from __future__ import annotations

import dataclasses

import pytest
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model import is_cut_key
from nsgeo.model.survey import Line
from nsgeo.velocity import VelocityModel
from nsgeo_qgis.session import SiteSession
from plugin_testing import synthetic_dzt
from test_plugin_session import GRID, GRID_B, Spy, _lines, _two_grids

V = [(1.0, 1.0), (6.0, 1.0)]


@pytest.fixture
def session(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    return s


def test_add_cut_names_marks_dirty_and_announces(session):
    session.add_grid(GRID)
    session._set_dirty(False)
    changed = Spy(session.cuts_changed)
    first = session.add_cut("A", V)
    assert is_cut_key(first)
    assert session.cut_for_key(first).name == "Cut 1"
    assert session.dirty
    assert len(changed.calls) == 1
    second = session.add_cut("A", V)
    assert session.cut_for_key(second).name == "Cut 2"
    session.remove_cut(first)
    third = session.add_cut("A", V)
    assert session.cut_for_key(third).name == "Cut 3"
    assert len(changed.calls) == 4
    assert session.cut_keys() == [second, third]
    assert session.cut_keys_on_grid("A") == [second, third]


def test_add_cut_refuses_an_unknown_grid_and_too_few_points(session):
    session.add_grid(GRID)
    changed = Spy(session.cuts_changed)
    with pytest.raises(KeyError):
        session.add_cut("nope", V)
    with pytest.raises(ValueError):
        session.add_cut("A", [(1.0, 1.0), (1.0, 1.0)])
    assert session.cut_keys() == [] and changed.calls == []


def test_rename_keeps_the_key_and_refuses_an_empty_name(session):
    session.add_grid(GRID)
    key = session.add_cut("A", V)
    changed = Spy(session.cuts_changed)
    session._set_dirty(False)
    session.rename_cut(key, "  Lower line ")
    assert session.dirty  # a rename is an edit the site must save
    assert session.cut_for_key(key).name == "Lower line"
    assert session.cut_keys() == [key]
    assert len(changed.calls) == 1
    with pytest.raises(ValueError):
        session.rename_cut(key, "   ")
    assert session.cut_for_key(key).name == "Lower line"
    with pytest.raises(KeyError):
        session.cut_for_key("cut:nope")


def test_remove_cut_marks_the_site_dirty(session):
    session.add_grid(GRID)
    key = session.add_cut("A", V)
    session._set_dirty(False)
    session.remove_cut(key)
    assert session.dirty and session.cut_keys() == []


def test_remove_grid_drops_its_cuts_and_keeps_the_others(session):
    session.add_grid(GRID)
    session.add_grid(GRID_B)
    on_a = session.add_cut("A", V)
    on_b = session.add_cut("B", V)
    order = []
    session.grids_changed.connect(lambda: order.append("grids"))
    session.cuts_changed.connect(lambda: order.append("cuts"))
    session.remove_grid("A")
    assert session.cut_keys() == [on_b]
    assert order == ["grids", "cuts"]
    with pytest.raises(KeyError):
        session.cut_for_key(on_a)
    session.save()  # validates: a cut on a removed grid would refuse it


def test_cut_velocity_is_the_grids_then_the_first_lines_header(session, tmp_path):
    session.add_grid(GRID)
    model = VelocityModel.constant(0.09)
    session.set_grid_velocity("A", model)
    assert session.cut_velocity("A") == model
    session.set_grid_velocity("A", None)
    with pytest.raises(KeyError):
        session.cut_velocity("A")
    session.add_lines(_lines(tmp_path, 3))
    keys = session.keys_on_grid("A")
    header = VelocityModel.from_dielectric(14.0)  # synthetic_dzt's rhf_epsr
    assert session.cut_velocity("A") == header
    # A line override never moves a cut (spec call 16): not the second line's,
    # and not the first's either.
    session.set_line_velocity(keys[1], VelocityModel.constant(0.05))
    session.set_line_velocity(keys[0], VelocityModel.constant(0.07))
    assert session.cut_velocity("A") == header
    with pytest.raises(KeyError):
        session.cut_velocity("nope")


def test_cut_velocity_takes_the_first_lines_header_when_dielectrics_differ(session, tmp_path):
    session.add_grid(GRID)
    lines = []
    for i, epsr in enumerate((9.0, 25.0)):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", epsr=epsr)
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5, 0.0, 1, p.stem)))
    session.add_lines(lines)
    assert session.cut_velocity("A") == VelocityModel.from_dielectric(9.0)
    assert session.cut_velocity("A") != VelocityModel.from_dielectric(25.0)


def test_cuts_survive_save_and_reopen(session, tmp_path):
    session.add_grid(GRID)
    key = session.add_cut("A", [(1.0, 1.0), (6.0, 2.0), (7.0, 4.0)])
    session.rename_cut(key, "Ditch")
    session.save()
    other = SiteSession()
    other.open_site(session.json_path)
    assert other.cut_keys() == [key]
    got = other.cut_for_key(key)
    assert got == session.cut_for_key(key)
    assert got.name == "Ditch"
    assert not other.dirty


def test_keys_stay_lines_only(session, tmp_path):
    _two_grids(session, tmp_path)
    cut = session.add_cut("A", V)
    assert cut not in session.keys()  # noqa: SIM118 -- SiteSession.keys(), not a dict
    assert not any(is_cut_key(k) for k in session.keys())  # noqa: SIM118
    assert dataclasses.is_dataclass(session.cut_for_key(cut))


def test_open_preview_trace_and_selection_accept_cut_keys(session):
    session.add_grid(GRID)
    key = session.add_cut("A", V)
    opened = Spy(session.line_opened)
    previews = Spy(session.preview_changed)
    session.set_preview(key, 7)
    assert previews.calls == [(key, 7)]
    session.open_line(key)
    assert opened.calls == [(key,)]
    assert session.current_key == key
    session.set_trace(
        key, 10_000
    )  # no upper clamp: the column count is the section's (plan call 4)
    assert session.current_trace == 10_000
    session.set_trace(key, -5)
    assert session.current_trace == -1
    session.set_selection(key, 12, 3)
    assert session.selection == (3, 12)


def test_resolved_velocity_of_a_cut_is_its_grids(session, tmp_path):
    session.add_grid(GRID)
    model = VelocityModel.constant(0.09)
    session.set_grid_velocity("A", model)
    key = session.add_cut("A", V)
    assert session.resolved_velocity(key) == model == session.cut_velocity("A")


def test_removing_the_working_or_previewed_cut_clears_it(session):
    session.add_grid(GRID)
    key = session.add_cut("A", V)
    other = session.add_cut("A", V)
    session.open_line(key)
    opened = Spy(session.line_opened)
    session.remove_cut(other)  # an unrelated cut leaves the working one alone
    assert session.current_key == key and opened.calls == []
    session.remove_cut(key)
    assert session.current_key is None
    assert opened.calls == [("",)]
    previewed = session.add_cut("A", V)
    session.set_preview(previewed, 3)
    previews = Spy(session.preview_changed)
    session.remove_cut(previewed)
    assert session.preview_key is None
    assert previews.calls == [("", -1)]


def test_removing_a_grid_clears_a_working_cut_on_it(session):
    session.add_grid(GRID)
    key = session.add_cut("A", V)
    session.open_line(key)
    opened = Spy(session.line_opened)
    session.remove_grid("A")
    assert session.current_key is None
    assert opened.calls == [("",)]


@pytest.mark.parametrize("working_is_cut", [True, False])
def test_removing_a_grid_announces_the_dropped_items_in_one_order(
    session, tmp_path, message_log, working_is_cut
):
    """`line_opened("")` before `preview_changed("")`, whichever kind each is (the
    profile asks for a key that is already gone otherwise)."""
    from nsgeo_qgis.ui.profile_dock import ProfileDock

    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 3))
    line = session.keys()[0]
    cut = session.add_cut("A", V)
    dock = ProfileDock(session)
    try:
        working, previewed = (cut, line) if working_is_cut else (line, cut)
        session.open_line(working)
        session.set_preview(previewed, 2)
        order = []
        session.line_opened.connect(lambda k: order.append(("opened", k)))
        session.preview_changed.connect(lambda k, t: order.append(("preview", k)))
        session.remove_grid("A", with_lines=True)
        assert order == [("opened", ""), ("preview", "")]
        assert session.current_key is None and session.preview_key is None
        assert not [m for m in message_log if "could not" in m]
    finally:
        dock.hide()
        dock.deleteLater()


def test_line_zero_of_a_cut_is_none_and_logs_nothing(session, message_log):
    """A cut has no zero of its own: its times are on its cube's clock (cut spec call 18)."""
    session.add_grid(GRID)
    key = session.add_cut("A", V)
    assert session.line_zero(key) is None
    assert session.line_zero(key, load=True) is None
    assert not [m for m in message_log if "time zero" in m or key in m], message_log
