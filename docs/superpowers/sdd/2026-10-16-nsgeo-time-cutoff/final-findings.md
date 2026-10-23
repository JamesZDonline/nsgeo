# Final whole-branch review — findings for the one fix wave

Range reviewed: c4701e8..d552871. All three findings below are Important. The riders after them are small and touch the same code.

## I1. A grab jumps to the pointer, so a drag released where it started still writes (Review Focus 5)

- Where: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py:619-623` (press) and `:678` (move).
- What's wrong: the press records only the starting value. The first move sets `snap_cutoff(time_of_y(y))` from the pointer's own y. Any press inside the ±5 px grab zone that is not on the line's exact pixel therefore moves the line on the first move event, and there is no drag threshold.
- Measured in the `opened` dock (900×360, 512 samples, 266-px image): press 4 px off the line, wiggle 1 px, release at the press point. The cutoff moved 8 samples (1.73 ns) and the session went dirty. The user gets a save prompt for an edit they never meant to make.
- Why the tests missed it: `test_a_drag_to_the_same_time_writes_nothing` (`test_plugin_profile_dock.py:1373`) emits the identical value at the dock, and the view tests press exactly on `round(_cutoff_y)`.
- Ruling R6 (controller; overrides Task 2 Step 5's pointer-absolute snap):
  - The grab keeps the press-to-line offset.
  - The line does not move until the pointer has travelled more than `DRAG_THRESHOLD_PX` vertically from the press.
  - While the pointer is within that distance, the value is exactly the grab's start value.
  - Beyond it, the value is `snap_cutoff(time_of_y(y + offset))`.
- Tests:
  - View: press 4 px off the line's pixel, wiggle 1 px, release at the press point, and assert the emitted value equals the original exactly.
  - Dock: the same gesture through a real `ProfileDock`, then assert no `stack_changed` and the session not dirty. Check dirty against the state before the gesture, not as a bare `dirty` assertion, which setup already makes true.
  - A real drag of N px, starting off-pixel, moves the line by N px, give or take one sample of snapping.

## I2. The working line's cutoff stays drawn, and grabbable, over a line whose samples have not loaded (Review Focus 4)

- Where: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py:432-445`, the no-profiles branch of `_show_line`.
- What's wrong: that branch calls `set_axes` and `set_image(None)` but never `_render`, so `view.set_cutoff(None)` never runs. Reproduced both ways:
  - In a preview of an unloaded line, `cutoff_ns` is still 32.22 while the title reads "PREVIEW: FILE__002".
  - After `open_line` to an unloaded line, the old line's cutoff is still drawn.
- Why it matters: the first hover over any line is exactly this case, because the loader starts the async load on `preview_changed`. If the load fails (a moved DZT), the line stays indefinitely. A drag then moves the line visibly and leaves it where it was dropped, with nothing written.
- Fix: in the no-profiles branch, set `self._cutoff_step = None` and call `self.view.set_cutoff(None)`.
- Tests:
  - Previewing an unloaded line hides the line.
  - Opening an unloaded line hides it.
  - An emitted `cutoff_dragged` there writes nothing.
  - Once the working line is shown loaded again, its line returns.
- `test_a_preview_hides_the_line_and_refuses_a_drag` uses the `previewing` fixture, where both lines are loaded, so it dodges this case.

## I3. With the Difference view on, selecting the cutoff leaves a stale, misleading image (both orders)

- Where: `profile_dock.py:687-713` (`current_radargram`) and `:728-733` (`_render`).
- **Order 1: Difference on (for background_mean), then select the cutoff row, which clips.**
  1. The decline fires.
  2. `set_difference_index(-1)` early-returns, so nothing re-renders.
  3. The final state is background_mean's difference image, with no line, the label cleared and the button unchecked.
- **Order 2: cutoff selected, then Difference on.**
  1. The decline fires.
  2. `_render`'s `rg is None` branch hides the line.
  3. The final state is the full 512-row unclipped record, with no line and no veil, while the cutoff is still selected.
- In both orders, clicking the same row does nothing; the user must select another row and come back. Order 1 already happens today for `time_zero`.
- Ruling R7 (controller):
  - In `current_radargram`, the difference view gets its own `try`.
  - On its `ValueError`/`IndexError`, call `_decline_difference(...)` (one message, button unchecked, label cleared) and fall through to the normal cutoff-bypass / `result()` path.
  - That path keeps its own `ValueError` → `error` + `None` handling.
  - Do not return `None` after a declined difference.
- Tests:
  - Both orders end with the bypass image (all rows) and the line shown, the button unchecked, and exactly one error message.
  - A `time_zero` difference declines to the ordinary result.
- Existing difference-view tests must stay green. Read `set_difference_index`'s and `_decline_difference`'s comments on re-entrancy before changing anything.

## Riders (small; same files)

1. `packages/nsgeo-core/src/nsgeo/processing/timecutoff.py`: the comment near lines 22-26 (and the one on the finiteness guard in `__init__`) misstates what NaN or inf would do without the guard. `math.ceil` raises `ValueError` for NaN and `OverflowError` for inf; neither is silent. Correct the reasoning; the guard stays.
2. `profile_view.py` label:
   - The cutoff label is drawn at `yy - 18`, under `setClipRect(r)`, so it is clipped when the line is within about 18 px of the image top. That is exactly where it is during a "keep one sample" drag.
   - Draw it below the line when there is no room above.
   - Test: with the line near the top, the label rect lies inside `r`. Factor the label rect into a small helper if that makes it testable without pixels.
3. `profile_view.py` `clear()`: also restore the normal cursor (the one `set_pick_mode` would set). Otherwise `SizeVerCursor` can stick over "no line open".
4. `profile_view.py`: `mousePressEvent` and `mouseReleaseEvent` are Qt-invoked overrides with no guard, and this branch added logic to both. Guard each body the way `mouseMoveEvent` does (`try` / `except Exception` → `_log(...)`), keeping behaviour identical.
5. `profile_dock.py` `_cutoff_row`: return -1 when `not self.session.is_open`. Then `close_site` is safe whatever the dock construction order, which today is the only thing protecting it.
6. Vacuous assertions:
   - `test_plugin_param_form.py:557`: change `all(c == ... for c in got)` to an exact `got == [...]`, or to `got == []` if no commit is expected.
   - The dock tests that expect a drag to write nothing (`test_plugin_profile_dock.py` around 1373, 1383, 1403): also assert that `message_log` holds no "could not move the time cutoff" entry. Use the `message_log` fixture from `tests/qgis/conftest.py`. Without it, a slot that crashes and logs is indistinguishable from a working no-op guard.

## Red-test seeds from the reviewer's probes

Probe tests the reviewer wrote outside the tree, which reproduce I1–I3 and the R3 round trip. They are in the session scratchpad, `/tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/bbee193a-c386-423b-a464-45f9e6f8a653/scratchpad/probe/` (its `conftest.py` reuses the repo fixtures):

- `test_probe_gesture.py` (I1)
- `test_probe_unloaded.py` (I2)
- `test_probe_plugin.py` (I3 order 1, plus a disabled-cutoff probe)
- `test_probe_diff_reverse.py` (I3 order 2)
- `test_probe_form_echo.py` (R3 end to end: drag, then an unedited `form.commit()` emits no `stack_changed`)

Read them for the exact reproduction. Write the real tests in the repo's test files, in the house style. Port `test_probe_form_echo.py` too, as the R3 regression pin, since the line-to-form direction is untested today.
