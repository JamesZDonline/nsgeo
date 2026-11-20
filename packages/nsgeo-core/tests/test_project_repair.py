"""A project holding a setting the rules refuse still opens (step-edges Task 4)."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.processing import StepStack, build_step
from nsgeo.processing.base import Radargram, get_step
from nsgeo.project import ProjectError, load_site, save_site

from tests.test_schema import _write_project_with_stack


def _load(tmp_path, stack):
    return load_site(_write_project_with_stack(tmp_path, stack))


def _only(site):
    return site.stacks["L0.DZT"].entries


def test_a_refused_setting_turns_the_step_off(tmp_path):
    site = _load(tmp_path, [{"step": "gain_agc", "params": {"eps": 0.0}}])
    step, enabled = _only(site)[0]
    assert enabled is False
    assert step.eps == 1e-12
    assert site.load_notes == [
        "Line L0.DZT (grid G): Automatic gain control is turned off. Its Epsilon was 0.0, "
        "which must be > 0.0; it is now 1e-12. Check the step and turn it back on."
    ]


def test_a_refused_preset_setting_is_stored_repaired(tmp_path):
    site = _load(tmp_path, [])
    site.presets["p"] = [{"step": "background_sliding", "params": {"window_traces": 1}}]
    out = tmp_path / "again.nsgeo.json"
    save_site(site, out)
    back = load_site(out)
    entry = back.presets["p"][0]
    assert entry["enabled"] is False
    assert entry["params"]["window_traces"] == 200
    assert back.load_notes[0].startswith("Preset 'p': ")
    stack = StepStack.from_dicts(back.presets["p"])
    stack.source = Radargram(
        data=np.random.default_rng(0).normal(size=(64, 300)), dt_ns=0.2, t0_ns=0.0
    )
    assert stack.result().data.shape == (64, 300)


def test_a_repaired_project_saves_clean(tmp_path):
    site = _load(tmp_path, [{"step": "gain_agc", "params": {"eps": 0.0}}])
    out = tmp_path / "saved.nsgeo.json"
    save_site(site, out)
    back = load_site(out)
    assert _only(back)[0][1] is False
    assert back.load_notes == []


def test_two_refused_settings_make_one_note(tmp_path):
    site = _load(tmp_path, [{"step": "gain_parametric", "params": {"mode": "bogus", "alpha": 8.0}}])
    step, enabled = _only(site)[0]
    assert (step.mode, step.alpha, enabled) == ("exponential", 0.05, False)
    assert len(site.load_notes) == 1
    assert "Its Mode was 'bogus'" in site.load_notes[0]
    assert "Its Alpha was 8.0" in site.load_notes[0]
    assert site.load_notes[0].count("Check the step") == 1


def test_time_zero_stays_on(tmp_path):
    site = _load(tmp_path, [{"step": "time_zero", "params": {"sample": 12.0}}])
    step, enabled = _only(site)[0]
    assert enabled is True
    assert step.sample == 0
    assert site.load_notes == [
        "Line L0.DZT (grid G): Time zero's Sample was 12.0, which must be a whole number; "
        "it is now 0. The step stays on, because turning Time zero off would move "
        "every time after it."
    ]


def test_a_refused_setting_with_no_default_removes_the_step(tmp_path):
    site = _load(
        tmp_path,
        [{"step": "bandpass", "params": {"low_mhz": float("nan"), "high_mhz": 400.0}}],
    )
    assert _only(site) == []
    (note,) = site.load_notes
    assert note == (
        "Line L0.DZT (grid G): Bandpass is removed. Its Low was nan, which must be "
        "a finite number, and Low has no default. It also held High 400.0. "
        "Add it again with the settings you want."
    )


def test_a_missing_required_setting_removes_the_step(tmp_path):
    site = _load(tmp_path, [{"step": "bandpass", "params": {"low_mhz": 100.0}}])
    assert _only(site) == []
    (note,) = site.load_notes
    assert note.startswith("Line L0.DZT (grid G): Bandpass is removed. It has no ")
    assert "which it needs" in note


def test_a_good_step_beside_a_bad_one_is_kept(tmp_path):
    site = _load(
        tmp_path,
        [
            {"step": "dewow", "params": {}},
            {"step": "gain_curve", "params": {"points": [[0.0, 0.0]]}},
        ],
    )
    assert [type(s).__name__ for s, _ in _only(site)] == ["Dewow"]


@pytest.mark.parametrize(
    "stack",
    [
        [{"step": "no_such_step", "params": {}}],
        [{"step": "dewow", "params": {"windows_ns": 4.0}}],
        ["not an object"],
        [{"params": {}}],
        [{"step": "dewow", "params": [1]}],
    ],
)
def test_structural_faults_still_refuse_the_project(tmp_path, stack):
    with pytest.raises(ProjectError, match="L0.DZT"):
        _load(tmp_path, stack)


def test_a_constructor_refusal_the_check_does_not_know_removes_the_step(tmp_path, monkeypatch):
    cls = get_step("dewow")

    def refuse(self, **kwargs):
        raise ValueError("x")

    monkeypatch.setattr(cls, "__init__", refuse)
    site = _load(tmp_path, [{"step": "dewow", "params": {}}])
    assert _only(site) == []
    assert site.load_notes == [
        "Line L0.DZT (grid G): Dewow is removed. It could not be built: x. "
        "Add it again with the settings you want."
    ]


def test_a_constructor_refusal_lists_the_settings_the_step_held(tmp_path, monkeypatch):
    cls = get_step("bandpass")

    def refuse(self, **kwargs):
        raise ValueError("x")

    monkeypatch.setattr(cls, "__init__", refuse)
    site = _load(tmp_path, [{"step": "bandpass", "params": {"low_mhz": 100.0, "high_mhz": 600.0}}])
    assert site.load_notes == [
        "Line L0.DZT (grid G): Bandpass is removed. It could not be built: x. "
        "It held Low 100.0 and High 600.0. Add it again with the settings you want."
    ]


def test_a_bandpass_with_one_bad_setting_keeps_the_others_in_its_note(tmp_path):
    site = _load(
        tmp_path,
        [
            {
                "step": "bandpass",
                "params": {"low_mhz": float("nan"), "high_mhz": 600.0, "taper_frac": 0.3},
            }
        ],
    )
    (note,) = site.load_notes
    assert note == (
        "Line L0.DZT (grid G): Bandpass is removed. Its Low was nan, which must be "
        "a finite number, and Low has no default. It also held High 600.0 and Taper 0.3. "
        "Add it again with the settings you want."
    )


def test_a_reset_then_constructor_refusal_gives_exactly_one_note(tmp_path, monkeypatch):
    cls = get_step("gain_agc")

    def refuse(self, **kwargs):
        raise ValueError("x")

    monkeypatch.setattr(cls, "__init__", refuse)
    site = _load(tmp_path, [{"step": "gain_agc", "params": {"eps": 0.0}}])
    assert _only(site) == []
    assert len(site.load_notes) == 1
    assert site.load_notes == [
        "Line L0.DZT (grid G): Automatic gain control is removed. "
        "Its Epsilon was 0.0, which must be > 0.0; "
        "it is now 1e-12. It could not be built: x. It held Epsilon 0.0. "
        "Add it again with the settings you want."
    ]


def test_a_removed_step_names_every_refused_setting(tmp_path):
    site = _load(
        tmp_path,
        [
            {
                "step": "bandpass",
                "params": {"low_mhz": float("nan"), "high_mhz": float("inf"), "taper_frac": -1},
            }
        ],
    )
    assert _only(site) == []
    (note,) = site.load_notes
    assert "Its Low was nan" in note
    assert "Its High was inf" in note
    assert "Its Taper was -1" in note
    assert note.count("Add it again with the settings you want.") == 1


def test_a_removed_step_names_every_missing_setting(tmp_path):
    site = _load(tmp_path, [{"step": "bandpass", "params": {}}])
    (note,) = site.load_notes
    assert "It has no Low, which it needs." in note
    assert "It has no High, which it needs." in note


def test_an_already_off_time_zero_is_reset_without_claiming_it_stays_on(tmp_path):
    site = _load(tmp_path, [{"step": "time_zero", "params": {"sample": 12.0}, "enabled": False}])
    step, enabled = _only(site)[0]
    assert (enabled, step.sample) == (False, 0)
    (note,) = site.load_notes
    assert "stays on" not in note
    assert "turned off" not in note
    assert "Its Sample was 12.0" in note
    assert "already off" in note


def test_an_already_off_agc_is_reset_without_claiming_it_was_turned_off(tmp_path):
    site = _load(tmp_path, [{"step": "gain_agc", "params": {"eps": 0.0}, "enabled": False}])
    step, enabled = _only(site)[0]
    assert (enabled, step.eps) == (False, 1e-12)
    (note,) = site.load_notes
    assert "is turned off" not in note
    assert "already off) had a setting reset" in note
    assert "Its Epsilon was 0.0, which must be > 0.0; it is now 1e-12." in note


def test_build_step_still_works_for_a_clean_stack(tmp_path):
    site = _load(tmp_path, [{"step": "dewow", "params": {"window_ns": 6.0}}])
    assert site.load_notes == []
    assert _only(site)[0][0].window_ns == build_step("dewow", window_ns=6.0).window_ns
