# Task 13 re-review — fix round 1 (scoped)

Scope: did C1, I1, I2, M6, M7, controller-A and controller-B actually close, and did the
fixes introduce anything new. Range `8369154..ab371e3`. M1–M5 and M8 are parked and not
re-raised. The original implementation is not re-reviewed.

Method: every claim below is an executed result. I built an isolated copy of
`view_transform.py` and the committed test file outside the worktree and ran a 36-mutation
sweep against it (19 rounding/clamp, 17 span/guard); I shadowed `io/dzt.py` the same way to
compare guard orderings without touching the tree; and I probed PyQt 5.15.10 / Qt 5.15.13
directly for the event-handler question. `git status` is clean — nothing in the worktree was
modified.

## Per-finding status

| Finding | Status |
|---|---|
| C1 — rounding convention unpinned | **CLOSED** (see N1 for a durability caveat on the sample axis) |
| I1 — time-axis clamp untested | **STILL OPEN, partially** — 3 of 5 named survivors closed, 2 still alive |
| I2 — degenerate widget sizes untested | **CLOSED** |
| M6 + controller B — negative index on empty data | **CLOSED** |
| M7 — NaN poisons the transform | **CLOSED** in substance; the guard is correct and sufficient |
| Controller A — `parse_header` doesn't validate `range_ns` | **STILL OPEN** — `nan` and `+inf` still reach `ViewTransform.fit()` |

---

### C1 — CLOSED

`test_index_lookups_use_the_left_edge_convention` discriminates across the full range of
conventions, on **both** axes, and the clamp bounds are pinned in both directions on both
axes. Every mutation below died at a correctly-named test:

```
CAUGHT  trace floor->round                 test_index_lookups_use_the_left_edge_convention
CAUGHT  trace floor->ceil                  test_index_lookups_use_the_left_edge_convention
CAUGHT  trace floor->floor(x + 0.5)        test_index_lookups_use_the_left_edge_convention
CAUGHT  sample floor->round                test_index_lookups_use_the_left_edge_convention
CAUGHT  sample floor->ceil                 (new test + test_index_lookups_clamp_to_the_data)
CAUGHT  sample floor->floor(x + 0.5)       test_index_lookups_use_the_left_edge_convention
CAUGHT  upper n_traces-1  -> n_traces      test_index_lookups_clamp_to_the_data
CAUGHT  upper n_traces-1  -> n_traces-2    test_index_lookups_clamp_to_the_data
CAUGHT  upper n_samples-1 -> n_samples     test_index_lookups_clamp_to_the_data
CAUGHT  upper n_samples-1 -> n_samples-2   test_index_lookups_clamp_to_the_data
CAUGHT  lower max(0, ..)  -> max(-1, ..)   test_index_lookups_clamp_to_the_data  (both axes)
```

So the reviewer's question "only pinned at the probes chosen?" is answered *no* for the
subtler mutations I was asked to try: `floor(x + 0.5)` dies at `x = 41.0`
(`trace_of_x = 100.5125`, half-up gives 101), and an off-by-one in the clamp bound rather
than the rounding dies in both directions on both axes.

Three mutations survive, and all three are **equivalent mutants**, not gaps:

- `math.floor(...)` → `int(...)` on either axis. Truncation differs from floor only for
  negative arguments, which the `max(0, …)` immediately outside maps to 0 either way.
- `math.floor(v)` → `math.floor(v + 1e-9)`. Differs only within 1e-9 of a column edge.
- `upper = max(0, n - 1)` → `abs(n - 1)`. For `n == 0` the axis span is forced to 0.0 by
  `with_window` (`min(max(hi-lo, 4.0), float(0)) == 0.0`), so `trace_of_x ≡ trace_lo ≡ 0.0`
  and the index is 0 regardless of the upper bound.

The durability caveat on the sample-axis probe is N1 below.

### I1 — STILL OPEN, partially

Nine of eleven clamp mutations die, including four the implementer did not try and the
review did not name:

