# Task 13 review — `ViewTransform`

Reviewed: `bb5fef8..8369154` (1 commit, 3 files, +224/-1).

## Verdicts

- **Spec compliance: PASS.** Every name, signature, parameter order, constant and file
  path in the brief's interface line is present exactly as specified. The committed module
  is semantically identical to the brief's Step 3 reference code (the only textual
  difference is a magic trailing comma in the `zoomed` → `with_window` call, which forces a
  4-line wrap where `ruff format` would otherwise keep one 100-column line; both forms are
  `ruff format` stable). The committed test file is **byte-identical** to the brief's Step 1
  test block after `ruff check --fix --select E,F,I,UP,B,SIM` + `ruff format --line-length
  100` — I reproduced this exactly, so the report's "verbatim in substance" claim is
  accurate, including the `0.0 <= z.trace_lo` → `z.trace_lo >= 0.0` rewrite (ruff SIM300,
  which the report did not name but which is ruff's doing, not a hand edit).

- **Task quality: CHANGES REQUESTED.** The *implementation* is good — better than the
  report argues. Under 20,000 randomised operation sequences (mixed `zoomed`/`panned`/
  `resized(0..2000, 0..2000)`/`with_window` with out-of-range arguments) the window
  invariants never break once: `source_rect()` stayed inside `[0, 608] × [0, 512]` with
  `w ≥ MIN_TRACE_SPAN` and `h ≥ MIN_SAMPLE_SPAN·dt` in every one of them. Repeated `zoomed`
  at a corner anchor, pan past both ends of both axes, and zoom-then-resize ordering all
  hold. I found no behavioural defect in the shipped code.

  The *test suite* is the problem, and the hole is in the one place this task said matters
  most: **the rounding convention of `trace_index_at` is not pinned by any test.** Changing
  `math.floor` to `round` or to `math.ceil` leaves all 9 tests green. That is the exact
  "pick lands on the wrong trace, silently" failure the task brief names, and it is
  currently undefended for Tasks 14, 15 and 18.

Finding counts: **1 Critical, 3 Important, 7 Minor.**

Method note: I ran a 27-mutation sweep against the committed test file (each mutation
applied to a scratch copy, never to the worktree; `git status` verified clean before and
after every run). 18 were caught, 9 survived. Everything below is a confirmed, executed
result, not a reading of the code.

---

## Critical

### C1. The trace/sample rounding convention is unpinned — `floor`→`round` and `floor`→`ceil` both survive the whole suite

`test_index_lookups_clamp_to_the_data` is the only test that touches `trace_index_at` /
`sample_index_at`, and its interior probes are degenerate:

```
trace_of_x(400)                       = 304.0                 exactly  → floor = round = ceil = 304
(time_of_y(150) - t0_ns) / dt_ns      = 256.00000000000006    → floor = round = 256
```

The other four assertions (`-50`, `800`, `-5`, `300`) only exercise the `max(0, …)` and
`min(n-1, …)` clamps. So **no assertion in the suite distinguishes floor from round**, and
`sample_index_at`'s `floor`→`round` mutation survives too. (`floor`→`ceil` in
`sample_index_at` is caught, but only incidentally, by the unrelated
`sample_index_at(300) == 511` clamp assertion — not by anything that names the convention.)

Concrete failure this permits. Window `[100, 110)` traces across 800 px = 80 px per trace:

| mouse x | correct (`floor`) | `round` variant | cursor drawn at `x_of_trace(idx + 0.5)` |
|---|---|---|---|
| 41.0 | 100 | **101** | 120 px — 79 px right of the pointer |
| 79.0 | 100 | **101** | 120 px |
| 120.0 | 101 | **102** | 200 px |

