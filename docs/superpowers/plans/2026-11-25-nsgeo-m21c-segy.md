# M21c: SEG-Y lines from RadExplorer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SEG-Y lines exported by RadExplorer (`.sgy` / `.segy`) import onto a grid, draw, process, slice and reopen exactly as DZT, DT1 and MALÅ lines do. They read as recorded: the static shift RadExplorer applied is undone, and time zero sits where the direct wave is. SEG-Y from any other software is refused by name.

**Architecture:** One new reader module, `nsgeo.io.segy`, and one registry entry. This is the second run of the spec's §7 checklist, and the first with float samples, so it also tests C5's promise that nothing downstream assumes integer amplitudes. The plugin changes nothing but the strings that list the formats, unless that promise turns out to be broken.

**Tech Stack:** Python 3.9+ numpy core (`packages/nsgeo-core`); QGIS plugin on QGIS 3.44 / PyQt5 and 4.2 / PyQt6 (`packages/nsgeo-qgis`); pytest.

**Spec:** `docs/superpowers/specs/2026-11-24-nsgeo-radar-formats-design.md`. Read in particular:
- §2, SEG-Y, **rewritten 2026-11-25**: the files turned out to be static-shifted, their marks don't match the text header, and time zero is settled.
- §4: C5–C7, C9 and C12.
- §7.
- **§15: the calls this plan makes.** Three of them revise C5, C6 and C7.

§13 and §14 still hold.

**Branch:** `nsgeo-m21c-segy` in `.worktrees/nsgeo-m21c-segy`, branched from `nsgeo-m21b-mala` (M21b, which stacks on M21a). Both walkthroughs are still pending.
- If either merges first, rebase onto `origin/main`.
- If either changes after its walkthrough, merge `nsgeo-m21b-mala` in before the next task.

## Global Constraints

- **Core:** numpy and the standard library only. EBCDIC decodes with the standard `cp500` codec.
  - Runtime Python 3.9: no `kw_only` dataclasses, no `zip(strict=)`, no `match`, no PEP 604 unions outside annotations.
  - `from __future__ import annotations` heads every new file.
  - `tests/test_boundary.py` stays green.
- **DZT, DT1 and MALÅ behaviour does not change.** Their tests pass **unedited**, with four exceptions: the assertions that spell out the full list of formats. Those gain SEG-Y and nothing else. They are:
  - `test_pure_lookup.py` lines 623 and 655
  - `test_plugin_import_dialog.py` line 367
  - `test_formats.py` line 147

  Any other edit to an existing test means the seam leaked: stop and report.
- **No schema change.** A SEG-Y line saves as its data file's path and placement. Its header is re-read on open.
- **No `cast` and no `type: ignore` for a header.** The SEG-Y reader joins the registry through `_checked`.
- **Plugin:** Qt only through `qgis.PyQt`, and every Qt slot guards its own body. Code and tests run on QGIS 3.44 and 4.2. Local QGIS is 3.44 only, so check CI's `plugin-qgis (qgis/qgis:4.2)` job after every push.
- **Privacy:**
  - No coordinate and no site name in any committed file, test, docstring, commit message or report.
  - The sample files' names carry the site, so in anything committed the survey is only `segy` and its lines are only `LINE01`–`LINE18`.
  - Every trace header holds geographic fixes in bytes 229–236. Nothing in this plan reads those bytes, and no test prints or asserts them.
  - `SegyHeader` keeps no X or Y: only the step and the jump count (§15).
- **Shared-worktree safety:** reviewers and mutation probes work on a scratch copy, never on this worktree. Set `PYTHONDONTWRITEBYTECODE=1` for every run. Touch no other worktree, M21a's and M21b's included.
- **Commits:**
  - This laptop has no git identity. Commit with `git -c user.name=… -c user.email=…`, taking both from `git log -1 --format='%an%n%ae' origin/main`. Never use `git config`.
  - End each message with a `Co-Authored-By:` line naming the model that wrote it.
  - Push each commit to `origin nsgeo-m21c-segy` as it is made.