```
CAUGHT  drop MIN_SAMPLE_SPAN lower clamp            test_zoom_is_clamped_...
CAUGHT  MIN_SAMPLE_SPAN*dt -> MIN_SAMPLE_SPAN       test_zoom_is_clamped_...
CAUGHT  drop s_span upper clamp (n_samples*dt)      test_zoom_is_clamped_...
CAUGHT  drop downward time clamp (t_end - s_span)   test_pan_is_clamped_to_the_data
CAUGHT  t_end - s_span -> t_end (off by a span)     test_pan_is_clamped_to_the_data   [new]
CAUGHT  time lower bound t0_ns -> 0.0               test_pan_is_clamped_to_the_data   [new]
CAUGHT  max time span off by one sample             test_zoom_is_clamped_...          [new]
CAUGHT  drop trace upper clamp (n_traces - t_span)  test_pan_is_clamped_to_the_data
CAUGHT  trace max span n_traces -> n_traces + 1     test_zoom_is_clamped_...          [new]
```

That is a genuine improvement, and the four extra kills show the two extended tests are
load-bearing well beyond the specific mutations the implementer ran.

**But two of the five survivors the original review named by name are still alive:**

```
SURVIVED  MIN_TRACE_SPAN  = 4.0 -> 1.0
SURVIVED  MIN_SAMPLE_SPAN = 4.0 -> 1.0
```

