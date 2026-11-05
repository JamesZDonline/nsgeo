# Task 1 — findings under verification (fix round 1; file:line refer to 42df503)

1. [Important] The apply_at test has no blank cells (test_slices_interpolate.py:695-701). On "lines" at max 0.25 m there are 240 data cells, 2160 targets and 0 blank cells, so none of the 200 sampled ids is NaN. A mutant that starts apply_at's output at np.zeros instead of NaN (interpolate.py:239) passes all 37 tests. The blank branch and the searchsorted clamp (interpolate.py:239, 244-245) are not exercised. Required: build from lines((5, 15, 35)) at max 0.25 m so rows around 25 are blank, and assert the sampled ids include at least one data cell, one target and one cell that is neither.

2. [Important] Per-slice apply breaks spec §7 ("must not be slower than today's fill") (interpolate.py:205-219, 227-234). On the 50 m grid of 0.5 m lines, kriging weights: 0.2 m — fill 3.5 ms vs apply 15.3 ms; 0.1 m — fill 18.6 ms vs apply 123.6 ms. Required: a fast path (gather + weighted sum in float32, renormalising only rows touching a non-finite source), with apply and apply_at on the same path so they stay bit-identical; re-measured apply vs today's fill on the record, docstring timing table updated.

3. [Spec compliance] One-line test, row half (test_slices_interpolate.py:630-631): `not fin[:5].any()` does not assert "all others NaN" (fin = whole row finite). Required: assert np.isnan(out[:5]).all() and np.isnan(out[16:]).all().

4. [Spec compliance] Cross-hatch test checks rows 5–35 only (test_slices_interpolate.py:641-644); the brief says everything inside rows and columns 5–55 is finite. Required: out[5:56, 5:56] all finite.

5. [Covering test for 2] Renormalisation not pinned: a mutant dropping the division at interpolate.py:218 passed all tests. Required: a constant 3.5 field with one NaN data cell, asserting every target that lists that cell equals 3.5 (idw and kriging); plus spec §9's all-blank input → all-blank output.

6. [Global constraint] Citations: module docstring cites "(spec §5.2)" / "(spec §5.3)" (interpolate.py:154, 159), not "(interpolation spec §…)"; _blend cites "(plan call 5)" (209), which dangles once the plan retires.