### Copy (exact)

- **The format's name** (`SegyHeader.format_name`, the picker, the facts line): `SEG-Y`.
- **Grid mode's picker:** `lookup.radar_file_filter()` returns exactly
  `All radar files (*.dzt *.DZT *.dt1 *.DT1 *.rd3 *.RD3 *.rd7 *.RD7 *.sgy *.SGY *.segy *.SEGY);;GSSI DZT (*.dzt *.DZT);;Sensors & Software DT1 (*.dt1 *.DT1);;MALÅ (*.rd3 *.RD3 *.rd7 *.RD7);;SEG-Y (*.sgy *.SGY *.segy *.SEGY);;All files (*)`.
  This comes from the registry, with no code change in `lookup.py`.
- **Unsupported extension:** `… it reads .dzt, .dt1, .rd3, .rd7, .sgy, .segy`, also from the registry.
- **SEG-Y errors** (`SegyError`). Traces are numbered from 1 in every message.
  - `{size} bytes: too short to be a SEG-Y file`
  - `not a RadExplorer SEG-Y, the only kind nsgeo reads yet: its text header begins {first!r}`, where `first` is the text header's first 60 characters, stripped, with control characters removed.
  - `little-endian SEG-Y is not read yet`
  - `its samples are in format {code}: only IEEE float (format 5) is read yet`
  - `its binary header gives {what} as {n}, which is not a whole number above 0`, where `what` is `the sample interval` or `the samples per trace`
  - `extended text headers are not read yet`
  - `its {n} bytes of traces are not whole traces of {record} bytes: refusing to guess where they start`
  - `trace {i} has {n} samples, not the {ns} its binary header gives: SEG-Y with traces of different lengths is not read yet`
  - `trace {i} gives a {a} ps sample interval, not the {b} ps its binary header gives: refusing to guess which is right`
  - `its traces start at different delays, {a:g} to {b:g} ns: not read yet`
  - `trace {i}'s samples start {lead} samples down, but its static of {s} ns is {expected:.0f} samples: refusing to guess which is right`
  - `its samples changed after its header was read`
  - `cannot read it: {exc}`
- **SEG-Y notes** (`RadarHeader.notes`, with no `"; "` in any):
  - `its traces carry a static shift of up to {max:g} ns: read as recorded, without it`. This note goes on every line with a non-zero static.
  - `its trace coordinates jump at {n} traces, the largest {m:.3g} m at trace {i}: placed at an even {step:.4g} m`, where `i` is the number of the trace after the largest jump.
  - `its trace coordinates are in arc seconds, not metres along the line: place it by hand`
- **Facts line:** `From this file's header: SEG-Y · antenna ? · sample interval 0.4060 ns · …`. It comes from M21a's `header_facts`, unchanged.
- **GPS mode:** unchanged. A SEG-Y file that reaches it through *All files* gets M21a's `no GPS log read for this format yet`.

### Before Task 1: the data (coordinator, once)

The virtualenvs from M21a (`.venv` and `.venv-qgis` in the main checkout) are reused. Create this worktree's own `.venv-tools` the same way as M21b's.

1. **Copy the survey.** Put the 18 `.sgy` files from `~/Documents/GitHub/sample_data/SEGY/` into the **main checkout's** `packages/nsgeo-core/tests/data/local/segy/`.
   - Rename them `LINE01.sgy` … `LINE18.sgy`, in the sorted order of their original names.
   - Copy each `.sgy.vm` beside its line as `LINE01.sgy.vm` and so on: the reader must ignore them.
   - Keep the name mapping only in your head or in the scratchpad, never in a committed file.
   - `git status` in the main checkout must show nothing new afterwards.
2. **Link it in.** Symlink `segy` into this worktree's `tests/data/local/`, beside the entries M21b linked. Link M21b's entries too if this worktree lacks them. `ls -L` must show real files.

### Verification commands (from the worktree root)