This is the exact defect the review described in words. Its I1 text reads: "`z.trace_hi -
z.trace_lo == pytest.approx(MIN_TRACE_SPAN)` compares the implementation against the
imported constant, so `MIN_TRACE_SPAN = 4.0 → 1.0` survives too. **The suite pins '*some*
minimum exists', not 'the minimum is 4'.**" The fix imported `MIN_SAMPLE_SPAN` and wrote

```python
assert z.time_hi - z.time_lo == pytest.approx(MIN_SAMPLE_SPAN * FIT.dt_ns)
```

which is the same tautology, now on the second axis. Changing the constant changes both
sides of the comparison. The fix propagated the weakness rather than closing it.

The report's mutation table is headed "all survived-mutations from the review, now caught;
**none lived**" and its summary says "11 mutations tried this round, 0 survived". That is
accurate for the 11 mutations run and false as a statement about the review's survivor
list: two of the nine survivors the review published are untouched. The implementer's own
round-1 lesson — mutate the behaviours no test is named after — applies verbatim to the
constants, which still have no test named after them.

Impact if the constants drifted: zoom-in floor becomes 1 trace / 1 sample instead of 4.
At `MIN_TRACE_SPAN = 1.0` a single trace fills all 800 px and the cursor/selection bands
become a full-width wash; at `MIN_SAMPLE_SPAN = 1.0` the time axis floor drops to
0.2165 ns and `nice_ticks` starts returning repeated labels sooner. Not fatal, which is why
this is the lower half of an Important rather than a Critical — but both constants are in
the brief's public interface list and neither has its *value* pinned anywhere.

Minimum close: assert the literal, not the symbol.

```python
assert MIN_TRACE_SPAN == 4.0 and MIN_SAMPLE_SPAN == 4.0   # public interface constants
assert z.trace_hi - z.trace_lo == pytest.approx(4.0)
assert z.time_hi - z.time_lo == pytest.approx(4.0 * 0.2165)   # 0.866 ns
```

### I2 — CLOSED

```
CAUGHT  fit drops max(1, width/height)      test_degenerate_widget_sizes_are_floored_to_one_pixel
CAUGHT  resized drops max(1, width/height)  test_degenerate_widget_sizes_are_floored_to_one_pixel
```

Both guards are pinned independently; neither masks the other. The bare
`z.trace_index_at(0.0)` with no assertion is unusual style but it does what the comment says
(it would raise `ZeroDivisionError` if `width` stayed 0) and no weaker form would.

### M6 + controller finding B — CLOSED

```
CAUGHT  trace  upper -> self.n_traces - 1   test_index_lookups_never_go_negative_on_empty_data
CAUGHT  sample upper -> self.n_samples - 1  test_index_lookups_never_go_negative_on_empty_data
```

Both axes revert cleanly to the review's exact symptom and both die at the eponymous test.

**Is returning 0 the right contract?** Yes, for the Task 14/15 callers, though for a
slightly different reason than the review gave, and it is worth recording which.

- The review's stated hazard — "a `-1` is a perfectly valid numpy index that silently
  selects the *last* row" — is only true when `ViewTransform.n_traces` disagrees with the
  array actually being indexed. On a genuinely empty array both indices raise:
  `np.zeros((512, 0))[:, 0]` and `[:, -1]` are both `IndexError`. The dangerous case is the
  *mismatch* (`set_axes(n_traces=0, …)` while `RadargramImage` still holds a real image), and
  there `-1` silently aliases trace 607 of 608 while `0` aliases trace 0. Wrong-at-the-start
  is far more visible to a user than wrong-at-the-end, and it is the answer the clamp's own
  `max(0, …)` semantics already promise. So `0 > -1` holds.
- `0 > raise` because of where these run. `trace_index_at` is called from
  `trace_hovered.emit(...)` on **every mouse move** (task-14-brief:568), from
  `pick_requested` (543) and twice from `range_selected` (563-564). I confirmed on this
  machine's PyQt 5.15.10 / Qt 5.15.13 that an exception raised inside `mouseMoveEvent` prints
  its traceback to stderr and the process continues — it neither aborts nor reaches the
  caller. A raise here would therefore produce one stderr traceback (or, under QGIS's
  excepthook, one Python-error dialog) **per mouse move**, with no behavioural benefit.
- The values are total and in-range whenever the axis is non-empty, so nothing downstream has
  to special-case them.

Verdict: defensible, keep it. Two follow-ups: the contract lives only in an inline code
comment and a test name (N7), and the empty-axis state the new test now formally blesses is
still a live `ZeroDivisionError` on the *forward* maps (N6).

### M7 — CLOSED in substance; guard quantities verified correct

```
CAUGHT  remove the isfinite guard entirely  test_nan_inputs_raise_instead_of_silently_poisoning_the_window
```

**Does the guard check the right quantities?** Yes — and I verified this rather than reasoned
it. I substituted `nan`, `+inf` and `-inf` into every single argument and every pair of
arguments of `with_window` (4 singles + 6 pairs × 3 values each), plus every argument of
`zoomed` and `panned`, and checked whether any call returned a window with a non-finite
bound:

```
shipped guard, all four quantities (lo, t_span, tlo, s_span)   leaks = 0
```

Checking `lo`/`tlo`/`t_span`/`s_span` instead of the derived `trace_hi`/`time_hi` is correct
and not an oversight: `trace_hi = lo + t_span` where `lo ∈ [0, n_traces]` and
`t_span ∈ [MIN_TRACE_SPAN, n_traces]`, so the sum cannot overflow to `inf` once both addends
are finite; same for the time axis. The derived values are non-finite **iff** one of the four
checked values is.

**Can a legitimate interaction now raise where it previously produced a usable window?** Not
from any input Task 14 can generate. `panned` receives `QPoint` deltas (integers);
`wheelEvent` computes `1.25 ** (angleDelta().y() / 120.0)`, which is finite and non-zero for
any real wheel; `one_to_one` passes existing finite window state; `resized` does not route
through `with_window` at all. `±inf` arguments do not raise either — they clamp to a sensible
window (`with_window(inf, 300, 0, 20)` → `(604.0, 608.0, 0.0, 20.0)`), which is the right
call. In practice the guard fires only on NaN.

The one case where a previously-limping interaction now raises is a transform that was
**already** poisoned at construction, and that is a real hole — see N2.

**Is raising still right given Qt swallows slot exceptions?** Yes. I checked the actual
behaviour rather than assuming it (`QT_QPA_PLATFORM=offscreen`, PyQt 5.15.10):

```
BEFORE sendEvent
Traceback (most recent call last): ... ValueError: non-finite view window: SIMULATED
AFTER sendEvent -- process survived, exception did NOT propagate to caller
Traceback (most recent call last): ... ValueError: non-finite view window: SIMULATED-MOVE
AFTER mouseMove + processEvents -- still alive
EXIT=0
```

So the raise does not abort the process and does not reach the emitter — the documented
swallow. Critically, the assignment `self.transform = self.transform.panned(...)` never
completes, so **the widget keeps its last good transform and stays usable**. Compare the
pre-fix behaviour: the NaN window was stored, and every subsequent `trace_index_at` raised
`ValueError: cannot convert float NaN to integer` from an unrelated call site, permanently.
Raising is strictly better in both respects: it fails at the cause, and it fails
non-destructively. Keep it. The residual obligation falls on Task 14 (N5).

### Controller finding A — STILL OPEN

`if range_ns <= 0` closes zero and negative ranges. It does **not** close NaN or `+inf`,
because both comparisons are false. Executed against the shipped `parse_header`:

```
REJECTED  range=0.0      -> header declares a non-positive range: 0.0 ns
REJECTED  range=-1.0     -> header declares a non-positive range: -1.0 ns
REJECTED  range=-0.0     -> header declares a non-positive range: -0.0 ns
REJECTED  range=-inf     -> header declares a non-positive range: -inf ns
ACCEPTED  range=nan      -> range_ns=nan  dt_ns=nan
ACCEPTED  range=+inf     -> range_ns=inf  dt_ns=inf
```

And with a **real file** from `tests/data/local` whose `rh_rng` bytes are replaced with a
NaN pattern (`01 00 C0 7F` at offset 26):

```
BEFORE the fix: ACCEPTED (n_samples=512, bits=32, dt_ns=nan)
AFTER  the fix: ACCEPTED (n_samples=512, bits=32, dt_ns=nan)     <- unchanged
```

That `dt_ns` then travels the exact path the finding names — task-15-brief:272-273 passes
`line.header.position_ns` and `line.header.dt_ns` straight into `set_axes` →
`ViewTransform.fit()` — with these results:

```
fit(608, 512, -11.09, nan, 800, 300)  -> time=[-11.09, nan]     (constructed silently)
    source_rect()                     -> (0.0, nan, 608.0, nan)
    sample_index_at(150)              -> ValueError: cannot convert float NaN to integer
    zoomed(1.25, 400, 150)            -> ValueError: non-finite view window: ...
    panned(3, 5)                      -> ValueError: non-finite view window: ...
