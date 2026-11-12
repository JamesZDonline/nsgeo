from __future__ import annotations

import dataclasses
import math

import pytest
from nsgeo.velocity_fit import StoredFit
from nsgeo.velocity_source import (
    METHOD_FIT,
    METHOD_WEIGHTED_MEAN,
    SourceFit,
    VelocitySource,
    weighted_mean,
)


def _stored(v=0.09, sigma=0.003, t0=15.6, zero=0.0, at="2026-11-01T10:00:00Z") -> StoredFit:
    return StoredFit(
        t0_ns=t0,
        v_m_ns=v,
        v_stderr_m_ns=sigma,
        rms_ns=0.2,
        apex_trace=10,
        points=((8, 16.0), (10, 15.6), (12, 16.0)),
        fitted_at=at,
        zero_ns=zero,
    )


def _member(label="FILE__003", fit_id="fit-1", **kw) -> SourceFit:
    return SourceFit.of(f"raw/{label}.DZT", fit_id, label, _stored(**kw))


def test_weighted_mean_matches_hand_values():
    v, s = weighted_mean([(0.0921, 0.0041), (0.0874, 0.0028), (0.0898, 0.0033)])
    w = [1 / 0.0041**2, 1 / 0.0028**2, 1 / 0.0033**2]
    assert v == pytest.approx((0.0921 * w[0] + 0.0874 * w[1] + 0.0898 * w[2]) / sum(w), rel=1e-12)
    assert s == pytest.approx(1 / math.sqrt(sum(w)), rel=1e-12)
    assert s < 0.0028


def test_weighted_mean_of_one_fit_is_that_fit():
    assert weighted_mean([(0.09, 0.003)]) == pytest.approx((0.09, 0.003), rel=1e-12)


def test_weighted_mean_refuses_a_zero_sigma_and_names_it():
    with pytest.raises(ValueError, match="fit 2 has σ 0.0"):
        weighted_mean([(0.09, 0.003), (0.088, 0.0)])


@pytest.mark.parametrize("sigma", [-0.001, math.nan, math.inf, -math.inf])
def test_weighted_mean_refuses_a_bad_sigma(sigma):
    with pytest.raises(ValueError, match="fit 1 has σ .*cannot be weighted"):
        weighted_mean([(0.09, sigma)])


def test_weighted_mean_of_nothing_is_refused():
    with pytest.raises(ValueError, match="no fits"):
        weighted_mean([])


def test_one_member_is_a_fit_record_and_several_an_average():
    a = _member("FILE__003", v=0.09, sigma=0.003)
    b = _member("FILE__004", v=0.08, sigma=0.002)
    one = VelocitySource.from_fits([a], "2026-11-12T09:00:00Z")
    assert one.method == METHOD_FIT
    assert (one.v_m_ns, one.v_stderr_m_ns) == (0.09, 0.003)
    assert one.summary() == "fit on FILE__003"
    two = VelocitySource.from_fits([a, b], None)
    assert two.method == METHOD_WEIGHTED_MEAN
    v, s = weighted_mean([(0.09, 0.003), (0.08, 0.002)])
    assert (two.v_m_ns, two.v_stderr_m_ns) == (v, s)
    assert two.summary() == "average of 2 fits"
    assert two.members == (a, b)


def test_from_fits_of_nothing_is_refused():
    with pytest.raises(ValueError, match="no fits"):
        VelocitySource.from_fits([], None)


def test_a_member_copies_the_fit_as_used():
    m = SourceFit.of("raw/A.DZT", "fit-3", "A", _stored(t0=12.3, zero=-0.4, v=0.0921))
    assert (m.line_key, m.fit_id, m.line_label) == ("raw/A.DZT", "fit-3", "A")
    assert (m.t0_ns, m.v_m_ns, m.v_stderr_m_ns, m.zero_ns) == (12.3, 0.0921, 0.003, -0.4)
    assert m.fitted_at == "2026-11-01T10:00:00Z"


@pytest.mark.parametrize("applied_at", [None, "2026-11-12T09:00:00Z"])
def test_a_record_round_trips_through_its_dict_bit_for_bit(applied_at):
    members = [_member("A", v=0.0921234567891234), _member("B", fit_id="fit-2", v=0.0874)]
    src = VelocitySource.from_fits(members, applied_at)
    assert VelocitySource.from_dict(src.to_dict()) == src


def test_a_member_names_a_fit_only_with_the_same_fitted_at():
    fit = _stored()
    m = SourceFit.of("raw/A.DZT", "fit-1", "A", fit)
    assert m.names("fit-1", fit)
    assert not m.names("fit-1", dataclasses.replace(fit, fitted_at="2026-11-02T10:00:00Z"))
    assert not m.names("fit-2", fit)


def _doc():
    return VelocitySource.from_fits([_member()], None).to_dict()


def test_from_dict_refuses_an_unknown_method():
    doc = _doc()
    doc["method"] = "median"
    with pytest.raises(ValueError, match="method"):
        VelocitySource.from_dict(doc)


def test_from_dict_refuses_no_members():
    doc = _doc()
    doc["members"] = []
    with pytest.raises(ValueError, match="member"):
        VelocitySource.from_dict(doc)


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_from_dict_refuses_a_non_finite_number(bad):
    for where in ("top", "member"):
        doc = _doc()
        (doc if where == "top" else doc["members"][0])["v_m_ns"] = bad
        with pytest.raises(ValueError):
            VelocitySource.from_dict(doc)


def test_from_dict_refuses_a_missing_key():
    doc = _doc()
    del doc["v_stderr_m_ns"]
    with pytest.raises(ValueError):
        VelocitySource.from_dict(doc)
