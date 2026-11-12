# Task 3 — fix round 2 (FIX_BASE 26da304)

The re-review confirmed most of round 1. Three items are open, and there's one ruling. All of them are small.
Append a "## Fix round 2" section to task-3-report.md, then commit and push (confirm with ls-remote).

1. **Minor 4, site replaced: reopen the SAME site.**
   - The test at `test_plugin_edit_lines_measure.py:458` opens a different folder (`new_site(tmp_path / "other")`).
   - The finding asked to close and reopen the same site mid-run: `json = session.json_path; session.close_site();
     session.open_site(json)`. Only that case tells the identity check apart from a path check.
   - Change the test (or add a second one) to do that, and assert the Site-changed copy and that nothing was
     written. The reviewer's probe shows the code already passes it.
2. **Minor 5: pin the sign** in the twice-measure test (`:333`).
   - The fixture injects features 0.15 m *ahead* along travel in both directions, so the destagger that cancels
     them is negative.
   - With the +1/120 m placement offset, the expected value is about −0.142. The reviewer measured −0.141 for the
     box and for every row, and +0.010 with no injection.
   - Replace `abs(box) == approx(0.15, abs=0.04)` with a signed assertion, `box == pytest.approx(-0.142, abs=0.02)`
     or equivalent, and assert the rows carry the same value.
   - Fix the docstring: the destagger to find is about −0.15, the value that cancels the injected stagger.
   - This matters: the feature exists because the sign flips between fitted and unfitted lines.
3. **New minor: progress test ordering race** (`:451-453`).
   - The worker sets `progress = (6, 6)` before it calls the canned function, so the status can read "comparing
     lines" before `canned.seen` is set.
   - Wait for `canned.seen` first (`assert spin_until(lambda: bool(canned.seen))`), then wait for the status.
4. **Ruling 11: an empty job.**
   - If no selected row is on this grid (for example, every selected row was moved to another grid), `measure()`
     starts nothing and shows the No-targets copy `Select the lines to fill, then press Measure.`. Today it
     starts a zero-line job, and Ruling 9's "no line could be read" sentence then misreports it.
   - Add a QGIS test: select all, move them to another grid, select all, press Measure. Assert the No-targets
     copy, that no job started (`not dialog._measurer.busy` right after the press), and that nothing changed.

Verification:
- run the Measure file and `test_plugin_edit_lines_dialog.py` (command as before), plus `test_pure_destagger_job.py`;
- ruff check and format --check;
- mypy with the CI list.

The commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