These are M21b's commands, with its tool paths. A real-data test that skips has validated nothing: the skip count must not rise, and the SEG-Y real-data tests must **pass, not skip**, locally.

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider -p no:xonsh -rs`
- **qgis, the files a task touches:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src packages/nsgeo-qgis/scripts/qgis_tests.sh <files> -q -p no:cacheprovider`
- **qgis, real data:** `… qgis_tests.sh packages/nsgeo-qgis/tests/qgis -m real_data -q -p no:cacheprovider -rs`
- **lint:** `.venv-tools/bin/ruff check . && .venv-tools/bin/ruff format --check .`
- **types:** `.venv-tools/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo`
- **Baseline on this laptop.** Anything beyond these failures is a regression:
  - `grid2` fails, because its links are broken here: 9 failed and 9 errors in core, and up to 6 in the QGIS real-data tier.
  - `test_plugin_cut_sections::test_an_open_cut_shows_the_message_when_its_engine_goes_away` fails here, on `main` too, and passes in CI.

## Review Focus

These are the inputs most likely to bite. Each is pinned by a test in the task that owns the code.

1. **Two byte orders in one file.** Everything is big-endian except the geographic flag (bytes 227–228) and the marks (237–240), which are little-endian. Read big-endian, the flag is 256, so a reader that counts `== 1` big-endian finds no geographic traces. (Task 1)
2. **Picoseconds.** The binary header's 406 is 0.406 ns, and the delay's 11766 is 11.766 ns. Read as standard SEG-Y microseconds, they are a million times too long. (Task 1)
3. **The static undo** (§15):
   - Each trace starts at its first non-zero sample. The line's sample count is the longest first-to-last non-zero run.
   - The static only cross-checks the shift. A synthetic trace whose recorded data truly begins with exact zeros must be refused, not cut.
   - An all-zero trace reads as zeros.
   - A file with no statics reads as stored, zeros included.
   - On the real files every sample of every line is non-zero after reading, which proves the undo lines up all 18. (Task 1)
4. **Trace 0's bogus static** needs no special case. A synthetic file with one 800 ns static and the rest under 50 ns reads at the short length, with trace 0 aligned like the others. (Task 1)
5. **Time zero's sign.** `position_ns` is `−delay`. On the real files the mean trace's first break falls between −1.0 and +3.5 ns. With the wrong sign it would be near +24. (Task 1)
6. **Spacing:**
   - The step is the mean of the regular steps, 68.44 mm. The median (68) is not the step, because the coordinates are integer millimetres.
   - LINE04's two jumps give the copy's note, and the line still gets 1 / 0.06844 traces per metre.
   - No X or Y value reaches a header field, a note or an error. (Task 1)
7. **What is refused:**
   - A SEG-Y without `RadExplorer` in its text header, and one with an ASCII text header without it.
   - A DZT renamed `.sgy`, and a file shorter than 3,600 bytes.
   - Little-endian binary headers, format codes other than 5, varying trace lengths, intervals or delays, and extended text headers.

   Each gets its own message from the copy. (Task 1)
8. **Float samples downstream (C5).** A SEG-Y line's `read_samples` is `float32`. It must go through processing, slicing and a cut with no integer assumption. The planning grep (`np.iinfo`, integer `dtype` checks, `astype(np.int…)`, `//` on amplitudes) found none on amplitudes; the integer dtypes in `slices/` are cell indices and counts. The builder reruns the grep and pins the result with tests. (Tasks 1 and 2)

---

### Task 1: The SEG-Y reader

**Files:**
- Create:
  - `packages/nsgeo-core/src/nsgeo/io/segy.py`
  - `packages/nsgeo-core/tests/segy_data.py` (the synthetic writer)
  - `packages/nsgeo-core/tests/test_segy.py`
  - `packages/nsgeo-core/tests/test_segy_real_files.py`
