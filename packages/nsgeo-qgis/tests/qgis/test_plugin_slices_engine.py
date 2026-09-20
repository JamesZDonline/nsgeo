"""SliceEngine: preparation, the plan cache, residency, one slice per tick."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.render import UnipolarClip
from nsgeo.slices import CoverageError, SliceWindow
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slices_engine import SliceEngine
from nsgeo_qgis.slices_plan import NO_TRANSFORM, Resolution, SourceChoice
from plugin_testing import synthetic_dzt

GRID = Grid("A", (500.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5)
PRESET = [
    {"step": "time_zero", "params": {}, "enabled": True},
    {"step": "dewow", "params": {}, "enabled": True},
    {"step": "gain_agc", "params": {}, "enabled": True},
]


@pytest.fixture
def sourced(qgis_app, tmp_path):
    """A session with four parallel lines in one grid, and an engine on it."""
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = []
    for i in range(4):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", 1.0 + i * 1.0, 0.0, 1, p.stem)))
    session.add_lines(lines)
    session.site.presets["p"] = list(PRESET)
    errors: list[tuple[str, str]] = []
    prepared: list[int] = []
    engine = SliceEngine(
        session,
        on_prepared=lambda: prepared.append(1),
        on_error=lambda msg: errors.append(("error", msg)),
    )
    yield engine, session, errors, prepared
    engine.dispose()


def _prepare(engine, session, transform="amp_envelope", preset="p"):
    engine.set_source(
        SourceChoice(
            grid_id="A", preset=preset, transform=transform, line_keys=tuple(session.keys())
        )
    )
    assert engine.wait_for_preparation(20_000), "preparation did not finish"
    engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))


def test_preparation_applies_the_preset_and_appends_the_transform(sourced):
    engine, session, errors, prepared = sourced
    _prepare(engine, session)
    assert errors == []
    assert prepared == [1]
    assert engine.is_prepared
    assert engine.line_count == 4
    assert engine.output_unipolar is True
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    covered = values[coverage > 0]
    assert covered.size > 0
    assert np.isfinite(covered).all()
    assert (covered >= 0.0).all(), "an envelope is unipolar; a negative means it was not applied"


def test_no_transform_leaves_the_data_bipolar_and_says_so(sourced):
    engine, session, errors, _ = sourced
    _prepare(engine, session, transform=NO_TRANSFORM)
    assert engine.output_unipolar is False
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    covered = values[coverage > 0]
    assert (covered < 0.0).any(), "a signed mean of a signed radargram should reach below zero"


def test_a_preset_that_already_carries_a_transform_is_refused_by_name(sourced):
    """Ruling 2. The refusal must name the step, because the user's fix is
    to remove that specific step from that specific preset."""
    engine, session, errors, _ = sourced
    session.site.presets["bad"] = [
        {"step": "amp_abs", "params": {}, "enabled": True},
        {"step": "gain_agc", "params": {}, "enabled": True},
    ]
    with pytest.raises(ValueError, match="amp_abs"):
        engine.set_source(
            SourceChoice(grid_id="A", preset="bad", transform="amp_square", line_keys=("x",))
        )
    assert not engine.is_prepared


def test_changing_the_cell_size_re_plans_every_line(sourced):
    """The defect M10's final review called M11's first bug. A LinePlan is
    a function of (line, frame, z) and every Resolution control changes
    one of them; reusing a plan across that change bins every trace into
    the wrong cell. Before M10's guard existed it did so SILENTLY, with
    plausible coverage. The engine must drop its plans, not rely on the
    guard to raise."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    coarse, _ = engine.slice_at(SliceWindow(4, 14))
    assert coarse.shape == (24, 24)  # 6 m / 0.25 m

    engine.set_resolution(Resolution(cell=0.5, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    fine, _ = engine.slice_at(SliceWindow(4, 14))  # must NOT raise
    assert fine.shape == (12, 12)

    # And a z-axis change, which the same plans would also survive by
    # length alone if nz happened to match.
    engine.set_resolution(Resolution(cell=0.5, dz_ns=0.25, t0_ns=2.0, t1_ns=16.0))
    again, _ = engine.slice_at(SliceWindow(4, 14))
    assert again.shape == (12, 12)


def test_streaming_and_a_resident_cube_give_the_same_slice(sourced):
    """Spec 11's property, in the form a user could notice: the mode they
    are in must not change what they see."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    engine.set_always_resident(False)
    assert engine.mode == "streaming"
    streamed, cov_s = engine.slice_at(SliceWindow(6, 18))

    engine.set_always_resident(True)
    assert engine.mode == "resident"
    resident, cov_r = engine.slice_at(SliceWindow(6, 18))

    np.testing.assert_array_equal(cov_s, cov_r)
    both = np.isfinite(streamed) & np.isfinite(resident)
    assert both.any()
    np.testing.assert_allclose(streamed[both], resident[both], rtol=1e-5, atol=1e-6)
    np.testing.assert_array_equal(np.isfinite(streamed), np.isfinite(resident))


def test_the_shared_limit_agrees_between_the_two_modes(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    clip = UnipolarClip()
    engine.set_always_resident(False)
    streamed = engine.shared_limit(10, clip)
    engine.set_always_resident(True)
    resident = engine.shared_limit(10, clip)
    assert streamed == pytest.approx(resident, rel=1e-4)
    assert streamed > 0.0


def test_provenance_names_the_lines_that_were_actually_prepared(sourced):
    """Not the lines that were asked for. A line that failed to prepare is
    not in the cube and must not be claimed by its provenance -- that
    record is what a reader trusts the thing by."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    prov = engine.provenance()
    assert prov.line_keys == tuple(session.keys())
    assert prov.preset_name == "p"
    assert prov.transform == "amp_envelope"
    assert len(prov.steps) == len(PRESET)
    assert prov.core_version
    assert prov.built_utc.endswith("Z")


def test_a_z_range_the_lines_do_not_cover_is_reported_with_the_line_named(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    engine.set_resolution(Resolution(cell=0.5, dz_ns=0.5, t0_ns=0.0, t1_ns=400.0))
    with pytest.raises(CoverageError, match="FILE__001"):
        engine.slice_at(SliceWindow(0, 4))


def test_the_status_line_follows_the_mode_and_the_line_count(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    engine.slice_at(SliceWindow(4, 14))
    text = engine.status_text()
    assert text.startswith("4 lines held in memory")
    assert "slices redraw in" in text
    engine.set_always_resident(True)
    engine.slice_at(SliceWindow(4, 14))
    assert "whole volume" in engine.status_text()


def test_closing_the_site_releases_everything(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    assert engine.is_prepared
    session.close_site()
    assert not engine.is_prepared
    assert engine.line_count == 0
    assert engine.frame is None


def test_a_line_that_cannot_be_prepared_is_reported_by_name(sourced, tmp_path):
    engine, session, errors, _ = sourced
    key = session.keys()[0]
    session.line_for_key(key).path.unlink()  # the file goes away under us
    engine.set_source(
        SourceChoice(grid_id="A", preset="p", transform="amp_abs", line_keys=tuple(session.keys()))
    )
    assert engine.wait_for_preparation(20_000)
    assert any(key in msg for _, msg in errors), f"no error named {key}: {errors}"
