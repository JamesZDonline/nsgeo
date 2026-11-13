# Trace a hyperbola from a box — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In velocity mode, a drag draws a box and the plugin traces the hyperbola inside it as
about ten ordinary working dots on the outer edge of its top band. Ctrl+click (Cmd+click on a
Mac) places dots, or draws a box, with velocity mode off.

**Architecture:**
- A numpy-only tracer in the core, `nsgeo/hyperbola_trace.py`, turns (amplitudes, times,
  distances, box) into dots.
- The profile view turns a drag into a box signal. The profile dock checks its refusals, runs the
  tracer and puts the dots in the working set, after which everything downstream (fit, curve,
  Save fit, Apply) is unchanged.
- The plugin switches velocity mode on when the view asks.

**Tech Stack:** Python 3.9 and numpy (core); PyQt5/6 through `qgis.PyQt` (plugin); pytest.

**Spec:** `docs/superpowers/specs/2026-11-13-nsgeo-hyperbola-tracer-design.md` (approved by the
author 2026-11-13). Read it before your task: §3 holds the author's decisions, §4 the tracer, §5
the gesture, §6 the panel, §7 the shortcut, §10 the tests.

## Global Constraints

- **Core:** numpy only (no scipy). The runtime is Python 3.9, so: no `zip(strict=)`, no `match`,
  and no PEP 604 unions outside annotations. `from __future__ import annotations` heads every new
  file. A new public module lists its names in `__all__`. Check `tests/test_public_api.py` and
  `tests/test_boundary.py` and keep them green.
- **Plugin:**
  - Qt only through `qgis.PyQt`. `tests/pure/test_plugin_boundary.py` and
    `test_no_orphan_signals.py` stay green.
  - Every Qt slot guards its own body:
    `except Exception as exc:  # noqa: BLE001 -- see the module docstring`. It logs or reports;
    it never raises.
- **Unchanged:**
  - `StoredFit`, the project file (no schema change), `fit_hyperbola`, Save fit, Apply, Clear and
    the velocity dialogs;
  - a hand click lands exactly where clicked;
  - Shift+click still authors a pick in any mode.
- **Never commit site data.**
  - The author's hand-fit data lives only under `packages/nsgeo-core/tests/data/local/`, which is
    gitignored. Never add anything from it with `git add -f`.
  - No real velocity, time, trace number, site name or file path from that data appears in a
    committed test, fixture, doc or ledger excerpt that is committed. Real-data tests assert the
    agreement rules only.
  - The measured constants in §Task 1 (dt, trace spacing, period, noise ratio) are allowed: they
    describe the instrument, not a site.
- **Shared-worktree safety:** reviewers and any mutation probes work on a scratch copy, never on
  this worktree. Set `PYTHONDONTWRITEBYTECODE=1` for every run.
- **Commits:** end each message with a `Co-Authored-By:` line naming the model that wrote it.
  Push each commit to `origin nsgeo-hyperbola-tracer` as it is made. Touch no other worktree.

### Copy (exact)

**Core, `trace_hyperbola` refusals** (`ValueError`):
- `"The box is too small to hold a hyperbola: draw it around the apex and at least part of a leg."`
- `"The box is too big to trace quickly ({traces} traces by {ns:.0f} ns). Draw it closer around one hyperbola."`
- `"No hyperbola was found in the box."`
- `"The hyperbola in the box is too faint to trace."`
- `"Too few points were left after cleaning ({n}); a fit needs at least 4."`
- Any `fit_hyperbola` message passes through unchanged.

