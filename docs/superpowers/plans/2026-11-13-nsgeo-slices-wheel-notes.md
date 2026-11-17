# Slices Panel: Wheel, Typing, Width and Notes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scrolling the Slices panel or the Edit lines table never changes a value. dz can't go
below the radar's sample interval, and no cube deeper than twice its lines' samples is built. A
Whole site refresh leaves a box being typed in alone. Refusals and warnings sit in full in a
Warnings section. The settings sections fold. The panel fits the Processing panel's minimum width.

**Architecture:** A small `wheel_guard` helper gives chosen boxes the focus rule and lets go of
focus when the user scrolls. A `WarningsPanel` under Position collects each scope's entries. The
level limit lives in `SliceEngine.set_resolution`, the one place both scopes' resolutions pass
through, as a pure check from `slices_plan`. Folding uses `QgsCollapsibleGroupBox`, with its
remembered state in our own settings keys. Width is pinned by a guard test against
`ProcessingDock`'s minimum.

**Tech Stack:** Python 3.12, PyQt via `qgis.PyQt` (Qt 5 on QGIS 3.44, Qt 6 on QGIS 4.2),
`qgis.gui.QgsCollapsibleGroupBox`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-13-nsgeo-slices-wheel-notes-design.md`. Read it with this
plan: the sections cited below (§n) are its own.

## Global Constraints

- **Both Qt versions.** QGIS 3.44 (Qt 5) and 4.2 (Qt 6) must both pass. Import Qt only through
  `qgis.PyQt`, and spell enums out in full (`Qt.FocusPolicy.StrongFocus`).
- **Guard every Qt entry point.** Every Qt override, event filter and slot guards its own body with
  `except Exception`, reporting through `_log` or the dock's existing path. Nothing raises into Qt.
- **Wheel rule scope.** It applies to `cell_spin`, `dz_spin`, `z0_spin`, `z1_spin` and the Edit
  lines per-row Grid combos only. No other widget's wheel behaviour changes.
- **One place per message.** A refusal shown in Warnings is never also emitted on `error` (the
  toast). `Resolution.__post_init__`'s own refusals ("t1_ns must exceed t0_ns", "dz_ns must be
  positive") stay toasts.
- **Records stay as saved.** A floor raise changes the box only, never a remembered resolution, a
  site resolution or a cube record.
- **Exact copy:**
  - the level-limit message: *"Too many levels: dz 0.2165 ns from 0 to 100,000 ns makes 461,894
    levels; this cube allows 1,024 (twice the 512 samples in each line). Narrow z0–z1 or raise
    dz."*;
  - the preview note (Task 2);
  - the coverage tooltip (Task 4).
- **Settings.** Tests never read or write a real QGIS settings file. Fold state goes through
  `nsgeo_qgis.ui.folds.fold_settings()`, which the test conftest replaces (Task 4).
- **Local data stays local.** Never `git add` anything under `packages/nsgeo-core/tests/data/local/`
  except its README (its entries in this worktree are symlinks).
- **Commits.** Push each commit as it is made: `git push origin nsgeo-slices-wheel-notes`. End
  commit messages with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **How to run tests.** Run from the worktree root
  (`/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-slices-wheel-notes`):
  - QGIS tests:
    `QT_QPA_PLATFORM=offscreen ../../.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/<file> -q`
  - pure tests: `../../.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q`

**Setup, done by the controller before Task 1:** link the real data into this worktree as the other
worktrees do (`for f in ../../packages/nsgeo-core/tests/data/local/*; do [ "$(basename "$f")" = README.md ] || ln -s "$(realpath "$f")" packages/nsgeo-core/tests/data/local/; done`),
so the `needs_real_data` tests run.

## Review Focus

1. **The author's own site already holds dz 0.001 ns** from the accident: in the grid's
   remembered resolution, the site resolution, and possibly a saved cube. Opening it must show
   0.2165, build a normal cube and leave every record still saying 0.001. Pinned in Task 3,
   one test per record kind.
2. **A site mixing radars**, for example a grid with 1,024 samples over the same 110.86 ns beside
   the 512-sample grids. The dz floor is the finest interval, and the seeded defaults are never
   refused, whichever grid comes first. Pinned in Task 3, both orders.
3. **A Warnings entry appearing or going while a Resolution box has focus**, with the panel
   scrolled to the bottom so its range shrinks. Focus and the typed value stay; the panel moving
   is not a user scroll. Pinned in Task 2.
4. **Keyboard users.**
   - Tab into dz while it is scrolled out of view: the panel scrolls it into view and dz keeps focus.
   - Arrow keys on the scroll bar count as a user scroll and do let go.
   - Pinned in Task 1, through `ensureWidgetVisible` and `triggerAction`.
5. **Qt 6.** Two behaviours must be checked in the `qgis/qgis:4.2` image, not only locally:
   - an ignored wheel event propagating to the scroll area;
   - `QgsCollapsibleGroupBox` folding while hidden.

   Task 5 runs the wheel, fold and width test files there.

---

### Task 1: The boxes leave you alone: the wheel rule and typing (#177 wheel, #176, #105)

Spec §2, §4, §5.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/wheel_guard.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (after `scroll` is built, ~line 724)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/edit_lines_dialog.py:217-223` (the per-row combo loop
  only; the M19a Plan B clash, spec §10)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py` (`set_spins_quietly`, ~463)
- Modify: `packages/nsgeo-qgis/tests/plugin_testing.py` (add `wheel_event`)
- Test: `tests/qgis/test_plugin_slices_dock.py` (new section `# ---- the wheel rule (#177) ----`),
  `tests/qgis/test_plugin_edit_lines_dialog.py`, `tests/qgis/test_plugin_site_scope.py`

**Interfaces:**
- Produces: `guard_wheel(widget: QWidget, scroll_area: QAbstractScrollArea) -> None`. It does three
  things:
  - sets `StrongFocus` on `widget`;
  - makes a wheel event on `widget` while it lacks focus be ignored and go on to its parents, so
    the scroll area scrolls;
  - on any user action of `scroll_area`'s scroll bars (`actionTriggered`), moves focus from
    `widget`, if it has it, to `scroll_area`.

  A value set in code, a range clamp or `ensureWidgetVisible` fires no action, so it keeps focus
  (spec §2). Adding a box later is one call.
- Produces: `plugin_testing.wheel_event(dy: int = -120) -> QWheelEvent`, a plain vertical notch built
  exactly as `_wheel` in `test_plugin_param_form.py` (which works on both Qt versions).
- Produces: `set_spins_quietly(dock, **values) -> bool`, same signature. It now skips a spin whose
  value already equals the target. It also skips a spin that has focus and whose text differs from
  its value's own display (`spin.cleanText() != spin.textFromValue(spin.value())`).

- [ ] **Step 1: Write the failing tests.** In `test_plugin_slices_dock.py`, using `_ready`:

```python
GUARDED = ("cell_spin", "dz_spin", "z0_spin", "z1_spin")

def _short_and_active(dock):
    """Floated short enough to scroll, shown and active, so focus is real."""
    dock.setFloating(True)
    dock.resize(420, 300)
    dock.show()
    dock.activateWindow()
    assert QTest.qWaitForWindowActive(dock)
    scroll = dock.findChild(QScrollArea)
    scroll.verticalScrollBar().setValue(0)
    return scroll

@pytest.mark.parametrize("name", GUARDED)
def test_the_wheel_over_an_unfocused_resolution_box_scrolls_the_panel_and_changes_nothing(docked, name):
    dock, _ = docked
    _ready(dock)
    scroll = _short_and_active(dock)
    dock.slice_slider.setFocus()
    values = {n: getattr(dock, n).value() for n in GUARDED}
    z, frame = dock.engine.z, dock.engine.frame
    QApplication.sendEvent(getattr(dock, name), wheel_event(-120))
    QTest.qWait(200)  # past the 120 ms debounce
    assert {n: getattr(dock, n).value() for n in GUARDED} == values
    assert dock.engine.z is z and dock.engine.frame is frame  # nothing re-prepared
    assert scroll.verticalScrollBar().value() > 0  # the panel scrolled

def test_a_focused_resolution_box_still_takes_the_wheel(docked):
    # dz focused; one notch up: value == before + singleStep (approx 1e-4)

def test_scrolling_the_panel_lets_go_of_the_box_you_typed_in(docked):
    # dz focused, dz.setValue(0.75); sendEvent(scroll.viewport(), wheel_event(-120))
    # -> not dz.hasFocus(); dz.value() == 0.75; scroll moved;
    # a second notch sent to dz leaves it at 0.75

def test_the_panel_moving_on_its_own_keeps_the_focus(docked):
    # dz focused; scroll.verticalScrollBar().setValue(maximum());
    # scroll.ensureWidgetVisible(dock.display_group) -> dz.hasFocus() still True;
    # then scroll.verticalScrollBar().triggerAction(QAbstractSlider.SliderAction.SliderSingleStepSub)
    # -> dz.hasFocus() False (a keyboard/arrow scroll is a user scroll)

def test_the_thickness_box_keeps_todays_wheel(docked):
    # thickness_spin unfocused: a notch changes it (the rule reaches only the four)
```

In `test_plugin_edit_lines_dialog.py`, using the `table` fixture, with the dialog shown and active:

```python
def test_the_wheel_over_an_unfocused_grid_combo_moves_no_line(table):
    # table focused; sendEvent(cellWidget(2, COL_GRID), wheel_event(-120)) for both directions
    # -> every row's combo still "Grid5"; dialog.accept() moves no line to "B"

def test_after_picking_a_grid_focus_goes_back_to_the_table(table):
    # combo = cellWidget(2, COL_GRID); combo.setFocus(); QTest.keyClick(combo, Qt.Key.Key_Down)
    # -> combo.currentText() == "B"; dialog.table.hasFocus()

def test_scrolling_the_table_lets_go_of_a_focused_grid_combo(table):
    # combo focused; table.verticalScrollBar().triggerAction(SliderSingleStepAdd) -> not combo.hasFocus()
```

In `test_plugin_site_scope.py`:

```python
def test_a_half_typed_value_survives_a_whole_site_ready_tick(plugin):
    # whole_site; float, show, activate; dz focused; select dz's number and QTest.keyClicks "0."
    typed = dock.dz_spin.cleanText()
    plugin.session.remember_site_resolution(dz_ns=0.433)  # the tick now wants another dz
    scope.ready_handled = None
    scope._run_tick()
    assert dock.dz_spin.cleanText() == typed

def test_an_unchanged_value_is_not_set_again(plugin, monkeypatch):
    dock = whole_site(plugin)
    calls = []
    monkeypatch.setattr(dock.dz_spin, "setValue", calls.append)
    assert site_scope_module.set_spins_quietly(dock, dz=dock.dz_spin.value()) is False
    assert calls == []
```

- [ ] **Step 2: Run them; expect failures.** The wheel tests change values and the panel does not
  scroll. The focus hand-back is absent. The half-typed text is overwritten. Run both
  `test_plugin_slices_dock.py -k "wheel or lets_go or focus or thickness_box"` and the Edit lines
  and site scope tests by name.

- [ ] **Step 3: Implement `guard_wheel`** in `ui/wheel_guard.py`.
  - The default focus policy of spin boxes and combos is `WheelFocus`, which Qt grants *before*
    delivering the wheel. That is why `StrongFocus` is required.
  - An event filter that calls `event.ignore()` and returns `True` lets Qt hand the event on to the
    parent. A filter returning `True` with the event accepted would swallow it.
  - The `actionTriggered` slot is guarded.
  - The filter object is parented to `widget`, so it dies with it.
  - The module docstring cites spec §2 and the `TimeSpinBox` precedent (`param_form.py`).

- [ ] **Step 4: Apply it.**
  - **Slices dock:** call `guard_wheel(spin, scroll)` for the four spins, right after
    `self.setWidget(scroll)`.
  - **Edit lines:** in the combo loop, add `guard_wheel(combo, self.table)` and
    `combo.activated.connect(lambda _i: self.table.setFocus())`. These are the only two lines that
    change there, so the M19a Plan B clash stays small.
  - **Site scope:** add the two skip rules to `set_spins_quietly`. Keep its return value meaning
    "whether any spin moved".

- [ ] **Step 5: Run the new tests, then the three files whole.**
  - The new tests pass.
  - `test_plugin_param_form.py -k wheel` still passes.
  - `test_plugin_slices_dock.py`, `test_plugin_edit_lines_dialog.py` and
    `test_plugin_site_scope.py` are green.

- [ ] **Step 6: Commit and push.** Message:
  `feat(slices): the wheel leaves dz, z0, z1, cell and Edit lines' Grid alone until clicked (#177, #176, #105)`.

---

### Task 2: A Warnings section, and refusals that stay (#163 item 1, #157 items 4 and 5)

Spec §6.1. Replaces `site_note`.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/warnings_panel.py`
- Modify: `nsgeo_qgis/ui/slices_dock.py` (remove `site_note` at ~464; add the panel after
  `position_group`; `_apply_resolution` frame-cap branch; `restore_cube`; `_seed_resolution_defaults`;
  `_on_source_changed`; `set_scope`)
- Modify: `nsgeo_qgis/ui/site_scope.py` (`show_scope_widgets`, `apply_resolution`, `refresh_slice`;
  `show_note` becomes `warnings`)
- Modify: `nsgeo_qgis/site_engine.py` (`_rebuild_geometry`, `_rebuild_geometry_reporting`, `clear`)
- Modify: `nsgeo_qgis/slices_plan.py` (`preview_note`)
- Test: new `tests/qgis/test_plugin_warnings_panel.py`; `tests/qgis/test_plugin_slices_dock.py`;
  `tests/qgis/test_plugin_site_scope.py`; `tests/qgis/test_plugin_site_engine.py`;
  `tests/pure/test_pure_slices_plan.py`

**Interfaces:**
- Produces, in `ui/warnings_panel.py`:
  - **Kinds:** `REFUSAL = "refusal"`, `WARNING = "warning"`, `NOTE = "note"`.
  - **Icons:** `ICONS = {REFUSAL: "⛔", WARNING: "⚠", NOTE: "ⓘ"}`.
  - **`Entry`:** `@dataclass(frozen=True) class Entry: kind: str; text: str`.
  - **`WarningsPanel(QGroupBox)`:** titled "Warnings".
    - `set_entries(entries: Iterable[Entry]) -> None` shows one word-wrapped `QLabel` per
      non-empty entry, reading `f"{ICONS[kind]} {text}"`. Order is refusals, then warnings, then
      notes, stable within a kind. The panel hides itself when there are none.
    - `entries() -> tuple[Entry, ...]` returns what is shown, in order.
- Produces `SlicesDock.warnings_panel` and `SlicesDock.show_warnings() -> None` (guarded). It asks
  `self._site.warnings()` in Whole site; in This grid it shows `self._grid_refusal`.
- Produces `SlicesDock._grid_refusal: str | None`, This grid's standing refusal. `_apply_resolution`
  sets it on a refusal and clears it on success. A grid change (`_on_source_changed`) and a scope
  switch (`set_scope`) clear it too.
- Produces `SiteScope.warnings() -> list[Entry]` from `self.drawn: bool`, which `refresh_slice` sets
  where it called `show_note`:
  - while drawn, `NOTE` with `engine.preview_note`;
  - while not drawn, `REFUSAL` with `f"Not drawn: {self.problem or engine.geometry_problem}"`;
  - `WARNING` with `mixed_clock_note(radar)` when the clocks are mixed (today's rule).
- Produces `SiteEngine.geometry_problem -> str | None` (a property):
  - `_rebuild_geometry` sets it to `str(exc)` when it raises, then re-raises;
  - a rebuild that completes sets it to `None`, and so does `clear()`;
  - `_rebuild_geometry_reporting` no longer calls `_report`, and logs instead.
- Produces `SlicesDock._set_cell_floor(grid_id: str) -> None`, the floor half of
  `_seed_resolution_defaults`, which now calls it. `restore_cube` calls it for the cube's grid
  before setting the cell.

- [ ] **Step 1: Write the failing tests.**

`test_plugin_warnings_panel.py`:

```python
def test_entries_show_in_full_in_kind_order_and_the_panel_hides_when_empty(qgis_app):
    panel = WarningsPanel()
    panel.set_entries([Entry(NOTE, "n"), Entry(REFUSAL, "r"), Entry(WARNING, "w"), Entry(NOTE, "")])
    assert [e.kind for e in panel.entries()] == [REFUSAL, WARNING, NOTE]
    assert [lbl.text() for lbl in panel.findChildren(QLabel)] == ["⛔ r", "⚠ w", "ⓘ n"]
    assert all(lbl.wordWrap() for lbl in panel.findChildren(QLabel))
    assert not panel.isHidden()
    panel.set_entries([])
    assert panel.isHidden() and panel.entries() == ()
```

`test_plugin_slices_dock.py`:
- **Rewrite `test_a_restored_cell_size_too_fine_to_draw_is_refused_not_attempted`** to cover the
  frame-cap backstop. Keep its setup.
  - `dock.warnings_panel.entries()` holds exactly one `REFUSAL`. Its text contains "too many to
    draw", "0.15" and "Still showing".
  - `errors == []`.
  - `dock.engine.frame is before`.
  - Then `cell_spin.setValue(0.25)` and a flush: the entries are empty.
- **`test_a_restored_cube_below_its_grids_floor_comes_back_at_the_floor(qgis_app, tmp_path)`:**
  - **Setup:** grids "A" (6 × 6 m) and "Big" (300 × 300 m), one synthetic line each. Prepare Big,
    `_save_cube` it, and set that record's `"cell"` to 0.05. Switch to A and let it prepare.
  - **Action:** `restore_cube`, then wait and flush.
  - **Asserts:**
    - `cell_spin.value() == pytest.approx(smallest_safe_cell(300.0, 300.0), abs=1e-3)`;
    - no entries;
    - `errors == []`;
    - the record's `"cell"` is still 0.05.
- **`test_a_warning_coming_and_going_keeps_the_box_you_type_in(docked)`** (Review Focus 3):
  - `_short_and_active`, with the scroll bar at its maximum;
  - dz focused, value set to 0.75;
  - `dock.warnings_panel.set_entries([Entry(REFUSAL, "x " * 200)])`, events pumped, then
    `set_entries([])`;
  - dz still has focus and reads 0.75.
- **`test_a_long_warning_never_widens_the_panel(docked)`:** the content's
  `minimumSizeHint().width()` is unchanged after a 400-character entry.

`test_plugin_site_scope.py`: rewrite every `dock.site_note` test (from ~3484 to ~3705) onto
`dock.warnings_panel.entries()`, keeping their names' intent:
- **The preview** is one `NOTE` equal to `engine.preview_note`. It clears when the site fits, and
  in This grid.
- **A failed resolution** is one `REFUSAL` starting `"Not drawn: "`, and
  **no** error carries its text (the old "the toast stays" assertion inverts).
- **A good resolution** clears it.
- **The clock warning** is its own `WARNING` entry, listed after the `REFUSAL` and before the `NOTE`
  (replacing `test_the_clock_warning_is_its_own_sentence_after_a_preview_or_a_reason`).
- **Width:** `test_the_site_note_never_widens_the_dock` becomes `test_a_long_warning_never_widens_the_site_panel`.
- **A geometry failure on an engine callback:**

```python
def test_a_geometry_failure_on_an_engine_callback_shows_in_warnings_not_a_toast(plugin, monkeypatch):
    dock = whole_site(plugin)
    errors = []
    dock.error.connect(errors.append)
    real = site_engine_module.SiteEngine._rebuild_geometry
    def boom(self):
        raise RuntimeError("the lattice could not be built")
    monkeypatch.setattr(site_engine_module.SiteEngine, "_rebuild_geometry", boom)
    dock.site_engine._rebuild_geometry_reporting()
    dock._site.refresh_slice()
    assert dock.site_engine.geometry_problem == "the lattice could not be built"
    assert [e.text for e in dock.warnings_panel.entries() if e.kind == REFUSAL] == [
        "Not drawn: the lattice could not be built"]
    assert not any("lattice" in e for e in errors)
    monkeypatch.setattr(site_engine_module.SiteEngine, "_rebuild_geometry", real)
    _nudge_cell(dock)
    assert dock.site_engine.geometry_problem is None
    assert not [e for e in dock.warnings_panel.entries() if e.kind == REFUSAL]
```

`test_pure_slices_plan.py::test_preview_note_is_exact_copy` gets new expectations:

```python
base = ("Preview at 0.4 m pixels: the site (1234 × 568 m) is too big to draw at 0.05 m. "
        "It draws in full at a 0.12 m cell or coarser.")
assert preview_note(0.4, 0.05, 1234.4, 567.6, 0.12, []) == base
assert preview_note(0.4, 0.05, 1234.4, 567.6, 0.12, ["C"]) == base[:-1] + ", or without grid C."
assert preview_note(0.4, 0.05, 1234.4, 567.6, 0.12, ["C", "D"]) == base[:-1] + ", or without grids C and D."
```

In `test_plugin_site_engine.py:1057`, replace `"Leaving out C"` with `"without grid C"`.

- [ ] **Step 2: Run them; expect failures.**
  - The `warnings_panel` import fails.
  - The site tests fail on the attribute.
  - The pure test fails on the old copy.

- [ ] **Step 3: Implement.**
  - **`WarningsPanel`:** must not raise the panel's minimum width; word-wrapped labels only.
  - **Placing the panel:** add it after `position_group` and delete `site_note`.
    `show_scope_widgets` stops touching `site_note`, and `set_scope` ends by calling
    `show_warnings()`.
  - **Frame-cap refusal copy:** "Cell {cell:g} m refused: grid {id} would be {cells:,} cells, too
    many to draw. Still showing {old:g} m. Use {safe:g} m or coarser." Here `old` is
    `self.engine.frame.cell`. Drop the "Still showing" sentence when there is no frame.
  - **`SiteScope.apply_resolution`:** stops emitting `error` in its engine-refusal branch. Its
    `Resolution` `ValueError` branch keeps the toast.
  - **The preview note:** the new copy. The site's `W × H` stays `:.0f`.

- [ ] **Step 4: Run the four test files and the pure tier; all green.**

- [ ] **Step 5: Commit and push.** Message:
  `feat(slices): a Warnings section for refusals, the clock warning and the preview note (#163, #157)`.

---

### Task 3: dz's floor and the level limit (#177)

Spec §3.

**Files:**
- Modify: `nsgeo_qgis/slices_plan.py` (add the limit beside `Resolution`)
- Modify: `nsgeo_qgis/slices_engine.py` (`set_resolution` ~1018, `_rebuild_geometry`)
- Modify: `nsgeo_qgis/site_engine.py` (`_rebuild_geometry`'s per-grid loop)
- Modify: `nsgeo_qgis/ui/site_scope.py` (`Spins`, `capture_spins`, `restore_spins`, new
  `set_dz_floor` and `site_dt_floor`, `seed_z`)
- Modify: `nsgeo_qgis/ui/slices_dock.py` (`_seed_dz_z_defaults`, `restore_cube`, `_apply_resolution`)
- Test: `tests/pure/test_pure_slices_plan.py`, `tests/qgis/test_plugin_slices_engine.py`,
  `tests/qgis/test_plugin_slices_dock.py`, `tests/qgis/test_plugin_site_scope.py`

**Interfaces:**
- Consumes: Task 2's `Entry`, `REFUSAL`, `SlicesDock._grid_refusal`, `show_warnings()`,
  `SiteEngine.geometry_problem`.
- Produces, in `slices_plan`:
  - `LEVELS_PER_SAMPLE = 2`.
  - `class TooManyLevels(ValueError)`.
  - `level_limit_problem(resolution: Resolution, samples: Sequence[int]) -> str | None`:
    - it returns `None` when `samples` is empty;
    - it counts levels as `ZAxis.from_range(t0, t1, dz).nz`, and the limit is
      `LEVELS_PER_SAMPLE * max(samples)`;
    - over the limit, it returns `f"Too many levels: dz {dz:.4g} ns from {t0:,g} to {t1:,g} ns makes {nz:,} levels; this cube allows {limit:,} ({why}). Narrow z0–z1 or raise dz."`;
    - `why` is `f"twice the {n:,} samples in each line"` when every count is equal, else
      `f"twice the {max:,} samples in its deepest line"`.
- Produces `SliceEngine.set_resolution(resolution)`. It raises `TooManyLevels` *before* storing
  anything, so the engine keeps its geometry. `samples` is the raw `header.n_samples` of
  `self._choice.line_keys` still in the session; no choice means no check.
  `SliceEngine._rebuild_geometry` leaves `frame`/`z` `None` when the stored resolution is over the
  limit for the current choice. It doesn't raise there, because it runs inside `set_source` and task
  callbacks.
- Produces `SiteEngine._rebuild_geometry`. A grid's `TooManyLevels` is re-raised as
  `TooManyLevels(f"Grid {grid_id}: {exc}")`, which reaches `SiteScope.problem`.
- Produces, in `site_scope`:
  - `Spins.dz_min: float`, captured from `dz_spin.minimum()` and restored first;
  - `set_dz_floor(dock, floor: float) -> None`, signals blocked, as `set_cell_floor`;
  - `site_dt_floor(session, included: Iterable[str]) -> float | None`, the smallest `header.dt_ns`
    among each included grid's first source line (as `header_z_seed` finds them).
- Produces `SlicesDock._apply_resolution`. `except TooManyLevels` sets `_grid_refusal`, calls
  `show_warnings()` and returns, leaving the engine and the map as they were. It sits before the
  generic `except`.
- The generic minimum before any line exists stays today's 0.001 ns *(spec §3.2, my call: "keeps")*.

- [ ] **Step 1: Write the failing tests.**

Pure:

```python
def test_the_level_limit_message_is_exact():
    res = Resolution(cell=0.25, dz_ns=0.2165, t0_ns=0.0, t1_ns=100_000.0)
    assert level_limit_problem(res, [512, 512, 512]) == (
        "Too many levels: dz 0.2165 ns from 0 to 100,000 ns makes 461,894 levels; this cube "
        "allows 1,024 (twice the 512 samples in each line). Narrow z0–z1 or raise dz.")

def test_the_level_limit_names_the_deepest_line_when_counts_differ():
    res = Resolution(cell=0.25, dz_ns=0.2165, t0_ns=0.0, t1_ns=100_000.0)
    assert "allows 2,048 (twice the 1,024 samples in its deepest line)" in level_limit_problem(res, [512, 1024])

def test_native_dz_over_the_whole_record_is_within_the_limit():
    assert level_limit_problem(Resolution(0.25, 0.21653, -11.086, 99.546), [512]) is None
    assert level_limit_problem(Resolution(0.25, 0.001, 0.0, 100.0), []) is None
```

QGIS tests:
- **The floor in This grid.** `test_dz_cannot_go_below_the_sample_interval_in_this_grid(docked)`:
  - `dz_spin.minimum()` is within 1e-4 of the first line's `header.dt_ns`;
  - `setValue(0.001)` gives the minimum;
  - `stepBy(1)` from the minimum gives minimum + dt, within 1e-4.
- **The floor in Whole site.** `test_dz_cannot_go_below_the_finest_interval_in_whole_site(plugin)`:
  the same, with `site_dt_floor`.
- **Remembered records** (Review Focus 1, one test each). In every case the box shows the floor,
  the cube builds (`engine.z.nz <= 1024`), and the record still says 0.001:
  - `test_a_remembered_dz_below_the_floor_comes_back_at_the_floor(docked_two_grids)`:
    `remember_slice_resolution("A", dz_ns=0.001)`, then switch to B and back to A;
  - `test_a_site_dz_below_the_floor_comes_back_at_the_floor(plugin)`:
    `remember_site_resolution(dz_ns=0.001)`, then `whole_site`;
  - `test_a_saved_cube_with_dz_below_the_floor_restores_at_the_floor(docked)`: a `_save_cube`
    record whose `"dz_ns"` is set to 0.001.
- **The floor follows the scope.** `test_the_dz_floor_travels_with_the_scope(docked_two_grids)`:
  `capture_spins(dock).dz_min` in This grid is unchanged after a trip to Whole site and back.
- **The limit in This grid.**
  `test_a_z_range_past_the_level_limit_is_refused_in_this_grid_and_the_map_stays(docked)`:
  - **Setup:** `_ready(dock)`, then record `z = dock.engine.z` and catch errors.
  - **Action:** `z1_spin.setValue(100_000.0)`, then flush.
  - **Asserts:**
    - `dock.engine.z is z`;
    - one `REFUSAL` entry starting `"Too many levels: dz 0.5 ns from 2 to 100,000 ns"`;
    - `errors == []`.
  - **Then:** `z1_spin.setValue(30.0)` and a flush leave no entries.
- **The same z range in Whole site.** `test_the_same_z_range_is_clipped_not_refused_in_whole_site(plugin)`:
  `z1` 100,000 gives `scope.problem is None`, a drawn site, and a site axis ending at the data.
- **Engine guards.**
  - `test_a_stored_resolution_past_the_limit_builds_nothing_once_lines_arrive(...)`, in
    `test_plugin_slices_engine.py`: `set_resolution` with no choice, then `set_source` with three
    lines and a wait. `engine.frame is None and engine.z is None`.
  - `test_set_resolution_refuses_before_storing(...)`: `TooManyLevels` raises, and
    `engine.z is` the old one.
- **Mixed radars.** `test_a_site_mixing_radars_never_refuses_its_seeded_defaults(open_plugin, first)`
  (Review Focus 2):
  - parametrized `first` in `("A", "B")`;
  - grid A has 512-sample lines and grid B has 1,024-sample lines over the same 110.864 ns
    (`write_dzt` with 1,024 rows);
  - `whole_site` gives `scope.problem is None` and both grids ready;
  - `dz_spin.minimum()` is within 1e-4 of B's interval.
- **Real data.** `@needs_real_data test_real_lines_floor_at_0_2165_and_allow_1024_levels(qgis_app, tmp_path)`:
  four `REAL_DZT` lines on one grid;
  - the floor is 0.2165 (`approx 1e-4`);
  - `level_limit_problem` at the floor over the seeded range is `None`;
  - at z1 100,000 its message names "1,024 (twice the 512 samples in each line)".

- [ ] **Step 2: Run them; expect failures.** The import fails, the minimum is 0.001, and the limit
  doesn't exist yet.

- [ ] **Step 3: Implement.**
  - **`_seed_dz_z_defaults`:** call `site_scope.set_dz_floor(self, header.dt_ns)` before setting the
    values.
  - **`restore_cube`:** sets the floor from its kept keys' first line before setting `dz_spin`
    (beside Task 2's `_set_cell_floor`).
  - **`SiteScope.seed_z`:** sets the floor from `site_dt_floor(self.session, self.included())`
    before `set_spins_quietly`.
  - **No record writes:** none of the three writes a record. `_seeding` and `_updating` already
    keep the clamps from being remembered; check that each floor raise sits inside one of them.

- [ ] **Step 4: Run the four test files and the pure tier; all green.** Also run
  `test_plugin_site_engine.py` and `test_plugin_slice_export.py`, which build resolutions through
  the engines.

- [ ] **Step 5: Commit and push.** Message:
  `feat(slices): dz floors at the sample interval; refuse a cube past twice its samples (#177)`.

---

### Task 4: Sections that fold, and the coverage view explained (#157 item 6)

Spec §6.2 and §7.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/folds.py`
- Modify: `nsgeo_qgis/ui/slices_dock.py` (`resolution_group`, `display_group` become
  `QgsCollapsibleGroupBox`; wire folds after the panels exist; `coverage_check` tooltip)
- Modify: `nsgeo_qgis/ui/finish_panel.py` (`FinishPanel` base class)
- Modify: `nsgeo_qgis/ui/site_panel.py` (`NormalisationPanel`'s inner group, exposed as `self.group`)
- Modify: `packages/nsgeo-qgis/tests/qgis/conftest.py` (autouse settings fixture)
- Modify: `docs/guide/getting-started.md` (Show coverage, ~559-570; step 3, ~490)
- Test: `tests/qgis/test_plugin_slices_dock.py`, `tests/qgis/test_plugin_site_scope.py`

**Interfaces:**
- Produces, in `ui/folds.py`:
  - `FOLD_GROUP = "nsgeo/slices/folded"`;
  - `fold_settings() -> QSettings`, which returns `QgsSettings()`. It is the only way fold state
    is read or written.
  - `remember_folds(name: str, boxes: Sequence[QgsCollapsibleGroupBox]) -> None`, which:
    - turns off QGIS's own saving on each box (`setSaveCollapsedState(False)`,
      `setSaveCheckedState(False)`);
    - sets each box from `f"{FOLD_GROUP}/{name}"` (default unfolded);
    - on any box's `collapsedStateChanged`, writes the key and sets the others alike, guarded
      against re-entry.
- Calls in the dock:
  - `remember_folds("resolution", [resolution_group])`;
  - `remember_folds("interpolation", [grid_finish, site_finish])`;
  - `remember_folds("normalisation", [normalisation_panel.group])`;
  - `remember_folds("display", [display_group])`.
- Produces `slices_dock.COVERAGE_TIP` (exact copy, spec §7):
  `"Shows how many traces fell in each cell, instead of the amplitude.\nUse it to see where your lines ran and where there is no data: blank cells had no line through them.\nIn a Whole site preview each pixel shows the largest count among the cells under it, so lines look wider than they are."`
- Conftest: an autouse fixture patches `nsgeo_qgis.ui.folds.fold_settings` to return
  `QSettings(str(tmp_path / "folds.ini"), QSettings.Format.IniFormat)`.

- [ ] **Step 1: Check the preview's coverage draw.** Read how a Whole site preview reduces coverage
  counts to its coarser pixel (`site_engine.py`, the coverage branch of `slice_at`). If it doesn't
  take the largest count, change `COVERAGE_TIP`'s last sentence and the guide's to say what it does.
  Say so in the task report.

- [ ] **Step 2: Write the failing tests.**

```python
FOLDING = ("resolution_group", "grid_finish", "display_group")

def test_each_settings_section_folds_and_unfolds(docked):
    # float + show; for each name: box.setCollapsed(True); events; box.isCollapsed() and
    # box.height() < its unfolded height; setCollapsed(False) restores it.

def test_source_position_and_warnings_do_not_fold(docked):
    for name in ("source_group", "position_group", "warnings_panel"):
        assert not isinstance(getattr(dock, name), QgsCollapsibleGroupBox)

def test_every_section_starts_unfolded(docked):
    # every box in FOLDING plus site_finish and normalisation_panel.group: not isCollapsed()

def test_the_two_interpolation_panels_fold_together(docked):
    # shown; grid_finish.setCollapsed(True) -> site_finish.isCollapsed()
    # (site_finish is hidden in This grid: QGIS applies its fold when it shows)

def test_folds_are_remembered_across_a_restart(docked):
    # shown; display_group.setCollapsed(True)
    # -> folds.fold_settings().value("nsgeo/slices/folded/display", type=bool) is True;
    # a new SlicesDock(session).display_group.isCollapsed() is True

def test_fold_state_never_touches_a_real_settings_file(tmp_path):
    assert Path(folds.fold_settings().fileName()).parent == tmp_path

def test_the_coverage_tooltip_explains_what_and_how_a_preview_draws_it(docked):
    assert dock.coverage_check.toolTip() == COVERAGE_TIP
```

In `test_plugin_site_scope.py`, add
`test_the_normalisation_section_folds_and_is_remembered(plugin)`.

- [ ] **Step 3: Run them; expect failures** (no `folds` module; plain group boxes).

- [ ] **Step 4: Implement.**
  - `FinishPanel(QgsCollapsibleGroupBox)` keeps `super().__init__("Interpolation", parent)`.
  - `NormalisationPanel` builds `self.group = QgsCollapsibleGroupBox("Normalisation")`.
  - Folding is wired after all four panels exist.
  - The coverage tooltip becomes `COVERAGE_TIP`.

- [ ] **Step 5: Edit the guide** (`docs/guide/getting-started.md`).
  - **Show coverage:** add the preview sentence, as worded in `COVERAGE_TIP`.
  - **Step 3** (Resolution), *my call: the guide would otherwise go stale*, three sentences:
    - the mouse wheel changes **Cell size**, **dz**, **z0** and **z1** only once you have clicked
      into the box, so scrolling past them changes nothing;
    - **dz** can't go below the radar's own sample interval;
    - the **Resolution**, **Interpolation**, **Normalisation** and **Display** headers fold their
      sections away, and nsgeo remembers which are folded.
  - **Warnings:** one sentence where step 4 says a preview "says so in the panel": it now says so
    under **Warnings**, below **Position**.

- [ ] **Step 6: Run the dock, site scope, finish panel and site panel test files; all green.**

- [ ] **Step 7: Commit and push.** Message:
  `feat(slices): settings sections fold and remember it; explain the coverage view (#157)`.

---

### Task 5: The panel fits Processing's minimum, and opens without sideways scroll (#121, #50)

Spec §8.

**Files:**
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_width.py`
- Modify: `tests/qgis/test_plugin_slices_dock.py:2103-2140`
  (`test_the_dock_minimum_does_not_force_the_main_window_to_grow`: drop only its
  `sizeHint().width() >= 280` line, now covered by the opening test)
- Modify, as the measurement shows: `nsgeo_qgis/ui/slices_dock.py` and the panels it holds
- Modify: `packages/nsgeo-qgis/README.md` (the stale "On Qt 6, the dock-width test is an expected
  failure until #50" sentence; the xfail went in 4e39772)

**Interfaces:**
- Consumes: Task 2's `warnings_panel` and Task 4's folding boxes, which are both in the panel being
  measured.
- Produces `width_fonts(points: float) -> context manager`, a test helper in the new file. It sets
  `QApplication.font()` with `setPointSizeF(points)` and restores the old font on exit. Build the
  docks inside it.

- [ ] **Step 1: Measure first** (spec §8.2, the builder check).
  - **What:** write a scratch script, not committed. At 9, 11 and 14 pt it prints:
    - `ProcessingDock(session).minimumSizeHint().width()`;
    - the Slices content's `minimumSizeHint().width()` in both scopes;
    - each top-level row's own minimum width.
  - **Session:** use one with three grids of synthetic lines (`site3`'s shape), a long cube name in
    `cube_combo`, the slider on its last slice (the longest readout), and every section unfolded.
    The memory label counts too, so set it to the GB form of its text.
  - **Report:** list the rows over the rule. Then, for each, apply one of these:
    - **wrap** `velocity_label` and `included_label`;
    - **cap the combo's content width** on `cube_combo` (`AdjustToMinimumContentsLengthWithIcon`,
      `setMinimumContentsLength(12)`);
    - **stack a label above its box.**

    The Interpolation row may be stacked only if the measurement puts it over.

- [ ] **Step 2: Write the guard tests** in `test_plugin_slices_width.py`:

```python
@pytest.mark.parametrize("points", [9.0, 14.0])
@pytest.mark.parametrize("scope", ["grid", "site"])
def test_the_slices_panel_fits_the_processing_panels_minimum(qgis_app, site3, points, scope):
    with width_fonts(points):
        session = _open_site(site3)            # three grids, lines, a preset
        limit = ProcessingDock(session).minimumSizeHint().width()
        dock = SlicesDock(session)
        dock.cube_combo.addItem("a cube name long enough to widen any combo box at all, 60 c")
        # every section unfolded; scope switched and settled
        dock.setFloating(True); dock.resize(limit, 500); dock.show(); settle
        scroll = dock.findChild(QScrollArea)
        assert scroll.verticalScrollBar().maximum() > 0       # the vertical bar is showing
        assert scroll.horizontalScrollBar().maximum() == 0    # nothing scrolls sideways

@needs_real_data
@pytest.mark.parametrize("points", [9.0, 14.0])
def test_a_real_site_fits_the_processing_panels_minimum(qgis_app, tmp_path, points):
    # the same on four REAL_DZT lines on one grid, both scopes; it skips cleanly in CI

@pytest.mark.parametrize("scope", ["grid", "site"])
def test_the_panel_opens_at_least_as_wide_as_its_contents(qgis_app, site3, scope):
    # dock.resize(dock.sizeHint()); show; settle -> horizontalScrollBar().maximum() == 0
```

- [ ] **Step 3: Run them; expect a failure.** Each failing row from Step 1 fails the guard. The
  opening test fails if `QScrollArea.sizeHint` leaves out the vertical bar.

- [ ] **Step 4: Make the rows give way, and make the dock open wide enough.** For the opening
  width, one option is a `QScrollArea` subclass whose `sizeHint` adds
  `verticalScrollBar().sizeHint().width()`.

- [ ] **Step 5: Run the width tests and the existing layout tests.** All must be green:
  - `test_the_dock_minimum_does_not_force_the_main_window_to_grow`;
  - `test_the_indicator_never_raises_the_dock_minimum_width`;
  - `test_the_refine_states_do_not_move_the_panel_under_the_wheel`;
  - `test_plugin_site_scope.py -k "layout or width or wheel"`.

- [ ] **Step 6: Run the whole local suite.** Both tiers must be green:
  - `QT_QPA_PLATFORM=offscreen ../../.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q`;
  - `../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q`.

- [ ] **Step 7: Run the Qt 6 image** (Review Focus 5). Expect green:

```bash
packages/nsgeo-qgis/scripts/in_qgis_docker.sh qgis/qgis:4.2 \
    python3 -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_slices_width.py \
    packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py \
    packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_dialog.py \
    packages/nsgeo-qgis/tests/qgis/test_plugin_warnings_panel.py -q -p no:cacheprovider
```

- [ ] **Step 8: Fix the README sentence.** Replace it with one line: the Slices panel's width is
  pinned to the Processing panel's minimum by `test_plugin_slices_width.py`.

- [ ] **Step 9: Commit and push.** Message:
  `feat(slices): the panel fits the Processing panel's minimum and opens without sideways scroll (#121, #50)`.

---

## After the plan (controller, not tasks)

These are spec §11 and §14 and the session process:
1. **Whole-branch review.**
2. **Deploy** to a new QGIS profile `ns_geo_wheel` with `scripts/dev_link.py`.
3. **Walkthrough artifact** covering spec §11.
4. **Merge** only when the author says so.
5. **At merge:** the PR closes #177, #176, #105 and #121. Comment on #157 (items 4, 5 and 6),
   #163 (item 1) and #50, without closing them; #121's comment explains the change of target.
   Update the README roadmap.