```

so the file opens, the viewer paints nothing, and every wheel notch and every pan drag raises.
`Radargram.__post_init__` does not save you here: it is correct (`if not self.dt_ns > 0`
rejects NaN) but it is downstream of the header-before-samples flow this guard exists to
protect.

The fix is one token, and the correct idiom is already in this repo four files away —
`processing/base.py:31` writes `if not self.dt_ns > 0:` precisely so NaN is rejected. Adding
`+inf` needs one more clause:

```python
if not math.isfinite(range_ns) or range_ns <= 0:
    raise DztError(f"header declares a non-finite or non-positive range: {range_ns} ns")
```

I verified `if not range_ns > 0:` alone catches NaN but still accepts `+inf`, so the
`isfinite` clause is load-bearing, not belt-and-braces.

**The repaired `test_rejects_unknown_bit_depth` was not weakened.** With the bit-depth guard
deleted from a shadow copy, the repaired header (`bits=24`, `range_ns=110.864`) parses
cleanly — `no raise` — so the test still fails for exactly the reason its name claims. The
`match="bit depth"` also means any future guard inserted above it breaks the test *loudly*
(wrong message) rather than silently, which is how this defect was caught in the first place.

**Nothing else constructs headers that now passes only incidentally.** I checked every one:
`test_rejects_zero_samples` (leaves `range_ns` at the zero-byte default, but the `n_samples`
guard runs first and its `match="samples"` does not match the range message, so a reorder
would break it loudly); `test_rejects_short_file` (100 bytes, never reaches any field guard);
the new `test_rejects_non_positive_range` (sets `bits=32`, so it reaches its own guard);
`tests/synthetic.py`'s `write_dzt` (`range_ns=110.864` default, and the only two callers that
override it pass `102.4`); the whole `nsgeo-qgis` qgis tier, which goes through
`plugin_testing.synthetic_dzt` → `write_dzt`; and
`test_pure_lookup.py:203` (`b"not a dzt file"`, 14 bytes → "too short", and it asserts only
on lookup.py's own `"cannot read header"` prefix, not the `DztError` text). The implementer's
`grep -rn "bytearray(1024)"` sweep and its conclusion both check out.

---

## New findings

**2 Important, 5 Minor, 0 Critical.**

### Important

#### N1. C1's sample-axis probe sits exactly on the floor/round tie, and survives on 3.55e-15 of float noise

The new test pins the sample axis with a single assertion:

```python
assert FIT.sample_index_at(FIT.y_of_time(FIT.t0_ns + 10.5 * FIT.dt_ns)) == 10
```

`10.5` is the one fraction at which `floor` and `round` agree, because Python's `round` is
banker's: `round(10.5) == 10 == math.floor(10.5)`. The assertion kills the `floor → round`
mutant today only because the round trip lands a hair *above* the tie:

```
y = 6.152343750000002    raw sample coord = 10.500000000000004
    floor 10 | round 11 | ceil 11 | floor(x+0.5) 11
    distance from 10.5: 3.552713678800501e-15
