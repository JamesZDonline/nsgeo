# nsgeo processing steps: edge cases, the migration test, trace stacking — design

Issues: #43, #40, #44, #42, #46, #125, #114. Session C of the issue-sessions plan. Branch
`nsgeo-step-edges`, from `origin/main` at `a3ca9f4`. Designed with the user on 2026-11-13.

After this change, a processing step never silently returns a blank line, a NaN line, or an
uncropped line because of a setting that cannot work or a single bad sample. A setting that cannot
work is refused with a plain message that names it. A bad sample damages only itself. A saved
project holding a setting that the new rules refuse still opens: that step is turned off and a note
says so. Migration gets the real-data test it merged without, and a new Trace stack step averages
each trace with its neighbours.

Almost all of it is in `nsgeo-core` (`packages/nsgeo-core/src/nsgeo/processing/` and
`nsgeo/project.py`). The plugin gains one thing: showing the load notes.

---

## 1. Why

The help-pages drafting (October) ran every step against odd values and found a family of silent
failures. Each one leaves the user looking at a wrong radargram with nothing to say why:

- A dewow or AGC window that rounds to one sample zeroes the line (dewow) or turns it into a pure
  ±target sign signal (AGC). Sliding background at 1 trace zeroes the line (#40).
- One NaN or inf poisons the rest of the axis through `running_mean`'s cumulative sum (#43).
- Settings that the form never produces but a project file or preset can hold, such as a
  float where an int belongs, NaN, a mode that does not exist or an unbounded gain, pass
  `build_step` and fail or misbehave later (#44).
- One NaN cancels Time zero's crop, and one inf moves it far down (#42).
- A band narrower than one frequency step returns zeros (#46).

The user's standing rule is real data first. Every fix here gets a test on a real line, not only on
a synthetic array.

Trace stacking (#114) is a field request: raise signal to noise along the line before slicing,
visible in the profile, without tying it to the slice cell size. It shares `running_mean` with three
of the bugs, which is why it is in this session.

The migration real-data test (#125) has been missing since M14 merged. Nothing downstream notices,
because the real files are gitignored and the test would skip on CI either way.

---

## 2. Starting state, measured on `main` (2026-11-13)

- `running_mean` (`processing/_util.py`) is a centred running mean with a shrinking window at the
  edges, built on `np.cumsum` along the axis. `window == 1` returns a copy. Callers: `dewow`
  (time), `gain_agc` (time, on the squared data) and `background_sliding` (traces).
- One NaN at `[100, 1]` on a random 512-row trace turns 420 rows of dewow output into NaN
  (re-run today).
- **#46 is half fixed already.** The leak through 0 MHz, where a taper ramp starting below 0 MHz
  passes part of DC, was fixed by #117 (PR #151): the low-side ramp is narrowed to start at 0 MHz,
  so DC is always removed. Re-run today: `low 100, high 500, taper 0.5` on a constant input leaves
  4e-4. The user's campus project holds exactly this case (bandpass 100–600 MHz at taper 0.25, on
  10 lines and its preset, all turned off).
- **The narrow-band case still exists, but narrower than the issue says.** #116 added zero padding
  to twice the trace, so on a 512-row line the frequencies are 4.51 MHz apart, not 9.97.
- **The plugin's Add-step dialog test-runs a new step on the line's first trace**
  (`ui/add_step_dialog.py`, `_validate`). It opens only for steps with a required setting (bandpass,
  migration, gain curve); every other step is added directly with its defaults
  (`ProcessingDock.add_step`). So a data-dependent refusal in bandpass or migration also fires on
  that one trace, which is often all zeros on a real line, recorded before the cart moved.
- **During slice preparation, a line whose stack refuses is named and skipped**; the other lines
  go ahead (`slices_engine.py`, around line 882).
- `load_site` (`project.py`) builds every line's stack and validates every preset through
  `StepStack.from_dicts`, and any `ValueError` becomes a `ProjectError` that stops the whole project
  opening (around lines 495 and 520).
- **No saved project of the user's holds a value the new rules refuse.** 13 project files were
  scanned on 2026-11-13: the campus, Nashville, Negley, Sunnyside, Site1 and Fort Negley projects,
  the walkthrough copies and the two hand-fit site copies. Every stack and preset uses Time zero
  (first break, 0.2), Time cutoff, Dewow 4 ns, Background mean, AGC (20 ns, target 1, epsilon
  1e-12), Bandpass (four bands), Migration and Gain curve. Sliding background, SVD and parametric
  gain appear nowhere. So §5's load repair protects other people's files and hand edits, not the
  user's.
- Record windows: every local line and every line in those projects is HS350US, 512 samples, 110.9
  ns (99.4 ns on Negley and Fort Negley), which leaves about 90–99 ns after time zero.

---

## 3. Decisions taken with the user

1. **A saved project holding a refused value still opens.** That step is turned off, the refused
   setting goes back to its default, and a note names the line or preset, the step, the setting and
   the old value. The old value is lost at the next save, but it is the value that was producing
   garbage. (User: "go with 2". The alternative, refusing to open with a clearer message, was
   declined because a project that opened yesterday should not stop opening after an update.
   AGC epsilon 0 is accepted by today's form.)
2. **Averages skip bad samples (#43).** When a running-mean window holds NaN or inf, its mean is
   the mean of the finite samples in it. The bad sample itself stays NaN or inf in the output of
   dewow, AGC and sliding background. A window with no finite samples gives NaN.
3. **Refuse and name the setting**, rather than returning zeros, NaN or an uncropped line, with
   two exceptions:
   - the bandpass taper keeps stopping at 0 MHz (§4.6), as it does today;
   - Time zero's first-break pick skips bad samples rather than refusing (§4.5).

   A third exception, keeping an all-zero line uncropped, was agreed and then dropped. The reason
   given for it (the Add-step dialog's first-trace test run) turned out not to apply to Time zero,
   so an all-zero line is now refused (§4.5). User: "go with your recommendation. Either way,
   there's no data."
4. **#125's diffractions** are Grid 2 FILE__033 fit-1 and FILE__032 fit-1 (§7). The user looked at
   both on radargrams, before and after migration, and confirmed them.
5. **No deep real case for #125.** A search of all 130 local lines found no diffraction below 40
   ns (§7.3). The user's call was to search and, failing that, rely on the synthetic depth sweep
   with the reason written into the test.
6. **At load, a Time zero step with a refused setting stays on** with that setting reset to its
   default, unlike every other step (§5). Turning Time zero off would move the clock under
   everything after it. The user expects this to be very rare, perhaps never.

---

## 4. The steps

### 4.1 `running_mean` (#43)

Same signature and shape contract: a centred running mean along `axis`, the window shrinking at
the edges exactly as today. That edge handling is what Trace stack (§6) and sliding background
both rely on.

New behaviour:

- **Non-finite samples are left out.** Each output is the sum of the finite samples in its window
  divided by their count. A window with no finite samples is NaN. A masked cumsum of the finite
  values plus a cumsum of the finite count does this in O(n). The count's cumsum is exact.
- **No precision loss at extreme dynamic range.** Today a value of 1e10 or more cancels against
  the cumulative total, so a quiet window after a loud sample can come out near zero. That made
  `gain_agc` exceed its own cap in a synthetic test. Required: a window's mean is correct to float
  rounding relative to the window's own magnitude, not the magnitude of everything before it on
  the axis. Builder's choice of method. Options include an exact windowed sum (sliding window view),
  or a cumsum with an error bound that falls back to the exact sum only where the bound is
  exceeded.
- **Speed budget.** Dewow and sliding background have to stay interactive. Measure today's time
  for `background_sliding` (200 traces) and `dewow` on a Grid 2 line (512 × ~1750) and stay within
  2× of it.

What each caller does with a bad sample, which follows from the formula:

| step | output at the bad sample | its neighbours |
|---|---|---|
| dewow | `x − mean` stays NaN or inf | finite, from the good samples |
| AGC | `x · target / max(rms, eps)` stays NaN or inf | finite, normal gain |
| sliding background | stays NaN or inf | finite |
| Trace stack (§6) | **the mean of its good neighbours** (the output *is* the average) | finite |

The last row is a consequence of decision 2, not a separate choice. A stack's output is the
average, so the bad sample is simply not in it. This is the builder's note to test, and the
reviewer's to check.

### 4.1a The other steps and bad samples (designer's call, from the builder check)

§1's promise ("a bad sample damages only itself") is kept for every step that averages, and the
steps that cannot keep it refuse instead of spreading NaN (decision 3):

- **Background mean** skips bad samples too. It is an average across traces, the same rule as
  decision 2. Today one NaN turns its whole row into NaN, and this step is in every saved stack
  and in #125's chain.
- **Bandpass, Envelope and SVD** refuse input that holds non-finite samples, with migration's
  message as the model (*"N of M traces hold samples that are not finite …"*), sharing one helper
  with migration. An FFT spreads one NaN along its whole trace, and SVD fails with an unclear
  `LinAlgError`.
- **Gains, Time cutoff, Trace stack and Migration** need nothing new. A gain multiplies, so a bad
  sample stays bad. Time cutoff crops. Trace stack averages (§4.1). Migration already refuses.

**Speed (§4.1) against accuracy:** accuracy is required, and speed is measured and reported, not a
hard test. The builder check measured today's `running_mean` on 512 × 1750 at 18 ms along time
(window 18) and 40 ms along traces (window 200). A plain finite-skipping version took 72 ms and
103 ms. A fast path for data with no bad samples is the expected way to stay near today's times.
Aim for roughly 100 ms per line or less, and record the measured numbers in the ledger.

### 4.2 One-sample windows (#40)

- **Dewow and AGC** refuse when the step runs, because the window in samples depends on the line's
  sample interval: `samples = round(window_ns / dt_ns)`. They need at least 2 samples. The check and
  the message share one threshold: the shortest accepted window is 1.5 × `dt_ns`. The message
  quotes that value rounded **up** to two decimals, and **the quoted value must itself be
  accepted**. Test that at the real `dt_ns` (0.21653 ns gives 0.33 ns).
  Example: *"Window 0.2 ns is one sample at this line's 0.217 ns sampling; use 0.33 ns or more."*
  Below half a sample (today's only refusal) the same message applies. Today's wording,
  "nothing to remove", is wrong at one sample, where everything is removed. It goes.
- **Sliding background**: the schema minimum of `window_traces` becomes 2, so it is refused at build
  (and repaired at load, §5). The `< 1` check in `apply` becomes `< 2`, with the same wording as
  the schema refusal, or is removed if `build_step` is the only way in. Builder's call.
- These run-time refusals use the same path every run-time refusal uses today (migration's
  are the model): the stack raises `ValueError` and the panel shows it.

### 4.3 Settings validation (#44)

All of it in `_validate_params` (`base.py`), through one per-setting check that the load repair
(§5) also uses:

- **choice:** the value must be one of `spec.choices`.
- **int:** an integral number (Python `int` or a numpy integer), not a `bool`, not a float (even
  `200.0`), not a string. This is the builder's hazard: plugin code may hand in numpy ints, for
  example a `sample` taken from a pick, and those must pass.
- **float and time:** a real number (int or float, numpy included), not a `bool`, not a string, and
  finite. NaN and inf are refused.
- **curve:** gains the checks `GainCurve.__init__` makes today (at least two points, each a pair
  of numbers, all finite), so the load repair (§5) sees them. A NaN dB value currently passes
  `_validate_params`, because comparisons with NaN are false.
- Bounds are checked after the type, as today.

New and changed bounds. The values are the builder's starting point and the designer's call; the
user may adjust them when reading this:

| step.setting | today | new | why |
|---|---|---|---|
| `background_sliding.window_traces` | min 1 | min 2 | #40 |
| `gain_agc.eps` | min 0 | must be > 0 | 0 gives NaN on all-zero windows (1,852 NaN samples on FILE__007) |
| `gain_agc.target` | min 0 | must be > 0 | 0 silently zeroes the whole line, the same family as #40 (designer's addition) |
| `gain_parametric.alpha` | none | −1 to 1 /ns | default 0.05; alpha 8 gave 66,910 inf on FILE__007; ±1 keeps a 110 ns record finite (e¹¹¹ ≈ 1.6e48) |
| `gain_parametric.exponent` | none | −10 to 10 | default 1; 111¹⁰ ≈ 2.8e20 stays finite |
| `background_svd.n_components` | min 0 | 0 to 20 | the step removes a few leading components; the line's own rank is still checked when it runs |

"Must be > 0" needs an exclusive minimum, which `ParamSpec` cannot express today. Add one, for
example a `min_exclusive` flag, so the bound stays declared on the schema where
`test_every_declared_bound_is_enforced_by_build_step` can find it. That test currently asserts
that "the bound itself is allowed", so it needs the exclusive case. The message wording follows
the existing pattern: *"step 'gain_agc': eps must be > 0.0, got 0.0"*.

`param_form.py` is left alone. #44's comment ("a bad saved mode shows as the default") can no
longer arise. A bad mode is refused at build, and at load it is reset to the default with the step
turned off (§5), so the form showing the default is now the truth. The builder confirms this with a
test that loads such a project and reads the step's `mode`. The form itself is not changed.

Bandpass `apply` has `< 0` checks for `low_mhz` and `taper_frac` that `build_step` makes
unreachable. Builder's call: remove them, or keep them with wording that agrees with the schema's.

### 4.4 AGC

Covered by §4.1 (bad samples, precision), §4.2 (one-sample window) and §4.3 (eps > 0, target > 0).
The output cap is `|out| ≤ target · sqrt(samples in window)`. It must hold on the issue's ≥ 1e10
case. That is the precision test.

### 4.5 Time zero's first break (#42)

`first_break_row` builds its envelope as the mean over traces of `|data|`, **skipping non-finite
samples** (decision 2). A row with no finite sample has no envelope value and cannot be picked. The
peak is the largest finite envelope value. Then, as today: `peak <= 0` (or no finite row at all)
gives 0, and the first row reaching `threshold × peak` is the pick.

So one NaN or inf no longer changes the cut. On FILE__007, a NaN or an inf at `[300, 5]` crops the
same 49 rows as the clean line.

**An all-zero line is refused** by `TimeZero.apply` in first-break mode, where today it silently
crops nothing. Example: *"Time zero found no first arrival: every sample on this line is zero."*
The same applies when no row has a finite sample. The refusal lives in `apply`, not in
`first_break_row`, which keeps returning 0 for "no signal" as today. Other code calls that function
directly: `first_break_ns`, and the hyperbola tracer branch, which imports it and may call it on a
crop. During slice preparation such a line is named and skipped (§2).

`first_break_ns` follows. The tracer's results on finite data are unchanged.

### 4.6 Bandpass (#46)

- **A band with no frequency inside it is refused** when the step runs: when the mask built over
  the padded FFT's frequencies is zero everywhere. The message names Low, High and the line's
  frequency step, and says how wide the band must be to be certain of one frequency:
  *"Bandpass 300–302 MHz holds no frequency on this line, whose frequencies are 4.51 MHz apart.
  Make High − Low at least 4.51 MHz."* (A closed band at least one step wide always holds one.)
- **The taper keeps stopping at 0 MHz** (exception 1). No change; the test that pins it stays.
- NaN and inf in Low, High and Taper are refused at build (§4.3). Today they give all-zero or
  all-NaN output.

---

## 5. Loading a project with a refused setting

In `load_site`, for every line's stack and every preset, each step entry goes through a repair
before `StepStack` is built:

- **Unknown step name, or unknown setting name** → `ProjectError`, as today. These are what a file
  saved by a *newer* build looks like, and dropping them would lose data at the next save.
- **A known setting whose value is refused** (wrong type, non-finite, out of bounds, not a choice):
  - if the setting has a default, the value is replaced by the default, the step is turned off
    (`enabled: false`), and a note is recorded;
  - if it has no default (bandpass Low or High, gain curve points), the step is **removed** and the
    note records what it held, so the user can re-add it.
- **A missing required setting** is handled like a refused setting with no default: the step is
  removed, with a note. Today this is a `ProjectError`; it falls under decision 1's "still opens".
- **Time zero is the exception (decision 6).** A refused Time zero setting is reset to its default
  and the step **stays on**. Its note says so. Turning it off would put the record back on the
  radar clock (about −11 ns at the top). Migration would then refuse the line, and Time cutoff and
  gain-curve times would land about 11 ns from where they were set.
- One note per affected step, naming all of its refused settings.
- **After repair, each step is test-built.** If its constructor still refuses, for a rule that does
  not live in the per-setting check, the step is removed with a note. "Still opens" then holds for
  every refusal, not only the ones the check knows about.
- **A refused value in a setting the current mode ignores** (parametric gain in power mode with
  alpha 8, say) is handled like any other: the setting is reset, the step is turned off, and there
  is a note. After the reset, turning the step back on gives exactly the old output, because the
  setting was unused. Notes for steps turned off end by telling the user to check the step and turn it back on; notes for removed steps end by asking the user to add the step again; the Time zero note says the step stays on, and the already-off note says it stays off.
  This keeps the check free of any knowledge about modes. (Designer's call, from the builder
  check.)

Notes:
- They are collected on the loaded site, for example `site.load_notes: list[str]`. They are not
  saved.
- Each names where (line file name or label, or preset name), the step's title, the setting's
  label, the old value, and what happened. Example: *"Line FILE__003.DZT (grid Grid2): Automatic gain control is
  turned off. Its Epsilon was 0.0, which must be greater than 0; it is now 1e-12."*
- Presets are stored repaired in `site.presets`, so applying one later works. Every other place
  that rebuilds steps from saved dicts reads these repaired copies: the session's preset and
  apply-to-grid paths and the slices engine's preset stacks. The builder confirms there is no
  other saved-dicts path, cubes included.
- `StepStack.from_dicts` stays strict. Code that builds a bad stack itself still fails loudly.

**The plugin** shows the notes when a project opens: a message-bar warning summarising how many
steps were turned off or removed, with each note in the log. Nothing else changes. The repaired
stacks reach the file at the next save, like any other edit. Until then, reopening the project
shows the notes again.

---

## 6. Trace stack (#114)

A new step in a new module, `processing/trace_stack.py`. Not `stack.py`, which holds `StepStack`.

- `name = "trace_stack"`, `title = "Trace stack"`, `group = "Filters"`, `order = 3` (after Dewow
  and Bandpass).
- One setting: `window_traces`, int, label "Window", unit "traces", default 3, min 1. Help text
  along the lines of *"Averages each trace with its neighbours: this many traces in all, centred on
  it. 1 leaves the line unchanged."*
- `apply`: `running_mean(rg.data, window_traces, axis=1)`. Window 1 is the identity. A window
  longer than the line is capped at the line's length, as in sliding background. Each trace then
  averages the traces within half that window on either side, which is the whole line only at its
  middle. An even window sits half
  a trace off-centre, as sliding background's does today; not refused.
- **Keeps the trace count and the time axis.** Picks, velocity fits, slice binning and the profile
  all index traces as they are (#114 explains why a decimating stack is a different step).
- **Difference view** works because the shape is unchanged. It shows what the stack removed.
- The Add-step dialog's first-trace test run is the identity on one trace, so it always passes.
- Registration needs: a `TITLES` entry and the Filters list in `tests/test_step_titles.py`; the
  params and bound in `tests/test_schema.py`. The Add menu lists it without any plugin code change
  (`test_plugin_processing_dock.py:66`). The pinned menu layout in the same file
  (`test_add_menu_is_grouped_in_processing_order`, `("Filters", ["dewow", "bandpass"])`) gains
  `trace_stack`.

---

## 7. The migration real-data test (#125)

### 7.1 The diffractions

Both are on Nashville City Cemetery 2023 **Grid 2**, already local as `tests/data/local/grid2`
(`GRID2_LINES`). They come from the user's saved hand fits (gitignored, in the hyperbola-tracer
worktree's `tests/data/local/hand-fits/site-1.nsgeo.json`). The test carries the numbers as
**literals** with that provenance in a comment, so it does not depend on those files.

| | FILE__033 fit-1 | FILE__032 fit-1 |
|---|---|---|
| apex trace | 1375 (of 1751) | 386 (of 1748) |
| apex time, radar clock | 19.947 ns (fit saved with `zero_ns` 0) | 19.363 ns (`zero_ns` 0) |
| apex time after default Time zero | **20.42 ns** (Time zero sits at −0.476 ns radar) | **19.84 ns** |
| velocity | 0.1027 ± 0.0014 m/ns | 0.1061 ± 0.0018 m/ns |
| rms, dots | 0.136 ns, 9 | 0.146 ns, 8 |
| depth | ≈ 1.05 m | ≈ 1.05 m |
| nearer line end | 6.25 m | 6.4 m |

Look the files up by path (`DATA / "grid2" / "FILE__033.DZT"`), never by stem (#141).

### 7.2 What it asserts

Processing: `time_zero` → `dewow` → `background_mean` → `migrate_fk(velocity_m_ns=v)`. Background
removal is the designer's addition to the spec's "time_zero then migrate_fk". It takes out the flat
banding that otherwise dominates any energy window around a 20 ns apex.

For each diffraction:

- **Peak trace:** the largest |amplitude| in a small search box around the apex (about ±0.3 m and
  from 1 ns above to 4 ns below the apex time) lies within a couple of traces of the apex trace.
- **Peak time:** the peak lies a measured offset *below* the hand apex. The dots sit on the top edge
  of the band; the strongest migrated lobe is the middle of it, about 1–2.5 ns lower. The builder
  measures the offset and asserts a window around it, not the hand apex time itself.
- **Windowed energy:** the same measure as `tests/test_steps_migration.py`'s `_focus` (energy in a
  17 × 17 box around the peak as a fraction of a total), with the total taken over a local window
  (about ±10 ns × ±1.5 m) rather than the whole line. Measured on 2026-11-13 with that window:
  FILE__033 0.024 unmigrated → 0.079 migrated, FILE__032 0.020 → 0.047. Assert a **literal**
  fraction between the two, chosen from the builder's own measurement, and that the migrated value
  is several times the unmigrated one.
- **Velocity sensitivity:** the focus at the fit's velocity beats the focus at 0.6× and 1.6× of
  it. Measured: FILE__033 0.047 / 0.079 / 0.038, FILE__032 0.035 / 0.047 / 0.017. (FILE__032
  focuses best a little below its fitted velocity: 0.050 at 0.9×.)

The real data is gitignored, so the test skips on CI. Share `_focus` rather than copying it.
Builder's call how.

### 7.3 No deep case, and why

The spec and the issue asked for a case deeper than 50 ns, because the defect the M14 review found
lived there. None exists in the local data:

- After Time zero, dewow and background mean, the median signal below 50 ns is 1.3–1.6× the noise
  in the 80–90 ns band. This holds on the campus lines, Grid 1 and Grid 2. Grid 2 by band: 20–30
  ns 15×, 30–40 ns 4.4×, 40–50 ns 2.6×, 50–60 ns 1.4×.
- A search of all 130 local lines for a spot that migration focuses, 40–85 ns, at 0.07, 0.085 and
  0.10 m/ns, found 25 places, almost all at 41–52 ns. The top five were drawn and all are short
  flat or gently dipping layers that migration bends into smiles, not diffractions. The same search
  finds FILE__033 and FILE__032 at their apex traces when pointed at 12–35 ns.

The test says so in its docstring, with these numbers, and points to the synthetic depth sweep
(`test_a_point_diffractor_collapses_to_its_apex`, 0.5–3.5 m at the real lines' sampling) as the
deep coverage.

---

## 8. Testing

Real lines first: every fix gets a test on `FILE__007` (campus) or a Grid 2 line, using
`tests/real_data.py`'s lists, plus synthetic tests only where they mirror the real case. The issues'
measured cases are the starting list:

- **#43:** a NaN at `[100, 300]` on FILE__007. With dewow, AGC and sliding background, only that
  sample is NaN in the output, and its neighbours equal a direct finite-only windowed mean. The
  same for an inf. The AGC cap holds on a ≥ 1e10 burst. `running_mean` matches a direct windowed
  mean, with the shrinking edges, on random data with NaN and inf sprinkled in.
- **#40:** on FILE__007 (Δt 0.21653 ns), dewow and AGC at 0.1, 0.2 and 0.3 ns are refused with the
  message; the quoted 0.33 ns is accepted. Sliding background at 1 is refused at build.
- **#44:** each case from the issue's comments refused by `build_step`, with the message naming
  the setting: the `"bogus"` modes, floats, bools and strings for ints, NaN, inf and strings for
  floats, the new bounds. Numpy ints are still accepted for ints.
- **#42:** FILE__007 with one NaN, and separately one inf, at `[300, 5]` crops 49 rows, as clean.
  An all-zero radargram is refused by Time zero with the message, while `first_break_row` on it
  still returns 0.
- **#46:** a band narrower than one step on FILE__007 is refused with the step size in the
  message; a band exactly one step wide runs.
- **Load repair:** a project with AGC epsilon 0 on a line and sliding background 1 in a preset
  opens. Both steps are off with defaults, there are two notes, and a save and reload keeps the
  repair. A bad parametric-gain `mode` comes back as the default with the step off. A Time zero
  with `sample` 12.0 comes back with the default and **still on**. Bandpass with NaN Low is
  removed with a note. A gain curve with a NaN point is removed with a note. An unknown step or
  setting still raises `ProjectError`.
- **Bad samples in the other steps (§4.1a):** on FILE__007 with one NaN, background mean leaves
  only that sample NaN, and bandpass, envelope and SVD refuse with the message.
- **Trace stack:** a constant section is unchanged; window 1 is the identity; shape and time axis
  are unchanged. On FILE__007 and a Grid 2 line, the variance of the trace-to-trace difference
  drops and a strong flat reflector's time does not move. `StepStack.difference` works across it.
- **#125:** §7.
- **Plugin:** opening a project with a refused value shows the warning and the step is off in the
  Processing panel. Run the **QGIS processing tests as well as core**: tighter validation can break
  QGIS tests that build steps with odd values.

Mutation testing follows the usual rules (`PYTHONDONTWRITEBYTECODE=1`, never in the tree the
branch commits from). Worth targeting: the finite mask in `running_mean`, the 1.5-sample threshold,
the exclusive minimum, and the empty-mask check in bandpass.

---

## 9. Manual checkpoints

Deploy the branch to its own QGIS profile for a short walkthrough. Both of these are gates before
any merge decision:

1. **Trace stack on a real line**, including the Difference view, at a couple of window sizes.
2. **Opening a project that holds a now-refused value.** A copy of a real project, hand-edited
   to hold AGC epsilon 0 on a line and sliding background at 1 trace in a preset. It opens, both
   steps are off, and the note names them.

---

## 10. Around this branch

- **Help pages.** Pages for dewow, sliding background, the gains, time zero and bandpass are on the
  unmerged `nsgeo-help-pages` branch (untouched since 2026-10-22) and describe today's behaviour.
  Do not edit that branch. The PR lists every settings change for whoever revives it:
  - dewow and AGC need a window of at least 1.5 samples;
  - sliding background needs at least 2 traces;
  - AGC epsilon and target must be above 0;
  - parametric gain alpha ±1 /ns, exponent ±10;
  - SVD at most 20 components;
  - choice, int and float settings are type-checked, and NaN and inf are refused;
  - averages skip bad samples, including background mean's;
  - bandpass, envelope and SVD refuse data holding NaN or inf;
  - Time zero's first break skips bad samples, and Time zero refuses an all-zero line;
  - bandpass refuses a band holding no frequency;
  - refused saved settings are turned off with a note when a project opens (Time zero's are reset
    and stay on);
  - the new Trace stack step.
- **The hyperbola tracer** (`nsgeo-hyperbola-tracer`, built, not merged) runs the user's hand fits
  through processing steps and imports `first_break_row`. Whichever branch merges second reruns the
  tracer's hand-fit tests.
- No other branch touches `nsgeo/processing/` (checked 2026-11-13). Four touch `project.py`:
  `nsgeo-m16` and `nsgeo-m16-b` in the slice-source helpers, and `nsgeo-m17-gps` and
  `nsgeo-m19-mag` in `load_site` itself, a few lines from the stack and preset code (a `crs` key;
  mag files and views). Expect small textual conflicts there, nothing semantic.
- When this merges, close #43, #40, #44, #42, #46, #125 and #114.

---

## 11. Approaches

- **Chosen: fix in the core, repair at load only.** Refusals live in the steps and in
  `_validate_params`. One per-setting check serves `build_step` and the loader. Only `load_site`
  repairs; everything else stays strict. The plugin only displays notes.
- **Rejected: make `StepStack.from_dicts` lenient everywhere.** Every caller would silently turn
  off steps, including code that builds a bad stack by mistake, which hides bugs instead of
  reporting them.
- **Rejected: handle it in the plugin.** The core is the single funnel for every front end
  (`_validate_params`' docstring), and the plugin does not parse the project file.
- **Rejected for the load question: keep refusing, with a clearer message.** The user chose to keep
  projects opening (decision 1).

---

## 12. Out of scope

- A decimating stack, or a Trace stack window in metres (#114's notes).
- Data-dependent bounds at build time, such as the SVD rank or a window in samples. They stay
  run-time checks.
- Any change to `param_form.py`, or to the help-pages branch.
- Time zero by eye (#158) and the other Time zero follow-ups.

---

## 13. Left to the builder

- `running_mean`'s exact method, within §4.1's accuracy and speed requirements.
- Wording of messages, within the examples' content: name the setting, the value and what to do.
- The exclusive-minimum mechanism on `ParamSpec`.
- Whether bandpass's unreachable `< 0` checks stay.
- Where the load notes live on the site object, the note wording, and how the plugin summarises
  them.
- How `_focus` is shared, and #125's tolerances, from measurement.
- The task split. The plan is 3–4 tasks; the session plan suggests size M.
