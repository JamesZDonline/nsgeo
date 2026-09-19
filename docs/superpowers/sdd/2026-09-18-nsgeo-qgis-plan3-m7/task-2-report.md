# Task 2 report: the profile shows the preview, and says so

## What I implemented

Followed the brief step by step, TDD order.

1. **Tests appended verbatim** to
   `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`: the `previewing`
   fixture and its 10 tests (including the Step 6b pick-guard test),
   exactly as given in the brief.
2. **Ran them and watched them fail (RED)** before touching
   `profile_dock.py` — output below.
3. **Split `_key` into `_working_key`/`_preview_key`** in
   `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`:
   - `__init__`: `self._key: str | None = None` became
     `self._working_key: str | None = None`, `self._preview_key: str | None = None`,
     `self._strip_was_visible = False`.
   - Added the `_key` property (returns `self._preview_key or self._working_key`)
     and the `_effective_difference_index` property, both with the brief's exact
     docstrings, next to `percentile`/`colormap_name`.
   - `_open` (was line 268): `self._key = key or None` → `self._working_key = key or None`,
     plus resetting `self._preview_key = None` and `self.preview_label.setText("")`.
   - `_clear` (was line 350): `self._key = None` → `self._working_key = None`,
     `self._preview_key = None`, `self.preview_label.setText("")`.
   - `current_radargram()` and `_render()`: the two `self._difference_index`
     reads that decide *what to draw* now read `self._effective_difference_index`.
     `_open`, `_clear`, `set_difference_index`, `_decline_difference` were left
     untouched — they manage the stored mode, not its rendering.
   - No read site among the ~29 was touched; they all resolved automatically
     through the new property.
4. **Added the banner** (`self.preview_label = QLabel("")`, added to the
   toolbar `bar` immediately after `self.difference_label`).
5. **Factored `_show_line(key)`** out of `_open`, verbatim from the brief,
   and rewrote `_open`'s tail to call it. Kept the existing C1 comment block
   above the `set_cursor(-1)`/`clear_selection()` calls.
6. **Added the preview slot**: `_on_preview_changed`, `_enter_preview`,
   `_exit_preview`, and the `session.preview_changed.connect(self._on_preview_changed)`
   wire-up in `__init__`, all verbatim from the brief.
7. **Step 6b**: added the preview guard as the first statement of `_pick`,
   verbatim, before the existing `I6` comment and guard.
8. Ran the three-file target (Step 7) — all pass, including every
   pre-existing test in those three files.
9. Ran both full tiers plus both linters (Step 8), fixed one lint issue
   (below), then committed and pushed.

## Deviation from the brief, and why

**One pre-existing test needed a one-line fix the brief did not mention.**
`test_refresh_velocity_returns_silently_once_the_site_is_closed` (line 568,
pre-existing, not part of this task's new tests) does:

```python
dock._key = key  # force the otherwise-unreachable state directly
```

The brief states `self._key` has exactly two assignment sites, both in
`profile_dock.py`. That count is correct for the *production* file, but this
test assigns to `dock._key` directly from outside the class to force
otherwise-unreachable state. Once `_key` becomes a read-only property (no
setter), that assignment raises `AttributeError: can't set attribute
'_key'`. I changed it to:

```python
dock._working_key = key  # force the otherwise-unreachable state directly
```

which forces the same "displayed key is non-None" state through the new
underlying attribute and preserves the test's original intent (proving the
`not self.session.is_open` half of `_refresh_velocity`'s guard is not
redundant with the `except KeyError` below it). No assertions or other
behaviour in that test changed.

**One formatting-only fix from `ruff format`.** The brief's literal test code
visually aligned two trailing comments:

```python
    assert dock._effective_difference_index == -1  # not computed on someone else's stack
    assert dock._difference_index == 0             # but remembered
```

`ruff format --check .` flagged the second line as needing reformatting (it
collapses the alignment padding to one space before `#`). I ran
`ruff format` on that one file to satisfy the global lint gate; the only
change was whitespace before the comment — the comment text itself
("but remembered") is untouched. Everything else in the file was already
ruff-format-clean.

No other deviations. Every other line of production and test code matches
the brief's given code exactly, including comment wording.

## Red-state failure output (Step 2)

```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py -q -p no:xonsh -k preview
...
E       AttributeError: 'ProfileDock' object has no attribute 'preview_label'
...
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py::test_preview_renders_the_previewed_line_not_the_working_one
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py::test_the_banner_names_the_previewed_line_and_clears_on_snap_back
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py::test_the_gain_strip_hides_during_a_preview_and_comes_back
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py::test_the_difference_index_survives_a_preview_round_trip
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py::test_hovering_the_profile_during_a_preview_does_not_move_the_working_trace
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py::test_previewing_the_working_line_is_not_a_preview
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py::test_opening_a_line_while_previewing_ends_the_preview
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py::test_closing_the_site_while_previewing_clears_the_banner
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py::test_a_shift_click_on_a_preview_authors_no_pick
9 failed, 1 passed, 27 deselected in 1.19s
```