```

Change any of `FIT`'s time-axis parameters and the discrimination vanishes silently. I swept
312 nearby fixtures (13 plausible `dt_ns`, 6 widget heights, 4 `t0_ns`) and the assertion
fails to distinguish floor from round in **276 of 312** of them. Concrete cases, each
evaluated against a `floor → round` mutated module:

```
t0=-11.09,  dt=0.2165, h=300   round mutant -> 11   assertion FAILS  (mutant caught)   <- as shipped
t0=-11.086, dt=0.2165, h=300   round mutant -> 10   assertion PASSES (mutant survives)
t0= 0.0,    dt=0.1,    h=300   round mutant -> 10   assertion PASSES (mutant survives)
t0=-5.0,    dt=0.1,    h=300   round mutant -> 10   assertion PASSES (mutant survives)
```

Note the second line: `-11.086` is not a hypothetical — it is the `rhf_position` value
`tests/synthetic.py:55` already packs into every synthetic DZT. A one-character difference
between two values already present in this repo flips the sample axis back to exactly the
degenerate state C1 was raised about. The trace axis is fine (its probes sit 0.0125 and
0.49875 away from the tie); this is the sample axis only.

This is the same failure shape the review diagnosed — "the tolerance is fine; the *probe
point* is the problem" — reproduced in the fix for it. The shipped code is correct; only the
test's durability is at issue, which is why it is Important and not Critical.

Fix: move the probe off the tie to a fraction in `(0.5, 1.0)`, which discriminates floor
from `round`, `ceil` **and** `floor(x + 0.5)` simultaneously. A `10.7 * dt` probe is
degenerate in **0 of 312** of the same fixture sweep:

```python
assert FIT.sample_index_at(FIT.y_of_time(FIT.t0_ns + 10.7 * FIT.dt_ns)) == 10
assert FIT.sample_index_at(FIT.y_of_time(FIT.t0_ns + 10.2 * FIT.dt_ns)) == 10   # optional, pins ceil
```

#### N2. M7's guard covers the mutators but not the constructor, which is the one that takes untrusted input

`with_window` now refuses to build a non-finite window. `ViewTransform.fit()` still builds
one, silently:

```python
>>> t = ViewTransform.fit(n_traces=608, n_samples=512, t0_ns=-11.09,
...                       dt_ns=float("nan"), width=800, height=300)
>>> t.time_lo, t.time_hi
(-11.09, nan)                      # constructed, no exception
>>> t.sample_index_at(150.0)
ValueError: cannot convert float NaN to integer
```

`t0_ns` does it too — `ViewTransform.fit(608, 512, float("nan"), 0.2165, 800, 300)` gives
`time=[nan, nan]`, and `rhf_position` at header offset 22 is read with no validation at all,
then handed to `set_axes` by task-15-brief:273.

This is the precise failure mode the fix-round report justifies M7 by preventing: "a
partially-NaN `ViewTransform` that only fails later, at an unrelated call site
(`trace_index_at` raising `ValueError: cannot convert float NaN to integer`), with the stack
trace pointing at the wrong place." The guard was placed at the choke point for *window
changes*, but the choke point for *entering the module* is `fit`, and `fit` is the one that
receives floats straight off a DZT header. The state is reachable today through controller
finding A's remaining NaN hole (above); with A fully closed it becomes unreachable via
`range_ns` but stays reachable via `position_ns`.

Fix, matching the style already chosen for `with_window`:

```python
@classmethod
def fit(cls, n_traces, n_samples, t0_ns, dt_ns, width, height):
    if not all(math.isfinite(v) for v in (t0_ns, dt_ns)):
        raise ValueError(f"non-finite axes: t0_ns={t0_ns}, dt_ns={dt_ns}")
    ...
