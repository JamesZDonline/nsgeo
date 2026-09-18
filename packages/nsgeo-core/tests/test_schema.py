"""Every step declares a schema the UI can build widgets from.

The plugin must never name a step. It enumerates the registry, reads each
step's schema, and builds a form. These tests are what make that safe.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from nsgeo.processing import StepStack  # noqa: F401  (registers every step)
from nsgeo.processing.base import (
    REQUIRED,
    ParamSpec,
    Radargram,
    available_steps,
    build_step,
    default_params,
    get_step,
    required_params,
)
from nsgeo.project import ProjectError, load_site

from tests.synthetic import write_dzt


def _placeholder(spec: ParamSpec):
    """Any value acceptable to the constructor, so `params` can be compared."""
    if spec.kind == "float":
        return 1.0
    if spec.kind == "int":
        return 1
    if spec.kind == "choice":
        return spec.choices[0]
    return [[0.0, 0.0], [10.0, 0.0]]  # curve


@pytest.mark.parametrize("name", available_steps())
def test_schema_names_match_params_keys_in_order(name):
    specs = get_step(name).schema()
    assert all(isinstance(s, ParamSpec) for s in specs)
    step = build_step(name, **{s.name: _placeholder(s) for s in specs})
    assert list(step.params) == [s.name for s in specs]


@pytest.mark.parametrize("name", available_steps())
def test_non_required_defaults_build_and_apply(name):
    if required_params(name):
        pytest.skip(f"{name} has required parameters by design")
    rng = np.random.default_rng(0)
    rg = Radargram(data=rng.normal(size=(64, 32)), dt_ns=0.2, t0_ns=-11.0)
    out = build_step(name, **default_params(name)).apply(rg)
    assert isinstance(out, Radargram)


def test_only_the_two_known_steps_have_required_params():
    """Do not invent default passband frequencies; the identity curve is the
    front end's job. Nothing else may become required by accident."""
    req = {n: required_params(n) for n in available_steps() if required_params(n)}
    assert req == {"bandpass": ("low_mhz", "high_mhz"), "gain_curve": ("points",)}


@pytest.mark.parametrize("name", available_steps())
def test_defaults_respect_declared_bounds_and_choices(name):
    for s in get_step(name).schema():
        if s.required:
            continue
        if s.kind == "choice":
            assert s.default in s.choices
        if s.kind in ("float", "int"):
            if s.min is not None:
                assert s.default >= s.min
            if s.max is not None:
                assert s.default <= s.max


def test_choice_kind_requires_choices_and_others_forbid_them():
    with pytest.raises(ValueError, match="choices"):
        ParamSpec(name="mode", kind="choice", label="Mode", default="a")
    with pytest.raises(ValueError, match="choices"):
        ParamSpec(name="w", kind="float", label="W", default=1.0, choices=("a",))


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="kind"):
        ParamSpec(name="x", kind="string", label="X", default="")


def test_required_sentinel_is_recognisable():
    spec = ParamSpec(name="low_mhz", kind="float", label="Low", default=REQUIRED)
    assert spec.required
    assert repr(REQUIRED) == "REQUIRED"
    assert not ParamSpec(name="w", kind="float", label="W", default=1.0).required


def test_default_params_omits_required_ones():
    assert set(default_params("bandpass")) == {"taper_frac"}
    assert default_params("gain_curve") == {}
    assert default_params("background_mean") == {}


def test_gain_curve_rejects_fewer_than_two_points_at_construction():
    with pytest.raises(ValueError, match="two"):
        build_step("gain_curve", points=[[0.0, 0.0]])


def test_gain_curve_rejects_non_finite_points_at_construction():
    with pytest.raises(ValueError, match="finite"):
        build_step("gain_curve", points=[[0.0, 0.0], [10.0, float("nan")]])


def _write_project_with_stack(tmp_path, stack):
    """A one-line survey file whose only line carries `stack`."""
    write_dzt(tmp_path / "L0.DZT", np.zeros((512, 20), dtype=np.int32))
    doc = {
        "schema_version": 1,
        "grids": [
            {
                "id": "G",
                "origin": [0.0, 0.0],
                "azimuth": 0.0,
                "size_x": 10.0,
                "size_y": 10.0,
                "crs": "EPSG:32616",
                "default_spacing": 0.5,
            }
        ],
        "lines": [
            {
                "path": "L0.DZT",
                "placement": {"type": "grid", "grid_id": "G", "axis": "y", "offset": 0.0},
                "stack": stack,
            }
        ],
    }
    path = tmp_path / "survey.nsgeo.json"
    path.write_text(json.dumps(doc))
    return path


def test_load_site_reports_an_invalid_stack_as_project_error(tmp_path):
    path = _write_project_with_stack(
        tmp_path, [{"step": "gain_curve", "params": {"points": [[0.0, 0.0]]}}]
    )
    with pytest.raises(ProjectError, match="L0.DZT"):
        load_site(path)


