# nsgeo lines in bulk and at import — design

Session D of the issue-sessions plan (https://claude.ai/artifact/A1w1dKGNENHd2S2GbmqECj).
Settled in chat on 2026-11-18/19, with a lavish mockup of every new dialog, row, menu and prompt
(`.lavish/session-d-lines-in-bulk.html`, local). Size M: a 4-task plan and a walkthrough.

- **Closes:** #129 (a processing preset at import), #57 (a map selection selects lines in the
  Survey panel), #58 (bulk preset and velocity on a selection), #221 (Remove says what goes),
  #16 (`_updating` as a depth counter), #17 (one rule for decimal input).
- **Branch** `nsgeo-lines-in-bulk`, from origin/main 6ee3646 (M17a merged, b5f608f).

Paths below are under `packages/nsgeo-qgis/nsgeo_qgis/` unless they start with `packages/`.

## 1. What this is for

The author's words, from the issues:

- #129: "When I'm adding lines to a grid, if there are presets I'd like to be able to set one at
  that point so the lines are readable immediately upon load."
- #57: "when you select several lines on the map it selects them all in the survey panel so you
  can choose which lines to delete that way."
- #58: "bulk edit on several lines sounds like an interesting idea. maybe applying a transform
  preset or velocity override."

Today a new line opens as raw data, and getting a preset onto new lines means opening one,
applying the preset, then **Apply to grid…**, which also overwrites every line already on the
grid. A selection can only be built in the Survey panel, and the only thing to do with it besides
Edit/Move is Remove. Remove does not say that a line's processing, velocity override and saved
fits go with it (#221), which matters more once a rectangle on the map can select twenty lines.

**Success:**
- Lines imported with a preset open processed; lines already on the grid are untouched.
- A rectangle on the map over bad rows, then Delete in the Survey panel, removes exactly the lines
  the map shows selected, after a prompt that names what goes with them.
- A preset, the open line's steps, a velocity or a cleared velocity reaches exactly the selected
  lines, in one step, after one prompt that gives the count.

**Anti-goals:**
- Selecting on the map or in the panel opening lines the user did not ask to open (each open reads
  a DZT file and switches the profile).
- A bulk action that silently overwrites: each one asks first, or is itself the question.
- An import preset that changes the slices of a grid the user has already looked at.
- Touching files other sessions are in beyond the small, separate edits listed in §8.

## 2. #129: a Processing preset box at import

### 2.1 The box

One self-contained widget, `ui/preset_box.py` (`PresetBox`), used by both import dialogs. M17b
will fold both dialogs into one **Add data ▾ › GPR…** dialog with a Grid/GPS switch (M17a decision
14), so the box must move as one piece: a combo and a grey note label under it, with no knowledge
of the dialog around it beyond what it is told (§2.3).

- **The list:** "None" first, then `session.preset_names()` (name order).
- **No presets saved:** the box shows None, greyed out, with the tooltip "Save a preset from the
  Processing panel first."
- **Presets change while the dialog is open** (both dialogs are modeless): the list refills on
  `session.presets_changed`, keeping the current choice if it still exists. If the chosen preset
  was deleted, the box drops to None and the note says so until another choice is made: "The
  preset {name} was deleted; these lines will import with none." (My call.)
- **The grey note** holds up to two lines, each shown only when true:
  - **Migration:** the chosen preset has an enabled Migration (Stolt f-k) step (`migrate_fk`).
    Text: "Its Migration (Stolt f-k) step uses 0.100 m/ns, the velocity it was saved with." (the
    first such step's `velocity_m_ns`). Migration does not follow the line's or grid's velocity,
    so this is the one setting in a preset worth naming.
  - **Slices:** the rule in §2.4 will set the grid's Slices preset. Text: "Grid3's first lines:
    this becomes its Slices preset too." Never shown for None, or in the GPS dialog.
- The migration sentence is built by one function shared with the bulk prompt (§4.3).

### 2.2 Where it sits

- **Import DZT files:** the last row of the options form, after "Label from" (the author's
  choice, mockup option B: placement first, then what happens to the lines once in).
- **Import GPS lines:** a form row under "Destagger (m)", above "Coordinates:".

### 2.3 What it starts on, and what is remembered

- **Starts on:** the target grid's remembered choice; for a grid that has none, the site's last
  choice; else None. The GPS dialog has no grid until M17b, so it starts on the site's last
  choice. Changing the DZT dialog's Target grid moves the box to that grid's starting value.
- **A remembered None stays None** for that grid (it does not fall through to the site's last).
- **A remembered name that is no longer a preset** reads as None. (My call.)
- **Remembered only at Import**, after the lines are added: the grid's entry (DZT) and the site's
  last choice (both dialogs) are set to the choice made, None included. Cancel remembers nothing.
  **A greyed-out box is not a choice:** when the site had no presets at Import, nothing is
  remembered, so a new site's first grids do not start on None for good once a preset exists.
  (My call.)
- **Stored in the site file**, as a new optional top-level field, kept apart from
  `slice_sources` so it never moves a surface's staleness (`slice_sources_changed`):

  ```json
  "import_presets": {"grids": {"Grid3": "Gain + bandpass", "Grid4": null}, "site": "Gain + bandpass"}
  ```

  - Core: a `Site.import_presets` field in `packages/nsgeo-core/src/nsgeo/model/survey.py`,
    written by `save_site` only when non-empty, read by the loader tolerantly as `slice_sources`
    is: a non-object reads as empty, a grid id the site does not have is dropped, a value that is
    neither a string nor null is dropped. A hand-edited file never blocks opening.
  - **No new schema version.** The loader ignores unknown top-level keys, so 0.4.0 opens a file
    with this field and simply forgets it. A test pins that an `import_presets` field does not
    change the written `schema_version`.
  - Session: `import_preset(grid_id: str | None) -> str | None` (the starting value, by the rule
    above) and `remember_import_preset(grid_id: str | None, name: str | None)`, which marks the
    site modified only when something changed.
  - A grid removed from the site loses its entry (on `remove_grid`, and on load).

### 2.4 The grid's Slices preset (DZT dialog only)

Decided: **only on the first import into an empty grid.** If, at Import, the target grid had no
lines and its remembered slice source has no preset, and the choice is not None, the choice also
becomes the grid's Slices preset. After that only the Slices panel changes it, and later imports
never touch it. Reason: a grid already looked at in Slices without picking a preset "has none"
too, and switching its slices because a few lines were added would surprise.

- "Had no lines" is read before `add_lines`. The preset is written **before** the lines are
  added, through the session's slice-source path with only the preset set (the line choice, gain,
  resolution and the rest stay unset), so the lines are prepared once, with the right preset. If
  `add_lines` then refuses, the grid's slice source is put back as it was.
- **The Slices panel follows it** (the author's choice, after the builder check found the gap):
  today `SlicesDock` reads a grid's remembered preset only when its grid combo moves to that grid
  (`_sync_included` → `_restore_remembered_source`). So when the panel is already on the empty
  grid (the only grid of a new site, say), it would prepare the new lines with the first preset
  by name, This grid and Whole site would disagree (the #100/#106 kind of bug), and the panel's
  next `_remember_source` would write the first preset back over the import's choice.
  - Fix: one new slot in `ui/slices_dock.py`, connected to `session.slice_sources_changed`. When
    the changed grid is the one This grid shows, and its remembered preset exists and differs
    from the preset combo, the combo switches to it as a hand choice would (pending restore values
    dropped, preparation re-run), without writing the record again. Every other case does nothing:
    the panel's own `_remember_source` (the record already matches), a gain/resolution/volume
    change (the preset is unchanged), another grid.
  - Session H's plan also edits `slices_dock.py`, elsewhere (around `_snap_inside` and
    `_step_levels`); this is a new function and one `connect` line.
- The Slices panel showing that grid then shows the new preset (walkthrough check, §10).

### 2.5 Applying it

At Import, after `session.add_lines(lines)` succeeds, the chosen preset is applied to **each new
line only**, through the bulk method of §4.4 (`apply_preset_to(name, keys)`), so lines already on
the grid keep their stacks. A preset deleted between choosing and Import is reported in the
dialog's status and nothing is imported (checked before `add_lines`, not after). In practice the
box has already dropped to None by then (§2.1), so this check only guards a race.

## 3. #57: the map and the Survey panel share one line selection

### 3.1 The rule

**The lines selected in the Survey panel are the lines selected on the map's `lines` layer**, so
the map always shows what Delete removes. It works both ways (the author's choice).

- **From the map** (QGIS's Select tool by click, rectangle, polygon, freehand; Select all;
  Deselect): whatever the `lines` layer's selection becomes is copied into the panel.
  - **Several lines:** they become the panel's selection; **nothing opens**.
  - **One line:** it opens, as today (`MapLink._on_selection`, Plan 3 spec §3.4), and is selected
    in the panel (today's `_follow_current` already does this).
  - **None** (a click on empty map, Deselect): the panel's selection is cleared. The open line
    stays open, as today.
- **From the panel:** whenever the panel's selection changes, the `lines` layer's selection is set
  to the selected line rows' features.
  - A plain click still opens a line (`_on_item_clicked`), and that line is now also highlighted
    on the map. (New: today the open line has no highlight.)
  - **A change made in the panel never opens a line from the map side**, including a Ctrl-click
    that shrinks the selection to one line: `_on_selection` must not treat a selection the panel
    pushed as the user's gesture.
  - Grid, cut and site rows are not mirrored. A panel selection with no line rows clears the
    `lines` layer's selection. #31's rule is unchanged: any line in the selection means Remove
    removes lines only.
- **Folded grids:** a selection arriving from the map unfolds each grid that holds a selected
  line, so the panel shows what Delete would remove. (My proposal, shown in the mockup.)
- **Opening a line by any other route** (a pick or mark selected on the map, a cut drawn, a line
  opened from another panel) selects just that line, as the panel does today (`_follow_current`),
  and the map follows: its `lines` selection becomes that one line. A cut opening leaves the
  `lines` selection empty. (My call: one rule, "the open line is the selection after an open".)
- **A map gesture replaces the panel's line selection** with the map's lines, as QGIS's own
  selection does. Unplaced lines selected in the panel are dropped by it, even by a Shift-add on
  the map, since they have no feature to be in the map's selection. (My call.)

### 3.2 What is covered

- **GPS lines** (M17a) are features of the same `lines` layer and select like any other line.
- **Unplaced lines** (time-triggered) have no feature, so they can be selected only in the panel.
  They stay selected there; the map shows the rest. Delete removes them too; the confirmation
  names them.
- **Magnetometer files** (M19a, not merged): checked on `nsgeo-m19-mag` 8328337. A mag file is not
  a `Line`: it is a "magfile" row under its own mag grid, with no processing stack, no velocity,
  and no feature on the `lines` layer. So it never arrives from the map, and §3.3's `select_lines`
  ignores keys that are not line rows.
- **Cuts** keep their own map behaviour (`_on_cut_selection` opens a single cut). Not mirrored.

### 3.3 How (approach A, the author's choice)

Two signals, wired in `plugin.py` next to the other Survey panel connections:

- `MapLink.lines_selected = pyqtSignal(list)` (line keys), emitted by `_on_selection` for every
  `lines` selection change the user made, of any size, before (for one line) opening it as today.
  The change to `_on_selection` stays small and separate (session G will also edit `map_link.py`).
- `MapLink.select_lines(keys)`: set the `lines` layer's selection to the features whose
  `line_key` is in `keys`, by `selectByIds`, doing nothing when the layer's selection already
  matches. While it runs, a depth-counted guard makes `_on_selection` ignore the
  `selectionChanged` it causes: no emit, no open.
- `SurveyDock.line_selection_changed = pyqtSignal(list)` (selected line keys, tree order),
  emitted from the tree's `itemSelectionChanged` when the change was the user's (not one being
  applied from the map, and not a rebuild in progress), and once at the end of every rebuild
  (§3.4).
- `SurveyDock.select_lines(keys)`: make exactly the line rows in `keys` selected, without opening
  anything and without moving the Shift anchor in a way that breaks a later Shift-click; unfold
  their grids; a depth-counted guard keeps it from emitting `line_selection_changed` back.
- New code goes in new functions in `survey_dock.py` and `map_link.py`; existing functions get
  one-line calls into them where needed (§8).

Approach B, keeping "the selected lines" in `SiteSession` with both views following it, was set
aside: it would make keeping the selection across a rebuild nearly free, but puts display state
into `session.py`, which nearly every open branch edits (M19a adds ~100 lines there).

### 3.4 Surviving a redraw

Every `lines_changed` rebuilds the panel and refills the `lines` layer. Today the rebuild keeps
only the current item and selects just the open line (`_restore_selection`: "the session's
current line always wins"), and the refill (`SiteLayers._refill`: provider `truncate` then
`addFeatures`) replaces every feature, so the layer's selected ids go stale or vanish.

- **The panel keeps its selection across a rebuild:** `_capture_state` also records the selected
  line keys, and the rebuild re-selects those still in the site. When it held no line, the rule is
  today's. The open line stays the current item when it is among them.
- **A refill is never the user's gesture:** whatever QGIS does to the layer's selection during a
  refill (it may emit `selectionChanged`, or keep stale ids), the panel's selection must survive
  it. After the rebuild the panel emits `line_selection_changed` once, and the map is re-selected
  by key on the new features.
- **Ordering hazard (verify with real layers, not assume):** `SiteLayers.refresh` is connected to
  `lines_changed` before `SurveyDock.rebuild` (construction order in `plugin.py`), so the refill
  runs first today. If the refill emits a `selectionChanged` that reaches `_on_selection` as an
  empty selection, it would clear the panel before the rebuild captures it. The build must find
  out which happens and guard it (for example: `MapLink` ignores `lines` selection changes while
  the session's `lines_changed` is being delivered, or `SiteLayers` brackets its refill in a
  guard `MapLink` reads). A QGIS-tier test pins it: select 6 lines, set a velocity on them (a
  `lines_changed`), and the 6 are still selected in the panel and on the map.

### 3.5 Limits that stay

- QGIS's Select tool selects on the current layer in the Layers panel; `lines` must be current.
- Zoomed out past where lines crowd, the `lines` layer hides (`_hide_when_lines_crowd`), and QGIS
  does not select in a layer outside its scale range.

## 4. #58: bulk actions on a selection

### 4.1 The menu

`SurveyDock._on_context_menu`, the selection branch (right-click inside a selection of more than
one item). New items in the dashed groups; existing items unchanged:

| Selection | Menu |
|---|---|
| Tape lines on one grid | Edit N lines… · Move N lines to grid ▸ · ─ · **Apply preset to N lines ▸** · **Apply steps from {open} to M lines…** · ─ · **Set velocity for N lines…** · **Clear velocity override on N lines** · ─ · Remove N lines from site |
| Tape lines across grids | Move N lines to grid ▸ (as today) · ─ · *the four new items* · ─ · Remove N lines from site |
| GPS lines only | Set destagger for N GPS lines… · ─ · *the four new items* · ─ · Remove N lines from site |
| Tape and GPS mixed | *the four new items* · ─ · Remove N lines from site |
| Holding a cut (lines-free) or a mag file | as today |

- **Apply preset to N lines ▸** lists the site's presets in name order; greyed when there are none.
- **Apply steps from {open} to M lines…** names the open line by its label (`line_label`). The
  open line is the source; if it is in the selection it is left as it is and not counted (M is
  the others). Greyed, as "Apply steps from the open line…", when no line is open, when a cut is
  open, or when M is 0.
- **Clear velocity override on N lines** is greyed when none of them has an override.
- The single-line menu does not change (the Processing panel already applies a preset to one
  line, and its Set velocity override… stays).

### 4.2 The prompts

Each asks first, with the count (the match for **Apply to grid…**, which asks), or is itself the
question. Cancel or No changes nothing.

- **Apply preset** (Yes/No): "Replace the processing of 6 lines with preset {name}?" plus, when
  the preset has a Migration step, the shared migration sentence (§2.1).
- **Apply steps** (Yes/No): "Replace the processing of 5 lines with the steps on {open}?" plus
  "{open} itself is left as it is." when it was selected, plus the migration sentence when its
  stack has an enabled Migration step.
- **Set velocity** (a number dialog, OK/Cancel; typing a number and OK is the confirmation, no
  second prompt):
  - "Velocity for 6 lines (m/ns):", with the one-line `VelocityDialog`'s range and decimals
    (0–0.3, 4 decimals).
  - Starts at the lines' shared override; else at the velocity the first selected line resolves to
    (`session.resolved_velocity`). (My call.)
  - When some selected lines have a velocity source record (their override came from their saved
    fits): "2 of these lines have a velocity from their saved fits; it will be replaced. The fits
    stay saved on the lines." (The author's choice: replace them and warn.)
  - Always: "Migration steps keep their own velocity."
- **Clear velocity override** (Yes/No): "Clear the velocity override on 2 of these 6 lines? They
  go back to their grid's velocity, or the one in the file's header." plus, when any has a source
  record, "1 of them has a velocity from its saved fits; the fits stay saved."
- **Afterwards** a message-bar line says what changed ("preset Gain + bandpass applied to 6
  lines", "velocity 0.100 m/ns set on 6 lines", "velocity override cleared on 2 lines"), and the
  selection stays as it was (§3.4).

### 4.3 Where each lives

The Survey panel's rule (its module docstring): a confirmation plus one session call lives in the
dock, as Remove does; a dialog is requested through a signal and answered by the plugin, as Set
destagger… is (`open_destagger_dialog`).

- **In `survey_dock.py`, new functions:** apply preset, apply steps, clear velocity (QMessageBox
  question + one session call), each a guarded slot.
- **In `plugin.py`, a new method:** the Set velocity dialog, requested by a new
  `SurveyDock.bulk_velocity_requested = pyqtSignal(list)`, shaped like `open_destagger_dialog`.
- The message-bar line: the dock has no message bar, so it reports through a small new signal
  the plugin answers, or the plugin method reports itself. (Builder's call; one shape for all
  four.)
- **The migration sentence** is one function (in `preset_box.py` or a small helper module),
  reading preset or stack dicts.

### 4.4 Session methods

New `SiteSession` methods, each one change: every key checked first (an unknown key raises
`KeyError` with the site untouched, as `remove_lines` does), one dirty mark, and nothing at all
when nothing would change. They follow `remove_lines` / `set_travel_shift`.

- `apply_preset_to(name, keys)`: a fresh stack from the preset for each key (`apply_preset`'s
  body), `stack_changed` per key as `apply_stack_to_grid` does today. Returns the keys changed.
- `apply_stack_to(source_key, keys)`: the source line's stack copied to each key except the
  source; `apply_stack_to_grid`'s body for a list of keys. Returns the keys changed.
- `set_lines_velocity(keys, model)`: each line's velocity set to `model` (None clears), and its
  velocity source record dropped (grid velocity spec §7.2: a bare number has no source), one
  `lines_changed`. Lines already holding exactly `model` with no record are left alone. Fits stay.

The single-line methods are not looped from the UI: each `set_line_velocity` emits its own
`lines_changed`, which rebuilds the panel and refills the map layer once per line.

## 5. #221: Remove says what goes with the lines

`SurveyDock._removal_text` gains one line, built by a new function of its own (M19a rewrites
`_removal_text` heavily; keeping #221's wording in a separate function keeps that merge to one
call site):

- **One line:** "Also removed: its processing steps, its velocity override and its 2 saved
  velocity fits."
- **Several lines, or a grid's lines:** "Also removed: processing steps on 5 of them, velocity
  overrides on 2, and 3 saved velocity fits on 2." For a grid removal the counts are over the
  grid's lines.
- Each part appears only when there is something to lose: **processing steps** = a stored stack
  with at least one step (`site.stacks`), **velocity override** = `line.velocity is not None`,
  **saved fits** = `line.velocity_fits`. With nothing to lose the line is left out and the prompt
  reads as today.
- Placed right after the question (and the key list, for several lines), before "The DZT file on
  disk is not touched…".
- **Default button:** No when any saved fit would go; Yes otherwise, as today (the author's
  choice). Applies to Remove line, Remove from site (Delete), and Remove grid.

## 6. #16 and #17: tidy-ups in `import_dialog.py`

- **#16:** `ImportDialog._updating` becomes a depth counter (`+= 1` / `-= 1` in `try/finally`,
  read as truthy), as `processing_dock.py` and `param_form.py` do. `_following` is the same
  set/clear shape in the same file and gets the same fix. The issue asks for a sweep: the other
  copies are listed in the PR, not edited, because other sessions are in those files:
  `ui/edit_lines_dialog.py` `_updating` (M19a Plan B edits Edit lines), `ui/grid_dialog.py`
  `_filling`, `ui/paraview_dialog.py` `_loading`, `ui/surfaces_dock.py` `_loading`, `layers.py`
  `_report_follow`.
- **#17:** the Offset cell reads its text with the same rule as `ParamForm._parse_number`'s
  float branch: `float(text)` after stripping spaces, a comma is not a number ("1,000" and "1,5"
  are refused, not read as 1.0 or 1.5), and NaN and infinities are refused. One shared function
  (`parse_decimal`, in a small new module) used by both `ParamForm` and `ImportDialog`, so the
  plugin reads decimal input one way. ParamForm keeps its messages. Session E's plan does not
  edit `param_form.py`; if that changes, ParamForm's switch is the part to drop.

## 7. Approaches considered

- **#57 sync, A (chosen) vs B:** §3.3.
- **Bulk changes as session methods (chosen) vs looping one-line methods:** §4.4. One change per
  bulk action, like `remove_lines` and `set_travel_shift`.
- **Preset memory in the site file (chosen) vs QSettings vs inside `slice_sources`:** presets are
  per site, so a per-user QSettings value would name presets another site does not have; inside
  `slice_sources` it would fire `slice_sources_changed` and has no home for the site's last
  choice.

## 8. Other sessions and open branches

- **Session E** (Processing panel) and **H** (Whole site engine) may run alongside. Nothing here
  edits `processing_dock.py`. The bulk actions are in the Survey panel, not the Processing
  panel's Presets menu.
- **Session H** is building (`nsgeo-site-never-stuck`) and edits `slices_dock.py`; §2.4 adds one
  new slot and one `connect` line there, nothing in H's regions.
- **Session G** (later) edits `map_link.py` (orphaned cut picks) and `survey_dock.py` (a sweep
  action). #57's change to `_on_selection` is a few lines plus new methods.
- **M19a** (`nsgeo-m19-mag`, built, not merged) edits `survey_dock.py` (+151), `plugin.py`,
  `session.py`, `import_dialog.py` (the grid combo lists GPR grids only), `project.py` and the
  core model. Expected overlaps: `_removal_text` (§5 keeps ours to one call), the selection
  branch of `_on_context_menu` (M19a adds `_is_mag_key` checks; the new items must not appear for
  mag keys, which `_selected_targets` returns only when no line is selected), and `save_site` /
  the loader beside `slice_colours`.
- **M17b** will merge the two import dialogs; `PresetBox` moves as one widget, and GPS imports
  then get a grid and join the per-grid memory with no change to §2.3's rule.
- **`plugin.py`:** new wiring lines beside the Survey panel's connections and one new method;
  nothing else.

## 9. Tests to pin

Real data first (`tests/data/local`, Grid 2 DZTs and the `with-dzg` GPS lines), synthetic only as
far as it mirrors them.

- **#129:**
  - Importing with a preset changes only the new lines' stacks, in both dialogs; lines already on
    the grid keep theirs (real DZTs into a grid that already has lines).
  - The box's starting value: grid's choice, else the site's last, else None; a remembered None
    stays None; a deleted preset reads as None; Cancel remembers nothing.
  - The Slices preset is set on the first import into an empty grid with no Slices preset, and
    not on a second import, not for a grid with a Slices preset, not for None.
  - With the Slices panel on that empty grid, it shows the import's preset and prepares the new
    lines with it, once; a later choice in the panel keeps it rather than writing the first preset
    back. An `add_lines` that refuses leaves the slice source as it was.
  - The note's two lines appear exactly when true.
  - Core: `import_presets` round-trips, is dropped tolerantly when malformed, loses a removed
    grid's entry, and does not change `schema_version`.
- **#17:** "1,000" and "1,5" are refused in the Offset cell and in ParamForm with the same rule;
  "nan" and "inf" refused; "1.5" read.
- **#16:** a re-entrant `_refresh_table` (and `_follow_spacing`) does not clear the guard early.
- **#57:**
  - A rectangle selection (several features selected on the `lines` layer) selects them in the
    panel and opens nothing; one feature opens it as today.
  - A Ctrl-click in the panel removes that line from the map selection and opens nothing, also
    when one line is left.
  - Clearing the map selection clears the panel's; the open line stays open.
  - GPS lines select the same way; an unplaced line selected in the panel stays selected.
  - The selection survives a `lines_changed` (§3.4's test).
  - #31's rule: a selection holding a line removes lines only, never a grid.
- **#58:** each bulk action reaches exactly the selected lines (and the source line is untouched
  by Apply steps); one `lines_changed` per velocity action; No/Cancel changes nothing; the fit
  warning counts the lines with a source record; Clear is greyed with no overrides; Apply steps is
  greyed with no open line or a cut open.
- **#221:** the Remove confirmation names what goes, for one line, several, and a grid, and
  leaves the line out when nothing goes; No is the default exactly when a fit would go.

## 10. Walkthrough

Its own QGIS profile, real data, an Artifact with a checks collection (as before). It covers at
least:

- Importing DZT lines with a preset into a grid that already has lines (only the new ones change;
  the box remembers; a second import starts on it).
- Importing into a new, empty grid with a preset: the grid's Slices preset is set, and the Slices
  panel shows it.
- Importing GPS lines (`with-dzg`) with a preset.
- Rectangle-selecting lines on the map, trimming the selection in the panel, then removing them
  with Delete; the prompt names what goes; No is the default when a line has fits.
- Applying a preset, the open line's steps, a velocity and a cleared velocity to a selection;
  the selection stays through each.

## 11. Left to the builder, and calls I made

**Left to the builder:** the guard mechanics in §3.3–3.4 (after finding what a refill does to the
selection); the exact Shift-anchor handling in `select_lines`; the message-bar route (§4.3); the
`PresetBox` API; where `parse_decimal` lives.

**My calls, for the author to check:**
- A remembered preset that no longer exists reads as None (§2.3).
- A selection from the map unfolds the grids holding its lines (§3.1).
- The Set velocity box starts at the shared override, else the first line's resolved velocity
  (§4.2).
- "Apply steps" leaves a selected open line out of the count; greyed when nothing is left.
- A preset deleted while an import dialog is open drops the box to None with a note (§2.1).
- A greyed-out box (no presets yet) remembers nothing at Import (§2.3).
- Opening a line by any route makes it the selection in both places; a map gesture drops unplaced
  lines from the selection (§3.1).
- Tape lines across grids keep **Move N lines to grid ▸**, as today; the mockup left it out by
  mistake (§4.1).
- `_following` in `import_dialog.py` is fixed with `_updating` (§6).
- `ParamForm` switches to the shared `parse_decimal` (§6).