- Modify:
  - `packages/nsgeo-core/src/nsgeo/io/formats.py`: the SEG-Y entry and `SEGY_NAME`
  - `packages/nsgeo-core/src/nsgeo/io/__init__.py`: export `SegyError` and `SegyHeader`
  - `packages/nsgeo-core/README.md`: their rows, and the `nsgeo.io` lead line names SEG-Y
  - `packages/nsgeo-core/tests/real_data.py`: `SEGY_DIR` and `SEGY`
  - `packages/nsgeo-core/tests/data/local/README.md`: `segy/` in the layout, described by its contents, not its site, and noting that the files are renamed
  - `packages/nsgeo-core/tests/test_formats.py`: line 147, plus SEG-Y's empty `prefer`

**Interfaces:**
- **Registry.** `RadarFormat(SEGY_NAME, (".sgy", ".segy"), segy.read_header, _segy_trace_count, _segy_read_samples)` is registered last, with `prefer` left empty. `SEGY_NAME = "SEG-Y"`.
- **Error.** `class SegyError(RadarFileError)`.
- **Header.** `@dataclass(frozen=True) class SegyHeader(RadarHeader)`, with `format_name = "SEG-Y"`. Its own fields:
  - `variant: str`: `"RadExplorer"`, the only one
  - `n_traces: int`: from the file size
  - `stored_samples: int`: per trace, in the file
  - `delay_ns: float`
  - `max_static_ns: float`: 0 when no trace has a static
  - `step_m: float`: 0 when there is none
  - `jumps: int`
  - `geographic_traces: int`: traces whose little-endian flag in bytes 227–228 is 1
- **`read_header(path) -> SegyHeader`**, in this order:
  1. A size under 3,600 bytes raises the short-file message.
  2. Text header (bytes 0–3199): decode as `cp500`, or as Latin-1 when byte 0 is `0x43` (ASCII `C`). If the text does not contain `RadExplorer`, raise the not-RadExplorer message.
  3. Binary header, big-endian (file offsets 3200–3599):
     - The format code at 3224 must be 5. If it is not, but its little-endian reading is 1–16, raise the little-endian message. Otherwise raise the format message.
     - The interval at 3216 (ps) and the samples per trace at 3220 must be above 0.
     - The extended-text-header count at 3504 must be 0.
  4. `record = 240 + 4 × ns`. The bytes after 3,600 must be a positive whole number of records. `n_traces` is their count.
  5. **Read the whole file** with `np.fromfile` and a structured dtype: 240 header bytes plus `ns` `>f4` per trace. Do not use `memmap`: on Windows it holds the file open. The trace-header fields, at 1-based SEG-Y byte positions, all big-endian except the flag:
     - 71–72: coordinate scalar
     - 73–76 and 77–80: X and Y
     - 89–90: coordinate units
     - 101–102: static, ns
     - 109–110: delay, ps
     - 115–116: samples
     - 117–118: interval, ps
     - 227–228: geographic flag, **little-endian**
  6. Every trace's samples and interval must equal the binary header's, or raise the first offending trace's message. The delay must be the same on every trace.
  7. **Statics** (§15). When any static is non-zero:
     - Each trace's `lead` is its first non-zero sample, and its run ends at its last.
     - For each trace with any non-zero sample, `|lead − static / dt_ns|` must be at most `4 + 0.01 × static / dt_ns`.
     - `n_samples` is the longest run.
     - `max_static_ns` is the largest static, and the static note is added.

     When no static is non-zero, `n_samples = ns` and nothing is shifted.

     Put this in one private function shared with `read_samples`.
  8. **Time.** `dt_ns = interval / 1000`, `range_ns = n_samples × dt_ns` and `position_ns = −delay / 1000`.
  9. **Spacing** (§15):
     - Coordinate units 2 give 0 traces per metre and the arc-second note.
     - Otherwise each coordinate is multiplied by the scalar (0 counts as 1, a negative value divides). The steps are `hypot(ΔX, ΔY)` between consecutive traces.
     - With fewer than 2 traces, or a median step of 0 or less, the result is 0 with no note.
     - Otherwise a step is regular when it is within 5 % of the median. `step_m` is the mean of the regular steps, and `traces_per_metre = 1 / step_m`.
     - `jumps` counts the irregular steps. If there are any, add the jump note, naming the largest.
  10. **The rest:** `n_channels = 1`, `epsr = 0.0`, `antenna = ""` and `not_a_profile = ""`.
