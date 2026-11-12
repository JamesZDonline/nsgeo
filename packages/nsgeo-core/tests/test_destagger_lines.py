"""Per-line destagger values, measured on the real Nashville grids (#159).

A line gets its own value only when it is clearly and repeatably off against
its neighbours; a line that changes partway along, or matches nothing, is named
and left at the grid value. Injected errors move real lines, so every case is
real data (`moved` is 0-based: index 30 is FILE__031).

Three spec tolerances cannot be met and are strict xfails with the measured
numbers (ruling 2). FILE__031 already sits 0.05 m ahead of its neighbours
before any move, below the own-value threshold, so its base value is the grid
value; once moved it gets an own value that corrects that 0.05 m as well, and
lands about 0.05 m from "base value - d". The move itself is recovered to
within 0.01 m (`test_two_moves_of_one_line_differ_by_the_difference_of_the_moves`).
"""

from __future__ import annotations

import tracemalloc

import numpy as np
import pytest
from nsgeo.destagger import LineStatus, measure_destagger, per_line
from nsgeo.destagger.profiles import STEP_M, peak

from tests.destagger_data import (
    GRID1_LENGTH,
    GRID2_LENGTH,
    lines_for,
    needs_grid1,
    needs_grid2,
)
from tests.real_data import GPS_LINES, GRID2_LINES

#: Own values on Grid 2 are pinned to within this of the values measured when the
#: per-line solve was built (2026-11-11); the prototype's agree to 0.03 m except
#: FILE__051 fitted (+0.147 there). FILE__027, which gets none, is pinned at the
#: prototype's +0.665 so its strict xfail fails loudly if it ever gets that value.
SIZE_TOL = 0.03

NOT_OWN = (LineStatus.GRID, LineStatus.CHANGES, LineStatus.NO_MATCH)


def line(result, name):
    (found,) = [ln for key, ln in result.lines.items() if key.endswith(f"/{name}.DZT")]
    return found


def grid_value(result):
    return result.axes["y"].destagger


def share_not_own(result):
    return sum(ln.status is not LineStatus.OWN for ln in result.lines.values()) / len(result.lines)


@pytest.fixture(scope="module")
def grid1_unfitted():
    return measure_destagger(lines_for(GPS_LINES, GRID1_LENGTH))


@pytest.fixture(scope="module")
def grid1_fitted():
    return measure_destagger(lines_for(GPS_LINES, GRID1_LENGTH, fitted=True))


@pytest.fixture(scope="module")
def grid2_unfitted():
    return measure_destagger(lines_for(GRID2_LINES, GRID2_LENGTH))


@pytest.fixture(scope="module")
def grid2_fitted():
    return measure_destagger(lines_for(GRID2_LINES, GRID2_LENGTH, fitted=True))


@pytest.fixture(scope="module")
def moved_forward():
    return measure_destagger(lines_for(GPS_LINES, GRID1_LENGTH, moved={30: 0.30}))


@pytest.fixture(scope="module")
def moved_back():
    return measure_destagger(lines_for(GPS_LINES, GRID1_LENGTH, moved={30: -0.50}))


@pytest.fixture(scope="module")
def moved_pair():
    return measure_destagger(lines_for(GPS_LINES, GRID1_LENGTH, moved={30: 0.30, 31: 0.30}))


@pytest.fixture(scope="module")
def placements(grid1_unfitted, grid1_fitted):
    return {"unfitted": grid1_unfitted, "fitted": grid1_fitted}


# --- injected errors (Grid 1 unfitted) -------------------------------------------------


@needs_grid1
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="FILE__031 gets -0.200 against the target base - 0.30 = -0.148 (off by 0.052): "
    "its own +0.052 m residual, below the threshold before the move, is corrected too",
)
def test_a_line_moved_forward_is_recovered(grid1_unfitted, moved_forward):
    base = line(grid1_unfitted, "FILE__031").destagger
    moved = line(moved_forward, "FILE__031")
    assert moved.status is LineStatus.OWN
    assert moved.destagger == pytest.approx(base - 0.30, abs=0.05)


