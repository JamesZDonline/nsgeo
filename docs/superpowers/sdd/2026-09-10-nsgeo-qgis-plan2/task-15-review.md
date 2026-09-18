# Task 15 review: profile dock and the M5 checkpoint

Reviewed commit `2849534` against `fc9237c`, brief `task-15-brief.md`, report
`task-15-report.md`.

## Verdicts

- **Spec compliance: PASS.** Every file, symbol, signal and behaviour the
  brief names is present. The three deviations are all documented and all
  improve on the brief's literal code.
- **Task quality: CHANGES REQUESTED.** The shipped behaviour is very nearly
  right — I drove the whole M5 path through the real `NsgeoPlugin` object and
  the real `LineLoader` and it works — but two things must change before M5:
  one real state-divergence bug the checkpoint can surface, and the fact that
  the three central M5 claims have no test that would fail if they broke.

**Findings: 2 Critical, 6 Important, 8 Minor.**

---

## Method

Everything below was run from a copy of `packages/` in the session scratchpad,
not in the worktree (the worktree is untouched: `git status` clean). Every
sweep ran with `PYTHONDONTWRITEBYTECODE=1`, `QT_QPA_PLATFORM=offscreen`, and
`__pycache__` removed immediately before *and* after each mutant, with the file
restored and re-cleared between runs.

**My own mutation ledger — 86 mutants, 36 killed, 50 survived.**

| Target | Mutants | Killed | Survived | Test scope |
|---|---|---|---|---|
| `ui/profile_dock.py` | 75 | 32 | 43 | `test_plugin_profile_dock.py` (the only file that imports it) |
| `nsgeo/velocity.py` `resolve_velocity` | 4 | 4 | 0 | full `tests/qgis` + `tests/pure` |
| `plugin.py` Step-4 block | 7 | 0 | 7 | full `tests/qgis` + `tests/pure` (258 tests) |

**Reconciliation with the implementer's 21.** All 15 of their kills reproduce
exactly, and all 6 of their survivors reproduce exactly. The ledger is honest
as far as it goes; it simply stops at 21. Scaling to 75 mutants on the same
file moves the survivor count from 6 to 43, and — this is the part that
matters — the newly exposed survivors are not more defence-in-depth guards.
They are the M5 observables themselves (below). Restricting the sweep to the
dock's own test file is sound: `grep -rln "ProfileDock" packages/nsgeo-qgis/tests`
returns exactly one file, and I confirmed by running the full 212-test QGIS
tier for a sample of survivors that no other file kills them.

---

## Critical

### C1. Cursor and selection survive a line switch — the view contradicts the session

`SiteSession.open_line` resets `_current_trace = -1` and `_selection = (-1, -1)`
but emits **no** `trace_changed` / `selection_changed` for the reset.
`ProfileDock._open` then calls `ProfileView.set_axes`, which does not touch
`_cursor` or `_selection` (only `ProfileView.clear()` does, and that is reached
only from `_clear_view_only`). So both carry across to the next line.

Measured, with the real trace counts from the M4 site (608 → 666):

```
before switch cursor/sel: 500 (100, 200)
AFTER  switch (608->666): 500 (100, 200) | session: -1 (-1, -1)
```

The view paints an orange cursor at trace 500 and a blue selection band over
traces 100–200 of `FILE__008` — a line on which the user selected nothing, and
which the session agrees has no selection. It is shape-independent (nothing in
`_open` resets either field), so it fires on every line switch in the M5 site.

Concrete failing input (add to `test_plugin_profile_dock.py`):

```python
session.set_trace(key, 120)
dock.view.range_selected.emit(5, 9)
session.open_line(key2)
assert dock.view._cursor == -1            # actual: 120
assert dock.view._selection == (-1, -1)   # actual: (5, 9)
```