The `round` variant is wrong for **the entire right half of every trace column**. Task 14
draws the cursor at `t.x_of_trace(self._cursor + 0.5)` (task-14-brief line 444), i.e. the
column *centre*, which confirms `floor` is the correct inverse of the edge convention
(`x_of_trace(i)` is the left edge of column `i`). `pick_requested` emits
`self.transform.trace_index_at(x)` (line 543) and `range_selected` emits two of them (lines
563-564), so a regression here writes the wrong trace index into authored picks and
selections. Silent, plausible-looking, and permanent in the project file.

**This is a defect in the brief**, and it refutes the report's headline claim. The
implementer writes "this brief's reference implementation had no defects" — true of the
*implementation*, false of the *test*: the brief's test for the module's single most
consequential behaviour is vacuous with respect to that behaviour. The report even
identifies the smoking gun ("`55.424/0.2165` sits at the 256.0 knife-edge") and then draws
the opposite conclusion — that the `in (255, 256)` tolerance "is correct, not a hedge
around a bug". The tolerance is fine; the *probe point* is the problem, and the same
problem afflicts `trace_index_at(400)`. I would keep the brief's assertions and **add**
non-degenerate probes; I would not relax anything.

Minimum fix (one test, no implementation change):

```python
def test_index_lookups_use_the_left_edge_convention():
    z = FIT.with_window(100.0, 110.0, 0.0, 20.0)   # 80 px per trace
    assert z.trace_index_at(0.0) == 100
    assert z.trace_index_at(41.0) == 100           # fails under round/ceil
    assert z.trace_index_at(79.9) == 100           # fails under round/ceil
    assert z.trace_index_at(80.1) == 101
    assert z.trace_index_at(z.x_of_trace(105) + 0.1) == 105
    # sample axis, off the sample boundary
    assert FIT.sample_index_at(FIT.y_of_time(FIT.t0_ns + 10.5 * FIT.dt_ns)) == 10
```

---

## Important

### I1. The entire vertical (time) half of the clamp logic is untested — three mutations survive

All three of these leave 9/9 passing:

1. deleting `max(time_hi - time_lo, MIN_SAMPLE_SPAN * self.dt_ns)` (the minimum time span);
2. deleting `min(…, self.n_samples * self.dt_ns)` (the maximum time span);
3. deleting `min(…, self.t_end - s_span)` (the *downward* pan/zoom clamp).

`MIN_SAMPLE_SPAN` is a public constant in the brief's interface list and **is never
imported by the test file at all** — setting it to `1.0` also survives. Its horizontal twin
is only half-defended: `z.trace_hi - z.trace_lo == pytest.approx(MIN_TRACE_SPAN)` compares
the implementation against the imported constant, so `MIN_TRACE_SPAN = 4.0 → 1.0` survives
too. The suite pins "*some* minimum exists", not "the minimum is 4".

Concrete failures each deletion permits:

- **(1)** `with_window(0, 608, 40.0, 40.0)` → `time_hi == time_lo` → `y_of_time` raises
  `ZeroDivisionError` **inside `paintEvent`**, which on this project is exactly the
  swallowed-slot-exception trap. Short of that exact input, ~500 wheel clicks
  (`1.25**steps`) at one anchor collapse the span to 1.4e-14 ns — 6.6e-14 of one sample —
  at which point `time_of_y` is constant across the widget, every pixel reports the same
  sample index, and `nice_ticks(time_lo, time_hi)` returns `[55.375, 55.375, 55.375]`:
  three identical axis labels. The correct implementation clamps to 0.866 ns = 4.0 samples.
- **(3)** `FIT.with_window(100, 300, 0, 20).panned(0.0, -100_000.0)` → time window
  `(6666.7, 6686.7)` ns against `t_end = 99.758`; `source_rect()` returns
  `(100.0, 30844.1, 200.0, 92.4)` — a source rectangle 30,000 rows below a 512-row image,
  so Task 14's `drawImage` paints nothing and the viewer goes **blank on a downward drag**,
  with no exception and no way for the user to recover except Fit. `test_pan_is_clamped_to_the_data`
  checks only the *upward* pan (`up.time_lo == approx(-11.09)`); the downward direction has
  no assertion anywhere.
