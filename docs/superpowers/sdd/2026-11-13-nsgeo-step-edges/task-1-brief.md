### Task 1: The migration real-data test (#125)

No product code. It lands first, and its numbers guard the later changes to dewow and background
mean.

**Files:**
- Modify: `packages/nsgeo-core/tests/real_data.py` (add `real_radargram`)
- Modify: `packages/nsgeo-core/tests/test_steps_migration.py` (new section at the end)

**Interfaces:**
- Produces: `real_radargram(path: Path) -> Radargram` in `tests/real_data.py`. It reads channel 0
  as float with `dt_ns=header.dt_ns`, `t0_ns=header.position_ns`, and
  `dx_m=1/header.traces_per_metre` (None when that is ≤ 0). It calls `pytest.skip` when `path` does
  not exist. Later tasks use it.

- [ ] **Step 1: Add `real_radargram` and write the test**

  Constants, with a provenance comment. They come from the user's hand fits on Nashville City
  Cemetery 2023 Grid 2, saved 2026-11-06 in the gitignored hand-fit site file. The times are after
  the default Time zero, which sits at −0.476 ns on the radar clock; the fits were saved on the
  radar clock (19.947 and 19.363 ns).

  ```python
  REAL_DIFFRACTIONS = (  # (file in grid2/, apex trace, apex ns after time zero, velocity m/ns)
      ("FILE__033.DZT", 1375, 20.42, 0.1027),
      ("FILE__032.DZT", 386, 19.84, 0.1061),
  )
  ```

  The measurement, the one algorithm here that the assertions don't determine:

  ```python
  def _real_focus(img, apex_row, apex_trace, dt_ns, dx_m):
      """(focus, d_row, d_trace) at the strongest sample near the apex.

      The window is +-10 ns x +-1.5 m around the hand apex. The peak is searched from 1 ns
      above to 4 ns below it and +-0.3 m across. Focus is `_focus` (17 x 17 box) over that
      window: the synthetic test's measure, with the window as the total.
      """
      hr, ht = round(10 / dt_ns), round(1.5 / dx_m)
      r0, t0 = max(apex_row - hr, 0), max(apex_trace - ht, 0)
      win = img[r0 : apex_row + hr + 1, t0 : apex_trace + ht + 1]
      ar, at = apex_row - r0, apex_trace - t0
      lo, hi, st = round(1 / dt_ns), round(4 / dt_ns), round(0.3 / dx_m)
      sub = np.abs(win[ar - lo : ar + hi + 1, at - st : at + st + 1])
      pr, pt = np.unravel_index(np.argmax(sub), sub.shape)
      pr, pt = pr + ar - lo, pt + at - st
      return _focus(win, pr, pt), pr - ar, pt - at
  ```

  The test is `test_a_real_diffraction_collapses_at_its_measured_velocity`, parametrized over
  `REAL_DIFFRACTIONS`:
  - Processing: `time_zero` → `dewow` → `background_mean`, then `migrate_fk(velocity_m_ns=v)`,
    all at defaults.
  - `apex_row = round(t_ns / dt_ns)`.
  - Assertions:
    - `abs(d_trace) <= 2`;
    - `0.5 <= d_row * dt_ns <= 2.0`. The hand dots sit on the band's top edge and the migrated
      peak is mid-band. Measured: +5 rows (1.08 ns) and +6 rows (1.30 ns).
    - `focus_migrated > 0.04` and `focus_migrated >= 2 * focus_unmigrated`. Measured: 0.075 vs
      0.024, and 0.050 vs 0.020.
    - `focus(v) > focus(0.6 v)` and `focus(v) > focus(1.6 v)`. Measured: 0.047 / 0.075 / 0.038
      and 0.035 / 0.050 / 0.017.

  The docstring says there is **no deep case** and why, with spec §7.3's numbers:
  - below 50 ns, the median signal is 1.3–1.6× the noise of the 80–90 ns band, on the campus lines,
    Grid 1 and Grid 2;
  - a search of all 130 local lines at 40–85 ns found only flat layers;
  - the deep coverage is the synthetic `test_a_point_diffractor_collapses_to_its_apex`.

- [ ] **Step 2: Run it**

  Run: core command on `packages/nsgeo-core/tests/test_steps_migration.py`.
  Expected: PASS for both cases. If a measured value differs from the numbers above by more than
  rounding, stop and report it. Don't loosen a threshold to make it pass.

- [ ] **Step 3: Check it fails when it should**

  Temporarily change the velocity to `v * 0.6` in the test. At least the focus assertions must
  fail. Revert.

- [ ] **Step 4: Commit and push**

  `test(migration): real diffractions on Grid 2 collapse at their hand-fit velocity (#125)`

---

