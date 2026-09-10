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


def test_load_site_reports_an_invalid_stack_as_project_error(tmp_path):
    dzt = tmp_path / "L0.DZT"
    write_dzt(dzt, np.zeros((512, 20), dtype=np.int32))
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
                "stack": [{"step": "gain_curve", "params": {"points": [[0.0, 0.0]]}}],
            }
        ],
    }
    (tmp_path / "survey.nsgeo.json").write_text(json.dumps(doc))
    with pytest.raises(ProjectError, match="L0.DZT"):
        load_site(tmp_path / "survey.nsgeo.json")