**Plugin, the velocity strip's note** (`ProfileDock.velocity_note`):
- Migration on: `"Cannot trace with Migration (Stolt f-k) on: it has already collapsed the hyperbolas. Switch it off in the processing stack to trace, or click the points by hand."` (the step's `title`)
- An amplitude transform on: `"Cannot trace with {title} on: it removes the edge the tracer follows. Switch it off in the processing stack to trace, or click the points by hand."` (titles `Absolute value`, `Square of the amplitude`, `Envelope`)
- A difference view: `"Cannot trace a difference view. Turn the difference off to trace."`
- Sample-mode time zero, after a successful trace: `"Time zero is set at a sample here, so the traced edge may not line up with it."`

**Plugin, tooltips:**
- `VELOCITY_TIP` = `"Velocity mode: click a diffraction hyperbola on the profile, apex first, or drag a box around it to trace it. Right-click a point to remove it. Ctrl+click (Cmd+click on a Mac) works with this off."`
- Pick's tip is unchanged.
- The guide's Velocity row (`docs/guide/getting-started.md`, toolbar table):
  `| **Velocity** | Turns velocity mode on and off. Click a diffraction hyperbola on the profile, or drag a box around it to trace it, to measure the radar velocity from it. Ctrl+click (Cmd+click on a Mac) does the same with velocity mode off. |`

## Verification commands (exactly these, from the worktree root)

The worktree uses the main checkout's virtualenvs, with the worktree's core on `PYTHONPATH`. A
local `.venv-tools` (git-excluded) holds the CI-pinned ruff 0.17.1 and mypy 2.4.0.

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
- **qgis:** `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh`
  - This takes 10+ minutes. Run single files while iterating; the coordinator runs the full tier.
- **lint:** `.venv-tools/bin/ruff check . && .venv-tools/bin/ruff format --check .`
- **types:** the `mypy` command in `.github/workflows/ci.yml`, run with `.venv-tools/bin/mypy`.

## Review Focus

These are inputs a person will meet that the spec implies but does not spell out. Each is
pinned by a test in its owning task.

1. **A box drawn from bottom-right to top-left, or over the axis margin.** The box is normalised
   and clipped to the radargram. Pinned by Task 3, `test_a_box_drawn_backwards_or_past_the_edge_is_normalised_and_clipped`.
2. **A traced fit saved, then refit later.** Its first dot is the apex guess, so `refit` gives
   the same velocity the strip showed. Pinned by Task 3,
   `test_a_saved_traced_fit_refits_to_the_velocity_shown`.
3. **A refusal while the author has unsaved hand dots.** The dots survive and the note says
   why. Pinned by Task 3, `test_a_refused_box_keeps_the_hand_dots`.
4. **Ctrl+click on a cut or with no line.** Nothing is placed and velocity mode stays off. On a
   cut, the cut tip is shown. Pinned by Task 4,
   `test_ctrl_click_on_a_cut_places_nothing_and_says_why`.
5. **A hyperbola whose leg runs off the box's bottom edge or into the line's end.** It is traced
   from the part inside. Pinned by Task 1, `test_a_leg_cut_off_by_the_box_is_traced_from_the_part_inside`.

---

### Task 1: The tracer in the core, against planted hyperbolas

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/hyperbola_trace.py`
- Create: `packages/nsgeo-core/tests/planted.py` (the planted-hyperbola helper, shared with the
  plugin tests)
- Create: `packages/nsgeo-core/tests/test_hyperbola_trace.py`
- Modify: `packages/nsgeo-core/tests/test_public_api.py`, if it enumerates modules

**Interfaces:**
- Consumes: `fit_hyperbola(x_m, t_ns, apex_guess_m, *, search_m=0.25) -> HyperbolaFit`
  (`nsgeo.velocity_fit`); `first_break_row(rg, threshold=0.2) -> int`
  (`nsgeo.processing.timezero`); `Radargram` (`nsgeo.processing.base`).
- Produces:
  ```python
  @dataclass(frozen=True)
  class TraceBox:
      first_trace: int   # inclusive; any order in, normalised by trace_hyperbola
      last_trace: int
      top_ns: float      # on the same clock as `times_ns`
      bottom_ns: float

  MAX_DOTS = 10
  MIN_DOTS = 4
  V_MIN_M_NS = 0.03
  V_MAX_M_NS = 0.30
  MAX_BOX_CELLS: int   # traces × samples; set in Task 2 from measurement. Start at 10**9.

  def trace_hyperbola(data: np.ndarray, times_ns: np.ndarray, distance_m: np.ndarray,
                      box: TraceBox, *, fraction: float = 0.2,
                      max_dots: int = MAX_DOTS) -> list[tuple[int, float]]
  def edge_time(trace: np.ndarray, times_ns: np.ndarray, start_ns: float, stop_ns: float,
                fraction: float) -> float | None
  ```
  - `data` is (n_samples, n_traces); `times_ns` is (n_samples,), each row's time on the fit's
    clock; `distance_m` is (n_traces,), possibly unevenly spaced.
  - `trace_hyperbola` returns dots `(trace, time on the times_ns clock)`, the apex-nearest
    first, then the rest in trace order. It raises `ValueError` with the copy above.
  - `edge_time` is the per-trace edge rule (spec §4.2): the first time within `[start_ns,
    stop_ns]` where |amplitude| reaches `fraction` of the window's peak |amplitude|, linearly
    interpolated between samples. `None` when the window holds no signal.

- [ ] **Step 1: Measure the instrument on the campus lines, and write `tests/planted.py`.**
  - Measure from `packages/nsgeo-core/tests/data/local/FILE__003.DZT`, after `time_zero`,
    `dewow` and `background_mean`:
    - dt;
    - metres per trace (from the DZX/header);
    - dominant wavelet period (the peak of the mean amplitude spectrum);
    - noise RMS as a fraction of the peak reflection amplitude below 10 ns.
  - Write them into `planted.py` as module constants with a comment naming the file and recipe:
    `REAL_DT_NS`, `REAL_DX_M`, `REAL_PERIOD_NS`, `REAL_NOISE_RATIO`.
  - `planted.py` provides:
    - `ricker(t_ns, period_ns)`;
    - `wavelet_onset_ns(period_ns, fraction=0.2)`: the time from a Ricker wavelet's start to
      where |amplitude| first reaches `fraction` of its peak, found on a fine grid;
    - `plant(n_traces, n_samples, hyperbolas, *, noise_ratio, seed, dx_m=REAL_DX_M,
      dt_ns=REAL_DT_NS, distance_m=None) -> (data, times_ns, distance_m)`.
  - Each hyperbola is `Planted(apex_trace, t0_ns, v_m_ns, amplitude=1.0,
    fade_from_trace=None)`. The wavelet is placed so its 0.2 onset lies exactly on t(x). Beyond
    `fade_from_trace` (counted from the apex), the amplitude falls to zero over 10 traces.

- [ ] **Step 2: Write the failing tests** in `test_hyperbola_trace.py`, all on `plant(...)`
  output at `REAL_NOISE_RATIO` unless named otherwise:
  - `test_a_planted_hyperbola_is_traced_to_its_velocity`
    - Plant v = 0.07, t0 = 15 ns, apex trace 100 of 200. Box traces 60–140, 10–30 ns.
    - Fit the dots with `fit_hyperbola` (apex guess = the first dot's distance).
    - `abs(fit.v_m_ns - 0.07) <= 2 * fit.v_stderr_m_ns`.
  - `test_the_edge_rule_matches_time_zeros_first_break`
    - On a single Ricker trace, `edge_time` and the time of `first_break_row` on a one-trace
      `Radargram` holding the same trace differ by at most one `dt`.
    - Use fractions 0.1, 0.2 and 0.5.
  - `test_at_most_ten_dots_and_the_apex_nearest_first`
    - `len(dots) <= 10`.
    - `dots[0]` is the dot whose trace is nearest the planted apex.
    - The rest are in increasing trace order.
  - `test_the_stronger_of_two_hyperbolas_is_traced`
    - Plant amplitude 1.0 at apex trace 80 and 0.4 at apex trace 120, both at t0 = 15 ns, in one
      box.
    - The fitted apex lies within 3 traces of trace 80.
  - `test_a_fading_leg_drops_the_faded_traces`
    - `fade_from_trace=25` on both legs, box ±60 traces.
    - Every dot lies within 35 traces of the apex.
    - The fitted v is still within 2σ of the truth.
  - `test_a_leg_cut_off_by_the_box_is_traced_from_the_part_inside`
    - The box holds the apex and only the right leg (apex at the box's left edge + 2), or the
      box's bottom edge cuts both legs at 25 ns.
    - Traced, and v within 2σ.
  - `test_noise_alone_is_no_hyperbola`
    - Pure noise raises `ValueError` matching `"No hyperbola was found in the box."` or
      `"The hyperbola in the box is too faint to trace."`.
  - `test_a_tiny_box_is_refused`
    - A box 3 traces wide raises the too-small copy.
  - `test_a_box_over_the_cell_limit_is_refused`
    - Monkeypatch `MAX_BOX_CELLS` to 100.
    - Any normal box raises the too-big copy, with its trace count and ns span filled in.
  - `test_uneven_trace_spacing_is_respected`
    - Plant with `distance_m` whose spacing varies ±30% along the line, the hyperbola computed
      from those true distances.
    - v within 2σ.
  - `test_a_backwards_box_is_normalised`
    - `TraceBox(140, 60, 30.0, 10.0)` gives the same dots as `TraceBox(60, 140, 10.0, 30.0)`.

- [ ] **Step 3: Run them to confirm they fail.**
  `... -m pytest packages/nsgeo-core/tests/test_hyperbola_trace.py -q` gives ImportError or
  failures.

- [ ] **Step 4: Implement `hyperbola_trace.py`** to spec §4.
  - **Scan.** Coarse to fine over apex trace (inside the box), apex time (inside the box) and v
    (`V_MIN_M_NS`–`V_MAX_M_NS`). Score is the mean |amplitude| or envelope sampled along the
    curve over the box's traces where the curve lies inside the box; your call which.
  - **Edges.** `edge_time` on each trace, in a window from about one period before the
    best curve to half a period after it. A forward search from the window's start, like
    `first_break_row`, is what makes the consistency test pass. A trace whose window peak is
    below 3× the box's median |amplitude| gives no edge ("too faint" when the apex region has
    none).
  - **Clean and thin.**
    1. `fit_hyperbola` on all the edges.
    2. Drop residuals over 3× the median absolute residual, and refit.
    3. Thin to `max_dots` evenly spaced along the traced extent. Keep the apex-nearest dot and put
       it first.
  - **Box checks.** Refuse a box under 8 traces or 8 samples (too small), or over
    `MAX_BOX_CELLS` (too big).

- [ ] **Step 5: Run the tests to confirm they pass.** Then run the full core + pure tier, lint
  and types.

- [ ] **Step 6: Commit and push.**
  `git add packages/nsgeo-core/src/nsgeo/hyperbola_trace.py packages/nsgeo-core/tests/planted.py packages/nsgeo-core/tests/test_hyperbola_trace.py`
  (plus `test_public_api.py` if changed)
  `git commit -m "feat(core): trace a diffraction hyperbola inside a box (#140)"`, then push.

### Task 2: Real-data validation on the author's saved hand fits

**Files:**
- Create: `packages/nsgeo-core/tests/make_hand_fit_data.py` (committed; holds no site data)
- Create: `packages/nsgeo-core/tests/test_hyperbola_trace_hand_fits.py`
- Modify: `packages/nsgeo-core/tests/real_data.py` (add `HAND_FIT_SITES`)
- Modify: `packages/nsgeo-core/src/nsgeo/hyperbola_trace.py` (set `MAX_BOX_CELLS`, plus any fix
  the real data forces)

**Interfaces:**
- Consumes: Task 1's `trace_hyperbola`, `TraceBox`, `MAX_BOX_CELLS`; `load_site`
  (`nsgeo.project`); `Radargram.from_profile`; `fit_at_zero`, `fit_hyperbola`; `retime_ns`.
- Produces:
  - `HAND_FIT_SITES: list[Path]`: the `*.nsgeo.json` files under `tests/data/local/hand-fits/`,
    sorted; `[]` when missing.
  - The local files `tests/data/local/hand-fits/rulings.json` and `pending.json`, both
    `{ "<absolute DZT path>#<fit id>": "<text>" }`.

- [ ] **Step 1: Write `make_hand_fit_data.py` and build the data.**
  - Usage: `python tests/make_hand_fit_data.py SITE.nsgeo.json [...]`. It copies each named site
    file into `tests/data/local/hand-fits/` under a neutral name (`site-1.nsgeo.json`, …).
  - It creates empty `rulings.json` and `pending.json` if absent.
  - Run it with the two site files named in spec §10:
    - `~/nsgeo-m4-check/Nashville_City_Cemetery (Copy)/survey.nsgeo.json`
    - `~/nsgeo-m4-check/Sunnyside/survey.nsgeo.json`
  - Confirm `git status` shows nothing from `tests/data/local/`.

- [ ] **Step 2: Write the tests**, parametrised over every saved fit in `HAND_FIT_SITES`, keyed
  `"<DZT path>#<fit id>"`. Skip with a reason when the list is empty or a DZT is missing.
  - **Per fit:**
    - Rebuild the line's saved stack (`site.stacks[key]`, source
      `Radargram.from_profile(line.load()[0])`) and take `result()`.
    - The fit's clock is the result's `zero_ns` when the stack sets time zero, else 0.0.
    - Hand: `fit_at_zero(fit, distance, zero)`.
    - Box: the hand dots' trace and time extent on that clock, widened by 20% of each extent
      per side, at least 5 traces and 2 ns.
    - Traced: `trace_hyperbola` with the line's own time-zero fraction (spec §4.2), then
      `fit_hyperbola` on the dots.
  - `test_a_traced_fit_agrees_with_the_hand_fit`:
    `abs(v_t - v_h) <= 2 * sqrt(sig_t**2 + sig_h**2)`.
  - `test_three_boxes_agree_with_each_other`:
    - margins 10%, 20% and 35%, the 35% one shifted by +10% of its width;
    - pairwise, the same rule.
  - `test_the_largest_box_traces_within_a_second`: time `trace_hyperbola` on the largest
    35%-margin box over all fits; assert under 1.0 s.
  - **Rulings:**
    - A key in `rulings.json` is skipped with its text.
    - A key in `pending.json` is `pytest.mark.xfail(strict=True, reason="pending the author's
      ruling: " + text)`.

- [ ] **Step 3: Run the tests, and triage every failure.**
  - Never change the tracer only to make one fit pass.
  - A failure that a planted test can reproduce is a tracer bug. Add that planted test to
    `test_hyperbola_trace.py`, fix, and commit.
  - Anything else goes into `pending.json` with one line saying what was seen (traced v, hand v,
    both σ). List it in the task report for the walkthrough.
  - Report how many fits agree, are pending, and could not be traced.

- [ ] **Step 4: Set `MAX_BOX_CELLS` from measurement.**
  - Time `trace_hyperbola` on boxes of growing size on a real line.
  - Set the limit at the largest size that still traces in 1.0 s, rounded down.
  - Record the measurements in the task report. If even the largest hand-fit box is over a
    second, report that instead of setting a limit that refuses real hyperbolas.

- [ ] **Step 5: Run core + pure, lint and types.** Then commit the script, the test, the
  `real_data.py` change and any tracer change (never the local data), and push.
  `git commit -m "test(core): trace the author's saved hand fits and agree with them (#140)"`

### Task 3: The box: gesture, panel wiring and refusals

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`
- Modify: `packages/nsgeo-qgis/tests/qgis/test_plugin_velocity_fit.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_velocity_box.py`

**Interfaces:**
- Consumes: Task 1's `trace_hyperbola`, `TraceBox`; `tests.planted.plant` and
  `tests.synthetic.write_dzt` (to write a DZT holding a planted hyperbola).
- Produces:
  - **`ProfileView`:**
    - `velocity_box_drawn = pyqtSignal(int, int, float, float)`: first trace, last trace, top
      ns and bottom ns, on the drawn axis, normalised and clipped to the radargram;
    - `velocity_mode_requested = pyqtSignal()` (emitted in Task 4, declared here so the
      gesture code has one shape);
    - `velocity_box_rect() -> QRectF | None`: the rectangle being dragged, for painting and
      tests.
  - **`ProfileDock`:**
    - the slot `_on_velocity_box_drawn(first_trace, last_trace, top_ns, bottom_ns)`;
    - `velocity_mode_requested = pyqtSignal()`, relayed from the view (wired in Task 4).

- [ ] **Step 1: Write the failing tests** in `test_plugin_velocity_box.py`.
  - **Fixture.** As `test_plugin_velocity_fit.py`'s `plugin` fixture, but line 1 is a DZT
    written from `plant(...)` with one hyperbola (v = 0.07, t0 = 15 ns, apex trace 60 of 120).
    Velocity mode is on.
  - Drive with real `QTest.mousePress` / `send_move_while_pressed` / `QTest.mouseRelease`.
  - The tests:
    - `test_a_drag_in_velocity_mode_traces_dots_into_the_working_set`
      - Drag around the hyperbola.
      - 4–10 dots, the first nearest trace 60.
      - The strip shows `v = `, and `Save fit` is enabled.
    - `test_a_wobble_shorter_than_the_drag_distance_places_one_dot`
      - Press, move `QApplication.startDragDistance() - 1` px, release.
      - Exactly one dot, at the press position.
    - `test_a_box_replaces_the_working_dots`
      - Click 3 dots, then box.
      - None of the 3 remain.
    - `test_a_refused_box_keeps_the_hand_dots`
      - Click 3 dots, enable a `migrate_fk` step, then box.
      - The 3 dots remain.
      - `velocity_note` shows the Migration copy.
    - `test_each_amplitude_transform_refuses_with_its_title`: parametrised over
      `amp_abs`, `amp_square`, `amp_envelope`.
    - `test_a_difference_view_refuses`.
    - `test_a_box_on_empty_ground_says_why_and_keeps_the_dots`
      - Box over noise only.
      - The note shows the core's reason.
      - The dots are unchanged.
    - `test_a_box_drawn_backwards_or_past_the_edge_is_normalised_and_clipped`
      - Drag from bottom-right to top-left, and once past the image's right edge.
      - The signal's values are ordered and inside the radargram.
    - `test_a_saved_traced_fit_refits_to_the_velocity_shown`
      - Box, Save fit.
      - `refit(stored, distance, zero).v_m_ns` equals the strip's v to 4 dp.
    - `test_sample_mode_time_zero_adds_the_note_after_a_trace`
      - A `time_zero` step in `sample` mode, then box.
      - The note includes the sample-mode copy.
      - After Clear, it is gone.
    - `test_the_edge_fraction_follows_the_lines_time_zero`
      - With `time_zero(threshold=0.5)`, the dock passes `fraction=0.5` (monkeypatch
        `trace_hyperbola` to record its kwargs).
      - With no time zero step, 0.2.
  - **The existing test.** Update
    `test_velocity_mode_leaves_selection_drag_and_the_cutoff_handle_alone` in
    `test_plugin_velocity_fit.py` only if it now fails. It runs with velocity mode off, so it
    should pass as is.

- [ ] **Step 2: Run them to confirm they fail.**

- [ ] **Step 3: Implement the view** (spec §5, without Ctrl, which is Task 4).
  - In velocity mode a left press inside the radargram arms `_box_press`. Nothing is emitted on
    press any more.
  - A move beyond `QApplication.startDragDistance()` in x or y sets the box rectangle and
    repaints.
  - Release with a box emits `velocity_box_drawn` (normalised, clipped, times via
    `transform.time_of_y`, traces via `transform.trace_at`). Release without a box emits
    `velocity_point_requested` at the press position.
  - Paint the rectangle with a 1 px dashed `SELECTION_EDGE` pen while dragging.
  - A release lost mid-drag clears the box on the next move with no left button, as
    `_cutoff_grab` does.

- [ ] **Step 4: Implement the dock** (spec §6).
  - **Refusals, in this order:**
    1. the preview (`_refuse_velocity_edit_on_preview`);
    2. the difference view (`_effective_difference_index >= 0`);
    3. any enabled `migrate_fk`, `amp_abs`, `amp_square` or `amp_envelope` in
       `session.stack_for(working_key, insert=False).entries`.
  - **The trace.** Times on the line's clock are `retime_ns(rg.times_ns(), shown_zero, zero)`,
    using `_shown_radargram` and `_line_zero()`. Run under
    `QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)` with the restore in `finally`.
  - **The fraction** is the `threshold` of an enabled `time_zero` step in `first_break` mode,
    else 0.2.
  - **On success:**
    - the working dots become the traced dots, converted to the radar clock with `retime_ns(t,
      zero, 0.0)`;
    - `_just_saved = None`;
    - set `_dots_traced`;
    - `_update_velocity_fit()`.
  - **On a refusal or `ValueError`:** the dots are unchanged and `_box_note` holds the reason.
  - **The note.** `_update_velocity_fit` shows `_box_note`, then the sample-mode copy while
    `_dots_traced` and the stack's time zero is in `sample` mode, then the existing time-zero
    note, joined by a space and skipping empties.
  - **What clears them.** `_box_note` and `_dots_traced` clear on:
    - the next click or box;
    - Clear;
    - Save fit;
    - a line switch;
    - velocity mode off.

- [ ] **Step 5: Run the new file, `test_plugin_velocity_fit.py` and `test_plugin_profile_view.py`
  to confirm they pass.** Then run core + pure, lint and types. Commit and push.
  `git commit -m "feat(profile): drag a box in velocity mode to trace a hyperbola (#140)"`

### Task 4: The Ctrl/Cmd shortcut, tooltips and the guide

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (relay the signal)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Modify: `docs/guide/getting-started.md`
- Modify: `packages/nsgeo-qgis/tests/qgis/test_plugin_velocity_box.py` (or a new
  `test_plugin_velocity_shortcut.py`)

**Interfaces:**
- Consumes: Task 3's `velocity_mode_requested` on the view and dock; `act_velocity`,
  `_toggle_velocity_fit_mode`.
- Produces: `VELOCITY_TIP` (the copy above); `Plugin._on_velocity_mode_requested()`.

- [ ] **Step 1: Write the failing tests.** All use real `QTest` events with
  `Qt.KeyboardModifier.ControlModifier`.
  - `test_ctrl_click_with_velocity_off_turns_it_on_and_places_a_dot`
    - `act_velocity` is checked.
    - The strip is visible.
    - One dot.
  - `test_ctrl_click_in_pick_mode_switches_to_velocity`
    - Pick is unchecked, Velocity checked.
    - No pick is authored.
  - `test_ctrl_drag_traces_a_box`: on the planted line.
  - `test_ctrl_shift_click_does_neither`
    - No pick, no dot.
    - Neither action changes.
  - `test_shift_click_still_picks_with_velocity_on`: unchanged behaviour.
  - `test_ctrl_click_on_a_cut_places_nothing_and_says_why`
    - With a cut shown, velocity stays off.
    - No dot.
    - The message bar receives `VELOCITY_ON_CUT_TIP`.
  - `test_the_velocity_tooltip_mentions_the_box_and_the_shortcut`: `act_velocity.toolTip() ==
    VELOCITY_TIP` with a line open.

- [ ] **Step 2: Run them to confirm they fail.**

- [ ] **Step 3: Implement** (spec §5 press order, §7).
  - **The press order:**
    1. Shift without Ctrl, or pick mode without Ctrl: a pick.
    2. Ctrl without Shift: if velocity mode is off, emit `velocity_mode_requested`. Arm the
       velocity gesture only if `_velocity_mode` is now on. The plugin answers synchronously.
    3. Ctrl+Shift: falls through to the cutoff grab and the selection.
    4. Velocity mode: the velocity gesture.
    5. The cutoff grab and the selection.
  - **The plugin's `_on_velocity_mode_requested`:**
    - if `act_velocity` is enabled, check it and call `_toggle_velocity_fit_mode(True)`;
    - else, when a cut is shown, `message(VELOCITY_ON_CUT_TIP, Info)`;
    - else nothing.
  - Update `VELOCITY_TIP` and the guide's row to the copy above.
  - **The Mac.** Confirm by reading QGIS and Qt sources or docs that QGIS does not set
    `Qt.ApplicationAttribute.AA_MacDontSwapCtrlAndMeta`. Note the finding in the report. It
    cannot be tested here.

- [ ] **Step 4: Run the shortcut tests, then every velocity and profile test file, then core +
  pure, lint and types.** Commit and push.
  `git commit -m "feat(profile): Ctrl+click (Cmd+click on a Mac) for velocity points (#88)"`

### After Task 4 (the coordinator, not an implementer)

1. Run the whole-branch review.
2. Run the full QGIS tier.
3. Link the plugin into the QGIS profile `ns_geo_velocity_fixes`.
4. Publish the walkthrough of spec §11 as an Artifact with a `checks` db collection. Include
   every pending hand-fit disagreement from Task 2 for the author to rule on (§11 step 9).
5. Wait for the author's results before anything merges.
