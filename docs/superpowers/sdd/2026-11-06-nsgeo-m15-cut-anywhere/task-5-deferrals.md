# Task 5 — deferred items (controller ruling, 2026-11-11)

The time-zero branch (#97) is not on main. None of its names exist on this branch: `Pick.zero_ns`, `SiteSession.line_zero`, `SiteLayers.follow_zero`/`_follow_key`, `nsgeo.processing.timezero.time_base_of`, `retime_ns`.

The #97 items in the Task 5 brief move to the later "Task 5b: time-zero hand-off". Do NOT build them now, and do not stub or anticipate them. #36 (edit or delete a pick from the profile) has not merged either, so its conditional does not apply.

Skip these items of the Task 5 brief:
1. In `add_cut_pick`'s contract: "`zero_ns=None` on the `Pick`". `Pick` has no `zero_ns` field yet. Keep "a finite time on the cube's clock, never converted".
2. In `test_a_pick_on_a_cut_lands_on_the_cut_and_records_its_provenance`: the `time_base` check and "the row's `zero_ns` is NULL". Keep everything else, including that `time_ns` equals the clicked time as given.
3. In `test_the_profile_overlays_cut_picks_at_their_columns`: drop "even when the shown cube's preset sets a time zero". Keep the overlay at `(column_at(key, distance_m), time_ns)` with no time conversion.
4. `test_a_pick_made_on_another_clock_is_left_out_and_counted`: skip it entirely.
5. `test_a_line_stack_change_never_rezeroes_cut_picks`: skip it entirely.
6. In Step 3: the part of the `_refresh_picks` bullet that leaves out, and counts, picks whose provenance `time_base` differs. Keep the `column_at` mapping and `time_ns` as stored.

Everything else in the brief stands.