Why Critical and not cosmetic: `session.py`'s own module docstring is
"SiteSession: the one place survey state lives … no widget holds survey state".
Here the widget holds state the session has already discarded. The cursor
self-corrects on the next hover; the **selection band does not** — it persists
until the next drag or a site close, and Task 17's "apply this step to the
selection" will read `session.selection == (-1, -1)` while the user is looking
at a band over traces 100–200. That is the bug this architecture exists to
prevent.

Fix: reset both in `_open` before configuring the new line, e.g.
`self.view.set_cursor(-1)` and `self.view.clear_selection()` right after
`self.image = None`. That also fixes M3 below for free if you clear the
transform at the same time.

### C2. The three central M5 observables have no test that would fail if they broke

Each of these mutants leaves the *entire* 16-test file green:

| Mutant | Shipped behaviour it silently removes |
|---|---|
| `_render`: drop `self.view.set_image(self.image.image)` | **the radargram never reaches the view at all** |
| `_refresh_velocity`: drop `self.view.set_velocity(model)` | **the depth axis never appears** (`_paint_axes` draws it only `if self._velocity is not None`) |
| `_open`: `line.header.position_ns` → `0.0` | **the depth/time axes start at 0, not −0.443 m / −11.086 ns** — i.e. the exact thing M5 asks the human to look for |
| `_open`: `line.header.n_samples` → `line.n_traces` | the pre-load sample axis is wrong |
| `_safe_distance`: always return `None` | the bottom axis silently degrades from metres to trace index |

The cause is that the whole file asserts only on `dock.image`, `dock.view.transform`
and `dock.view._cursor`. `grep -n "view._image\|view._velocity\|depth_tick"` over
`test_plugin_profile_dock.py` returns nothing. `dock.image is not None` proves the
dock *built* an image; it proves nothing about whether the widget the user is
looking at ever received it.

`test_opening_shows_axes_and_loading_before_samples_arrive` is the test whose
name promises exactly this and whose body checks only `n_traces`. Four lines fix
the lot:

```python
# before set_profiles
assert dock.view.transform.n_samples == line.header.n_samples
assert dock.view.transform.t0_ns == pytest.approx(line.header.position_ns)
assert dock.view._velocity is not None and dock.view.depth_tick_labels()
assert dock.view._distance is not None          # metres, not trace index
# after set_profiles
assert dock.view._image is not None
```

`ProfileView.depth_tick_labels()` was added in Task 14 as a public test hook for
precisely this and is not used anywhere. The real values, measured:
`t0_ns = -11.086`, `depth_at(time_lo) = -0.4434 m`, `_distance_unit_label() == "m"`.

This is Critical because M5 is the gate these tests are supposed to protect, and
because the trap is the exact one this branch keeps paying for: an assertion a
do-nothing implementation satisfies.

---

## Important

### I1. `plugin.py`'s entire Step-4 block is untested

All seven plugin mutants survive the full 258-test suite:

- delete the four lines that construct, wire, add and track `ProfileDock` → **258 passed**
- delete `addDockWidget(...)` → 258 passed
- delete `self.docks.append(self.profile_dock)` (the dock is then never removed
  or deleted on unload — a leak) → 258 passed
- delete `self.profile_dock = None` in `unload` → 258 passed
- delete `self.profile_dock.error.connect(...)` → 258 passed
- delete the whole `for dock in self.docks: removeDockWidget; deleteLater` loop → 258 passed
- construct the dock parentless instead of parented to `main` → 258 passed

The plugin could ship with **no profile dock at all** and the suite is green,
which is a poor state to be in on the commit immediately before "reload the
plugin and look at the dock". `test_plugin_loads.py` checks the toolbar, the
menu and the loader, and nothing about docks; `test_plugin_survey_dock.py:106`
checks `plugin.survey_dock in fake_iface.docks` and there is no profile
equivalent. Two lines:

```python
assert plugin.profile_dock in fake_iface.docks
...
plugin.unload()
assert fake_iface.docks == [] and plugin.profile_dock is None
```