- **`trace_count(path, header) -> int`** stats the file and repeats step 4's count. It must equal `header.n_traces`, or raise the step-4 message.
- **`read_samples(path, header=None) -> np.ndarray`** returns `float32` of shape `(1, n_samples, n_traces)`.
  - Read as in step 5 and convert from `>f4` to native `float32`.
  - When the header has statics, move each trace up by its `lead`, recomputed by step 7's function. Copy at most `n_samples` samples and leave zeros after.
  - If the recomputed `n_samples` differs from the header's, raise `its samples changed after its header was read`.
- **`tests/segy_data.py`:**
  - `RADEXPLORER_TEXT` holds the real text header's wording, items 1–4 as in §2, which mentions no site.
  - `write_segy(path, data, *, dt_ps=406, delay_ps=11766, x_mm=None, y_mm=None, scalar=-1000, units=1, statics_ns=None, shifts=None, stored_samples=None, text=RADEXPLORER_TEXT, ascii_text=False, format_code=5, little_endian=False, extended=0, geographic=True, trace_samples=None, trace_dt=None, delays=None) -> Path`.
    - `data` is `(n_samples, n_traces)` `float32`.
    - `x_mm` defaults to `arange(n) × 68` and `y_mm` to zeros.
    - `statics_ns` (per trace) writes each trace `round(static / dt)` samples down. `shifts` overrides those sample counts, to test the cross-check.
    - `stored_samples` defaults to `n_samples + max shift`.
    - `trace_samples`, `trace_dt` and `delays` override single traces' words (`{index: value}`).
    - `geographic` writes the little-endian flag 1 and leaves the coordinate bytes zero. The writer never writes a real coordinate.
- **`tests/real_data.py`:** `SEGY_DIR = DATA / "segy"` and `SEGY = radar_files(SEGY_DIR, ".sgy")`.

- [ ] **Step 1: Write the failing synthetic tests** in `test_segy.py`:

```python
def test_a_segy_round_trips_its_samples_and_header(tmp_path):
    data = np.linspace(-5, 5, 300 * 40, dtype=np.float32).reshape(300, 40)
    p = write_segy(tmp_path / "LINE01.sgy", data)
    h = read_header(p)                       # nsgeo.io's dispatcher
    assert isinstance(h, SegyHeader) and h.format_name == "SEG-Y" and h.variant == "RadExplorer"
    assert (h.n_samples, h.stored_samples, h.n_traces, h.n_channels) == (300, 300, 40, 1)
    assert h.dt_ns == pytest.approx(0.406) and h.position_ns == pytest.approx(-11.766)
    assert h.traces_per_metre == pytest.approx(1 / 0.068) and h.jumps == 0
    assert h.notes == () and h.antenna == "" and h.geographic_traces == 40
    s = read_samples(p, h)
    assert s.dtype == np.float32 and s.shape == (1, 300, 40)
    np.testing.assert_array_equal(s[0], data)

def test_the_geographic_flag_is_read_little_endian(tmp_path): ...       # Review Focus 1
    # geographic=False -> 0; the flag bytes written as 01 00 -> counted
def test_times_are_picoseconds(tmp_path): ...                              # Review Focus 2
def test_a_static_shift_is_undone(tmp_path):                               # Review Focus 3, 4
    rng = np.random.default_rng(3)
    data = rng.uniform(1, 2, size=(50, 6)).astype(np.float32)   # no zeros in the data
    statics = [800, 0, 10, 20, 30, 41]
    p = write_segy(tmp_path / "S.sgy", data, statics_ns=statics)
    h = read_header(p)
    assert h.stored_samples > 1900 and h.n_samples == 50
    assert h.max_static_ns == 800
    assert h.notes == ("its traces carry a static shift of up to 800 ns: read as recorded, without it",)
    np.testing.assert_array_equal(read_samples(p, h)[0], data)
def test_zeros_that_disagree_with_the_static_are_refused(tmp_path): ...
    # shifts=[0, 0, 12, ...] with statics_ns=[0, 0, 0, ...]: data beginning with exact zeros
def test_an_all_zero_trace_reads_as_zeros(tmp_path): ...
def test_without_statics_zeros_are_kept(tmp_path): ...
def test_spacing_from_trace_coordinates(tmp_path): ...                     # Review Focus 6
    # x_mm alternating 68/69 steps -> 1 / 0.0685; scalar 0, +10, -1000; Y steps count (hypot);
    # two jumps -> the note, for example "its trace coordinates jump at 2 traces, the largest 3.15 m at
    # trace 9: placed at an even 0.068 m"; units 2 -> 0 + the arc-second note;
    # all X equal -> 0, no note; one trace -> 0, no note
def test_no_coordinate_reaches_the_header(tmp_path): ...
    # x_mm offset by 712_345_000 (an easting-sized number): no field, note or repr holds it
@pytest.mark.parametrize(...)
def test_what_is_refused(tmp_path, ...): ...                               # Review Focus 7
    # other software (EBCDIC and ASCII); short file; little-endian; format 1; extended=1;
    # trace_samples / trace_dt / delays on one trace; a truncated last trace
def test_a_dzt_renamed_sgy_is_refused_by_its_text_header(tmp_path): ...    # via tests' DZT writer
def test_a_file_that_changed_after_its_header_was_read_is_refused(tmp_path): ...
def test_the_vm_beside_a_line_is_not_a_radar_file(tmp_path): ...
    # format_for("LINE01.sgy.vm") raises UnsupportedFormat
def test_a_segy_line_opens_loads_slices_and_takes_a_processing_step(tmp_path): ...  # Review Focus 8
    # Line.open + load() + a dewow step; Radargram.t0_ns == -11.766; and a grid of three
    # synthetic SEG-Y lines through the core's slice builder gives finite values
```

  Add to `test_formats.py`: SEG-Y's `prefer` is `()`. Line 147 becomes `(".dzt", ".dt1", ".rd3", ".rd7", ".sgy", ".segy")`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** `segy.py` and the writer. Register SEG-Y last through `_checked` and export the two names. Rerun the C5 grep over `nsgeo-core/src` and `nsgeo_qgis`. If it finds an integer assumption on amplitudes, fix it in this task with a test, and say so in the report.
- [ ] **Step 4: Run the synthetic tests to pass.** Then run core and pure. Every DZT, DT1 and MALÅ test passes unedited, and `test_public_api.py` passes once the core README names the exports.
- [ ] **Step 5: Write the real-data tests** in `test_segy_real_files.py`. Each skips with a reason naming `tests/data/local` when the data is absent. They assert only counts, intervals, times, sample indices and metres:

```python
COUNTS = {"LINE01": 517, "LINE02": 524, "LINE03": 487, "LINE04": 587, "LINE05": 761,
          "LINE06": 758, "LINE07": 946, "LINE08": 387, "LINE09": 572, "LINE10": 445,
          "LINE11": 351, "LINE12": 1217, "LINE13": 316, "LINE14": 316, "LINE15": 384,
          "LINE16": 242, "LINE17": 293, "LINE18": 292}
SHORT = {"LINE01", "LINE02", "LINE03", "LINE04", "LINE05", "LINE06", "LINE07"}  # 344 samples; the rest 424

@pytest.mark.skipif(not SEGY, reason="no segy survey in tests/data/local")
def test_segy_lines_read_with_their_counts_samples_and_spacing():
    assert {p.stem: read_header(p).n_traces for p in SEGY} == COUNTS
    for p in SEGY:
        h = read_header(p)
        assert trace_count(p, h) == h.n_traces
        assert h.n_samples == (344 if p.stem in SHORT else 424)
        assert h.dt_ns == pytest.approx(0.406)
        assert h.step_m == pytest.approx(0.06844, abs=2e-5)
        assert h.geographic_traces == h.n_traces              # a count, never a coordinate
        assert h.max_static_ns > 0 and h.notes[0].startswith("its traces carry a static shift")
    assert read_header(SEGY_DIR / "LINE02.sgy").position_ns == pytest.approx(-9.766)
    assert read_header(SEGY_DIR / "LINE12.sgy").position_ns == pytest.approx(-11.766)
    assert read_header(SEGY_DIR / "LINE08.sgy").max_static_ns == 836

@pytest.mark.skipif(not SEGY, reason="no segy survey in tests/data/local")
def test_line04s_jumps_are_a_note_and_it_stays_evenly_spaced():
    h = read_header(SEGY_DIR / "LINE04.sgy")
    assert h.jumps == 2 and h.traces_per_metre == pytest.approx(1 / 0.06844, rel=1e-3)
    assert h.notes[1] == ("its trace coordinates jump at 2 traces, the largest 3.15 m at trace 586: "
                          "placed at an even 0.06844 m")

@pytest.mark.skipif(not SEGY, reason="no segy survey in tests/data/local")
def test_every_sample_is_live_once_the_static_is_undone():           # Review Focus 3
    for p in SEGY:
        assert (read_samples(p) != 0).all(), p.stem

@pytest.mark.skipif(not SEGY, reason="no segy survey in tests/data/local")
def test_time_zero_is_at_the_direct_wave():                           # Review Focus 5
    # mean trace's first sample past 10 % of its peak: -1.0 <= position_ns + i * dt_ns <= 3.5
    ...
```

- [ ] **Step 6: Run the real-data tests locally. They must pass, not skip.** Then run core and pure, lint and types.
- [ ] **Step 7: Commit and push** (`feat(core): read RadExplorer SEG-Y lines, undoing their static shift (M21c)`).

---

### Task 2: The import lists SEG-Y, and a float line goes all the way through

