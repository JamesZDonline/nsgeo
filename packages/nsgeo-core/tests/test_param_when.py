"""Parameters that belong to a mode (`ParamSpec.when`) and the `row` kind."""

from __future__ import annotations

import pytest
from nsgeo.processing import build_step, param_visible
from nsgeo.processing.base import _REGISTRY, ParamSpec, param_problem, register
from nsgeo.processing.timezero import TimeZero


def test_a_row_param_is_validated_like_an_int():
    spec = ParamSpec("sample", "row", "Sample", 0, min=0)
    assert param_problem(spec, 3) is None
    assert param_problem(spec, 3.0) == "must be a whole number"
    assert param_problem(spec, True) == "must be a whole number"
    assert param_problem(spec, -1) is not None


def test_param_visible_follows_its_mode():
    s = {spec.name: spec for spec in TimeZero.schema()}
    assert param_visible(s["sample"], {"mode": "sample"})
    assert not param_visible(s["sample"], {"mode": "first_break"})
    assert param_visible(s["threshold"], {"mode": "first_break"})
    assert not param_visible(s["threshold"], {"mode": "sample"})
    assert param_visible(s["mode"], {"mode": "sample"})


def _step_class(name: str, when):
    class Throwaway:
        title = "Throwaway"
        group = "Time"
        order = 99

        def __init__(self, mode="a", x=0.0):
            self.mode, self.x = mode, x

        @property
        def params(self):
            return {"mode": self.mode, "x": self.x}

        @classmethod
        def schema(cls):
            return (
                ParamSpec("mode", "choice", "Mode", "a", choices=("a", "b")),
                ParamSpec("x", "float", "X", 0.0, when=when),
            )

    Throwaway.name = name
    return Throwaway


@pytest.mark.parametrize(
    "when",
    [("nope", ("a",)), ("mode", ("a", "zzz")), ("x", ("a",))],
    ids=["no such sibling", "unknown value", "sibling not a choice"],
)
def test_register_refuses_a_when_that_names_no_choice(when):
    name = "throwaway_when_bad"
    try:
        with pytest.raises(ValueError, match=rf"{name}.*'x'"):
            register(_step_class(name, when))
    finally:
        _REGISTRY.pop(name, None)


def test_register_accepts_a_good_when():
    name = "throwaway_when_good"
    try:
        register(_step_class(name, ("mode", ("b",))))
    finally:
        _REGISTRY.pop(name, None)


def test_a_saved_time_zero_and_gain_load_unchanged():
    tz = build_step("time_zero", mode="sample", sample=44, threshold=0.3)
    assert tz.params == {"mode": "sample", "sample": 44, "threshold": 0.3}
    g = build_step("gain_parametric", mode="power", alpha=0.07, exponent=2.0)
    assert g.params["alpha"] == 0.07 and g.params["exponent"] == 2.0


def test_first_break_row_or_none_tells_no_signal_from_row_zero():
    import numpy as np
    from nsgeo.processing import Radargram, first_break_row_or_none

    data = np.zeros((20, 4))
    assert first_break_row_or_none(Radargram(data=data, dt_ns=0.2, t0_ns=0.0)) is None
    data[7:, :] = 1.0
    assert first_break_row_or_none(Radargram(data=data, dt_ns=0.2, t0_ns=0.0)) == 7
