# Task 4 report: picks on the profile

## Status: DONE

## What I implemented

`packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`:
- `__init__`: `session.picks_changed.connect(self._on_picks_changed)`, inserted
  right after `session.stack_changed.connect(self._on_stack_changed)`.
- `_on_picks_changed(self) -> None`: the slot `picks_changed` invokes. Guards
  its own body (try/except around `self._refresh_picks()`), logging via
  `_log(..., Qgis.MessageLevel.Critical)` on failure — matches every other
  slot in this file and satisfies the conftest's
  `_no_swallowed_slot_exceptions` fixture.
- `_refresh_picks(self) -> None`: reads `self._key` (the *displayed* line —
  working line or preview, whichever is on screen), and calls
  `self.view.set_picks([(p.trace, p.time_ns) for p in self.session.picks_for(key)])`,
  or `self.view.set_picks([])` when `self._key is None`.
- `_show_line`: one new line, `self._refresh_picks()`, added at the end,
  after `self._refresh_velocity()`. This is the single place both `_open`
  (working line) and `_enter_preview` (preview) configure the view, so both
  paths now populate/refresh the picks with no per-caller duplication.
- No change was needed to `_clear_view_only` — `ProfileView.clear()` already
  resets `_picks` to `[]`, and `_clear()` (wired to `session.site_closed`)
  already calls it.

`packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py`:
- Removed `"picks_changed"` and its comment from `KNOWN_UNCONSUMED`.
- Rewrote the module docstring's NOTE block. It previously said the real
  orphan count was "SEVEN" (four in `KNOWN_UNCONSUMED` + `pick_requested` +
  `ParamForm.error` + `ProfileView.set_pick_mode`), but that text was already
  stale at HEAD: Task 3 had already wired both `pick_requested` (plugin.py →
  `_on_pick_requested`) and `set_pick_mode` (plugin.py line 461,
  `self.profile_dock.set_pick_mode(bool(checked))`) — confirmed by grep
  before editing. The new NOTE explains that `pick_requested` and
  `picks_changed` have both left the unconsumed set (the first in Task 3,
  the second here), and names what remains: `ParamForm.error` (invisible to
  the name-keyed check — see `SHADOWED`) plus the three dead `SurveyDock`
  signals still in `KNOWN_UNCONSUMED`. This matches the outer task
  description's correction ("down to `ParamForm.error` plus the three dead
  `SurveyDock` signals") rather than the brief's own slightly looser
  phrasing ("down to the three dead `SurveyDock` signals"), since
  `ParamForm.error` is still genuinely unconsumed per `SHADOWED["error"] =
  {"declared": 2, "connects": 1}` and dropping it from the NOTE would have
  been inaccurate.

`packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`:
- Appended the brief's `dock_with_picks` fixture and five tests verbatim
  (no changes needed — the fixture matches the established `pickable`
  pattern already used in `test_plugin_session.py`, and every test ran and
  asserted as written). Did not touch `opened`/`previewing` per the brief's
  explicit instruction.

## What I tested and the results

### TDD Evidence

**RED** (before implementation), pure tier:
```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q -p no:xonsh
```
```
F.................................................                       [100%]
=================================== FAILURES ===================================
___________________ test_every_declared_signal_has_a_connect ___________________
...
E       AssertionError: signals declared with no consumer anywhere in the plugin: {'picks_changed': 'session.py'}. ...
1 failed, 49 passed in 0.81s
```
Expected: `picks_changed` left `KNOWN_UNCONSUMED` with no connect yet, so
`test_every_declared_signal_has_a_connect` fails — exactly the failure the
brief predicts.

**RED** (before implementation), QGIS tier, focused file:
```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py -q -p no:xonsh
```
```
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py::test_a_new_pick_appears_on_the_profile_without_reopening_the_line
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py::test_opening_a_line_shows_the_picks_already_on_it
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py::test_a_preview_shows_the_previewed_lines_own_picks
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py::test_a_failing_pick_read_is_logged_not_escaped
4 failed, 53 passed in 7.57s
```
All four failed with `assert [] == [(...)]` (or, for the logging test,
`assert False` on the message-log check) — `dock.view._picks` stayed empty
because nothing yet called `set_picks`. The fifth new test,
`test_closing_the_site_clears_the_picks_from_the_view`, already passed at
this point: it only exercises the pre-existing `site_closed` → `_clear` →
`_clear_view_only` → `ProfileView.clear()` path, which already reset
`_picks` before this task. That is expected, not a defect in the test.

**GREEN** (after implementation), pure tier (orphan-signals file):
```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py -q -p no:xonsh
```
```
....                                                                     [100%]
4 passed in 0.61s
```

