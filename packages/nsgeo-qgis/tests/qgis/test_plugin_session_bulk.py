"""The session's bulk methods (#58): one change for many lines, every key checked first."""

from __future__ import annotations

import pytest
from nsgeo.processing import build_step
from nsgeo.velocity import VelocityModel
from nsgeo.velocity_fit import StoredFit
from nsgeo.velocity_source import SourceFit, VelocitySource
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.preset_box import migration_note
from test_plugin_session import Spy, _two_grids

A = [f"raw/FILE__00{i}.DZT" for i in (1, 2, 3)]
B = ["raw/FILE__004.DZT"]
MODEL = VelocityModel.constant(0.095)


@pytest.fixture
def session(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    _two_grids(s, tmp_path)
    s.append_step(A[0], build_step("migrate_fk", velocity_m_ns=0.1))
    s.save_preset("Migrate", A[0])
    s.remove_step(A[0], 0)
    s.append_step(A[0], build_step("dewow", window_ns=10.0))
    s.save_preset("Plain", A[0])
    s.save()
    return s


def test_apply_preset_to_replaces_only_the_named_lines(session):
    others = {k: session.stack_for(k) for k in (A[2], B[0])}
    changed = session.apply_preset_to("Migrate", [A[0], A[1]])
    assert changed == [A[0], A[1]]
    for k in (A[0], A[1]):
        assert session.stack_for(k).to_dicts() == session.site.presets["Migrate"]
    for k, stack in others.items():
        assert session.stack_for(k) is stack
    assert session.dirty


def test_apply_preset_to_emits_stack_changed_per_key(session):
    spy = Spy(session.stack_changed)
    session.apply_preset_to("Plain", [A[1], B[0]])
    assert [c[0] for c in spy.calls] == [A[1], B[0]]


def test_apply_preset_to_checks_every_key_first(session):
    before = {k: session.stack_for(k) for k in A + B}
    with pytest.raises(KeyError):
        session.apply_preset_to("Plain", [A[1], "raw/NOPE.DZT"])
    with pytest.raises(KeyError):
        session.apply_preset_to("No such preset", [A[1]])
    for k, stack in before.items():
        assert session.stack_for(k) is stack
    assert not session.dirty


def test_apply_stack_to_skips_the_source_and_copies_to_the_rest(session):
    source = session.stack_for(A[0])
    changed = session.apply_stack_to(A[0], [A[0], A[1], B[0]])
    assert changed == [A[1], B[0]]
    assert session.stack_for(A[0]) is source
    for k in changed:
        assert session.stack_for(k).to_dicts() == source.to_dicts()
        assert session.stack_for(k) is not source
    assert session.dirty


def test_apply_stack_to_checks_every_key_first(session):
    before = session.stack_for(A[1])
    with pytest.raises(KeyError):
        session.apply_stack_to(A[0], [A[1], "raw/NOPE.DZT"])
    with pytest.raises(KeyError):
        session.apply_stack_to("raw/NOPE.DZT", [A[1]])
    assert session.stack_for(A[1]) is before
    assert not session.dirty


def _fit() -> StoredFit:
    return StoredFit(30.0, 0.09, 0.003, 0.2, 30, ((30, 30.0), (15, 31.0)), "t")


def test_set_lines_velocity_is_one_change_and_keeps_fits(session):
    fit_id = session.add_velocity_fit(A[0], _fit())
    member = SourceFit.of(A[0], fit_id, "FILE__001", _fit())
    session.apply_line_velocity(
        A[0], VelocityModel.constant(0.09), VelocitySource.from_fits([member], None)
    )
    session.set_line_velocity(A[2], MODEL)  # already at the model, no record
    session.save()
    spy = Spy(session.lines_changed)
    changed = session.set_lines_velocity(A, MODEL)
    assert len(spy.calls) == 1
    assert changed == [A[0], A[1]]
    for k in A:
        line = session.line_for_key(k)
        assert line.velocity == MODEL and line.velocity_source is None
    assert set(session.line_for_key(A[0]).velocity_fits) == {fit_id}
    assert session.dirty


def test_set_lines_velocity_checks_every_key_first(session):
    with pytest.raises(KeyError):
        session.set_lines_velocity([A[0], "raw/NOPE.DZT"], MODEL)
    assert session.line_for_key(A[0]).velocity is None
    assert not session.dirty


def test_set_lines_velocity_none_clears_and_is_silent_when_nothing_changes(session):
    spy = Spy(session.lines_changed)
    assert session.set_lines_velocity(A, None) == []
    assert spy.calls == [] and not session.dirty
    session.set_line_velocity(A[1], MODEL)
    spy.calls.clear()
    assert session.set_lines_velocity(A, None) == [A[1]]
    assert len(spy.calls) == 1
    assert session.line_for_key(A[1]).velocity is None


def test_migration_note_reads_the_first_enabled_migration_step():
    dicts = [
        {"step": "dewow", "params": {"window_ns": 10.0}, "enabled": True},
        {"step": "migrate_fk", "params": {"velocity_m_ns": 0.1}, "enabled": True},
        {"step": "migrate_fk", "params": {"velocity_m_ns": 0.2}, "enabled": True},
    ]
    assert migration_note(dicts, saved=False) == "Its Migration (Stolt f-k) step uses 0.100 m/ns."
    assert migration_note(dicts, saved=True) == (
        "Its Migration (Stolt f-k) step uses 0.100 m/ns, the velocity it was saved with."
    )
    disabled = [{"step": "migrate_fk", "params": {"velocity_m_ns": 0.1}, "enabled": False}]
    assert migration_note(disabled, saved=True) is None
    assert migration_note([], saved=False) is None