def test_an_unknown_parameter_name_is_refused_rather_than_ignored(tmp_path):
    """A typo in a hand-edited project file, or a parameter renamed between
    versions. Passed through to the constructor it was a TypeError nobody
    caught by name; silently dropped it would apply a step the file does
    not describe. `build_step` is the funnel both the UI and
    `StepStack.from_dicts` come through, so one check covers both."""
    with pytest.raises(ValueError, match="windows_ns"):
        build_step("dewow", windows_ns=4.0)
    path = _write_project_with_stack(tmp_path, [{"step": "dewow", "params": {"windows_ns": 4.0}}])
    with pytest.raises(ProjectError, match="L0.DZT"):
        load_site(path)


def test_a_missing_required_parameter_is_refused_by_name():
    with pytest.raises(ValueError, match="high_mhz"):
        build_step("bandpass", low_mhz=100.0)


_BOUNDED = [
    (name, spec)
    for name in available_steps()
    for spec in get_step(name).schema()
    if spec.kind in ("float", "int") and (spec.min, spec.max) != (None, None)
]


def test_the_registry_declares_the_bounds_these_tests_cover():
    """Keeps the parametrisation below from silently covering nothing, and
    makes a newly bounded (or newly unbounded) parameter a visible edit."""
    assert {f"{name}.{spec.name}" for name, spec in _BOUNDED} == {
        "background_sliding.window_traces",
        "background_svd.n_components",
        "bandpass.low_mhz",
        "bandpass.high_mhz",
        "bandpass.taper_frac",
        "dewow.window_ns",
        "gain_agc.window_ns",
        "gain_agc.target",
        "gain_agc.eps",
        "time_zero.sample",
        "time_zero.threshold",
    }


@pytest.mark.parametrize("name, spec", _BOUNDED, ids=[f"{n}.{s.name}" for n, s in _BOUNDED])
def test_every_declared_bound_is_enforced_by_build_step(name, spec):
    """Every bound a step declares must actually be enforced somewhere.

    The plugin's parameter form reads neither `spec.min` nor `spec.max` --
    its own docstring says the core's validation is the only validation --
    so if the core does not check them, nothing does. Driven off the
    registry rather than a hand-written list, so a step added later cannot
    declare a bound that quietly goes unenforced.
    """
    specs = get_step(name).schema()
    for edge, bound in ((spec.min, "min"), (spec.max, "max")):
        if edge is None:
            continue
        params = {s.name: _placeholder(s) for s in specs}
        params[spec.name] = edge - 1 if bound == "min" else edge + 1
        with pytest.raises(ValueError, match=spec.name):
            build_step(name, **params)
        params[spec.name] = edge  # the bound itself is allowed
        build_step(name, **params)


def test_the_two_bound_breaches_that_corrupt_a_radargram_silently():
    """Both were verified to build and run without raising.

    `gain_agc(target=-3.0)` -- the schema says min 0.0 -- multiplies every
    sample by a negative number, inverting the polarity of the whole
    radargram, which is a misinterpretation rather than a cosmetic
    problem. `time_zero(threshold=5.0)` -- the schema says max 1.0 -- makes
    the first-break pick match nothing, so the correction appears applied
    and does nothing at all. Neither announced itself.
    """
    with pytest.raises(ValueError, match="target"):
        build_step("gain_agc", target=-3.0)
    with pytest.raises(ValueError, match="threshold"):
        build_step("time_zero", threshold=5.0)
    # Both still build at a legitimate value: the guard is a bound, not a ban.
    assert build_step("gain_agc", target=3.0).params["target"] == 3.0
    assert build_step("time_zero", threshold=0.5).params["threshold"] == 0.5


def test_gain_curve_refuses_a_db_runaway_and_keeps_real_gains(tmp_path):
    """`GainCurve.apply` is `10 ** (db / 20)`, which overflows every sample
    to `inf` once dB reaches the thousands -- and the plugin's percentile
    clip then renders that as a fully saturated radargram presented as a
    result. The drag runaway this branch fixed (over 1,000,000 dB) was
    fixed in the gain strip's own clamp only, so any project file written
    by an earlier commit still holds it and reproduces on load.
    """
    with pytest.raises(ValueError, match="points"):
        build_step("gain_curve", points=[[0.0, 0.0], [20.0, 1616316.7]])
    with pytest.raises(ValueError, match="points"):
        build_step("gain_curve", points=[[0.0, -400.0], [20.0, 0.0]])
    # A real, generous gain is untouched: 30 dB is a factor of ~32.
    assert build_step("gain_curve", points=[[0.0, 0.0], [20.0, 30.0]]).points[1][1] == 30.0

    path = _write_project_with_stack(
        tmp_path,
        [{"step": "gain_curve", "params": {"points": [[0.0, 0.0], [20.0, 1616316.7]]}}],
    )
    with pytest.raises(ProjectError, match="L0.DZT"):
        load_site(path)