```

That moves the failure to `set_axes`, at survey-open time, where Task 15 can report it
through the plugin's `message()` convention — instead of onto the user's first wheel notch.

### Minor

#### N3. The M7 test does not pin *which* quantities the guard checks

All three call shapes in `test_nan_inputs_raise_instead_of_silently_poisoning_the_window`
(`zoomed(nan, …)`, `panned(nan, 0.0)`, `with_window(nan, 110.0, 0.0, 20.0)`) put the NaN into
`trace_lo`, so they all poison `lo` and `tlo`. Narrowing the guard to
`(lo, tlo)` survives the whole suite, and leaks 17 ways:

```python
>>> FIT.with_window(100.0, float("nan"), 0.0, 20.0)   # under a (lo, tlo)-only guard
ViewTransform(..., trace_lo=100.0, trace_hi=nan, time_lo=0.0, time_hi=20.0)
```

(`max(nan, 4.0)` returns `nan` but `min(max(100.0, 0.0), 608 - nan)` returns `100.0`, so
`lo` stays clean while `t_span` is poisoned.) Two more assertions close it:

```python
with pytest.raises(ValueError):
    FIT.with_window(100.0, float("nan"), 0.0, 20.0)      # NaN reaches t_span only
with pytest.raises(ValueError):
    FIT.with_window(100.0, 300.0, 0.0, float("nan"))     # NaN reaches s_span only
```

Narrowing to `(t_span, s_span)`, and narrowing to a NaN-only test (`v != v`), are both
equivalent mutants — 0 leaks each — so they are not gaps.

#### N4. The new guard's position ahead of the bit-depth check costs diagnostic quality on about half of all non-DZT files

The new check sits between `n_samples` and `bits`. For 200,000 random 1024-byte buffers (the
"user pointed the importer at something that isn't a DZT" case):

```
BEFORE: {'bit depth': 199989, 'ACCEPTED': 9, 'zero samples': 2}
AFTER : {'bit depth': 100249, 'non-positive range': 99743, 'ACCEPTED': 6, 'zero samples': 2}
```

Half of those files now report `header declares a non-positive range: -1.7014e+38 ns` where
they used to report `unsupported bit depth 51234; expected one of [8, 16, 32]`. The bit-depth
message is the better one for this case: it is a three-value identity check that says "this
is not a DZT", whereas the range message reads like a plausible DZT with a bad setting and
invites the user to go looking for a fix that does not exist.

The order is defensible — it is consistent with the existing `n_samples` plausibility check
also sitting ahead of `bits` — and the realistic named case is unaffected (a real `.DZX`
sidecar fed to `parse_header` still reports `unsupported bit depth 25974` both before and
after, because its bytes at offset 26 happen to be a positive float). The new guard also
tightens the sieve slightly (`ACCEPTED` 9 → 6 per 200k). But moving the `bits` check above
the `range_ns` check is a free improvement, and it is safe: `test_rejects_non_positive_range`
already sets `bits=32`, so it keeps passing. Do **not** move `range_ns` above `n_samples` —
that would break `test_rejects_zero_samples`, which leaves `range_ns` at the zero default.

#### N5. The new raise lands on a Qt event-handler path that Task 14's brief does not guard

`plugin.py`'s module docstring states the project's rule: "Every slot below that does real
work … guards its own body and reports failure through `message()` … rather than let a
real-world failure … disappear into stderr while the user is left thinking nothing happened."
`with_window` now raises, and its callers on the interactive path — `zoom_at`
(task-14-brief:401, reached from `wheelEvent`) and `mouseMoveEvent` (556) — have no
`try/except` in the brief's reference code. Confirmed above on PyQt 5.15.10: the traceback
goes to stderr, the process lives, the widget keeps its last good transform. Under QGIS's
`sys.excepthook` it becomes a Python-error dialog instead — once per wheel notch, or once per
mouse-move sample during a pan drag, if the transform is persistently poisoned (which N2
makes possible).

Not a defect in this round's code — it is a carry-forward obligation onto Task 14, which is
next. Wrap `zoom_at` and the `panned` branch of `mouseMoveEvent` and route to `message()`,
per the module docstring. Worth writing into the Task 14 brief now rather than discovering it
in Task 14's review.

#### N6. The empty-axis state the new M6 test blesses is a live `ZeroDivisionError` on the forward maps

`test_index_lookups_never_go_negative_on_empty_data` establishes `fit(n_traces=0, …)` and
`fit(n_samples=0, …)` as representable states and pins `trace_index_at` / `sample_index_at`
on them. The *inverse* maps on those same two objects still raise:

```
n_traces=0   window=(0.0, 0.0, -11.09, 99.758)
    x_of_trace(0)   -> ZeroDivisionError: float division by zero
    y_of_time(0)    -> 30.014...            (fine)
