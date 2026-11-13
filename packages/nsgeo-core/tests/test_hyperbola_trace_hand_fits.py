"""The tracer against the author's own saved hand fits (#140). Local only.

The site files are copied by `make_hand_fit_data.py` into the gitignored
tests/data/local/hand-fits/. Nothing here holds a site name, path or number;
the tests assert the agreement rules only. CI has no such data and skips.

`rulings.json` maps "<absolute DZT path>#<fit id>" to the author's ruling that
the hand fit was off (the comparison is skipped); `pending.json` maps a key to
a note on a disagreement awaiting a ruling (the test is a strict xfail). A
key plus "|boxes" does the same for the three-box test alone.
"""

from __future__ import annotations

import contextlib
import json
import time
from dataclasses import dataclass
from functools import cache
from itertools import combinations
from pathlib import Path

import numpy as np
import pytest
from nsgeo import hyperbola_trace as ht
from nsgeo.hyperbola_trace import TraceBox, trace_hyperbola
from nsgeo.processing.base import Radargram, retime_ns
from nsgeo.project import line_key, load_site
from nsgeo.velocity_fit import fit_at_zero, fit_hyperbola

from tests.real_data import DATA, HAND_FIT_SITES

FOLDER = DATA / "hand-fits"


def _read(name: str) -> dict[str, str]:
    path = FOLDER / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


RULINGS = _read("rulings.json")
PENDING = _read("pending.json")


@dataclass
class Case:
    key: str
    data: np.ndarray
    times: np.ndarray
    distance: np.ndarray
    hand: object  # StoredFit at the fit's clock
    fraction: float
    zero: float
    missing: str = ""


def _fraction(stack) -> float:
    """The line's own time-zero fraction: the last enabled first-break step's
    threshold, else 0.2 (no such step, or sample mode)."""
    found = 0.2
    for step, on in stack.entries:
        if on and step.name == "time_zero" and step.mode == "first_break":
            found = float(step.threshold)
    return found


@cache
def _cases() -> tuple[Case, ...]:
    out: list[Case] = []
    for site_file in HAND_FIT_SITES:
        site = load_site_or_none(site_file)
        if site is None:
            continue
        root = site_file.resolve().parent
        for line in site.lines:
            if not line.velocity_fits:
                continue
            key = line_key(line.path, root, allow_absolute=True)
            fit_ids = sorted(line.velocity_fits)
            if not Path(line.path).exists():
                out.extend(
                    Case(f"{line.path}#{f}", *([None] * 5), 0.2, 0.0, "DZT missing")
                    for f in fit_ids
                )  # type: ignore[arg-type]
                continue
            stack = site.stacks[key]
            stack.source = Radargram.from_profile(line.load()[0])
            result = stack.result()
            zero = result.zero_ns if stack.sets_time_zero() else 0.0
            distance = line.distance_along()
            for fid in fit_ids:
                hand = fit_at_zero(line.velocity_fits[fid], distance, zero)
                out.append(
                    Case(
                        f"{line.path}#{fid}",
                        result.data,
                        result.times_ns(),
                        distance,
                        hand,
                        _fraction(stack),
                        zero,
                    )
                )
    return tuple(out)


def load_site_or_none(path: Path):
    try:
        return load_site(path)
    except Exception:  # noqa: BLE001 -- an unreadable copy is a skip, not an error
        return None


def _params(suffix=""):
    if not HAND_FIT_SITES:
        return [pytest.param(None, marks=pytest.mark.skip(reason="no hand-fit data (local only)"))]
    params = []
    for case in _cases():
        marks = []
        if case.missing:
            marks.append(pytest.mark.skip(reason=f"{case.missing}"))
        if case.key in RULINGS:
            marks.append(pytest.mark.skip(reason=f"author's ruling: {RULINGS[case.key]}"))
        if case.key + suffix in PENDING:
            marks.append(
                pytest.mark.xfail(
                    strict=True,
                    reason="pending the author's ruling: " + PENDING[case.key + suffix],
                )
            )
        params.append(pytest.param(case, id=case.key, marks=marks))
    return params


def _hand_extent(case: Case):
    traces = np.array([p[0] for p in case.hand.points])
    times = retime_ns(np.array([p[1] for p in case.hand.points]), 0.0, case.zero)
    return traces, times


def _box(case: Case, margin: float, shift: float = 0.0) -> TraceBox:
    traces, times = _hand_extent(case)
    n_traces = case.data.shape[1]
    w = max(float(traces.max() - traces.min()), 1.0)
    h = float(times.max() - times.min())
    pad_x = max(margin * w, 5.0)
    pad_t = max(margin * h, 2.0)
    first = traces.min() - pad_x
    last = traces.max() + pad_x
    width = last - first
    first += shift * width
    last += shift * width
    return TraceBox(
        int(max(0, np.floor(first))),
        int(min(n_traces - 1, np.ceil(last))),
        float(max(case.times[0], times.min() - pad_t)),
        float(min(case.times[-1], times.max() + pad_t)),
    )


def _trace_fit(case: Case, box: TraceBox):
    dots = trace_hyperbola(case.data, case.times, case.distance, box, fraction=case.fraction)
    tr = np.array([d[0] for d in dots])
    return fit_hyperbola(
        case.distance[tr], np.array([d[1] for d in dots]), float(case.distance[tr[0]])
    )


def _agree(a_v, a_sig, b_v, b_sig) -> bool:
    return abs(a_v - b_v) <= 2 * float(np.hypot(a_sig, b_sig))


@pytest.mark.parametrize("case", _params())
def test_a_traced_fit_agrees_with_the_hand_fit(case):
    traced = _trace_fit(case, _box(case, 0.2))
    t, h = traced, case.hand
    assert _agree(t.v_m_ns, t.v_stderr_m_ns, h.v_m_ns, h.v_stderr_m_ns), (
        f"traced {t.v_m_ns:.4f}+-{t.v_stderr_m_ns:.4f} hand {h.v_m_ns:.4f}+-{h.v_stderr_m_ns:.4f}"
    )


@pytest.mark.parametrize("case", _params("|boxes"))
def test_three_boxes_agree_with_each_other(case):
    fits = [
        _trace_fit(case, _box(case, 0.10)),
        _trace_fit(case, _box(case, 0.20)),
        _trace_fit(case, _box(case, 0.35, shift=0.10)),
    ]
    for a, b in combinations(fits, 2):
        assert _agree(a.v_m_ns, a.v_stderr_m_ns, b.v_m_ns, b.v_stderr_m_ns), (
            f"{a.v_m_ns:.4f}+-{a.v_stderr_m_ns:.4f} vs {b.v_m_ns:.4f}+-{b.v_stderr_m_ns:.4f}"
        )


def test_the_largest_box_traces_within_a_second():
    if not HAND_FIT_SITES:
        pytest.skip("no hand-fit data (local only)")
    cases = [c for c in _cases() if not c.missing]
    if not cases:
        pytest.skip("no hand-fit DZT is present")
    boxes = [(c, _box(c, 0.35)) for c in cases]
    case, box = max(
        boxes,
        key=lambda cb: (cb[1].last_trace - cb[1].first_trace) * (cb[1].bottom_ns - cb[1].top_ns),
    )
    start = time.perf_counter()
    with contextlib.suppress(ValueError):  # a refusal still has to be quick
        trace_hyperbola(case.data, case.times, case.distance, box, fraction=case.fraction)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"{elapsed:.2f} s"
    assert ht.MAX_BOX_CELLS > 0
