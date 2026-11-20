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