n_samples=0  window=(0.0, 608.0, -11.09, -11.09)
    x_of_trace(0)   -> 0.0                  (fine)
    y_of_time(0)    -> ZeroDivisionError: float division by zero
```

Task 14 calls `x_of_trace` from `_paint_cursor`, `_paint_selection`, `_paint_picks` and
`_paint_axes`, and `y_of_time` from the depth and time tick paths — i.e. on every repaint, so
this is the `paintEvent` variant of the swallowed-exception trap. The finiteness guard does
not help: a zero-span window is entirely finite. This half of M6 was listed in the original
review's first bullet and was outside the controller's stated scope for this round (which was
the negative index, both axes), so it is recorded here rather than counted against M6.

Two ways to close it, whichever the controller prefers: floor the spans in `with_window` and
`fit` (`t_span = max(t_span, MIN_TRACE_SPAN)` unconditionally, accepting a window wider than
the data for an empty axis), or reject an empty axis at `fit` the same way N2 rejects a
non-finite one. The second is probably right — an empty radargram has nothing to show.

#### N7. Two contract details are recorded only in comments

- `test_nan_inputs_raise_instead_of_silently_poisoning_the_window` uses bare
  `pytest.raises(ValueError)` with no `match=`. Every `test_rejects_*` in `test_dzt_header.py`
  uses `match=`, and this round's own bit-depth incident is the argument for it: a `match=`
  turns a guard that starts firing for the wrong reason into a loud failure. `match="non-finite"`
  costs nothing.
- `trace_index_at` and `sample_index_at` have no docstring, so the empty-axis contract ("0,
  never -1") exists only in an inline comment and a test name. Tasks 14, 15 and 18 all consume
  these. One line each.

---

## Summary

The round closed C1, I2, M6 and controller finding B outright, and closed M7's substance with
a guard whose quantity choice I verified exhaustively rather than took on trust. Two things
did not close: **I1** left two of the review's five named survivors alive by re-using, on the
time axis, the same constant-compared-against-itself assertion the review had criticised on
the trace axis; and **controller finding A** closed `0` and `< 0` while leaving `nan` and
`+inf` to reach `ViewTransform.fit()` by the very path the finding was written about. Both
have one-line fixes. The two new Important findings are of a piece with those: a probe placed
on the one fraction where the conventions agree (N1), and a guard placed on the mutators but
not the constructor (N2). Nothing found in this round is a live defect against real data; all
of it is about whether the next change to this module will be caught.