- **(2)** `test_zoom_is_clamped_to_the_data_and_a_minimum_span` asserts only
  `out.trace_lo` / `out.trace_hi`. It never looks at the time axis, so zoom-out past the
  record is unguarded by tests in both the min and max directions.

Fix: assert the time axis alongside the trace axis in the two existing clamp tests, import
`MIN_SAMPLE_SPAN`, and add the downward pan case. Roughly four extra assertions.

### I2. The degenerate-widget-size guards in `fit` and `resized` are untested

Deleting `max(1, width)` / `max(1, height)` from either `fit` or `resized` survives the
suite. These are not theoretical: Task 14's `image_rect()` subtracts
`MARGIN_LEFT=56 + MARGIN_RIGHT=48`, so a dock dragged narrower than 104 px yields
`r.width() <= 0`, and `resizeEvent` feeds that straight into `resized`. With the guard
removed, `resized(0, 300)` gives:

```
x_of_trace(10)   =  0.0      x_of_trace(600) = 0.0    # every trace collapses onto pixel 0
trace_of_x(5.0)     -> ZeroDivisionError
trace_index_at(5.0) -> ZeroDivisionError   # raised inside mouseMoveEvent
zoomed(1.25, 5, 5)  -> ZeroDivisionError   # raised inside wheelEvent
```

i.e. the viewer dies on the next mouse move after a narrow resize. The shipped code is
correct; nothing defends it. `assert FIT.resized(0, 0).width == 1` is a one-line fix.

### I3. The mutation testing targeted only behaviours that already have eponymous tests, so it confirmed wiring rather than measuring strength

The report calls its three mutations "the three least-obvious behaviours", but each one has
a test *named after it* — `test_zoom_keeps_the_point_under_the_anchor_fixed`,
`test_pan_is_clamped_to_the_data`, `test_round_trips`. Mutating a behaviour a test is named
after is near-certain to be caught; those three runs demonstrate that the tests are wired
up, not that the suite is strong. The report then generalises from them: "the clamp is
defended" (only the *right-edge trace* clamp is; three of the other four clamp directions
are not — I1), and **Concerns: None**.

The report also flags, correctly, that "Task 14 depends on these exact shapes without
further scrutiny of its own" — which makes the un-mutated behaviours the ones that needed
the attention. A useful heuristic for the next task: mutate the behaviours that *no test is
named after*. Here that list was short and would have surfaced C1 immediately —
`math.floor`, `MIN_SAMPLE_SPAN`, `max(1, width)`, and the two unasserted clamp directions.

Nine of my 27 mutations survived:

```
SURVIVED  floor->round in trace_index_at            <- C1
SURVIVED  floor->ceil  in trace_index_at            <- C1
SURVIVED  floor->round in sample_index_at           <- C1
SURVIVED  drop MIN_SAMPLE_SPAN lower clamp          <- I1
SURVIVED  drop s_span upper clamp (n_samples*dt)    <- I1
SURVIVED  drop time upper clamp (t_end - s_span)    <- I1
SURVIVED  MIN_TRACE_SPAN 4.0 -> 1.0                 <- I1
SURVIVED  MIN_SAMPLE_SPAN 4.0 -> 1.0                <- I1
SURVIVED  fit drops max(1, width/height)            <- I2
SURVIVED  resized drops max(1, width/height)        <- I2
SURVIVED  nice_ticks drops np.round                 <- M1
SURVIVED  nice_ticks drops the 1e-9 in `first`      <- M4
SURVIVED  nice_ticks reversed-range guard weakened  <- M5
```

