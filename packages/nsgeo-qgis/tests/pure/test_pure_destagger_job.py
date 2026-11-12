from __future__ import annotations

import math

import nsgeo_qgis.destagger_job as job_module
import numpy as np
from nsgeo.destagger import (
    AxisResult,
    DestaggerResult,
    LineResult,
    LineStatus,
    envelope_bins,
)
from nsgeo.geometry import GridPlacement
from nsgeo.io.dzt import read_header, read_samples
from nsgeo_qgis.destagger_job import JobLine, MeasureJob, box_value, measure_summary
from plugin_testing import synthetic_dzt


def _job_lines(tmp_path, n=4, **kw):
    out = []
    for i in range(n):
        path = synthetic_dzt(tmp_path, f"FILE__00{i + 1}.DZT", n_traces=60, **kw)
        placement = GridPlacement(
            "G", "y", 0.25 + 0.5 * i, 0.0 if i % 2 == 0 else 10.0, 1 - 2 * (i % 2)
        )
        out.append(JobLine(path.name, f"line {i + 1}", path, read_header(path), placement))
    return out


def _count_reads(monkeypatch):
    calls: list = []
    real = job_module.read_samples

    def counting(path, header=None):
        calls.append(path)
        return real(path, header)

    monkeypatch.setattr(job_module, "read_samples", counting)
    return calls


def test_the_job_reads_only_lines_it_has_not_prepared(tmp_path, monkeypatch):
    lines = _job_lines(tmp_path)
    first = lines[0]
    cached = {
        first.key: envelope_bins(
            read_samples(first.path, first.header)[0], first.header.dt_ns, first.header.position_ns
        )
    }
    calls = _count_reads(monkeypatch)
    monkeypatch.setattr(job_module, "measure_destagger", lambda ls, stop: DestaggerResult({}, {}))
    job = MeasureJob(lines, cached)
    assert job.progress == (0, 3)
    job.run(lambda: False)
    assert len(calls) == 3
    assert first.path not in calls
    assert set(job.prepared) == {ln.key for ln in lines}
    assert job.progress == (3, 3)


def test_an_unreadable_file_is_recorded_not_raised(tmp_path, monkeypatch):
    lines = _job_lines(tmp_path)
    lines[1].path.unlink()
    seen: list = []

    def canned(ls, stop):
        seen.extend(ln.key for ln in ls)
        return DestaggerResult({}, {})

    monkeypatch.setattr(job_module, "measure_destagger", canned)
    job = MeasureJob(lines, {})
    job.run(lambda: False)
    assert list(job.unreadable) == [lines[1].key]
    assert job.unreadable[lines[1].key]
    assert seen == [lines[0].key, lines[2].key, lines[3].key]
    assert job.result is not None
    assert not job.stopped


def test_a_stop_between_reads_ends_the_job_quietly(tmp_path):
    lines = _job_lines(tmp_path)
    asked = []

    def stop():
        asked.append(1)
        return len(asked) > 1

    job = MeasureJob(lines, {})
    job.run(stop)
    assert job.stopped
    assert job.result is None
    assert len(job.prepared) == 1


def test_a_multi_channel_file_is_measured_on_its_first_channel(tmp_path, monkeypatch):
    from tests.synthetic import write_dzt

    rng = np.random.default_rng(3)
    data = (rng.normal(size=(2, 512, 40)) * 1e6).astype(np.int32)
    path = tmp_path / "TWO.DZT"
    write_dzt(path, data, n_channels=2)
    header = read_header(path)
    line = JobLine("TWO", "two", path, header, GridPlacement("G", "y", 0.25, 0.0, 1))
    monkeypatch.setattr(job_module, "measure_destagger", lambda ls, stop: DestaggerResult({}, {}))
    job = MeasureJob([line], {})
    job.run(lambda: False)
    expected = envelope_bins(read_samples(path, header)[0], header.dt_ns, header.position_ns)
    got = job.prepared["TWO"]
    assert np.array_equal(got.data, expected.data)
    assert (got.t0_ns, got.dt_ns) == (expected.t0_ns, expected.dt_ns)
    assert not np.array_equal(
        got.data,
        envelope_bins(read_samples(path, header)[1], header.dt_ns, header.position_ns).data,
    )