Matches the brief's expectation exactly: `AttributeError:
'ProfileDock' object has no attribute 'preview_label'`. The one test that
passed vacuously (`test_a_hidden_gain_strip_stays_hidden_after_a_preview`) is
the one whose assertions ("stays hidden") happened to hold trivially before
any preview wiring existed, since `set_preview`/`clear_preview` at the
session level were already functional from Task 1 and the strip was never
shown to begin with — nothing in the dock reacted to the signal yet, so
"stays hidden" was true by default. It fails to distinguish itself from a
correct implementation only in isolation; the sibling test
(`test_the_gain_strip_hides_during_a_preview_and_comes_back`) covers the case
that does discriminate, and that one failed red as expected.

## Test commands and output (green state)

Three-file target (Step 7):
```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py packages/nsgeo-qgis/tests/qgis/test_plugin_difference_presets.py -q -p no:xonsh
70 passed in 15.09s
```

Pure tier:
```
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
363 passed, 2 skipped in 1.37s
```
Identical to the base-commit count (363 passed, 2 skipped) — this task touches
nothing under the pure tier.

QGIS tier:
```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
399 passed in 90.48s
```
Base was 388 passed; 399 = 388 + 11 new tests (the 10 from the brief's Step 1
list plus the Step 6b pick-guard test), all passing, zero regressions.

Re-ran both tiers again after the `ruff format` fix to confirm the
reformatting didn't change behaviour: pure stayed at 363 passed, 2 skipped;
QGIS stayed at 399 passed.

Linters:
```
$ .venv/bin/ruff check .
All checks passed!
$ .venv/bin/ruff format --check .
1 file would be reformatted   # test_plugin_profile_dock.py, see Deviations above
$ .venv/bin/ruff format packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py
1 file reformatted
$ .venv/bin/ruff check . && .venv/bin/ruff format --check .
All checks passed!
92 files already formatted
```

## Anything I'm unsure about

- The `_strip_was_visible` capture-on-first-entry logic and the
  `_effective_difference_index` split were both exercised directly by the
  brief's tests (`test_the_difference_index_survives_a_preview_round_trip`,
  `test_a_hidden_gain_strip_stays_hidden_after_a_preview`) and passed without
  needing any adjustment, so I'm confident in them, but I did not add any
  test beyond the brief's own for a hover-to-hover preview transition (line A
  previewed, then line B previewed without an intervening `clear_preview`) —
  the brief's comment on `_strip_was_visible` describes this case
  ("hovering straight from one line to another re-enters without an
  intervening exit") but the brief's test list does not include a test that
  exercises two consecutive `_enter_preview` calls. I did not add one myself
  since the brief says its tests are complete and I was told to follow it
  exactly; flagging this only so the reviewer knows it's untested by name,
  not that I believe it's broken (the guard `if self._preview_key is None`
  before capturing `_strip_was_visible` is straightforward and the manual
  trace through the code confirms it does the right thing on a second
  `_enter_preview` while `_preview_key` is already set).
- No other opennesses. All five pieces of "context the brief cannot know"
  were consistent with what I found in the code and needed no adjustment to
  my approach.

---

## Fix report (post-review)

The coordinator's review found three Important issues. All three are fixed;
tests added or strengthened for each; both tiers and both linters re-run
green.

### Finding 1 — a preview could write to the session via the channel combo

`_channel_changed` called `self.session.set_channel(self._key, index)`, and
`self._key` is the *displayed* line. `SiteSession.set_channel` has no
`current_key` guard (unlike `set_trace`/`set_selection`), so a multi-channel
previewed line's combo click would permanently repoint that line's channel —
a live write from a hover, exactly what spec §3.3 forbids.

Fixed in `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`:
- `_channel_changed`: added `if self._preview_key is not None: return` as
  the first statement, per the review's given code.
- `_enter_preview`: `self.channel_combo.setEnabled(False)`.
- `_exit_preview`: `self.channel_combo.setEnabled(True)`.
- **Beyond the review's literal fix**: also added
  `self.channel_combo.setEnabled(True)` in `_open`. Reason: a preview can
  end by *promotion* (`session.open_line` on the previewed key), which
  resets the session's preview state without emitting `preview_changed` —
  the dock's `_open` clears `self._preview_key` directly and
  `_exit_preview` never runs. Without this, disabling the combo in
  `_enter_preview` and only re-enabling it in `_exit_preview` would leave
  the combo permanently disabled after a preview that ends via promotion
  instead of snap-back. Verified by trace through the code: `_open`'s tail
  already resets `_preview_key`/`preview_label` for exactly this reason
  (Task 2's original code); the enable call sits next to it for the same
  reason.

Test added: `test_a_channel_change_is_refused_while_previewing` — asserts
`session.channel(keys[1])` is unchanged after `dock._channel_changed(0)`
while previewing, and that the combo re-enables on `clear_preview()`.

### Finding 2 — the gain strip could reappear mid-preview

`show_gain_strip` had no `_preview_key` guard, so `plugin.py`'s
`_resync_gain_strip` (which guards on `current_key`, not the displayed key)
calling it for the *working* line's own curve while a different line was
being previewed would put a live, drag-writable strip over the previewed
radargram — the C2 configuration spec §3.3 names explicitly.

Fixed in `profile_dock.py`:
- `show_gain_strip`: added the preview guard as the first check. Deferred
  rather than dropped — `self._deferred_strip = None if points is None
  else (points, owner)`, then hides the strip and returns — because the
  request can carry a *new* curve (the working line finishing its load
  mid-preview) that must still be honoured once the preview ends.
- `__init__`: `self._deferred_strip: tuple[list[list[float]], Any] | None
  = None`.
- `_exit_preview`: pops `_deferred_strip`; if one is pending, calls
  `self.show_gain_strip(*deferred)` (now off the preview path, so it takes
  the normal branch); otherwise falls back to the existing
  `_strip_was_visible` restore. `_enter_preview` was left untouched, per
  the review's explicit note: it must not clear `_deferred_strip`, since
  hovering straight from one previewed line to another re-enters without
  an intervening exit, and a deferred request from the first hover is
  still pending.

Test added: `test_a_gain_strip_request_mid_preview_is_deferred_and_honoured_on_exit`
— calls `show_gain_strip` while previewing, asserts the strip stays
hidden, then asserts it is shown with exactly those points once
`clear_preview()` runs.

### Finding 3 — none of the 11 original tests rendered anything

The `previewing` fixture never called `set_profiles`, so both lines had
`stack.source is None` and `_render()` returned immediately every time.
The rendering assertions (`dock.image is not None`, the difference-view
round trip) were checking nothing real, and the specific hazard
`_effective_difference_index` exists to prevent —
`stack.difference(i)` evaluated against a previewed line's stack that does
not have `i` steps — was never executed by any test.

Fixed in `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`:
- `previewing` fixture: now calls `session.set_profiles(key, line.load())`
  for both lines (the same idiom `opened`-based tests already use), after
  `open_line`. Kept the fixture's yield shape (`dock, session, keys`)
  unchanged rather than also yielding the `Line` objects — none of the 13
  tests need them directly; every one reaches a line via
  `session.line_for_key(keys[i])` already.
- `test_preview_renders_the_previewed_line_not_the_working_one`: now
  captures `before = dock.image` before previewing and asserts
  `dock.image is not None and dock.image is not before` — proves a real
  render happened for the previewed line, not just a title change.
- `test_the_difference_index_survives_a_preview_round_trip`: strengthened
  per the review's given code — asserts `"dewow" in
  dock.difference_label.text()` before previewing, asserts
  `dock.difference_label.text() == ""` and `dock.image is not None` while
  previewing keys[1] (whose stack is empty, so index 0 does not exist on
  it — if `current_radargram()` used `self._difference_index` instead of
  `self._effective_difference_index` here, this would raise `IndexError`
  inside the `_on_preview_changed` slot, which is `qFatal()` in the LTR
  container, not a local test failure), and asserts `"dewow"` is back in
  the label after `clear_preview()`.
- Verified `"dewow"` is the right substring by reading
  `nsgeo.processing.dewow.Dewow.name = "dewow"` and `_render`'s
  `step_text = f"Difference: {entries[...][0].name}"` — not guessed.

## Commands run for the fix, and results

Targeted preview tests:
```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py -q -p no:xonsh -k preview
12 passed, 27 deselected in 1.06s
```
(10 of the original 11 preview tests match `-k preview` by name, plus the
2 new ones — `test_snap_back_restores_the_working_lines_cursor_and_selection`
doesn't contain "preview" in its name and is covered by the full-file run
below instead.)

Three-file target:
```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py packages/nsgeo-qgis/tests/qgis/test_plugin_difference_presets.py -q -p no:xonsh
72 passed in 16.24s
```
(70 before the fix + 2 new tests, zero regressions.)

Pure tier:
```
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
363 passed, 2 skipped in 1.34s
```
Unchanged from before the fix and from the base commit.

QGIS tier:
```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
401 passed in 90.59s
```
399 before the fix + 2 new tests = 401. Zero regressions.

Linters:
```
$ .venv/bin/ruff check . && .venv/bin/ruff format --check .
All checks passed!
92 files already formatted
```

## Minors not addressed (as instructed)

The coordinator explicitly listed two Minors as deliberately out of scope
and told me not to fix them: no test exercises two consecutive
`_enter_preview` calls without an intervening exit (verified working by the
reviewer's own probe), and `_enter_preview` sets `self._preview_key = key`
before the `line_for_key(key)` call that could theoretically raise —
unreachable in practice because `session.set_preview` already validates
the key before emitting. Left both exactly as they were.

---

## Fix report (second re-review)

The coordinator's re-review confirmed all three earlier findings addressed
and raised one further Important (Finding 4) plus one Minor to fix in the
same pass (Finding 5). Both fixed; tests added; both tiers and both linters
re-run green.

### Finding 4 — `_deferred_strip` survived promotion and a site close

`_deferred_strip` was cleared only in `_exit_preview`. Two other paths end
a preview without going through `_exit_preview` at all: promotion
(`session.open_line` on the previewed key, handled by `_open`) and a site
close (`_clear`). In both, the deferred payload — captured while a
*different* line was working — would survive into whatever line becomes
working next, and `_exit_preview`'s later replay would put that stale
curve on the strip over the new working line. Since a drag on the strip
resolves its write target through `session.current_key` (`plugin.py`'s
`_on_gain_points`), this was not just a display glitch: it was a route for
one line's gain curve to land on a step in a different line, exactly the
C2 shape spec §3.3 forbids.

Fixed exactly as given: added `self._deferred_strip = None` to both `_open`
(next to the existing `_preview_key = None` / channel-combo re-enable) and
`_clear` (next to its own `_preview_key = None`), with the review's comment
explaining why dropping rather than replaying is correct there specifically
(the working line has already changed by the time either method runs,
unlike `_exit_preview`, where it hasn't).

**Ordering check for the site-close test, as asked:** in the `previewing`
fixture, `session.open_line(keys[0])` runs first, so `_current_key` is set
before any test body runs. `SiteSession.close_site()`
(`packages/nsgeo-qgis/nsgeo_qgis/session.py:374-395`) guards
`line_opened("")` on `had_current_line` and emits it *before*
`site_closed`, both confirmed by reading the source directly (not
inferred): `line_opened("")` fires first when `had_current_line` is true,
`site_closed` always fires after. So for
`test_a_deferred_strip_is_dropped_when_the_site_closes`, `_on_line_opened("")`
→ `_open("")` already clears `_deferred_strip` before `_clear()` (bound to
`site_closed`) ever runs — `_open` is the method that actually does the
work for this specific test; `_clear`'s copy is not exercised by it.
`_clear`'s copy is not redundant in general, though: it is the only thing
that clears `_deferred_strip` when `close_site()` runs with no line ever
having been opened (`_current_key` already `None`, so `had_current_line` is
false and `line_opened` is never emitted at all) — a state a preview can
still be in, since `set_preview` does not require a working line. Left in,
per the review's explicit instruction to fix both places.

### Finding 5 — a mid-preview explicit hide could be overridden by a stale `_strip_was_visible`

In `show_gain_strip`'s preview branch, `show_gain_strip(None)` mid-preview
correctly set `_deferred_strip = None` but left `_strip_was_visible`
whatever it was captured as on `_enter_preview`. On exit, the `elif
self._strip_was_visible:` branch would then re-show the strip with the
*previous* curve, for a step the user had explicitly deselected — a
curve the user did not ask for (display-only, since a write still needs
`_gain_step` to pass its owner check, but still wrong on screen).

Fixed exactly as given: when `points is None` inside the preview branch,
also set `self._strip_was_visible = False`, with the review's comment.

### Tests added (all three, verbatim from the review)

- `test_a_deferred_strip_is_dropped_when_the_preview_is_promoted`
- `test_a_deferred_strip_is_dropped_when_the_site_closes`
- `test_a_hide_arriving_mid_preview_is_honoured_on_exit`

## Commands run, and results

Targeted tests:
```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py -q -p no:xonsh -k "deferred or hide_arriving or previewing"
8 passed, 34 deselected in 1.09s
```

Three-file target:
```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py packages/nsgeo-qgis/tests/qgis/test_plugin_difference_presets.py -q -p no:xonsh
75 passed in 16.22s
```
(72 before this fix + 3 new tests, zero regressions.)

Pure tier:
```
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
363 passed, 2 skipped in 1.36s
```
Unchanged.

QGIS tier:
```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
404 passed in 91.79s
```
401 before this fix + 3 new tests = 404. Zero regressions.

Linters:
```
$ .venv/bin/ruff check . && .venv/bin/ruff format --check .
All checks passed!
92 files already formatted
```