(The 18 caught include both zoom-anchor mutations, the trace clamps in both directions,
`t_end` and `fit`'s `time_hi` off-by-one-sample, the `panned` dy sign flip,
`x_of_trace` using `width - 1`, `source_rect`'s width, and two `nice_ticks` epsilon
mutations. The suite is genuinely load-bearing everywhere it does reach.)

---

## Minor

### M1. `np.round(ticks, 10)` in `nice_ticks` is not magnitude-safe, and buys nothing

- `nice_ticks(0.0, 1e-11)` → `[0., 0., 0., 0., 0., 0.]` — six identical zero ticks; every
  tick is rounded away.
- `nice_ticks(0.0, 1e300)` → `[0., inf, inf, inf, inf, inf]` plus a numpy
  `RuntimeWarning: overflow encountered in multiply` (round-to-10-dp multiplies by 1e10,
  which overflows above ~1.8e298).

Neither magnitude is reachable here: the time axis is ns (min span `4·dt` ≈ 0.2–4 ns), and
the depth and distance axes are metres (min span ~0.01 m), so the smallest `step` in
practice is ~1e-3. And the rounding is redundant anyway — Task 14 formats every tick with
`f"{tick:g}"`, which already suppresses float dust, and `_depth_ticks` uses the value
numerically via `np.interp`. Deleting the line survives the suite, which is consistent with
it being a no-op. Suggest dropping it, or replacing it with a magnitude-relative round.

### M2. `nice_ticks` raises on infinite bounds, returns empty on NaN

`nice_ticks(0.0, inf)` and `nice_ticks(-inf, 0.0)` → `OverflowError: cannot convert float
infinity to integer` (from `math.floor(math.log10(inf))`). NaN is handled gracefully
(`not vmax > vmin` is True → empty array), which is the right behaviour. All four Task 14
call sites derive their bounds from finite window state, so this is unreachable today.

### M3. `target` is uncapped: `nice_ticks(0.0, 10.0, target=100000)` returns 100,001 ticks

`max(1, target)` guards `target <= 0` (both `target=0` and `target=-5` give a sane 2-tick
result) but there is no upper bound. Every caller uses the default 6; noted only because
the function is public and Task 18's gain strip may want its own tick density.

### M4. The `1e-9` epsilon in `first = math.ceil(vmin / step - 1e-9) * step` is untested

Deleting it survives the suite. It is the guard against `vmin` being a hair above an exact
multiple of `step` (which would drop the first tick). It is also an *absolute* epsilon in
units of tick counts, so it silently stops doing anything once `vmin/step` exceeds ~1e7 —
float spacing at 1e7 is larger than 1e-9. Harmless at ns/metre magnitudes.

### M5. The `not vmax > vmin` guard is load-bearing and untested for the reversed case

Weakening it to `vmax == vmin` survives the suite, and turns a reversed range into
`ValueError: math domain error` from `math.log10` of a negative `raw`. The shipped guard
correctly returns an empty array. Every Task 14 call site orders its arguments (line 522
uses an explicit `min`/`max`), so this is unreachable today; the test only covers
`vmin == vmax`.

### M6. Empty-data degeneracies: `n_samples == 0` returns a silent `-1` index

- `ViewTransform.fit(n_traces=0, …)` → `trace_hi == trace_lo == 0.0` → `x_of_trace` and
  `trace_of_x` raise `ZeroDivisionError`.
- `ViewTransform.fit(n_samples=0, …)` → **`sample_index_at(150)` returns `-1`**, and
  `source_rect()` returns `h = 0.0`. A `-1` is a perfectly valid numpy index that silently
  selects the *last* row — of the two failure modes this is by far the more dangerous, and
  it is the one that does not announce itself.
- `dt_ns == 0` → `ZeroDivisionError` from `sample_index_at` and `source_rect`.