def _axis(axis, value, used=10, spread=0.02, reason=""):
    return AxisResult(axis, value, spread if value is not None else math.nan, used, reason)


def _line(key, axis, status, value=None, reason=""):
    return LineResult(key, axis, status, value, reason)


def test_box_value_takes_the_axis_with_more_lines():
    result = DestaggerResult({"x": _axis("x", 0.1, used=5), "y": _axis("y", 0.2, used=9)}, {})
    assert box_value(result) == 0.2
    failed = DestaggerResult(
        {"x": _axis("x", 0.1, used=5), "y": _axis("y", None, used=9, reason="r")}, {}
    )
    assert box_value(failed) is None
    assert box_value(DestaggerResult({}, {})) is None


LABELS = {f"k{i}": f"L{i}" for i in range(12)}


def test_summary_words():
    ok = DestaggerResult({"y": _axis("y", 0.152, used=58, spread=0.011)}, {})
    assert measure_summary(ok, [], {}, LABELS) == "Measured +0.152 m from 58 lines (±0.011 m)."

    two = DestaggerResult(
        {"x": _axis("x", -0.1, used=8, spread=0.02), "y": _axis("y", 0.2, used=9, spread=0.03)}, {}
    )
    assert measure_summary(two, [], {}, LABELS) == (
        "Along x: measured -0.100 m from 8 lines (±0.020 m). "
        "Along y: measured +0.200 m from 9 lines (±0.030 m)."
    )

    reason = "every line was walked the same way, so there is no stagger to measure"
    one_failed = DestaggerResult({"y": _axis("y", None, reason=reason)}, {})
    assert measure_summary(one_failed, ["k0"], {}, LABELS) == (
        f"Could not measure: {reason}. Nothing was changed."
    )

    half = DestaggerResult(
        {"x": _axis("x", 0.1, used=8, spread=0.02), "y": _axis("y", None, reason="why")}, {}
    )
    assert measure_summary(half, [], {}, LABELS) == (
        "Along x: measured +0.100 m from 8 lines (±0.020 m). "
        "Along y: could not measure (why); nothing changed there."
    )
    both = DestaggerResult(
        {"x": _axis("x", None, reason="a"), "y": _axis("y", None, reason="b")}, {}
    )
    assert measure_summary(both, ["k0"], {}, LABELS) == (
        "Along x: could not measure (a); nothing changed there. "
        "Along y: could not measure (b); nothing changed there."
    )


def test_summary_groups():
    lines = {
        "k0": _line("k0", "y", LineStatus.GRID, 0.1),
        "k1": _line("k1", "y", LineStatus.OWN, 0.25),
        "k2": _line("k2", "y", LineStatus.OWN, -0.05),
        "k3": _line("k3", "y", LineStatus.CHANGES, 0.1),
        "k4": _line("k4", "y", LineStatus.NO_MATCH, 0.1),
        "k5": _line("k5", "y", LineStatus.NOT_MEASURED, None, "too short to measure"),
        "k6": _line(
            "k6", "y", LineStatus.NOT_MEASURED, None, "no line walked the other way beside it"
        ),
        "k9": _line("k9", "y", LineStatus.OWN, 0.9),
    }
    result = DestaggerResult({"y": _axis("y", 0.1, used=6, spread=0.01)}, lines)
    filled = ["k0", "k1", "k2", "k3", "k4", "k5", "k6", "k7"]
    text = measure_summary(result, filled, {"k7": "boom"}, LABELS)
    assert text == (
        "Measured +0.100 m from 6 lines (±0.010 m). "
        "Own values: L1 +0.250, L2 -0.050. "
        "Left at the grid value: L3 changes partway along; L4 has no clear match. "
        "Not measured, left as they were: L5 (too short to measure); "
        "L6 (no line walked the other way beside it); L7 (could not be read: boom)."
    )  # k9 is not a filled row, so it is not named


def test_summary_names_at_most_six_per_group():
    lines = {f"k{i}": _line(f"k{i}", "y", LineStatus.OWN, 0.2 + i / 100) for i in range(9)}
    result = DestaggerResult({"y": _axis("y", 0.1, used=9, spread=0.01)}, lines)
    text = measure_summary(result, list(lines), {}, LABELS)
    assert text.endswith("L5 +0.250, and 3 more.")
    assert "L6" not in text