The code itself is correct — I verified it directly: `initGui` yields
`['SurveyDock', 'ProfileDock']` in `fake_iface.docks`, `unload` empties the list,
and after one `sendPostedEvents(None, DeferredDelete)` pass `sip.isdeleted(dock)`
is `True`. No leak, no connection left on a dead object.

### I2. `Fit`, `1:1` and the pick relay are wired but unproven

Deleting `fit_button.clicked.connect(self.view.fit)`,
`one_to_one_button.clicked.connect(self.view.one_to_one)`, or
`self.view.pick_requested.connect(self._pick)` all leave the suite green. Two of
those three are M5 observables ("Fit and 1:1 restore"), and `pick_requested` is a
named output of the brief's interface that Task 19 will consume. Each is a
one-line test — `dock.fit_button.click(); assert transform.trace_hi - trace_lo == n_traces`.
(I confirmed all three do work today: after a 4× zoom, `fit_button.click()`
restores 0–240; `dock.view.pick_requested.emit(10, 5.0)` relays
`('raw/FILE__001.DZT', 10, 5.0)`.)

### I3. `velocity_source`'s identity trick is *weaker* than `==`, and its docstring overclaims

The dispatch asked me to confirm a regression would be caught. It is: mutating
`resolve_velocity` to return `VelocityModel(layers=grid.velocity.layers)`
instead of `grid.velocity` fails exactly one test —
`test_plugin_profile_dock.py::test_velocity_label_names_its_source`, with
`assert 'header ε 14' == 'Grid A'`. All four of my `resolve_velocity` mutants
(copy-on-line, copy-on-grid, copy-on-both, precedence swap) are killed. So the
contract *is* pinned, by one test, in the right file. Good.

But two things are wrong with the reasoning in the docstring and report:

1. **`==` strictly dominates `is` here.** I mutated `is` → `==` on both
   comparisons; both survive, i.e. the two are indistinguishable on every input
   the suite has. They differ on exactly one class of input: a `resolve_velocity`
   that returns a copy. `is` names the wrong tier there; `==` still names the
   right one. And `==` cannot misfire, because a `VelocityModel` is a frozen
   dataclass with value equality and the only competing candidates are `None`
   (never equal to a model) or a model that genuinely *is* the resolved tier.
   The variant chosen is the fragile one.
2. **"this can never name the wrong tier, whatever the precedence becomes" is
   false.** It is true for *reordering* the existing three tiers (I confirmed:
   swapping the two `if`s in `velocity_source` is an equivalent mutant). It is
   false for *adding* one. GitHub issue #4 changes this precedence; if it adds,
   say, a site-level default, a line resolving to that default falls through both
   identity checks and is labelled `header ε 14` while the readout says
   `v = 0.100 m/ns` — a label confidently naming the wrong tier, which the
   docstring itself calls "worse than no label at all". The unguarded `return`
   on the last line is the hole.

   Concrete failing input, today's code, one plausible future `resolve_velocity`:
   line with no override, grid A with no velocity, a site default of 0.10 m/ns →
   label reads `v = 0.100 m/ns (header ε 14)`.

   Fix: use `==`, and make the fallback branch assert rather than assume —
   `if resolved == VelocityModel.from_dielectric(line.header.epsr): return f"header ε …"`
   then `return "unknown source"`. Or, better and once: have `resolve_velocity`
   return `(model, tier)` so there is nothing to derive at all.

### I4. Survivor #6's justification is wrong: `ProjectError` is not a `KeyError`

The report says the `not self.session.is_open` half of `_refresh_velocity`'s
guard is "provably redundant with the exception handler immediately below it".
It is not. With `self._key` set and the site closed,
`session.resolved_velocity(key)` → `line_for_key` → `_require_site()` raises
`ProjectError`, and `class ProjectError(Exception)` — verified, not a `KeyError`
subclass. So without that half, the call lands in the *broad*
`except Exception` and **logs a Critical message to the QGIS log** instead of
returning silently. I verified the raise directly:
`resolved_velocity raises: ProjectError no site is open | is KeyError: False`.

