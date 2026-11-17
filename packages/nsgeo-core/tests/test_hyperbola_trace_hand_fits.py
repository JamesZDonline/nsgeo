"""The tracer against the author's own saved hand fits (#140). Local only.

The site files are copied by `make_hand_fit_data.py` into the gitignored
tests/data/local/hand-fits/. Nothing here holds a site name, path or number;
the tests assert the agreement rules only. CI has no such data and skips.

`rulings.json` maps "<absolute DZT path>#<fit id>" to the author's ruling that
the hand fit was off (the comparison is skipped); `pending.json` maps a key to
a note on a disagreement awaiting a ruling (the test is a strict xfail). A
key plus "|boxes" does the same for the three-box test alone. `expected.json`
maps a key to {"ratio": [lo, hi], "reason": ...}: a difference the author has
accepted as expected, so the traced-to-hand velocity ratio must lie in
[lo, hi], and the traced sigma stay within ``EXPECTED_MAX_REL_SIGMA`` of its
velocity, instead of the two agreeing (the three-box test is unchanged). Each
fit's band is centred on its accepted ratio, so a lobe jump still fails.

In the three-box test a box the tracer refuses is left out: a refusal is not
a disagreement (the author redraws the box). The 20% box must trace, at least
two boxes must trace in all, and every traced pair must agree.

A saved stack may have Migration or an amplitude transform switched on. The
panel refuses to trace with those on and tells the author to switch them off,
and the hand fit was clicked on the hyperbola they collapse, so each line is
traced with them off, as the author would.
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


def _read(name: str) -> dict:
    path = FOLDER / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


RULINGS = _read("rulings.json")
PENDING = _read("pending.json")
EXPECTED = _read("expected.json")

#: The steps the panel refuses to trace with: Migration and the amplitude
#: transforms (spec §3, decision 3).
REFUSED_STEPS = ("migrate_fk", "amp_abs", "amp_square", "amp_envelope")
#: An accepted difference must still be a precise trace: a ratio inside its
#: band means little when the traced sigma could hide a jump.
EXPECTED_MAX_REL_SIGMA = 0.05


@dataclass
class Case:
    key: str
    data: np.ndarray
    times: np.ndarray
    distance: np.ndarray
    hand: object  # StoredFit at the fit's clock
    zero: float
    missing: str = ""


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
                    Case(f"{line.path}#{f}", *([None] * 4), 0.0, "DZT missing") for f in fit_ids
                )  # type: ignore[arg-type]
                continue
            stack = site.stacks[key]
            for index, (step, on) in enumerate(stack.entries):
                if on and step.name in REFUSED_STEPS:
                    stack.set_enabled(index, False)
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
    dots = trace_hyperbola(case.data, case.times, case.distance, box)
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
    expected = EXPECTED.get(case.key)
    if expected is not None:
        lo, hi = expected["ratio"]
        ratio = t.v_m_ns / h.v_m_ns
        assert lo <= ratio <= hi, (
            f"traced/hand {ratio:.3f} outside [{lo}, {hi}]: {expected['reason']}"
        )
        rel_sigma = t.v_stderr_m_ns / t.v_m_ns
        assert rel_sigma <= EXPECTED_MAX_REL_SIGMA, (
            f"traced sigma/v {rel_sigma:.3f} over {EXPECTED_MAX_REL_SIGMA}: {expected['reason']}"
        )
        return
    assert _agree(t.v_m_ns, t.v_stderr_m_ns, h.v_m_ns, h.v_stderr_m_ns), (
        f"traced {t.v_m_ns:.4f}+-{t.v_stderr_m_ns:.4f} hand {h.v_m_ns:.4f}+-{h.v_stderr_m_ns:.4f}"
    )


@pytest.mark.parametrize("case", _params("|boxes"))
def test_three_boxes_agree_with_each_other(case):
    fits = [_trace_fit(case, _box(case, 0.20))]  # a refusal here fails the test
    for margin, shift in ((0.10, 0.0), (0.35, 0.10)):
        with contextlib.suppress(ValueError):  # a refusal is not a disagreement
            fits.append(_trace_fit(case, _box(case, margin, shift)))
    assert len(fits) >= 2, "only the 20% box traced"
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
        trace_hyperbola(case.data, case.times, case.distance, box)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"{elapsed:.2f} s"
    assert ht.MAX_BOX_CELLS > 0