**GREEN** (after implementation), QGIS tier, focused file:
```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py -q -p no:xonsh
```
```
.........................................................                [100%]
57 passed in 7.84s
```
(52 pre-existing + 5 new.)

### Full tiers (run once, before committing)

Pure tier:
```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
```
```
367 passed, 2 skipped in 1.69s
```
Matches the stated baseline exactly (367 passed, 2 skipped).

QGIS tier:
```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
```
```
509 passed in 183.57s (0:03:03)
```
Baseline was 504; 509 = 504 + 5 new tests. Above baseline, as required.

### Lint / types

```
.venv/bin/ruff check .
```
```
All checks passed!
```
```
.venv/bin/ruff format --check .
```
```
95 files already formatted
```
```
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
```
```
Success: no issues found in 24 source files
```
`profile_dock.py` was not added to the mypy invocation, per the brief.

## Pixel-measurement evidence (Step 5)

The brief's script imports `plugin_testing.synthetic_dzt`, which does
`from tests.synthetic import write_dzt`. That module lives at
`packages/nsgeo-core/tests/synthetic.py`, not under
`packages/nsgeo-qgis/tests`. The brief's script only put
`packages/nsgeo-qgis` and `packages/nsgeo-qgis/tests` on `sys.path`, so it
failed immediately with `ModuleNotFoundError: No module named
'tests.synthetic'`. `packages/nsgeo-qgis/tests/conftest.py` (used by the
real pytest suite) also inserts `packages/nsgeo-core` onto `sys.path` for
exactly this import, with the comment `# for \`from tests.synthetic import
write_dzt\``. I added the same third `sys.path.insert(0, "packages/nsgeo-core")`
line to the script (nothing else changed) and it then ran to completion.

Script as run (`sys.path` block shown; body unchanged from the brief):
```python
import sys, tempfile
from pathlib import Path

sys.path.insert(0, "packages/nsgeo-qgis")
sys.path.insert(0, "packages/nsgeo-qgis/tests")
# ADJUSTED from the brief: plugin_testing.synthetic_dzt does
# `from tests.synthetic import write_dzt`, which resolves against
# packages/nsgeo-core/tests (not packages/nsgeo-qgis/tests, which has no
# synthetic.py of its own) -- exactly what tests/conftest.py's own sys.path
# setup does for the real suite. Without this the script fails at
# synthetic_dzt() with ModuleNotFoundError: No module named 'tests.synthetic'.
sys.path.insert(0, "packages/nsgeo-core")

from qgis.core import QgsApplication, QgsProject
QgsApplication.setPrefixPath("/usr", True)
app = QgsApplication([], False)
app.initQgis()

from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.profile_dock import ProfileDock
from plugin_testing import synthetic_dzt

tmp = Path(tempfile.mkdtemp())
project = QgsProject.instance()
session = SiteSession()
session.new_site(tmp)
layers = SiteLayers(session, project=project)
session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
p = synthetic_dzt(tmp / "raw", "FILE__001.DZT", n_traces=240)
line = Line.open(p, GridPlacement("A", "y", 0.0, 0.0, 1, "FILE__001"))
session.add_lines([line])
key = session.keys()[0]
dock = ProfileDock(session)
dock.resize(900, 360)
dock.show()
session.open_line(key)
session.set_profiles(key, line.load())

before = dock.view.grab_image()
session.add_pick(key, 120, 40.0)
after = dock.view.grab_image()

# Bounding box of every pixel the pick changed.
xs, ys = [], []
for y in range(after.height()):
    for x in range(after.width()):
        if before.pixel(x, y) != after.pixel(x, y):
            xs.append(x)
            ys.append(y)
print("pick stored as:", [(pk.trace, pk.time_ns) for pk in session.picks_for(key)])
print("view holds:    ", dock.view._picks)
if not xs:
    print("CHANGED PIXELS: none -- the pick is INVISIBLE")
else:
    print(f"changed pixel box: x {min(xs)}..{max(xs)}  y {min(ys)}..{max(ys)}")
    r = dock.view.image_rect()
    want = dock.view._pick_positions(dock.view.transform)
    print("marker should be at (local):", want)
    print("i.e. widget coords:", [(r.left() + x, r.top() + y) for x, y in want])

dock.hide()
layers.detach()
project.clear()
app.exitQgis()
```

Run:
```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python <script>
```

Output:
```
This plugin does not support propagateSizeHints()   (x2, harmless offscreen-platform Qt noise)
pick stored as: [(120, 40.0)]
view holds:     [(120, 40.0)]
changed pixel box: x 446..456  y 128..137
marker should be at (local): [(395.64166666666665, 129.0236716035038)]
i.e. widget coords: [(451.64166666666665, 137.0236716035038)]
```