The mutant survives because that state is not reachable today (`close_site`
emits `line_opened("")` before `site_closed`, so `_key` is already `None`), not
because the two are equivalent. Keep the guard; correct the claim. This matters
because "provably redundant" is the note that gets a guard deleted in Task 18.

### I5. Two brief-written tests pass vacuously

- `test_closing_the_site_clears_the_view` never calls `set_profiles`, so
  `dock.image` is already `None` when it asserts `dock.image is None`. Deleting
  `self.image = None` from `_clear_view_only` survives. Add
  `session.set_profiles(key, line.load())` before `session.close_site()` and the
  assertion becomes real.
- `test_cursor_and_selection_follow_the_session_and_vice_versa` checks
  session→view for the cursor (`dock.view._cursor == 12`) but only view→session
  for the selection. Deleting `self.view.set_selection(a, b)` from
  `_on_selection_changed` survives. Add
  `session.set_selection(key, 5, 9); assert dock.view._selection == (5, 9)`.

Both are the brief's own tests, not the implementer's. Named here so the brief's
side is the one corrected.

### I6. `_pick` is the one slot that does not guard its body

Eight session signals and three view signals were checked individually, not
sampled:

| Signal | Slot | Guarded |
|---|---|---|
| `line_opened` | `_on_line_opened` | yes (`_open` wrapped) |
| `line_loaded` | `_on_line_loaded` | yes |
| `stack_changed` | `_on_stack_changed` | yes |
| `trace_changed` | `_on_trace_changed` | yes |
| `selection_changed` | `_on_selection_changed` | yes |
| `lines_changed` | `_refresh_velocity` | partly — see below |
| `grids_changed` | `_refresh_velocity` | partly |
| `site_closed` | `_clear` | yes |
| `view.trace_hovered` | `_hovered` | yes |
| `view.range_selected` | `_range_selected` | yes |
| `view.pick_requested` | `_pick` | **no** |

Plus four widget signals: `valueChanged`/`currentTextChanged` → `_display_changed`
(guarded), `currentIndexChanged` → `_channel_changed` (guarded), and
`fit_button`/`one_to_one_button` wired straight to `ProfileView.fit`/`one_to_one`,
which are unguarded but only re-emit `view_changed` — no subscriber today.

`_pick` re-emits `self.pick_requested`, which runs every downstream slot
synchronously. Today nothing connects it, so nothing can raise; Task 18/19 will
connect a picking dock, and at that point an exception in the picking handler
escapes `_pick`, escapes `ProfileView.mousePressEvent`, and vanishes — the exact
hazard this file's own docstring says every slot must guard. Wrap it now while
it is one line.

Separately, `_refresh_velocity`'s last two statements (`self.view.set_velocity(model)`
and `self.velocity_label.setText(...)`) sit *outside* its try. Low risk, but the
file's stated rule is "guards its own body", and this body is not fully inside.

---

## Minor