**Files:**
- Modify (tests only, unless Task 1's grep or these tests find an integer assumption):
  - `packages/nsgeo-qgis/tests/pure/test_pure_lookup.py`
  - `tests/pure/test_pure_gps_import.py`
  - `tests/qgis/test_plugin_import_dialog.py`
  - `tests/plugin_testing.py`: gains `synthetic_segy(folder, name, n_traces=60, n_samples=500, **kw)`, a thin wrapper over the core's writer with a visible float pattern
- Create: `tests/qgis/test_plugin_segy.py`

**Interfaces:** none new. `plan_import`, `_prefer` and `gps_import` already handle any registered format. If a plugin change turns out to be needed, it must be format-neutral, and the report names it.

- [ ] **Step 1: Write the failing tests.**
  - pure, lookup:
    - The two format-list strings (lines 623 and 655) gain SEG-Y, per the copy.
    - `plan_import` over a static-shifted synthetic SEG-Y gives a ticked, placeable row with the static note beside the dielectric note.
    - A synthetic SEG-Y with a jump gives a ticked row with the jump note.
    - A non-RadExplorer SEG-Y gives an unticked row, whose note is `cannot read header: not a RadExplorer SEG-Y, …`.
  - pure, GPS: a `.sgy` is refused with `NO_GPS_FORMAT`, though its traces carry the geographic flag.
  - qgis, import dialog:
    - The filter string (line 367) gains SEG-Y.
    - Choose a DZT, a DT1, a MALÅ `.rd7` and a SEG-Y. That fills four ticked rows, and importing puts four lines on grid A.
  - qgis, `test_plugin_segy.py`, modelled on `test_plugin_mala.py`:
    - A static-shifted SEG-Y line draws its profile at the undone length, with `t0_ns == −11.766`.
    - It takes a dewow step, saves and reopens with the same `float32` samples and steps.
    - Two SEG-Y lines on a grid make a slice and a cut that are finite (Review Focus 8).
    - `header_facts` begins `From this file's header: SEG-Y · antenna ? · sample interval 0.4060 ns`.
- [ ] **Step 2: Run them.** The format strings fail. Everything else should pass with no plugin change. If anything else fails, find out why before changing code.
- [ ] **Step 3: Fix what failed**, format-neutrally.
- [ ] **Step 4: Run the touched files, the pure tier and the real-data tier to pass,** then lint and types.
- [ ] **Step 5: Commit and push** (`feat(m21c): SEG-Y lines in the import, through processing, slices and cuts`).

---

### Task 3: The documentation

**Files:**
- Modify `README.md`:
  - The lead paragraph names SEG-Y from RadExplorer beside DZT, DT1 and MALÅ.
  - "A note on survey data" already names `.sgy`. Add that a SEG-Y file can carry GPS fixes inside it.
- Modify `docs/guide/getting-started.md`, Step 3. Say that:
  - A SEG-Y line is one `.sgy` or `.segy` file, as exported by RadExplorer. SEG-Y from other software is refused.
  - nsgeo undoes the static shift RadExplorer applies, so lines come in as recorded, with time zero at the direct wave.
  - A line whose wheel jumped is placed evenly, and its row says so.
  - GPS placement of SEG-Y lines comes later.

- [ ] **Step 1:** Make the edits. Name no site, and keep the guide's voice: what the user does, then what they see.
- [ ] **Step 2:** Run `tests/pure/test_release_docs.py` and lint; both pass.
- [ ] **Step 3: Commit and push** (`docs: SEG-Y lines in the README and the guide (M21c)`).

---

## After the tasks

- **Finish:**
  - The coordinator runs `qgis_tests.sh full` once and reads CI on both QGIS versions.
  - If M21a or M21b has moved, merge `nsgeo-m21b-mala` in, or rebase onto `origin/main` if they have merged.
  - Then update the README roadmap's M21 entry (M21c built, awaiting its walkthrough) in its own `docs(roadmap):` commit.
- **The walkthrough** runs on its own QGIS profile, `ns_geo_m21c`, deployed with `scripts/dev_link.py` from this worktree. The data goes in `~/nsgeo-m21c-walk/segy/`:
  - copies of `LINE02`, `LINE04`, `LINE08`, `LINE12`, `LINE13` and `LINE14`, with their `.sgy.vm`;
  - `NOT_SEGY.sgy`, a copy of one campus DZT renamed.

  LINE12 is the longest, at 83 m.
  1. In Grid mode, open Add data ▾ ▸ GPR… on a new grid at least 90 m long. The picker lists *SEG-Y* fifth. Choose all seven files through *All radar files*.
     - Expect six ticked rows. Each has the static note and the dielectric note, and LINE04 also has its jump note.
     - `NOT_SEGY.sgy` is unticked, with `not a RadExplorer SEG-Y, the only kind nsgeo reads yet: its text header begins …`.
  2. Import, then open LINE12. It is 424 samples, about 172 ns.
     - The direct wave is at the top, within a few nanoseconds of zero.
     - There is no staircase of shifted traces.
     - The first trace looks like its neighbours, not pushed to the bottom.
  3. Open LINE02, the line whose delay is 9.766 ns rather than 11.766. Its direct wave should sit about 3 ns below zero.
     - Say whether it looks offset from the others: that decides whether its delay can be trusted.
     - A Time zero step fixes it either way.
  4. Open LINE04. Its last 3 m were jumped by the wheel, and the line is placed evenly, so it ends about 3 m short of where the wheel said. Look at the end for anything odd.
  5. Add dewow and gain steps, slice the grid, and cut across the slice. The lines were not recorded as a parallel grid, so slices will look sparse.
  6. Save, close and reopen. Lines, steps and slices come back.
  7. In GPS mode, choose `LINE12.sgy` through *All files*. It is refused with `no GPS log read for this format yet`.
- Merging waits for the user's go after this walkthrough, and after M21a's and M21b's.
