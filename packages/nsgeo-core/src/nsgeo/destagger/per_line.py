"""Per-line destagger values: lines clearly off on their own get their own value (#159).

After the grid value, each line is read against the mean of its two neighbours
walked the other way (design 7.4). Most lines' leftover is noise, about 0.05 m,
and they keep the grid value. A line gets its own value only when it is clearly
and repeatably off: its whole-record peak is clear, at least `MIN_OWN_M` from
zero, confirmed by a pair of independent halves (shallow and deep bins, or the
first and second half along the line), and not contradicted by a decisive half
(C13: a half without a clear peak neither confirms nor counts against it).

Comparing with the mean of both neighbours shows a single moved line as half
its move on each neighbour, and two adjacent moved lines blur into each other.
So the lines that qualify are solved jointly: each run of adjacent candidates
takes the corrections that best line up every pair of neighbours it touches,
with each line either left alone or moved by at least `MIN_OWN_M` (an exact
search along the run). The lines are then read again with those corrections;
an own value that no longer qualifies is dropped for good, and a line that now
qualifies joins, until nothing changes. Re-reading is cheap: shifting a line
shifts its pair curves, so nothing is recomputed.

Two kinds of line are named and left at the grid value: one whose two halves
along it both have decisive peaks that disagree by more than `CHANGE_M`
(*changes partway along*, such as a wheel slip), and one whose whole-record peak
is not clear (*no clear match*).

Only adjacent lines are solved together and every other line stays put, so a
shift that grows steadily across the lines (a skew, or a feature crossing at an
angle) cancels in each line's comparison and is never "straightened".
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from nsgeo.destagger.profiles import STEP_M, PairCurves, is_clear, peak

# Thresholds, tuned on Nashville 2023 Grids 1 and 2, unfitted and fitted, with injected
# moves of +0.30 and -0.50 m, two adjacent +0.30 m moves and a 0.02 m/line skew
# (2026-11-11). Each was varied alone with the rest held; the range given is where every
# real-data test still passes.

#: A line's own value is at least this far from the grid value. Per-line readings scatter
#: by about 0.05 m (halves disagree by a median 0.05 to 0.09 m). Works from 0.12 to 0.18;
#: at 0.20 the skew moves a Grid 1 line across it.
MIN_OWN_M = 0.15
#: Two readings agree within max(AGREE_M, AGREE_FRACTION x the line's residual): halves
#: carry their own noise plus the depth trend (deep reflectors want 0.03 to 0.08 m more).
#: AGREE_M works from 0.10 to 0.18 as the limit for a decisive half that counts against
#: a line (0.20 lets the skew flip Grid 1 fitted FILE__009) and from 0.12 to 0.25 for
#: confirming; AGREE_FRACTION from 0.3 to 0.4 (0.2 loses Grid 2 unfitted FILE__045).
AGREE_M = 0.15
AGREE_FRACTION = 0.3
#: Changes partway along: both halves along the line are decisive and differ by more than
#: this. Works from 0.25 to 0.40; Grid 1 unfitted FILE__011, the 4 m wheel slip, reads
#: +0.30 and -0.79.
CHANGE_M = 0.30
#: A half counts against a line, or names it as changing, only when its peak is decisive:
#: no other maximum above this fraction of it (`is_clear` asks 0.8 to confirm). A half
#: that is only just clear otherwise flips lines on a skew. Works from 0.5 to 0.7.
DECISIVE_RATIO = 0.6
#: An own value must raise its run's summed correlation by at least this; it breaks ties
#: towards fewer own values. Works from 0 to 0.05.
OWN_GAIN = 0.02
#: Passes of solving and re-reading at most; the Nashville grids settle in 1 to 3.
MAX_PASSES = 8

_HALVES = (("shallow", "deep"), ("first", "second"))


@dataclass(frozen=True)
class LineVerdicts:
    """Per-line results by line index. Lines in none of these keep the grid value."""

    own: dict[int, float]  # own correction (m) to add to the grid value
    changes: frozenset[int]  # changes partway along
    no_match: frozenset[int]  # no clear match


def per_line_values(
    pairs: PairCurves,
    order: Sequence[int],
    directions: Sequence[int],
    neighbours: dict[int, list[int]],
    grid: float,
    max_lag: int,
    check: Callable[[], None] = lambda: None,
) -> LineVerdicts:
    """Own values, and the lines that change partway along or match nothing.

    `pairs` holds the pair curves of the lines in `order` (by offset), `neighbours` each
    line's opposite-direction neighbours, `grid` the grid destagger (m) and `max_lag` the
    search range in steps. `check` is called at least once per line in every loop.
    """
    return _Solver(pairs, order, directions, neighbours, float(grid), max_lag, check).run()


class _Solver:
    def __init__(
        self,
        pairs: PairCurves,
        order: Sequence[int],
        directions: Sequence[int],
        neighbours: dict[int, list[int]],
        grid: float,
        max_lag: int,
        check: Callable[[], None],
    ) -> None:
        self.pairs = pairs
        self.order = list(order)
        self.dirs = np.asarray(directions, dtype=float)
        self.nb = neighbours
        self.grid = grid
        self.check = check
        self.pos = {k: p for p, k in enumerate(self.order)}
        self.grid_lags = np.arange(-pairs.lags, pairs.lags + 1, dtype=float)
        self.own_lags = np.arange(-max_lag, max_lag + 1, dtype=float)
        self.curves = self._cache_curves(self._depth_split())
        smallest = int(np.ceil(MIN_OWN_M / STEP_M - 1e-9))
        steps = np.arange(-max_lag, max_lag + 1)
        self.states = np.concatenate([[0], steps[np.abs(steps) >= smallest]])

    def _depth_split(self) -> int:
        """The bin dividing shallow from deep: each side holds half the grid's evidence.

        Evidence is each bin's correlation between neighbours at the grid value, averaged
        over the pairs (negative counts as none). This adapts to the antenna and record,
        where a fixed time would not; on Nashville it falls at 36 ns on Grid 1 and at 24 and
        28 ns on Grid 2 unfitted and fitted.
        """
        p = self.pairs
        n_bins = p.energy.shape[1]
        evidence = np.zeros(n_bins)
        for pos, a in enumerate(self.order):
            self.check()
            if not self._linked(pos):
                continue
            b = self.order[pos + 1]
            curves = p.by_bin[(a, b)]
            at = -self.dirs[a] * 2 * self.grid / STEP_M
            value = np.array([np.interp(at, self.grid_lags, c) for c in curves])
            scale = np.sqrt(p.energy[a] * p.energy[b])
            evidence += np.divide(value, scale, out=np.zeros(n_bins), where=scale > 0)
        evidence = np.clip(evidence, 0.0, None)
        if evidence.sum() <= 0:
            return max(1, n_bins // 2)
        split = int(np.searchsorted(np.cumsum(evidence) / evidence.sum(), 0.5))
        return min(max(split, 1), n_bins - 1)

    def _cache_curves(self, split: int) -> dict[tuple[int, int, str], np.ndarray]:
        """Each pair's normalised curve for the whole record and the four halves."""
        out: dict[tuple[int, int, str], np.ndarray] = {}
        for pos, a in enumerate(self.order):
            self.check()
            if not self._linked(pos):
                continue
            b = self.order[pos + 1]
            out[(a, b, "full")] = self.pairs.normalised(a, b)
            out[(a, b, "shallow")] = self.pairs.normalised(a, b, slice(0, split))
            out[(a, b, "deep")] = self.pairs.normalised(a, b, slice(split, None))
            out[(a, b, "first")] = self.pairs.normalised(a, b, half=0)
            out[(a, b, "second")] = self.pairs.normalised(a, b, half=1)
        return out

    def _pair(self, a: int, b: int, part: str) -> np.ndarray:
        """a's normalised curve against b over grid lags (a shifted along the axis)."""
        if (a, b, part) in self.curves:
            return self.curves[(a, b, part)]
        return self.curves[(b, a, part)][::-1]

    def curve(self, k: int, part: str, own: np.ndarray) -> np.ndarray:
        """k's curve against its neighbours, over its own-travel lags, with every other
        line moved by its own correction (`own`, metres) and k by the grid value only."""
        out = np.zeros(self.own_lags.size)
        for j in self.nb[k]:
            rel = (self.dirs[k] * self.grid - self.dirs[j] * (self.grid + own[j])) / STEP_M
            out += np.interp(
                self.dirs[k] * self.own_lags - rel, self.grid_lags, self._pair(k, j, part)
            )
        return out / len(self.nb[k])

    def classify(self, k: int, own: np.ndarray) -> str:
        """'no_match', 'changes', 'candidate' or 'grid', read against corrected neighbours."""
        names = ("full", "shallow", "deep", "first", "second")
        curves = {name: self.curve(k, name, own) for name in names}
        reading = {name: peak(c)[0] * STEP_M for name, c in curves.items()}
        if not is_clear(curves["full"]):
            return "no_match"
        decisive = {name: is_clear(curves[name], ratio=DECISIVE_RATIO) for name in names[1:]}
        along = abs(reading["first"] - reading["second"])
        if decisive["first"] and decisive["second"] and along > CHANGE_M:
            return "changes"
        u = reading["full"]
        if abs(u) < MIN_OWN_M:
            return "grid"
        tol = max(AGREE_M, AGREE_FRACTION * abs(u))
        clear = {name: is_clear(curves[name]) for name in names[1:]}
        confirmed = any(
            clear[a] and clear[b] and abs(reading[a] - reading[b]) <= tol for a, b in _HALVES
        )
        against = any(decisive[name] and abs(reading[name] - u) > tol for name in decisive)
        return "candidate" if confirmed and not against else "grid"

    def classify_all(self, own: np.ndarray) -> dict[int, str]:
        out = {}
        for k in sorted(self.nb):
            self.check()
            out[k] = self.classify(k, own)
        return out

    def _linked(self, p: int) -> bool:
        """Positions p and p + 1 in offset order are a pair of neighbours."""
        return p + 1 < len(self.order) and (self.order[p], self.order[p + 1]) in self.pairs.by_bin

    def _match(self, a: int, b: int, steps: np.ndarray) -> np.ndarray:
        """How well neighbours a, b (a first) line up when their own corrections sum to
        `steps` (own-travel steps; they walk opposite ways, so the sum is what moves them
        apart)."""
        at = -self.dirs[a] * (2 * self.grid / STEP_M + steps)
        return np.interp(at, self.grid_lags, self._pair(a, b, "full"))

    def solve_run(self, run: list[int], own: np.ndarray) -> np.ndarray:
        """The best corrections for a run of adjacent lines, each 0 or at least MIN_OWN_M,
        with the lines either side held: an exact search (Viterbi) along the run."""
        st = self.states.astype(float)
        penalty = np.where(st == 0, 0.0, OWN_GAIN)
        first, last = self.pos[run[0]], self.pos[run[-1]]
        score = -penalty
        back = []
        for t, k in enumerate(run):
            self.check()
            if t == 0:
                if first > 0 and self._linked(first - 1):
                    left = self.order[first - 1]
                    score = score + self._match(left, k, own[left] / STEP_M + st)
                continue
            prev = run[t - 1]
            if self._linked(self.pos[prev]):
                step = self._match(prev, k, st[:, None] + st[None, :])
            else:
                step = np.zeros((st.size, st.size))
            total = score[:, None] + step
            best = np.argmax(total, axis=0)
            back.append(best)
            score = total[best, np.arange(st.size)] - penalty
        if self._linked(last):
            right = self.order[last + 1]
            score = score + self._match(run[-1], right, st + own[right] / STEP_M)
        choice = [int(np.argmax(score))]
        for best in reversed(back):
            choice.append(int(best[choice[-1]]))
        out = own.copy()
        for k, i in zip(run, reversed(choice)):
            out[k] = st[i] * STEP_M
        return out

    def runs(self, candidates: set[int]) -> list[list[int]]:
        """Candidates grouped into runs of neighbours, in offset order."""
        out: list[list[int]] = []
        for p, k in enumerate(self.order):
            self.check()
            if k not in candidates:
                continue
            if out and out[-1][-1] == self.order[p - 1] and self._linked(p - 1):
                out[-1].append(k)
            else:
                out.append([k])
        return out

    def solve(self, candidates: set[int]) -> np.ndarray:
        """Own corrections for the candidates, refined to each line's own peak."""
        own = np.zeros(len(self.dirs))
        for run in self.runs(candidates):
            own = self.solve_run(run, own)
        return self.refine(own)

    def refine(self, own: np.ndarray) -> np.ndarray:
        """Each own value moved to the peak of its line's curve against the others, in
        offset order (one Gauss-Seidel sweep)."""
        own = own.copy()
        for k in sorted(np.flatnonzero(own), key=lambda k: self.pos[int(k)]):
            self.check()
            own[k] = -peak(self.curve(int(k), "full", own))[0] * STEP_M
        return own

    def _failing(self, own: np.ndarray, kinds: dict[int, str]) -> set[int]:
        """Own lines that no longer qualify against the others' corrections."""
        return {
            int(k)
            for k in np.flatnonzero(own)
            if kinds[int(k)] != "candidate" or abs(own[k]) < MIN_OWN_M
        }

    def run(self) -> LineVerdicts:
        own = np.zeros(len(self.dirs))
        kinds = self.classify_all(own)
        candidates = {k for k, kind in kinds.items() if kind == "candidate"}
        rejected: set[int] = set()
        for _ in range(MAX_PASSES):
            own = self.solve(candidates)
            kinds = self.classify_all(own)
            bad = self._failing(own, kinds)
            new = {k for k, kind in kinds.items() if kind == "candidate"}
            new -= candidates | rejected
            if not bad and not new:
                break
            rejected |= bad
            candidates = (candidates - bad) | new
        else:
            # Did not settle. Drop the own values that failed, re-fit the rest without them
            # (they were solved together) and read again, until every one left qualifies.
            # Each round drops at least one line, so this ends.
            while bad:
                own[sorted(bad)] = 0.0
                own = self.refine(own)
                kinds = self.classify_all(own)
                bad = self._failing(own, kinds)
        return LineVerdicts(
            own={int(k): float(own[k]) for k in np.flatnonzero(own)},
            changes=frozenset(k for k, kind in kinds.items() if kind == "changes" and own[k] == 0),
            no_match=frozenset(
                k for k, kind in kinds.items() if kind == "no_match" and own[k] == 0
            ),
        )
