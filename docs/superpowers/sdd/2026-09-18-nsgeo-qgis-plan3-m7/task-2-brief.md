## Task 2: The profile shows the preview, and says so

The profile must state which line it is showing and whether that is the working line or a preview — without it, the user cannot tell whether what they are looking at is what they are about to edit, which reintroduces the confusion the split exists to prevent (spec §3.3).

Two overlays are bound to the working line and must not follow a preview: the **gain strip** (it edits a step in the working line's stack, and it writes on drag — a strip whose curve belongs to a line that is not on screen is precisely the C2 configuration) and the **difference view** (a property of a selected step). Both hide during a preview and return when the view snaps back. Returning matters: `_difference_index` must survive the round trip.

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py` (append)

**Interfaces:**
- Consumes (Task 1): `session.preview_changed(str, int)`, `session.preview_key`, `session.current_trace`, `session.selection`.
- Produces: no new public API. `ProfileDock._key` changes from an attribute to a read-only property returning the **displayed** key.

- [ ] **Step 1: Write the failing tests**

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`.

That file's existing `opened` fixture builds only **one** line, and every test here needs a second one to preview. Add a sibling fixture rather than changing `opened`, which 20-odd existing tests depend on. `GRID`, `synthetic_dzt`, `Line`, `GridPlacement` and `build_step` are already imported at the top of that file.

```python
# ---- preview rendering (M7, spec §3.3) --------------------------------------


@pytest.fixture
def previewing(qgis_app, tmp_path):
    """Two lines on one grid, the first open. `opened` has only one line,
    and a preview needs somewhere else to point."""
    session = SiteSession()
    dock = ProfileDock(session)
    dock.resize(900, 360)
    dock.show()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    for i in range(2):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=240)
        session.add_lines([Line.open(p, GridPlacement("A", "y", i * 2.0, 0.0, -1, p.stem))])
    keys = session.keys()
    session.open_line(keys[0])
    yield dock, session, keys
    # Parentless top-level widget: torn down explicitly rather than left
    # for Python's GC to race Qt's widget teardown. See `opened`.
    dock.hide()
    dock.deleteLater()


def test_preview_renders_the_previewed_line_not_the_working_one(previewing):
    dock, session, keys = previewing

    session.set_preview(keys[1], 5)

    assert dock._key == keys[1]
    assert session.current_key == keys[0]
    label = session.line_for_key(keys[1]).path.stem
    assert label in dock.windowTitle()


def test_the_banner_names_the_previewed_line_and_clears_on_snap_back(previewing):
    dock, session, keys = previewing
    assert dock.preview_label.text() == ""

    session.set_preview(keys[1], 5)
    assert session.line_for_key(keys[1]).path.stem in dock.preview_label.text()

    session.clear_preview()
    assert dock.preview_label.text() == ""
    assert dock._key == keys[0]


def test_the_gain_strip_hides_during_a_preview_and_comes_back(previewing):
    dock, session, keys = previewing
    dock.show_gain_strip([[0.0, 1.0], [1.0, 2.0]], owner=("x", 0, 0))
    assert dock.gain_strip.isVisible()

    session.set_preview(keys[1], 5)
    assert not dock.gain_strip.isVisible()

    session.clear_preview()
    assert dock.gain_strip.isVisible()


def test_a_hidden_gain_strip_stays_hidden_after_a_preview(previewing):
    dock, session, keys = previewing
    assert not dock.gain_strip.isVisible()

    session.set_preview(keys[1], 5)
    session.clear_preview()

    assert not dock.gain_strip.isVisible()


def test_the_difference_index_survives_a_preview_round_trip(previewing):
    dock, session, keys = previewing
    session.append_step(keys[0], build_step("dewow", window_ns=4.0))
    dock.set_difference_index(0)
    assert dock._difference_index == 0

    session.set_preview(keys[1], 5)
    assert dock._effective_difference_index == -1  # not computed on someone else's stack
    assert dock._difference_index == 0             # but remembered

    session.clear_preview()
    assert dock._effective_difference_index == 0


def test_snap_back_restores_the_working_lines_cursor_and_selection(previewing):
    dock, session, keys = previewing
    session.set_trace(keys[0], 9)
    session.set_selection(keys[0], 3, 11)

    session.set_preview(keys[1], 5)
    session.clear_preview()

    assert dock.view._cursor == 9
    assert dock.view._selection == (3, 11)


def test_hovering_the_profile_during_a_preview_does_not_move_the_working_trace(
    previewing,
):
    """The C2 guard at the widget level."""
    dock, session, keys = previewing
    session.set_trace(keys[0], 9)
    session.set_preview(keys[1], 5)

    dock.view.trace_hovered.emit(40)

    assert session.current_trace == 9
    assert session.current_key == keys[0]


def test_previewing_the_working_line_is_not_a_preview(previewing):
    dock, session, keys = previewing

    session.set_preview(keys[0], 5)

    assert dock.preview_label.text() == ""
    assert dock._key == keys[0]


def test_opening_a_line_while_previewing_ends_the_preview(previewing):
    dock, session, keys = previewing
    session.set_preview(keys[1], 5)

    session.open_line(keys[1])

    assert dock.preview_label.text() == ""
    assert dock._key == keys[1]


def test_closing_the_site_while_previewing_clears_the_banner(previewing):
    dock, session, keys = previewing
    session.set_preview(keys[1], 5)

    session.close_site()

    assert dock.preview_label.text() == ""
    assert dock._key is None
```

`ProfileView._cursor` (an `int`, `-1` when none) and `ProfileView._selection` (a `tuple[int, int]`, `(-1, -1)` when cleared) are the real attribute names — verified in `profile_view.py:67-68`. That file exposes no public accessors for either.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py -q -p no:xonsh -k preview`

Expected: FAIL — `AttributeError: 'ProfileDock' object has no attribute 'preview_label'`.

- [ ] **Step 3: Split the displayed key from the working key**

`self._key` has exactly **two** assignment sites (`profile_dock.py:268` in `_open`, `profile_dock.py:350` in `_clear`) and ~29 read sites. Turning it into a property means the read sites need no edits at all and automatically mean "the displayed line", which is what every one of them wants.

In `__init__`, replace `self._key: str | None = None` with:

```python
        self._working_key: str | None = None
        self._preview_key: str | None = None
        self._strip_was_visible = False
```

Add the property next to the `percentile` / `colormap_name` properties:

```python
    @property
    def _key(self) -> str | None:
        """The line being DISPLAYED -- the preview when there is one.

        Every read site in this file wants this: a stack_changed on the
        line currently on screen should re-render it whether that line is
        the working one or a preview, and `_on_trace_changed`'s key filter
        should reject the working line's cursor while a preview is up.
        The two assignment sites became `_working_key` instead.
        """
        return self._preview_key or self._working_key

    @property
    def _effective_difference_index(self) -> int:
        """`-1` while previewing: the difference view is a property of a
        step in the WORKING line's stack, and `_difference_index` indexes
        that stack. Computing it against a previewed line's stack would be
        an index into the wrong list -- at best an IndexError, at worst a
        plausible-looking image of the wrong subtraction. Kept separate
        from `_difference_index` itself so the mode is remembered and
        returns intact when the view snaps back (spec §3.3)."""
        return -1 if self._preview_key is not None else self._difference_index
```

Change line 268 (`_open`) from `self._key = key or None` to `self._working_key = key or None`, and line 350 (`_clear`) from `self._key = None` to:

```python
        self._working_key = None
        self._preview_key = None
        self.preview_label.setText("")
```

Then replace both uses of `self._difference_index` inside `current_radargram()` and `_render()` with `self._effective_difference_index`. **Do not** change the uses in `_open`, `_clear`, `set_difference_index` or `_decline_difference` — those manage the stored mode itself, not the rendering of it.

- [ ] **Step 4: Add the banner**

In `__init__`, in the toolbar row, immediately after `self.difference_label`:

```python
        self.preview_label = QLabel("")
        bar.addWidget(self.preview_label)
```

- [ ] **Step 5: Factor the shared view configuration out of `_open`**

`_open` currently does two things: it resets the difference view and forgets the previous line's cursor, and it configures the view for a line. A preview needs only the second. Extract it verbatim — do not retype it — as:

```python
    def _show_line(self, key: str) -> None:
        """Configure the view for `key`: title, direction, axes, image,
        channels, velocity. Shared by `_open` (the working line) and
        `_enter_preview`. Deliberately does NOT touch the difference view
        or the cursor/selection: those differ between the two callers,
        which is the whole reason this is a separate method."""
        line = self.session.line_for_key(key)
        label = getattr(line.placement, "label", None) or line.path.stem
        self.setWindowTitle(f"nsgeo Profile · {label} · {line.n_traces} traces")
        self.view.set_direction(int(getattr(line.placement, "direction", 1)))
        self.image = None
        profiles = self.session.profiles_for(key)
        if profiles:
            self._configure_channels(len(profiles))
            self._render()
        else:
            self.channel_combo.hide()
            self.view.set_axes(
                line.n_traces,
                line.header.n_samples,
                line.header.position_ns,
                line.header.dt_ns,
                self._safe_distance(line),
            )
            self.view.set_image(None)
        self._refresh_velocity()
```

`_open`'s body after `self._working_key = key or None` becomes:

```python
        self._preview_key = None
        self.preview_label.setText("")
        if not key:
            self._clear_view_only()
            return
        # C1: open_line resets the session's cursor and selection without
        # emitting for that reset, and set_axes touches neither -- cleared
        # explicitly so the previous line's cursor does not carry across.
        self.view.set_cursor(-1)
        self.view.clear_selection()
        self._show_line(key)
```

Keep the existing C1 comment block that sits above those two view calls; it explains exactly this.

- [ ] **Step 6: Add the preview slot**

```python
    def _on_preview_changed(self, key: str, trace: int) -> None:
        try:
            if key and key != self._working_key:
                self._enter_preview(key, trace)
            else:
                # Either the preview was cleared, or the pointer is over
                # the line already being worked on -- which is not a
                # preview at all: showing a banner and hiding the gain
                # strip for the line the user is editing would be pure
                # noise, and a re-render of what is already on screen.
                self._exit_preview()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not show the preview of {key!r}: {exc}", Qgis.MessageLevel.Critical)

    def _enter_preview(self, key: str, trace: int) -> None:
        if self._preview_key is None:
            self._strip_was_visible = self.gain_strip.isVisible()
        self._preview_key = key
        self.gain_strip.hide()
        self.difference_label.setText("")
        line = self.session.line_for_key(key)
        label = getattr(line.placement, "label", None) or line.path.stem
        self.preview_label.setText(f"Preview: {label} — select it on the map to work on it")
        self._show_line(key)
        self.view.clear_selection()
        self.view.set_cursor(trace)

    def _exit_preview(self) -> None:
        if self._preview_key is None:
            return
        self._preview_key = None
        self.preview_label.setText("")
        if self._working_key is None:
            self._clear_view_only()
            return
        self._show_line(self._working_key)
        self.view.set_cursor(self.session.current_trace)
        start, end = self.session.selection
        if start < 0 or end < 0:
            self.view.clear_selection()
        else:
            self.view.set_selection(start, end)
        if self._strip_was_visible:
            self.gain_strip.show()
        self._strip_was_visible = False
```

`_strip_was_visible` is captured only on the *first* `_enter_preview` of a run: hovering straight from one line to another re-enters without an intervening exit, and re-reading the (now hidden) strip would lose the memory that it had been showing.

Connect it in `__init__` beside the other session connections:

```python
        session.preview_changed.connect(self._on_preview_changed)
```

- [ ] **Step 6b: Refuse to author a pick while previewing**

`_pick` (profile_dock.py:578) emits `self.pick_requested.emit(self._key, trace, time_ns)`, and `self._key` is now the *displayed* line. Nothing consumes that signal today, so M7 ships no defect — but M8 connects it to `session.add_pick`, and it would then author a pick on a line the user only hovered over. Spec §4.3: "Picking targets the **working line**, never a preview." Guard it in the task that creates the hazard, not in the one that would trip over it.

Add as the first statement of `_pick`'s body, before the existing guard:

```python
        if self._preview_key is not None:
            # A preview never authors data (spec §3.3, §4.3). `self._key`
            # is the DISPLAYED line, so without this a shift-click on a
            # previewed radargram would emit a pick for a line the user
            # only hovered. Nothing consumes pick_requested until M8 --
            # this is guarded here, in the change that makes `_key` mean
            # "displayed", rather than left for M8 to discover.
            return
```

And the test:

```python
def test_a_shift_click_on_a_preview_authors_no_pick(previewing):
    dock, session, keys = previewing
    emitted = []
    dock.pick_requested.connect(lambda k, t, ns: emitted.append((k, t, ns)))
    session.set_preview(keys[1], 5)

    dock.view.pick_requested.emit(20, 15.0)

    assert emitted == []
```

**Note — no guard is needed on `_hovered`.** Hovering the profile during a preview calls `session.set_trace(self._key, trace)` with `_key` = the previewed line, and `set_trace` returns early because that is not `current_key`. The safety is structural, not a check that could be forgotten. The test asserts it anyway.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py packages/nsgeo-qgis/tests/qgis/test_plugin_difference_presets.py -q -p no:xonsh`

Expected: PASS, including every pre-existing test in all three files.

- [ ] **Step 8: Run both tiers and the linters, then commit**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
.venv/bin/ruff check . && .venv/bin/ruff format --check .
git add packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py
git commit -m "feat: render the previewed line, and say that it is a preview

The dock's _key becomes the DISPLAYED line, so every read site means the
right thing without edits. The gain strip and the difference view stay
bound to the working line and hide while a preview is up: the strip writes
on drag, and a curve belonging to a line that is not on screen is exactly
the C2 configuration.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

