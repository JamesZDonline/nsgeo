from __future__ import annotations

import json

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line, Site
from nsgeo.processing import StepStack, build_step
from nsgeo.project import ProjectError, load_site, save_site

from tests.synthetic import write_dzt


def _site(tmp_path):
    p = tmp_path / "L0.DZT"
    write_dzt(p, np.zeros((512, 20), dtype=np.int32))
    grid = Grid("G", (0.0, 0.0), 0.0, 10.0, 10.0, "EPSG:32616", 0.5)
    return Site(grids=[grid], lines=[Line.open(p, GridPlacement("G", "y", 0.0))])


def test_presets_round_trip_and_are_omitted_when_empty(tmp_path):
    site = _site(tmp_path)
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    assert "presets" not in out.read_text()
    stack = StepStack()
    stack.append(build_step("dewow", window_ns=6.0))
    stack.append(build_step("background_mean"))
    site.presets["campus"] = stack.to_dicts()
    save_site(site, out)
    back = load_site(out)
    assert back.presets == {"campus": stack.to_dicts()}
    assert StepStack.from_dicts(back.presets["campus"]).to_dicts() == stack.to_dicts()


def test_invalid_preset_is_a_project_error(tmp_path):
    site = _site(tmp_path)
    out = tmp_path / "survey.nsgeo.json"
    site.presets["bad"] = [{"step": "no_such_step", "params": {}}]
    save_site(site, out)
    with pytest.raises(ProjectError, match="bad"):
        load_site(out)


def test_malformed_top_level_presets_is_a_project_error(tmp_path):
    """A hand-edited file can put anything under "presets". A list (or any
    other non-object) reaching `presets.items()` unchecked would raise a
    raw AttributeError with no mention of the file or the key -- unlike
    every other malformed-input case `load_site` handles. This is
    deliberately a *list*, not a dict with a bad value: the latter is
    already caught per-preset by `test_invalid_preset_is_a_project_error`
    above; this is the layer above that."""
    site = _site(tmp_path)
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    doc = json.loads(out.read_text())
    doc["presets"] = ["not", "an", "object"]
    out.write_text(json.dumps(doc))
    with pytest.raises(ProjectError, match="presets"):
        load_site(out)