1. **Same-shape line switch inherits the previous line's zoom window.** Measured:
   two 240-trace lines, zoom to traces 90–150 on the first, open the second —
   `dock.view.transform is zoomed` is `True`, literally the same object. This
   contradicts `test_switching_lines_does_not_inherit_the_previous_lines_window`'s
   own docstring ("the second line's view would incorrectly inherit the first
   line's stale window instead of a fresh fit"): the guard it pins only fires
   when the shapes differ. Harmless at M5 — the M4 site's ten trace counts
   `[608, 625, 629, 658, 613, 608, 635, 666, 653, 606]` include two 608s, so it
   is reachable but only between `FILE__001` and `FILE__006`. Decide which you
   want (keeping zoom while flipping through lines is arguably the nicer
   behaviour) and gate it on `_key` changing rather than on shape, so it is
   consistent either way. The C1 fix subsumes this if you clear the transform in
   `_open`.
2. **The whole multi-channel path is untested.** `_channel_changed`,
   `_configure_channels`'s `setCurrentIndex(session.channel(...))`,
   its `blockSignals`, its `clear()`, and the `currentIndexChanged` connection
   are all survivable mutations; only the single-channel "combo is hidden" case
   is covered. It does work — I built a 2-channel DZT with
   `write_dzt(..., n_channels=2)` (the helper already supports it) and confirmed
   the combo shows 2 items, `setCurrentIndex(1)` reaches
   `session.set_channel`, and the rendered data changes. One test would pin it.
3. **Slider range and default are unpinned.** `setRange(900, 1000)` → `(900, 999)`
   and `setValue(990)` → `setValue(900)` both survive. The second ships a 90 %
   clip instead of 99 % — a visibly more saturated image at M5. The brief names
   `900–1000, tenths of a percent` in its interface; assert it.
4. **`_render`'s `if rg is None: return` and `current_radargram`'s
   `if stack.source is None: return None` are both unpinned.** Removing either
   converts a silent no-op into a logged Critical / a spurious
   `"stack has no source radargram"` in the message bar. Not reachable today.
5. **Dead weight confirmed by equivalent mutants.** `session.site_closed.connect(self._clear)`,
   `self._key = None` inside `_clear`, and `session.grids_changed.connect(self._refresh_velocity)`
   are all fully redundant today: `close_site` emits `line_opened("")` first
   (which runs `_open("")` → `_key = None` → `_clear_view_only()`), and
   `replace_grid` emits `lines_changed` alongside `grids_changed`. Keep them as
   belt-and-braces, but they are not "guards" — note that, or the next reviewer
   will chase them as gaps.
6. **`setObjectName("nsgeoProfileDock")` is unpinned** (mutating it survives).
   QGIS restores dock geometry by object name across sessions, so a typo here
   costs the user their layout silently. `test_plugin_loads.py` already pins
   `toolbar.objectName()`; do the same for both docks.
7. **The dock will open short.** Nothing sets a size; `ProfileView.setMinimumSize(240, 120)`
   is the only constraint, so the bottom dock's initial height is roughly
   `titlebar + 30 px control bar + 120 px view` ≈ 185 px, of which 36 px is axis
   margin. The brief's own tests use `dock.resize(900, 360)`. Consider
   `self.view.setMinimumHeight(240)` so the first sight of real data is not a
   ~90 px-tall strip.
8. **Display-gain re-render cost is per slider step**, not debounced: 9.4 ms per
   step measured on a 666×512 line, so a 100-step drag is ~1 s of cumulative
   numpy. Fine for this dataset (M5 will feel instant); worth remembering when
   lines get larger, since `PercentileClip.limit` re-scans the whole array each
   time.

---

## Verdict on the implementer's 6 surviving mutants

Asked for a second opinion, particularly on the `SiteSession` key-sync
invariant. All six reproduce; my verdict differs on two of the six *reasons*,
not on the conclusion to keep every guard.

| # | Survivor | My verdict |
|---|---|---|
| 1 | `_render`'s `rg.n_traces == line.n_traces` guard | **Agree.** No step in the registry changes trace count; `time_zero` crops samples only. Unreachable. Correctly filed, correctly not tested. |
| 2 | `_on_trace_changed` key guard | **Agree it is unkillable today; disagree with the reason.** |
| 3 | `_on_selection_changed` key guard | Same as #2. |
| 4 | `_channel_changed` guard | **Agree.** The only unblocked `currentIndexChanged` comes from a user acting on a visible combo, which requires an open line; `_configure_channels` blocks signals around both `clear()` and `setCurrentIndex`. |
| 5 | `_range_selected` guard | **Agree.** `ProfileView.mouseReleaseEvent` emits only when `_press is not None and transform is not None`, and `_clear`/`_open("")` null `_key` and the transform inside one synchronous call, so no event can interleave. |
| 6 | `_refresh_velocity`'s `is_open` half | **Disagree with the reason — see I4.** `ProjectError` is not a `KeyError`; the two halves are behaviourally distinguishable (silent return vs logged Critical). Unreachable today, but not redundant. |

**On #2/#3 and the key-sync invariant specifically.** The report frames these as
"defense-in-depth against SiteSession's own invariant" — that
`set_trace`/`set_selection` gate on `key == self._current_key` before emitting,
so the dock can only ever see its own key. That is true of the *emitter*, but it
is not where the risk lives. The real exposure is a slot-ordering window that
already exists:

`SiteSession.open_line` sets `self._current_key = key2` **and then** emits
`line_opened(key2)`. Three objects subscribe to `line_opened`, and PyQt runs
them in connection order, which `initGui` fixes as: `LineLoader` (constructed
first), `SurveyDock`, `ProfileDock` (constructed last). For the duration of the
first two slots, `session._current_key == key2` while `dock._key` is still
`key1`. Any subscriber ahead of `ProfileDock` that calls
`session.set_trace(key2, n)` from its `line_opened` handler emits
`trace_changed(key2, n)` straight into a dock whose `_key` is `key1` — and the
guard fires for real.

Today neither of the two earlier subscribers does that: `LineLoader._on_line_opened`
only calls `request(key)`, and `SurveyDock._follow_current` only calls
`tree.setCurrentItem`. I checked both. But Tasks 16 (map link) and 18 (picking)
are exactly the kind of code that reacts to a line opening by positioning a
cursor or restoring a saved trace, and `plugin.py` appends new docks *after*
`ProfileDock`, so whether the window is live depends on nothing more than the
order of two `connect()` calls.

So: **keep both guards, do not write a test for them** (a test would have to
forge the divergence through private state, which pins an implementation
detail), and replace the justification comment with the ordering argument
above — it is the one a future reader needs, and it is the one that tells them
the guard becomes load-bearing the moment they add a subscriber.

---

## On the 8 tests added beyond the brief

Asked to check the judgement. **All eight are justified; keep every one.** Each
maps to a mutant that is otherwise unkilled, and I reproduced every one of those
kills:

| Added test | Mutant it alone kills | Verdict |
|---|---|---|
| `..._falls_back_to_the_header_dielectric` | header-tier label | keep — the brief's own velocity test never reaches tier 3 |
| `..._same_shape_keeps_the_current_zoom` | keep-window restore removed | keep |
| `..._does_not_inherit_the_previous_lines_window` | `keep_window`'s `n_traces` half → `True` | keep (its docstring needs the M1 correction) |
| `..._stack_change_on_a_different_line_is_ignored` | `_on_stack_changed` key guard | keep |
| `..._line_loaded_for_a_different_line_is_ignored` | `_on_line_loaded` key guard | keep |
| `..._hover_with_no_line_open_is_a_silent_no_op` | `_hovered` key guard | keep — and it is *not* a do-nothing assertion; I confirmed the mutant is killed |
| `..._set_difference_index_shows_what_a_step_actually_removed` | difference branch → `stack.result()` | keep, and it is sound: the expected value comes from `StepStack.source`/`intermediate`, not from `difference()` itself, and `difference()` is `before - after` (stack.py:127), so a sign flip would fail it |
| `..._time_triggered_line_shows_a_trace_axis_instead_of_raising` | `_safe_distance` catching `KeyError` | keep — this is a real brief defect caught (below) |

None of them pins an intermediate state that would reject a better
implementation, and none computes its expected value from the code under test.
The one caveat is that the set is aimed at the guards and misses the observables
— see C2.

---

## Where the brief is wrong

Six defects; in every case I would keep the implementation's side.

1. **`line.distance_along()` passed raw to `set_axes` in both `_on_line_opened`
   and `_render`.** Raises `ValueError` for a time-triggered acquisition
   (`traces_per_metre <= 0`) from inside a `line_opened` slot, which PyQt
   swallows — no axes, no error. The implementer's `_safe_distance` is correct
   and the added test is correct. **Keep the implementation.**
2. **The brief's dock has no slot guards at all.** Every slot in the brief's
   code is bare, which contradicts the hazard rule stated in this branch's own
   `plugin.py`, `survey_dock.py` and `profile_view.py` docstrings and re-stated
   in the brief's own context note. **Keep the implementation.**
3. **The brief lists `resolve_velocity` as consumed and then never imports or
   calls it**, duplicating its three-tier cascade inside `velocity_source`
   instead. **Keep the implementation** (with the `==`/fallback corrections in I3).
4. **`test_closing_the_site_clears_the_view` never loads samples**, so its
   `dock.image is None` assertion is satisfied by an image that was never
   created (I5). **Fix the brief's test.**
5. **`test_cursor_and_selection_follow_the_session_and_vice_versa` tests the
   selection in one direction only** (I5). **Fix the brief's test.**
6. **The M5 checkpoint asks for an observation the UI does not offer.** "The
   depth axis on the right starts at about −0.44 m" is *numerically correct* —
   `t0_ns = -11.086`, `v = 0.080 m/ns`, `depth_at(-11.086) = -0.4434 m`, all
   measured — but `ProfileView._depth_ticks` labels `nice_ticks(-0.443, 4.0)`,
   which yields `['0', '1', '2', '3']`. There is no `-0.44` label, and likewise
   the time axis reads `['0', '20', '40', '60', '80']` with no `-11`. The human
   sees the 0 m and 0 ns ticks sitting about 10 % of the image height *below the
   top edge*. Reword the checkpoint: "the 0 ns and 0 m ticks sit about a tenth of
   the way down, not at the very top — time zero has not been applied; wheel-zoom
   into the top of the image to read the negative values."

---

## Is M5 safe for a human to run?

**Yes.** I drove the entire path end to end through the real `NsgeoPlugin`,
the real `LineLoader` background task and the real `QgsDockWidget`, not through
the test doubles. Every claim in the checkpoint holds except the one the brief
itself got wrong:

| M5 claim | Result |
|---|---|
| axes appear at once | `open_line` → header axes in **0.16 ms** |
| the image within a second | first render **11.7 ms** (666 × 512), via the real `QgsTask` loader |
| display-gain slider remaps instantly | **9.4 ms** per slider step |
| wheel-zoom about the cursor, middle-drag pan | untouched by this task; `ProfileView` handlers reviewed in Task 14, and the dock adds no event filter |
| Fit and 1:1 restore | verified: 4× zoom → `fit_button.click()` restores 0–240 |
| depth axis starts near −0.44 m because time zero is not applied | **true in the data** (`depth_at(time_lo) = -0.4434 m`), **not readable as a label** — see brief defect 6 |
| click another line, previous reopens from cache | works; `profiles_for` hit renders immediately |
| unload is clean | both docks removed, `sip.isdeleted(profile_dock)` `True` after one DeferredDelete pass, no leak |

Three things to tell whoever drives it, so they do not chase phantoms:

1. **The −0.44 will not appear as a number.** Check instead that the 0 m and 0 ns
   ticks sit about a tenth of the way down from the top of the image, and
   wheel-zoom into the top if they want to read the negative values.
2. **"1:1" will look like it does nothing.** These lines are 606–666 traces in a
   dock roughly 1200 px wide, so one-trace-per-pixel is wider than the line and
   clamps back to the fit. That is correct behaviour, not a dead button.
3. **If they hover the image and then click a different line in the tree, the
   orange cursor — and any blue selection band from a left-drag — stays behind
   from the previous line.** That is C1, a real bug in this commit, not a QGIS
   rendering artefact. Nothing else about the switch is wrong.

None of the findings above risks corrupting data, crashing QGIS, or wasting the
human's five minutes. Fix C1 before or after the checkpoint as you prefer — but
fix C2 before Task 16 builds on top of an untested viewer.
