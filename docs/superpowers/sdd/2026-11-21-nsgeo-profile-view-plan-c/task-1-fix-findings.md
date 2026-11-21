# Task 1 fix findings (review a213e487e3ae505a1, of 773e84e..2664e3b)

## F1 (ruling, spec §4.14 Q3 updated in the commit after 2664e3b) — the row-mismatch guard is too strict
profile_dock.py current_radargram, row-handle branch: `(bypass.n_samples, bypass.t0_ns) != (received.n_samples, received.t0_ns)`.
A time_cutoff after Time zero (the usual stack) cuts the bypass's bottom, so n_samples differ and the view ALWAYS falls back.
New rule: fall back only when the bypass's first row is at a different radar-clock time or dt differs:
  abs((bypass.t0_ns + bypass.zero_ns) - (received.t0_ns + received.zero_ns)) > tol  or  bypass.dt_ns != received.dt_ns (use math.isclose / a tolerance of ~1e-6 * dt).
A shorter bypass (bottom cut) is drawn. snap_row already clamps the drag to the drawn record's rows (view_transform.py:137).
Tests:
- new: a stack [time_zero(k), a step that changes data (dewow or gain), time_cutoff(end_ns that bites in the bypass)]; select the Time zero row: the drawn data == result_bypassing(row).data, drawn n_samples < input's, drawn t0/zero on the line's clock (row k reads 0), limit from the bypass (not the input).
- keep test_a_bypass_with_other_rows_falls_back green (second Time zero crops the top — first-row time differs). If it relied on n_samples only, make sure it still fails under a mutant that drops the guard.

## F2 (Important) — no test fails for any _scale_reference change (profile_dock.py:2276-2289)
Three mutants survived all 38 related tests: (A) `if handle_row >= 0:` (always `shown`), (B) `if False:` (ignore the flag), (C) drop `rows.append(handle_row)`.
Reviewer-verified tests that kill all three and pass on 2664e3b:
- Mismatch-fallback scale pin: stack [time_zero(20), gain_agc, time_zero(10)], select 0; assert `dock.image.reference is dock.image.rg` and `dock.image.limit == _clip(dock)(stack.source.data)`. Kills B.
- Curve pin: stack [time_zero(20), dewow, gain_curve(points=[[0,0],[50,40]])], select 0; assert `dock.image.reference.data` equals `stack.result_bypassing(0, 2).data` (array_equal). Kills A and C.
(Use the file's existing helpers; adapt names if `_clip` etc. differ. Check each test fails on its mutant, then restore.)

## Minor (do these)
- M1: module docstring profile_dock.py:27-29 and :40-45 still says a row handle shows what the step receives, on its own scale. Rewrite to the bypass with its two fallbacks (§4.14 Q3).
- M2: stale text: `_shows_row_handle` docstring (~2323) "draws that step's input"; `_show_cutoff` comment (~2339) "on the record it receives"; test section header test_plugin_profile_dock.py:~2830 "draws what the step receives"; docstrings of test_a_migrated_line_still_draws_time_zeros_input (~2912, "the input view never runs it") and test_plugin_difference_presets.py:~121 ("migration ... never runs") — now the bypass runs migration, which refuses, so the fallback draws the input.
- M4: _scale_reference calls _handle_row() twice (once via _shows_row_handle()); `rows.sort()` is a no-op (memo keys are frozensets). Tidy.
- M5: reset `self._row_view_is_bypass = False` at the top of current_radargram so the invariant doesn't depend on _render's early return.

## Not doing
- Minor 3 (duplicate migrate_fk fixture across tests): brief-mandated; F2 spreads coverage.
- ⚠️ memo size 2 vs three keys with a gain curve: a recompute on select/deselect only; raising the memo costs a whole radargram of memory. Left.