**Judgement:** the two boxes agree. `_paint_picks` draws its triangle marker
five pixels either side of the point and nine pixels above it. The reported
marker widget position is x≈451.64, y≈137.02. Five pixels either side gives
x 446.64..456.64; nine pixels above gives y 128.02..137.02 (the point itself
is the triangle's bottom apex). The measured changed-pixel box — x 446..456,
y 128..137 — straddles that position almost exactly (the ~0.64px difference
at the edges is sub-pixel rounding from `QPainter`'s anti-aliased fill, not
a positioning error). The pick is genuinely visible where it was made, and
drawn at the position the view itself reports for it — not a cosmetic-only
change, an end-to-end confirmed one.

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` — `_on_picks_changed`,
  `_refresh_picks`, one `connect`, one call in `_show_line`.
- `packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py` — removed
  `picks_changed` from `KNOWN_UNCONSUMED`, rewrote the NOTE block.
- `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py` — appended
  `dock_with_picks` fixture and five tests.

`profile_dock.py` grew by 23 net lines (25 insertions, 2 of which are the
blank-line/connect additions), to roughly 890 lines. This is the size the
brief's own file-structure section anticipated (`_on_picks_changed` and
`_refresh_picks` beside `_on_stack_changed`, one `connect`, one line at the
end of `_show_line`) — no restructuring judgement call was needed and none
was made.

## Self-review findings

- Checked that `_refresh_picks` reads `self._key` (the property that
  resolves to `self._preview_key or self._working_key`), not
  `self._working_key` directly — confirmed by re-reading the diff and by
  `test_a_preview_shows_the_previewed_lines_own_picks` passing, which is
  exactly the test that would fail if this were swapped.
  `test_add_pick_refuses_a_line_that_is_not_the_working_line` (in
  `test_plugin_session.py`, unchanged, already passing) independently
  confirms `add_pick` itself still guards against a preview write, so
  reading-via-`_key` does not weaken that invariant.
- Checked `_on_picks_changed`'s exception guard against the same pattern
  used by every sibling slot in this file (`_on_stack_changed`,
  `_on_trace_changed`, etc.): `except Exception as exc:  # noqa: BLE001 --
  see the module docstring` and `_log(..., Qgis.MessageLevel.Critical)`.
  Matches exactly.
- Verified the `KNOWN_UNCONSUMED` comment removal left no dangling
  reference: grepped for `picks_changed` across `nsgeo_qgis/` and the test
  file — the only remaining occurrence outside this task's own new code is
  the signal's declaration in `session.py` and its (unchanged) emission and
  existing consumer tests in `test_plugin_session.py`.
  `test_shadowed_signals_match_their_pinned_shape` and
  `test_every_shadowed_signal_name_is_pinned` both still pass, confirming
  the `SHADOWED` table needed no change for this task (`picks_changed` was
  never a shadowed name).
  I did not touch the pre-existing typo at line 23 of
  `test_no_orphan_signals.py` (`SHADOWED_CONNECT_COUNTS`, which should read
  `SHADOWED`) — it predates this task, is not part of the brief's scope, and
  is a comment, not a test assertion, so it has no behavioural effect.
- Confirmed `dock_with_picks`'s teardown (`dock.deleteLater()` without a
  prior `dock.hide()`) matches the brief exactly; the dock in this fixture
  is never `show()`n (unlike `opened`/`previewing`), so there is no visible
  top-level widget to hide first. No test in the appended block depends on
  the dock being shown — all assertions read `dock.view._picks`, a plain
  Python list, not anything requiring a live paint event.
  Ran the five new tests in isolation and inside the full file; no ordering
  dependency or leaked state observed (`509` in the full QGIS run vs `57`
  in the focused file both check out against their respective baselines).
- Confirmed each new test is falsifiable against a plausible wrong
  implementation: reading `_working_key` instead of `_key` fails the
  preview test; forgetting the `__init__` connect fails the "new pick
  appears" test; forgetting the `_show_line` call fails the "opening a
  line shows existing picks" test; an unguarded `_on_picks_changed` fails
  the logging test via the autouse `_no_swallowed_slot_exceptions`
  fixture (verified this directly during the RED run above — the failure
  was the assertion on `dock.view._picks`/`message_log`, not a slot
  exception escaping, since the slot didn't exist yet; once implemented
  and monkeypatched to raise, I confirmed by inspection that the
  try/except in `_on_picks_changed` is what keeps `boom`'s `RuntimeError`
  from reaching `sys.excepthook` — the full-file GREEN run above having
  `_no_swallowed_slot_exceptions` active and passing is the direct
  confirmation of this).

No issues found that needed fixing before reporting.

## Issues or concerns

None. Both tiers are green and above baseline, lint and mypy are clean, the
pixel measurement confirms the pick is drawn where the view reports it
(not merely present in a list), and the diff is scoped to exactly the three
files the brief named.
