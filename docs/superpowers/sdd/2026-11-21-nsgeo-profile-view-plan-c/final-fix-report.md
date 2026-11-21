# Plan C final fix wave report
Commit: see git log (one commit, "fix(profile): ... (Plan C final review)"), pushed to origin/nsgeo-profile-view.
- I1 profile_view.py readout_text: `_hover is None` check moved after the W5 drag branch. Test test_the_selection_length_stays_while_the_drag_leaves_the_image: RED on 8f1bc46 (read-out "" with _selection (20,199)); green after.
- M1 profile_view.py release branch: `was_dragging` -> self.update(QRect(0,0,width,MARGIN_TOP)). Test test_releasing_a_drag_repaints_the_readout_strip (update spy); fails with the update disabled.
- M2 getting-started.md rewrapped.
- Z1 test_a_later_time_zero_that_only_moves_the_zero_still_falls_back; mutant (compare bypass.t0_ns - received.t0_ns only) FAILS it; restored, git diff clean of it.
- Z2 _scale_reference docstring; Z3 docstring; Z4 cutoff_ns ~ 0 assert.
Tests: profile_view 145, profile_dock 181, difference_presets 20, time_zero_drag 8, time_cutoff 13, pure 434 (+4 skipped), real_data 57; ruff check and format clean.