None of these is reachable through today's pipeline: `Radargram.__post_init__` rejects
`dt_ns <= 0` (`processing/base.py:30`), the DZT reader rejects zero samples
(`io/dzt.py:79`) and zero traces (`io/dzt.py:118`), and `TimeZero.apply` refuses a shift
that would consume the record (`processing/timezero.py:74`). So this is a latent hazard,
not a live defect — but it becomes live the moment any future step can yield an empty
radargram, and a `min(n-1, max(0, …))` clamp that can return `-1` is the kind of thing
worth a `max(0, n - 1)` on the upper bound now that it costs one token.

### M7. NaN arguments poison the transform silently instead of raising

`FIT.zoomed(float('nan'), 400, 150)` returns a window of `(nan, nan, nan, nan)` — no
exception. Every subsequent `trace_index_at` then raises `ValueError: cannot convert float
NaN to integer`, so the viewer is permanently dead with the stack trace pointing at the
*wrong* call. `panned(nan, 0.0)` poisons the trace axis only, leaving the time axis intact —
a half-dead transform. By contrast `zoomed(0.0, …)` fails fast with `ZeroDivisionError`,
and `trace_index_at(nan)` / `trace_index_at(inf)` fail fast with
`ValueError`/`OverflowError`, which is the preferable behaviour. Unreachable from Task 14
(the wheel factor is `1.25**steps` and drag deltas are integers), so this is a robustness
observation rather than a bug.

### M8. `source_rect`'s "image pixels" docstring means *unbinned* trace/sample indices

The returned rect is in trace-index and sample-index units. Task 14 correctly rescales it
(`sx = self._image.width() / t.n_traces`, `sy = self._image.height() / t.n_samples`,
task-14-brief line 425-429) because `RadargramImage` may have run `decimate_columns` at
`max_width=8192`. That is the right split of responsibility, but "in image pixels" invites
the opposite reading — that the rect can be handed straight to `drawImage` — which would
silently draw the wrong horizontal region of any decimated profile (a 20,000-trace line
would be off by a factor of 2.4). Worth one clause in the docstring: "in unbinned
trace/sample units; scale by the rendered image's dimensions if it was decimated."

---

## What is right, and worth saying

- The edge convention is coherent end to end: `x_of_trace(i)` is the left edge of column
  `i`, `trace_index_at` is `floor`, and Task 14 adds `+ 0.5` to draw at the centre. The same
  convention governs the time axis. This is the part that is easiest to get subtly wrong and
  it is right.
- `fit` matches Task 14's two positional call sites (lines 332, 385) exactly, and
  `nice_ticks(vmin, vmax, target=6)` matches all four of its call sites. No breaking change
  to already-written downstream code.
- Frozen throughout: `zoomed`, `panned`, `resized` and `with_window` all go through
  `dataclasses.replace`; there is no attribute assignment anywhere in the module.
- Import boundary is clean (`math`, `dataclasses`, `numpy`), `from __future__ import
  annotations` present, CI mypy line correctly extended, and the return annotation style
  (bare `np.ndarray`) matches the convention used throughout `nsgeo-core`.
- Over 200,000 random `nice_ticks` ranges spanning 12 orders of magnitude, no tick ever fell
  outside `[vmin, vmax]` and no call produced a runaway array. The 1-2-5 selection and both
  epsilons are sound.
- The clamps are genuinely un-defeatable by operation sequencing. I tried specifically for
  the failure modes the task named — repeated `zoomed` at a corner anchor (60 iterations,
  lands exactly on `(0, 4)` and `(604, 608)`), `panned` past both ends of both axes, and
  `resized` to degenerate sizes interleaved with zoom — and found nothing. The report
  undersells this by not testing for it.

## Recommendation

Add the C1 test (six assertions, no implementation change) before Task 14 starts, since
Tasks 14, 15 and 18 all route picking and hovering through `trace_index_at`. I1 and I2 are
worth the four-to-five extra assertions in the same sitting. No implementation change is
required for any finding; M6 (`sample_index_at` returning `-1`) and M8 (the docstring) are
the only two I would consider touching the module for, and both are optional.
