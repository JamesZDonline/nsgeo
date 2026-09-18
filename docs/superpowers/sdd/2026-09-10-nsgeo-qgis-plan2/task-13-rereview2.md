# Task 13 re-review — fix round 2 (scoped, final)

Scope: did the six named items close, and did these fixes introduce anything new. Range
`ab371e3..a650ecb`. The parked minors (guard ordering, "pin which quantities the guard
checks", the two contract-in-comments items) and the Task-14 slot-guarding carry-forward
are not re-raised.

Method: every claim below is an executed result, not a reading. I built a shadow
`nsgeo_qgis.ui.view_transform` package and a full shadow `nsgeo` package outside the
worktree and ran a 31-mutation sweep (23 on `ViewTransform`, 6 on `dzt.py`, plus 8 extra
I1 constant mutations) against the committed test files; a 390-fixture probe-degeneracy
sweep; and a 40,000-operation fuzz of legitimate window changes. `git status --porcelain`
in the worktree is empty — nothing under review was modified.

*Method note worth recording:* my first mutation run reported three false SURVIVEDs from
stale `__pycache__` (two mutants differed in neither file size nor mtime-second, so CPython
reused the previous `.pyc`). Every result below was re-run with `PYTHONDONTWRITEBYTECODE=1`
and hand-confirmed on the survivors. Anyone repeating this sweep should set that variable.

## Per-finding status

| Finding | Status |
|---|---|
| I1 — the two surviving constant mutants | **CLOSED** |
| Controller A — `nan`/`+inf` reaching `fit()` via `range_ns` | **CLOSED** |
| `rhf_position` → `t0_ns` (previously unvalidated) | **CLOSED** |
| N1 — the sample-axis probe on the floor/round tie | **CLOSED** |
| N2 — the constructor gap | **CLOSED** |
| N6 — the empty-axis divide-by-zero | **CLOSED** |

---

### I1 — CLOSED

Both constants now die, and they die at **two independent tests**, so neither is propping
up the other:

```
MIN_TRACE_SPAN  4.0 -> 1.0    caught -> test_minimum_span_constants_are_four,
                                        test_zoom_is_clamped_to_the_data_and_a_minimum_span
MIN_SAMPLE_SPAN 4.0 -> 1.0    caught -> (both, same two)
MIN_TRACE_SPAN  4.0 -> 3.0 / 4.001 / 8.0     caught (both tests, every value)
MIN_SAMPLE_SPAN 4.0 -> 3.0 / 4.001 / 8.0     caught (both tests, every value)
```

A 0.025 % drift (`4.0 → 4.001`) is enough to kill it, so this is a genuine value pin and
not a coarse sanity band.

**Are the literals independently derived?** Yes. `pytest.approx(4.0)` and
`pytest.approx(4.0 * 0.2165)` read neither `MIN_TRACE_SPAN`, `MIN_SAMPLE_SPAN`, nor
`FIT.dt_ns` — both operands are literals, so the constant under test appears on only one
side of the comparison. That is the structural difference from round 1's
`approx(MIN_SAMPLE_SPAN * FIT.dt_ns)`, and it is the difference that matters: the round-1
form held for every value of the constant, this one holds for exactly 4.0. The `0.2165` is
a restatement of `FIT`'s own constructor literal, which is the correct kind of duplication
(a fixture value restated) rather than the tautological kind (the implementation's own
symbol restated). The unit factor is still pinned too — the round-1 units mutation
`MIN_SAMPLE_SPAN * self.dt_ns → MIN_SAMPLE_SPAN` and a new `→ MIN_SAMPLE_SPAN * 1.0` both
die at `test_zoom_is_clamped_to_the_data_and_a_minimum_span`.

**Both constants on both axes?** Yes: each axis's *effect* is pinned by its own literal
assertion in the clamp test, and both symbols' *values* are pinned in
`test_minimum_span_constants_are_four`. Two mutations survive and both are true equivalent
mutants, not gaps: making the trace clamp read `MIN_SAMPLE_SPAN` and making the time clamp
read `MIN_TRACE_SPAN` are behaviourally identical while both constants are 4.0.

### Controller finding A (`range_ns`) — CLOSED

Against a shadow `nsgeo` package, all three range mutations die at the eponymous test:

```
drop the isfinite clause, keep `range_ns <= 0`   caught -> test_rejects_non_finite_or_non_positive_range
drop the `<= 0` clause, keep isfinite            caught -> test_rejects_non_finite_or_non_positive_range
remove the range guard entirely                  caught -> test_rejects_non_finite_or_non_positive_range
```

Both clauses are load-bearing and both are pinned — the second mutation is the one the
round-1 fix would have survived. The three-case loop (`0.0`, `nan`, `+inf`) is what earns
that.

### `rhf_position` → `t0_ns` — CLOSED

```
remove the position guard entirely            caught -> test_rejects_non_finite_position
isfinite -> not isnan (i.e. accept +-inf)     caught -> test_rejects_non_finite_position
tighten to `if not position > 0`              caught -> 70+ tests, including all ten
                                                       test_header_matches_verified_expectations[FILE__001..010.DZT]
```

The third mutation is the interesting one. The decision the implementer had to get right
here was *finiteness, not positivity* — and that decision is not merely asserted in a
comment, it is pinned by the real data itself: tightening the guard to `> 0` breaks every
real-file test in the core suite. That is the strongest possible regression barrier for
this choice, and it is there by construction rather than by intent.

I confirmed the two guards are complete for the failure they target — see **Q5** below.

### N1 — CLOSED

The `10.7` probe is not merely non-degenerate at the shipped `FIT` values; it is
non-degenerate everywhere I could make it fail. Swept 390 fixtures (13 `dt_ns` × 6 widget
heights × 5 `t0_ns`, including the real `-11.086392402648926`, the synthetic `-11.086`,
`0.0` and `-5.0`), requiring at each one that `floor` give 10 **and** that `round`, `ceil`
and `floor(x + 0.5)` all *not*:

```
OLD probe 10.5    degenerate in 294 of 390   (min distance to the .5 tie: 0.0)
NEW probe 10.7    degenerate in   0 of 390   (min distance to the .5 tie: 0.2)
NEW probe 10.2    degenerate in   0 of 390   (min distance to the .5 tie: 0.3; pins ceil)
```

The margin went from `3.55e-15` of float noise to `0.2` — thirteen orders of magnitude of
headroom — and the specific adversarial case the last round named,
`t0 = -11.086, dt = 0.2165, h = 300`, now gives `raw = 10.699999999999996`:
`floor 10 / round 11 / ceil 11 / half-up 11`. Not degenerate.

**Is the trace-axis probe equally safe?** Yes, and by a different mechanism worth naming.
Its probes are absolute pixel positions against a fixed-width fixture, so they are
independent of every time-axis parameter; the only fixture value they depend on is
`width`. Swept `width ∈ {800, 799, 801, 400, 1920, 97}`: at every width, `x = 41.0` and
`x = 79.9` still *discriminate* floor from round/ceil/half-up, and where the fixture width
changes the expected index the assertion **fails loudly** rather than silently stopping
discriminating. That is the opposite of N1's failure shape. The margins at the shipped
width are 0.0125 (`x = 41.0`) and 0.49875 (`x = 79.9`, `x = 80.1`, `x_of_trace(105)+0.1`) —
so even if the thin 0.0125 probe were eroded, three half-width probes remain.

Mutations, all at the correctly-named test:

```
sample floor -> round / ceil / floor(x+0.5)   caught -> test_index_lookups_use_the_left_edge_convention
trace  floor -> round / ceil / floor(x+0.5)   caught -> test_index_lookups_use_the_left_edge_convention
```

### N2 — CLOSED

```
__post_init__ body disabled                caught -> test_construction_rejects_non_finite_axes_not_just_window_changes
__post_init__ drops both t0_ns and dt_ns   caught -> (same test)
__post_init__ drops t0_ns only             caught -> (same test)
```

**Does it break any legitimate construction? No.** I fuzzed 2,000 transforms
(`n_traces ∈ {1..65535}`, `n_samples ∈ {1..8192}`, five `t0_ns` including the real value,
six `dt_ns` from `1e-6` to `1e3`, five widget sizes including `1×1`) × 20 operations each —
40,000 `zoomed`/`panned`/`resized`/`with_window` calls using only values Task 14 can
actually generate (`1.25 ** (angleDelta/120)` wheel factors, integer pixel deltas,
degenerate and huge widget sizes):

```
exceptions raised across 40,000 legitimate ops: NONE
non-finite windows produced: 0
```

The `replace()` interaction specifically: `with_window` runs its own check *before*
`replace()`, and `t0_ns`/`dt_ns` are carried through unchanged from an already-validated
`self`, so re-validation on every window change is a no-op that cannot newly fire.
`resized` likewise only changes `width`/`height`. I also confirmed the round-1 finding that
**±inf arguments still clamp gracefully rather than raising** — `with_window(inf, 300, 0,
20) → (604.0, 608.0, 0.0, 20.0)`, and the same for `-inf` and for inf in each of the other
three arguments — so `__post_init__` did not silently convert that documented behaviour
into a raise. (`panned(inf, 0)` raises, but it raised in round 1 too: `-inf + inf` is NaN
before `__post_init__` is ever reached.)

**Is the duplication justified? Partly, and it is now untested — see New finding 1.**

### N6 / the empty-axis divide-by-zero — CLOSED

```
drop the x_of_trace span guard        caught -> test_empty_axis_forward_maps_do_not_divide_by_zero
drop the y_of_time  span guard        caught -> test_empty_axis_forward_maps_do_not_divide_by_zero
x_of_trace zero-span returns 1.0      caught -> (same test)
y_of_time  zero-span returns 1.0      caught -> (same test)
```

Both guards are pinned independently — neither masks the other — and, unusually and
correctly, the *returned value* is pinned too, not just the absence of a raise. My judgment
on whether 0.0 is the right value is **Q2** below.

---

## Answers to the six questions

**Q1 — `__post_init__` on every construction path.** It breaks nothing (40,000 legitimate
operations, zero raises; the `replace()` paths cannot newly fire, as above). The
duplication, however, is not the two-jobs arrangement the report describes. `__post_init__`
**strictly subsumes** `with_window`'s check: every quantity `with_window` guards reaches
`__post_init__` through the sums it feeds (`trace_hi = lo + t_span`, `time_hi = tlo +
s_span`), and NaN propagates through addition, so there is no NaN that `with_window`
catches and `__post_init__` would not. The only surviving difference is the message. That
makes it exactly the kind of redundancy that drifts — and nothing will notice, because it
is now completely untested (New finding 1). Keeping it is still defensible for the better
message; the fix is one assertion, not a deletion.

**Q2 — returning `0.0` on a zero span. It handles; it does not mask.** The decisive fact is
that a zero span is **unreachable for any non-empty axis**. I swept `n ∈ {1..39, 608,
65535}` × `dt_ns ∈ {0.2165, 1e-30, 1e30, 1.0}` × five operations (`fit`, zoom in, zoom out,
extreme pan, `with_window`) looking for any state with `n_traces ≥ 1` or `n_samples ≥ 1`
and a zero span: **0 found**. `with_window` floors the spans at `min(MIN_SPAN, n)`, which
is strictly positive for `n ≥ 1`. So the branch can only ever be entered on the empty-axis
state the M6 test blesses — where `0.0` is the *same* contract `trace_index_at` already
promises ("0, never a value that aliases real data"), and where there is no data to draw
wrongly. Against the alternative: Task 14 calls `x_of_trace` from `_paint_cursor`,
`_paint_selection` and `_paint_picks` (`set_cursor` is fed by `trace_index_at`, which
returns 0 on an empty axis, so `_cursor >= 0` and the call does happen), and a
`ZeroDivisionError` there is the `paintEvent` variant of the swallowed-exception trap
`plugin.py`'s own module docstring warns about — a traceback or a QGIS error dialog *per
repaint*. Returning 0.0 is the right call.

Two qualifications, neither of which changes that verdict:

- `nice_ticks(lo, hi)` returns an empty array when `lo == hi`, so `_paint_axes`'s tick loops
  never reach the forward maps on an empty axis anyway. The guard's real beneficiaries are
  the cursor/selection/pick painters.
- The one state where `0.0` *is* a silent substitute for a loud failure is `dt_ns == 0.0`
  with `n_samples > 0`: finite, so `__post_init__` accepts it; `y_of_time` now silently
  collapses the whole time axis to `y = 0` where it used to raise — while `source_rect()`
  and `sample_index_at()` on the *same object* still raise `ZeroDivisionError`, so the
  handling is inconsistent. I checked reachability rather than speculating: the smallest
  `dt_ns` any header accepted by `parse_header` can produce is `2.14e-50` (minimum float32
  subnormal / 65535 samples), so `dt_ns == 0` is unreachable from a real or corrupt DZT
  file now that the range guard is complete. Hypothetical only; recorded, not charged.

*Carry-forward for Task 14, alongside N5:* `paintEvent` (task-14-brief:427) computes
`sx = self._image.width() / t.n_traces` before `source_rect()`, which is a live
`ZeroDivisionError` on the empty-trace state whenever an image is set. That division is
Task 14's code, not Task 13's, so it is not charged here — but the empty-axis state is not
fully paint-safe until it is guarded too. Worth writing into the Task 14 brief now.

**Q3 — the N1 probe.** Genuinely discriminating, not merely correct at one value: 0 of 390
adversarial fixtures degenerate, minimum tie distance 0.2, non-degenerate at both
`-11.086` and the exact real `-11.086392402648926`. Trace axis safe at every width tested,
and fails loudly rather than silently if the fixture changes. Detail above.

**Q4 — I1's literals.** Independently derived (neither constant nor `FIT.dt_ns` is read),
both constants pinned on both axes, and pinned twice over. Detail above.

**Q5 — are the two new core guards complete?** Yes, for the failure they target. I walked
every float `parse_header` reads and traced each to its consumer:

| Field | Status |
|---|---|
| `range_ns` | guarded (finite **and** `> 0`) — closes `dt_ns` |
| `position` | guarded (finite only, correctly) — closes `t0_ns` |
| `samples_per_second` | unvalidated, but has **zero consumers** anywhere in either package: it is stored on the dataclass and never read. No division, no velocity, no gap. |
| `epsr` | unvalidated at parse, fully covered at its only consumer. `VelocityModel.from_dielectric` rejects `nan`, `0` and negatives with `not epsr > 0.0`; `+inf` slips that check but is caught one layer deeper by `VelocityModel.__post_init__` (`C/sqrt(inf) → 0.0` → "interval velocities must be positive and finite"). Verified all four by execution. `plugin.py:398` already wraps it and downgrades to a Warning. No gap. |
| `traces_per_metre` | `0` is deliberately handled (time-triggered surveys) — expected, not flagged. `nan` and negatives are also rejected, by the same `not spm > 0` at `placement.py:59` and `lookup.py`. **`+inf` is the one value that slips**: it parses, `placeable` is `True`, `distance_along(5)` returns `[0,0,0,0,0]` and `length_m` computes as `0.0` — a zero-length line with every trace at one coordinate, silently. Pre-existing, unrelated to this round's change, not on the `ViewTransform` path, and out of Task 13's scope; recorded as an observation below, not a finding. |
| `n_samples`, `bits` | guarded (pre-existing) |
| `tag`, `zero`, `antenna`, `n_channels` | not on any division or velocity path |

So `range_ns` and `position` were in fact the only two header floats feeding
`ViewTransform.fit()`, and both are now closed.

**Q6 — is the honesty correction itself accurate?** Yes. I independently reproduced all
seven claimed kills at the correctly-named tests (the two constants, `floor → round` under
the new probe, `__post_init__ → pass`, the `x_of_trace` span guard, the range `isfinite`
clause, the position guard), plus 24 mutations of my own. The "literal independently-derived
expected values" claim checks out structurally, not just numerically. The round-1
retraction is stated correctly and for the right reason. Two trivia, neither material: the
report says `10.7` and `10.2` are "both `0.2` away from the nearest [tie]" — `10.2` is
actually `0.3` away, an error in the safe direction; and "every dataclass construction path
runs `__init__`" is true for construction but not for `pickle`/`copy.deepcopy`, neither of
which is used on a `ViewTransform` anywhere in the tree (checked), and both of which would
only copy an already-valid object.

---

## New findings

**0 Critical, 0 Important, 2 Minor** (plus one out-of-scope observation).

### Minor

#### M-A. `with_window`'s finiteness guard is now dead redundancy, and deleting it survives the entire suite

```
disable the with_window isfinite guard entirely     SURVIVED (16/16 pass)
narrow it to (lo, tlo) only                          SURVIVED
```

Behaviour is unchanged either way — `__post_init__` raises the same `ValueError` a moment
later — so this is a message-quality regression, not a correctness one, which is why it is
Minor. But it is precisely the drift the report anticipated and argued against: the guard
the implementer kept "for diagnostic quality on the common path" is the one thing in this
module that no test now protects. One assertion closes it, and it is the same `match=` the
parked N7 already wanted:

```python
with pytest.raises(ValueError, match="non-finite view window"):   # with_window's own message
    FIT.with_window(float("nan"), 110.0, 0.0, 20.0)
with pytest.raises(ValueError, match="requires finite axes"):     # __post_init__'s message
    ViewTransform.fit(608, 512, float("nan"), 0.2165, 800, 300)
```

Worth noting on the credit side: this also retires the substance of parked **N3**. Narrowing
`with_window`'s guard to `(lo, tlo)` no longer leaks a non-finite window — `__post_init__`
catches all 17 of the cases N3 enumerated — so that mutation is now equivalent in effect,
and the parked finding is moot rather than outstanding.

#### M-B. `__post_init__`'s tuple is only partially pinned: three of its six entries can be dropped without a test noticing

```
drop self.dt_ns from the tuple                  SURVIVED
drop the four window fields from the tuple      SURVIVED
isfinite -> not isnan (i.e. stop rejecting inf) SURVIVED
```

`test_construction_rejects_non_finite_axes_not_just_window_changes` covers three cases, and
between them `t0_ns` alone accounts for all three kills: both `fit()` cases poison the
derived window bounds *and* an axis field, and the direct-construction case puts the NaN in
`t0_ns`. Concrete inputs that would slip under each mutant, in the same style as the test's
own third case:

```python
# dt_ns alone non-finite, everything else finite -- currently untested
ViewTransform(n_traces=608, n_samples=512, t0_ns=-11.09, dt_ns=float("nan"),
              width=800, height=300, trace_lo=0.0, trace_hi=608.0,
              time_lo=-11.09, time_hi=99.758)
# window alone non-finite, axes finite -- currently untested
ViewTransform(n_traces=608, n_samples=512, t0_ns=-11.09, dt_ns=0.2165,
              width=800, height=300, trace_lo=0.0, trace_hi=float("nan"),
              time_lo=-11.09, time_hi=99.758)
# inf rather than nan -- currently untested
ViewTransform.fit(608, 512, float("inf"), 0.2165, 800, 300)
```

All three raise correctly today; none is defended. Three more `pytest.raises` lines in the
existing test. Minor because the shipped guard is right and these construction shapes are
reachable only from a direct call, not from `fit()` or any mutator.

### Observation, not a finding (out of scope, pre-existing)

`traces_per_metre == +inf` parses, reads as `placeable`, and yields a zero-length line with
every trace at one coordinate — the only header float that still reaches a consumer without
being either validated or deliberately handled (`0` is). It is not on the `ViewTransform`
path and predates this task; noting it so it is on the record for whoever owns
`placement.py` next, not as anything Task 13 should fix.

---

## Verdict

All six named findings are closed, and closed on evidence rather than on assertion: the two
I1 constants now die at two independent tests and at a 0.025 % drift; the header chain is
shut at both fields, with the "finiteness, not positivity" decision pinned by all ten real
files; the N1 probe went from degenerate in 294 of 390 fixtures to 0 of 390 with a 0.2
margin; `__post_init__` closes the constructor without breaking any of 40,000 legitimate
operations; and the zero-span guard handles a state that is provably unreachable for any
non-empty axis rather than masking one that is not.

Nothing found this round is a live defect, against real data or otherwise. The two new
Minors are both test-strength items on guards that are themselves correct, worth four
assertions total whenever this file is next touched — M-A ideally sooner, since it is the
one place a future edit could silently undo work this round paid for. Neither is worth a
third fix round.

**Task 13 can close.**
