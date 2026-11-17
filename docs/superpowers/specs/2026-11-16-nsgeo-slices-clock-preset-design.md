# nsgeo Slices: the right clock and preset after a change — design

Session B of the issue-sessions plan (https://claude.ai/artifact/A1w1dKGNENHd2S2GbmqECj).
Settled in chat on 2026-11-16. Size M: a 3–4 task plan and a short walkthrough.

- **Closes:** #162 (a restored cube on the wrong clock, three paths), #102 (the next survey opens
  at the old site time), #152 (a fallback grid keeps the removed grid's preset), #200 (a restore
  just after leaving Whole site applies its resolution to the old grid).
- **Takes items from #163, without closing it:** items 3, 4, 5 and 6. Item 1 was session A's
  (#198); item 2 is session F's.
- **Filed instead of built:** the grid-velocity clock warning (#163's comment from PR #186) is S,
  not XS, so it went to session K as #201 (§7).

Branch `nsgeo-slices-clock-preset`, from origin/main 140f64e, after session A (PR #198,
c7eb1e5). M16 Plan A (PR #190) is still open, so it is not in the base (§11).

## 1. What this is for

The Slices panel holds a few values for later: a depth shift a restored cube still owes, the
palette it was saved with, the slice time carried back from Whole site, a resolution owed to a grid
not yet prepared, and the preset a grid opens on. Each bug here is one of those values outliving
the site, grid or preset change it was made for. The design (time zero spec §5.4, §8) says a
restored cube is never silently a different cube. Today three paths bring one back a line zero
away (about 0.5 ns on the campus lines, 1.3–1.6 ns on the GPS survey) under the same name, with
no note.

**Success:** restoring any saved cube, old or new, brings back the slices it showed, or says
exactly how it moved. Switching surveys, grids or scopes quickly never carries one site's or
grid's value into another. This grid and Whole site draw a grid with the same preset.

**Anti-goals:**
- A note that appears in two places. A note in Warnings has no toast.
- A fix that clears a value a restore still needs. That is bug #162 item 2, and the reason the
  rule below is about *which* changes clear, not about clearing more often.

## 2. The rule: a pending value belongs to the site and source it was made for

Fixes #162 item 2, #163 item 4 and #102.

**Pending values:** the shift a restore owes (`_pending_z_shift`, which now also carries its
direction, §4), the restored palette (`_pending_palette`), the slice time carried back
(`_pending_top_ns`) and the owed resolution (`_resolution_owed`).

**They are dropped:**
- **When a site opens or closes.** `rebuild_source` (both `site_opened` and `site_closed` reach it)
  checks once, at its start, whether the site is new (`session.site is not self._site_seen`). If
  it is, the values are dropped before anything in that call can use one. When the survey closed
  under Whole site, the same call switches back to This grid (`set_scope("grid")` →
  `_resume_grid`), which sets the slice time and can owe a resolution again. Those are dropped
  after the switch, beside `SiteScope.forget()`.
- **On a source change:** by hand (`_on_source_changed`, `set_included`) and from the site list
  (`_switch_resumed_grid`), as today. A grid the combo falls back to on its own counts too (§5).

**They are no longer dropped** by a `grids_changed`, `lines_changed` or `presets_changed` that
leaves the source as it was. Today `rebuild_source` clears the owed shift on every one of them;
that is #162 item 2.

`_on_prepared` still uses the values up when it runs, as today.

**Approaches considered:** tag each value with its site and source, and drop it where it is used
when they differ; or drop values at known change points. Change points were chosen (my call, as
the brief allowed). Both points already exist: `rebuild_source` is the one place that notices a new
survey, and the manual source changes already drop a restore's values. Tagging would need a check
in five places that use the values (`_on_prepared`, the no-preparation restore,
`_run_pending_grid_prepare`, `_sync_grid_slider`, `_apply_resolution`).

## 3. One settle sequence: shift, clamp, check, push (#162 item 3, #200)

Every path that brings a restored or owed range to the engine runs one helper, in this order:
1. **shift** by the owed amount, if one is owed (§4);
2. **clamp** to what every prepared line covers (`_clamp_z_to_prepared`);
3. **check:** the frame cap and A's level limit (A's spec §3.3). Both already sit in
   `_apply_resolution` and in `set_resolution`'s `TooManyLevels`, so they check the shifted,
   clamped range;
4. **push** it to the engine.

**The paths:** `_on_prepared`; a restore that needs no preparation (`_apply_owed_z_shift` today);
and `_run_pending_grid_prepare`. That last path clamps and applies before it shifts today, so the
range starts about 2.4 ns late. No path pushes a range before its owed shift.

**#200, a restore that has to wait for a site task:** after A, `restore_cube` prepares first and
then flushes the debounce. If `prepare()` defers (R-P5: a Whole site task is still live), that
flush applies the cube's resolution to the grid that was showing. The level limit or frame cap
of that other grid can then refuse it. The fix: when `prepare()` defers, the restore marks the
resolution owed and stops the debounce instead of flushing. `_run_pending_grid_prepare` then
settles it through the helper once the cube's grid is prepared, as a grid switch in the same
window already does (#70).

## 4. A preset whose clock changed since the save (#162 item 1)

The author chose to **shift in both directions and say so** (option A), so every restore path
behaves the same.

- **The cube's clock:** `recipe.time_base`, with no marker read as `"radar"` (that record is from
  before #97).
- **The preset's clock now:** `time_base_of` the preset's current steps.
- **The same clock:** no shift.
- **Radar → time zero** (an unmarked record, or a radar record whose preset has since gained Time
  zero): the range moves by the median line zero (`engine.median_zero()`, `retime_ns(t, 0,
  median)`), as an unmarked record already does.
- **Time zero → radar** (the preset has since lost Time zero): the prepared lines are on the
  radar's clock and each reports a zero of 0.0, so there is no line zero to read. The shift is
  the median **first break** of the prepared lines, picked by Time zero's own rule at its default
  threshold (`first_break_ns`, 0.2). The range moves by `retime_ns(t, median, 0.0)`, the reverse
  of the gained case, so its sign follows the break's. A new engine read beside `median_zero` gives
  it.
  - **The accepted catch:** the cube's record does not keep its Time zero settings. Only its npz
    does, and a restore never reads the npz. A cube made with Sample mode or another threshold
    can be a few samples off, and the steps the preset runs before the pick can move it by about
    one sample. The note gives the number.
- **With nothing prepared** (every line failed) there is nothing to measure: no shift, no note,
  as today.

**The note** is an ⓘ entry in Warnings (§8). It names the cube, the preset and the shift, with
its sign. The wording is the builder's within these facts:
- unmarked record: today's `old_cube_note` sentence;
- gained: *"Cube X was saved on the radar's clock, and preset P now has Time zero. It was rebuilt
  from each line's first break, with its range moved by −0.52 ns (the median line zero)."*
- lost: *"Cube X was saved with Time zero, and preset P no longer has it. It was rebuilt on the
  radar's clock, with its range moved by +0.52 ns, the median first break as Time zero finds it by
  default."*

**The guide** (`docs/guide/getting-started.md`, the paragraph on cubes saved before 0.4.0) gains
one sentence: a cube whose preset has gained or lost Time zero since it was saved comes back the
same way, and the Slices panel says by how much.

## 5. The grid the panel falls back to (#152)

When `_sync_included`'s grid-changed branch runs for a grid the combo moved to on its own, not
one you picked, This grid selects `site_scope.default_preset(session, grid_id)` inside the
`_updating` guard, as #106 does for the switch from the site list. "On its own" means the
selected grid was removed, or a site opened (my call). *Corrected in the build (Task 1):* opening
does not carry a same-named preset over today, because `open_site` closes the open survey first
and that empties the preset combo. The rule covers a site open anyway, and a guard test pins it.
Nothing is written to the grid's record.
That move also drops a restore's pending values (§2), because it is a source change.

A grid **picked by hand** still carries the preset over. `_remember_source` then records it, as
today.

## 6. #163 items 3, 5 and 6

- **Item 3, a time field's bound before the samples load.** `ProcessingDock.input_axis` falls
  back to the header (`position_ns`, the radar's clock) when the stack has no source. With an
  enabled Time zero step above the row, it must not do that:
  - the form's time bound stays open until the samples load;
  - once they load, the form takes the real bound. The builder checks that something re-shows it,
    and makes it so if nothing does.
  - **A new step's seeded time** (`add_step_with_dialog` seeds a cutoff at the record's end, as a
    no-op) is in the same state. On the campus lines the header's end would sit about one sample
    inside the time-zero record and crop it. The seed must still be a no-op. One way: on the
    time-zero clock the record starts at 0 and has at most the header's `n_samples`, so
    `n_samples × dt` is never inside it.
- **Item 5, `load_cube` and the cube's clock: closed with no change.** No path shows a saved cube
  without rebuilding it:
  - `load_cube` has no caller outside the tests, on main, on PR #190 or on any other branch
    (checked 2026-11-16);
  - `restore_cube` rebuilds from the record, which carries `time_base`;
  - M15's cuts read the cube held in memory (ruled when M15's Task 5b was built).

  The PR comment on #163 gives this reason.
- **Item 6, test gaps and tidying.** The velocity-curve retime in `velocity_curve_points`
  (`profile_dock.py`) gets a test that fails without it. That needs a step-input view, where the
  shown zero differs from the line's zero. The site-note items still apply after A, re-checked
  against its Warnings section:
  - `SiteScope.warnings()` (which replaced `show_note`) still says "drawn grids". Queued and
    preparing grids are counted from their presets; the docstring says so.
  - `grid_time_bases`' preset-only mode (`site_engine=None`) is used by one test only. Drop it
    and update that test.
  - Add a test for a grid with no lines, which is left out like a failed one.
  - `engine.provenance()` is built just to read `.steps`. Use a cheaper read if the engine has
    one. If it has none, leave it and say so in the report.
- **Item 6's "no fit test on real ground"** was answered by the tracer work's hand fits. It is
  not in this session.

## 7. The grid-velocity clock warning: filed as #201

The brief allowed this if it stayed XS. It doesn't. It needs the grid's `velocity_from_fit`
record, each member line's own clock, and an entry in both scopes, with tests in each. It is
filed as #201 for session K.

## 8. Notes in Warnings

- **The restore notes move from the toast to This grid's Warnings,** as ⓘ notes: the clock note
  (§4) and the "line(s) moved to another grid since it was saved" note. The second is my call: both
  describe the same restore, and one of them in a toast would be the anti-goal.
- **Order,** per A's rule: ⛔ refusals first, then ⚠ warnings, then ⓘ notes.
- **A note stays** until the Cube box leaves that cube (an edit marks it unsaved, or another cube
  is picked), or the source, grid or scope changes. A refusal still clears as A specified.
- This grid's `show_warnings` grows from one refusal to the refusal plus the notes. Whole site is
  unchanged.

## 9. Tests to pin

Each must fail before its fix.

- **#162 item 2:** restore an unmarked cube and emit `lines_changed` before the preparation
  finishes. The shift lands, and the note shows.
- **#163 item 4:** restore a cube, then close the site and open another during the preparation.
  No palette carries over.
- **#102:** in Whole site at a mid-window time, close the survey and open another. This grid
  starts at its own first slice.
- **#162 item 3:** with the preparation and the resolution both owed and the engine already
  prepared, the engine's `z.t0_ns` is the shifted, clamped start.
- **#162 item 1:** restore a marked cube against a preset that gained Time zero, and one against
  a preset that lost it. Each comes back shifted, by the median zero and by the median first break
  respectively, with its note.
- **#200,** with `docked_mixed_radar`:
  1. keep a site task live;
  2. restore one of B's deep cubes while A shows;
  3. let the task finish.

  B draws at the cube's dz and z range, and Warnings is empty. Also parked Ruling 36's sharper
  test: put a refusal on A, then restore an old-clock record of B. Warnings is empty as soon as
  `restore_cube` returns, before the preparation finishes.
- **#152:** This grid shows A with `raw`, and B has no record. Remove A. This grid's preset is the
  one Whole site draws B with, and B's record stays empty. A grid picked by hand still carries the
  preset over.
- **#163 item 3:** a time field behind Time zero, before the samples load, has no radar-clock
  bound, and its seed is a no-op. After the load, the bound is the time-zero record's.
- **#163 item 6:** the retime pin, the no-lines grid, and the `grid_time_bases` change.
- **Real lines,** on both surveys where the local data exists, skipped cleanly in CI:
  - restoring an unmarked cube moves the range by the median line zero (about 0.5 ns campus,
    1.3–1.6 ns GPS);
  - the first-break estimate used for "lost" agrees with the time-zero median within one sample
    on each survey. This is the check that the estimate is fair.

## 10. The walkthrough

Built and deployed to its own QGIS profile, in a sandbox copy of the campus and GPS surveys, never
the author's real project. It covers:
- **restoring an old cube and a new one.** The old (pre-#97) cube is made in the sandbox by
  stripping `time_base` from a copied cube's record in the survey file and from its npz;
- **a preset that gained, then lost, Time zero** since a cube was saved;
- **editing while lines prepare:** change a line, a grid or a preset in the second after a restore;
- **switching sites and grids quickly**, including closing and reopening within a second of a
  restore;
- **closing from Whole site and opening another survey,** and the same from This grid. A new
  survey now opens at its own first slice either way (Task 1 found that the slider kept the closed
  survey's position);
- **removing a grid in This grid** (#152).

#200 needs a site task still finishing when you restore, which is hard to hit by hand. The tests
cover it, and the walkthrough says so rather than ask for it.

## 11. Constraints and clashes

- **M16 Plan A (PR #190)** adds about 90 lines to `slices_dock.py` for the export, around the
  Save cube… row. Whichever branch merges second resolves the textual conflicts. None is
  expected in the restore and settle code.
- **A's Warnings section** is the only place a note goes (§8). The panel-width rule (A §8.2)
  holds: notes wrap.
- **QGIS 3.44 (Qt 5) and 4.2 (Qt 6)** must both pass. CI runs both.
- **Every slot and Qt override guards its own body,** as the codebase does throughout.
- **Never touch the author's real project.** The sandbox copy is the walkthrough's.

## 12. Left to the builder

- The settle helper's name and signature, and how the owed shift's direction is carried.
- The engine read for the median first break, and building a `Radargram` from a prepared line
  for `first_break_ns`.
- The exact note wording, within §4's facts.
- How "the grid moved on its own" reaches `_sync_included` (a parameter, say), so a hand pick and
  a fallback are told apart.
- How the open time bound and the no-op seed are expressed (§6).

## 13. When it merges

- The PR closes #162, #102, #152 and #200.
- Comment on #163 listing items 3, 4, 5 and 6 as done, with item 5's reason (§6). Item 2 stays
  open for session F.
- The README roadmap's Done table takes it into the next release's row.