@needs_grid1
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="FILE__031 gets +0.596 against the target base + 0.50 = +0.652 (off by 0.056): "
    "its own +0.052 m residual is corrected too, and the grid value moves by +0.003",
)
def test_a_line_moved_back_is_recovered(grid1_unfitted, moved_back):
    base = line(grid1_unfitted, "FILE__031").destagger
    moved = line(moved_back, "FILE__031")
    assert moved.status is LineStatus.OWN
    assert moved.destagger == pytest.approx(base + 0.50, abs=0.05)


@needs_grid1
@pytest.mark.parametrize("case", ["moved_forward", "moved_back"])
def test_the_neighbours_of_a_moved_line_keep_their_values(grid1_unfitted, case, request):
    """A bad line does not drag its neighbours (spec 7.4)."""
    moved = request.getfixturevalue(case)
    for name in ("FILE__030", "FILE__032"):
        before, after = line(grid1_unfitted, name), line(moved, name)
        assert after.status is before.status
        assert after.destagger == pytest.approx(before.destagger, abs=0.02)


@needs_grid1
def test_two_moves_of_one_line_differ_by_the_difference_of_the_moves(moved_forward, moved_back):
    """The move itself is recovered: its own residual cancels between the two."""
    forward, back = line(moved_forward, "FILE__031"), line(moved_back, "FILE__031")
    assert forward.status is back.status is LineStatus.OWN
    assert forward.destagger - back.destagger == pytest.approx(-0.80, abs=0.01)


@needs_grid1
@pytest.mark.parametrize(
    "name",
    [
        pytest.param(
            "FILE__031",
            marks=pytest.mark.xfail(
                strict=True,
                raises=AssertionError,
                reason="FILE__031 gets -0.218 against base - 0.30 = -0.148 (off by 0.070): "
                "its own +0.052 m residual again, plus 0.018 m of the shared pair",
            ),
        ),
        "FILE__032",
    ],
)
def test_two_adjacent_moved_lines_are_both_recovered(grid1_unfitted, moved_pair, name):
    base = line(grid1_unfitted, name).destagger
    moved = line(moved_pair, name)
    assert moved.status is LineStatus.OWN
    assert moved.destagger == pytest.approx(base - 0.30, abs=0.05)


# --- skew and shares -------------------------------------------------------------------


@needs_grid1
@pytest.mark.parametrize("placement", ["unfitted", "fitted"])
def test_a_skew_creates_no_own_values(placements, placement):
    """P9: the skew creates and removes no own value 0.20 m or more from the grid value,
    own values in both runs differ by at most 0.03 m, the grid value by under 0.01 m."""
    base = placements[placement]
    skewed = measure_destagger(
        lines_for(GPS_LINES, GRID1_LENGTH, fitted=placement == "fitted", skew=0.02)
    )
    assert grid_value(skewed) == pytest.approx(grid_value(base), abs=0.01)
    for key, before in base.lines.items():
        after = skewed.lines[key]
        own_before, own_after = before.status is LineStatus.OWN, after.status is LineStatus.OWN
        if own_before and own_after:
            assert after.destagger == pytest.approx(before.destagger, abs=0.03), key
        elif own_before:
            assert abs(before.destagger - grid_value(base)) < 0.20, key
        elif own_after:
            assert abs(after.destagger - grid_value(skewed)) < 0.20, key


@needs_grid1
@pytest.mark.parametrize("placement", ["unfitted", "fitted"])
def test_most_grid1_lines_keep_the_grid_value(placements, placement):
    # Measured 2026-11-11: 56 of 60 unfitted, 60 of 60 fitted.
    assert share_not_own(placements[placement]) >= 0.85


@needs_grid1
def test_unfitted_file_011_gets_no_own_value(grid1_unfitted):
    """The known 4 m wheel slip: a shift cannot fix it."""
    assert line(grid1_unfitted, "FILE__011").status in (LineStatus.CHANGES, LineStatus.NO_MATCH)


# --- Grid 2: lines the spike found clearly off ------------------------------------------


