### Task 1: The gap rule and Gap over, in the core

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/geometry/spacing.py`
- Modify: `packages/nsgeo-core/src/nsgeo/geometry/track.py` (`TrackPlacement`), `packages/nsgeo-core/src/nsgeo/project.py` (track placement save/load, ~lines 164-172 and the track branch of the loader)
- Test: `packages/nsgeo-core/tests/test_spacing.py` (new), `packages/nsgeo-core/tests/test_spacing_real_files.py` (new), `packages/nsgeo-core/tests/test_project.py`

**Interfaces:**
- Produces, in `nsgeo.geometry.spacing`:
  - `GAP_FACTOR: float = 6.0`
  - `usual_step(distance: np.ndarray) -> float` — median of `abs(diff(distance))`; `0.0` for fewer than 2 traces.
  - `gap_threshold(distance: np.ndarray, gap_m: float | None = None) -> float` — `gap_m` when given, else `GAP_FACTOR * usual_step`; `math.inf` when the usual step is 0. `ValueError` for a `gap_m` that is not finite and above 0.
  - `gap_steps(distance: np.ndarray, gap_m: float | None = None) -> np.ndarray` — bool, length `n - 1` (empty below 2 traces): `abs(step) > threshold`.
  - `left_out(distance: np.ndarray, gap_m: float | None = None) -> np.ndarray` — bool, length `n`: True where the steps on both sides are gaps; never the first or last trace.
- Produces: `TrackPlacement.gap_m: float | None = None` (last field). `__post_init__` raises `ValueError` unless it is None or finite and > 0. Saved as `"gap_m"` only when not None; loaded with `doc.get("gap_m")`.

- [ ] **Step 1: Write the failing tests** in `test_spacing.py`:

```python
def test_the_usual_step_is_the_median_step():
    assert usual_step(np.array([0.0, 0.02, 0.04, 0.06, 1.0, 1.02])) == pytest.approx(0.02)

def test_a_step_over_six_usual_steps_is_a_gap():
    d = np.concatenate([np.arange(10) * 0.02, 0.18 + 0.5 + np.arange(10) * 0.02])
    assert gap_steps(d).tolist() == [False] * 9 + [True] + [False] * 9

def test_the_threshold_is_strictly_longer_than_six_usual_steps():
    base = np.arange(20) * 0.02
    assert not gap_steps(np.append(base, base[-1] + 0.119)).any()
    assert gap_steps(np.append(base, base[-1] + 0.121))[-1]

def test_a_typed_gap_over_replaces_the_automatic_threshold():
    d = np.array([0.0, 0.02, 0.04, 0.10, 0.12, 0.62, 0.64])
    assert gap_steps(d, gap_m=0.05).tolist() == [False, False, True, False, True, False]
    assert not gap_steps(d, gap_m=1.0).any()

def test_traces_between_two_gap_steps_are_left_out():
    d = np.array([0.0, 0.02, 0.04, 0.5, 1.0, 1.5, 1.52, 1.54])
    assert left_out(d).tolist() == [False, False, False, True, True, False, False, False]

def test_a_single_gap_step_leaves_both_its_traces_drawn():
    d = np.array([0.0, 0.02, 0.04, 1.5, 1.52, 1.54])
    assert not left_out(d).any()

def test_a_falling_distance_has_the_same_gaps_as_its_reverse(): ...  # gap_steps(-d) == gap_steps(d); left_out likewise
def test_a_line_with_no_spacing_has_no_gaps(): ...  # constant d: usual_step 0, no gaps, nothing left out, no numpy warning (pytest -W error)
def test_fewer_than_two_traces(): ...  # n=1: gap_steps empty, left_out == [False]; n=0: both empty
def test_a_lift_at_either_end_leaves_the_end_trace_drawn(): ...  # gaps at step 0 and step n-2: left_out[0] and left_out[-1] False
def test_a_tiny_gap_over_leaves_out_everything_but_the_ends(): ...  # gap_m=0.001 on an even 0.02 line: left_out[1:-1] all True, ends False
def test_gap_over_must_be_finite_and_positive(): ...  # gap_steps(d, gap_m=v) and TrackPlacement(..., gap_m=v) raise ValueError for 0, -1, nan, inf
```

In `test_project.py`: `test_gap_over_round_trips_and_is_saved_only_when_typed` — a GPS line with `gap_m=0.25` saves `"gap_m": 0.25` and reloads as 0.25; with `gap_m=None` the saved track has no `"gap_m"` key and reloads None. Build the placement as the existing track round-trip test does.

In `test_spacing_real_files.py` (skips when `with-dzg/` or `grid2/` is absent, as `test_track_real_files.py` does, with its projector): `test_the_gps_surveys_lifts_are_gaps_and_their_slips_are_not`:
- `FILE__028` (with-dzg): the step from trace 841 to 842 is a gap;
- `FILE__016` (with-dzg): traces 355–362 are left out, 354 and 363 are not;
- the number of lines, over both surveys, with at least one gap: measure it and pin it with a comment (§17 measured 19 lines by fix-to-fix stretches; per-trace steps may differ slightly; report the measured value).

- [ ] **Step 2: Run them to see them fail.** core+pure command, `-k "spacing or gap_over"`. Expected: ImportError / AttributeError.
- [ ] **Step 3: Implement** `spacing.py`, `TrackPlacement.gap_m` and the save/load. Wrap the median and comparisons in `np.errstate` so a constant line raises no warning.
- [ ] **Step 4: Run core+pure in full.** Expected: all pass.
- [ ] **Step 5: Commit and push** (`feat(m17c): one gap rule for GPS lines, and Gap over on the track placement (#134)`).

---