@needs_grid2
@pytest.mark.parametrize(
    "placement, name, side, measured",
    [
        ("unfitted", "FILE__045", +0.25, 0.884),
        ("unfitted", "FILE__028", +0.25, 0.687),
        pytest.param(
            "unfitted",
            "FILE__027",
            +0.25,
            0.665,
            marks=pytest.mark.xfail(
                strict=True,
                raises=AssertionError,
                reason="FILE__027 has no clear match once FILE__028 is corrected: the "
                "027-028 pair reads -0.52 m (search to 2 m), so they are not both 0.5 m off, "
                "and the strong reflector at 8.8 m lines up on 027-030 with 028 alone moved "
                "(+0.525); the prototype's 027 +0.50 moves that reflector 0.35 m out of line",
            ),
        ),
        ("fitted", "FILE__051", +0.10, 0.173),
        ("fitted", "FILE__059", -0.10, -0.288),
    ],
)
def test_grid2_clearly_off_lines_get_own_values(
    grid2_unfitted, grid2_fitted, placement, name, side, measured
):
    result = grid2_unfitted if placement == "unfitted" else grid2_fitted
    found = line(result, name)
    assert found.status is LineStatus.OWN
    if side > 0:
        assert found.destagger > grid_value(result) + side
    else:
        assert found.destagger < grid_value(result) + side
    assert found.destagger == pytest.approx(measured, abs=SIZE_TOL)


@needs_grid2
def test_grid2_fitted_file_050_gets_no_own_value(grid2_fitted):
    assert line(grid2_fitted, "FILE__050").status in (LineStatus.CHANGES, LineStatus.NO_MATCH)


@needs_grid2
@pytest.mark.parametrize("placement", ["unfitted", "fitted"])
def test_most_grid2_lines_keep_the_grid_value(grid2_unfitted, grid2_fitted, placement):
    # Measured 2026-11-11: 51 of 60 unfitted, 55 of 60 fitted.
    result = grid2_unfitted if placement == "unfitted" else grid2_fitted
    assert share_not_own(result) >= 0.80


@needs_grid2
def test_lines_left_at_the_grid_value_carry_it(grid2_unfitted):
    grid = grid_value(grid2_unfitted)
    statuses = {ln.status for ln in grid2_unfitted.lines.values()}
    assert {LineStatus.OWN, LineStatus.NO_MATCH, LineStatus.GRID} <= statuses
    for ln in grid2_unfitted.lines.values():
        if ln.status in NOT_OWN:
            assert ln.destagger == grid
        else:
            assert ln.destagger != grid


@needs_grid2
def test_per_line_results_are_deterministic(grid2_fitted):
    again = measure_destagger(lines_for(GRID2_LINES, GRID2_LENGTH, fitted=True))
    assert again == grid2_fitted


@needs_grid1
def test_memory_does_not_grow_with_every_line_held_at_once():
    """Lines are compared in a sliding window over offset order: the first version held
    every line's FFT at once (110 MB traced on Grid 1)."""
    lines = lines_for(GPS_LINES, GRID1_LENGTH)
    tracemalloc.start()
    try:
        measure_destagger(lines)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 40e6


@needs_grid2
def test_a_solve_that_does_not_settle_keeps_only_own_values_that_still_hold(monkeypatch):
    """Grid 2 unfitted needs a second pass: FILE__027 and FILE__041 fail their first
    check. Stopped after one pass, each own value left must still qualify against the
    others, and sit at its own peak rather than where it was solved beside a dropped line."""
    solvers = []
    run = per_line._Solver.run

    def spy(self):
        solvers.append(self)
        return run(self)

    monkeypatch.setattr(per_line._Solver, "run", spy)
    monkeypatch.setattr(per_line, "MAX_PASSES", 1)
    result = measure_destagger(lines_for(GRID2_LINES, GRID2_LENGTH))
    (solver,) = solvers
    grid = grid_value(result)
    own = np.array(
        [
            ln.destagger - grid if ln.status is LineStatus.OWN else 0.0
            for ln in result.lines.values()
        ]
    )
    assert np.count_nonzero(own) >= 5
    for k in np.flatnonzero(own):
        assert solver.classify(int(k), own) == "candidate"
        refit = -peak(solver.curve(int(k), "full", own))[0] * STEP_M
        assert refit == pytest.approx(own[k], abs=0.005)
