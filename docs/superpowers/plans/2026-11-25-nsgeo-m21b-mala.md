# M21b: MALÅ `.rd3` / `.rd7` lines — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MALÅ lines (`.rd3` or `.rd7`, with their `.rad`) import onto a grid, draw, process, slice and reopen exactly as DZT and DT1 lines do. When both files of a line are chosen, only the `.rd7` is ticked.

**Architecture:** One new reader module, `nsgeo.io.mala`, and one registry entry. This is the first run of the spec's §7 checklist, so M21a's seam is what is being tested. `RadarFormat` gains one defaulted field, `prefer`, which the import's planner reads to untick the lesser file of a pair. Apart from that, the plugin changes nothing but the strings that list the formats.

**Tech Stack:** Python 3.9+ numpy core (`packages/nsgeo-core`); QGIS plugin on QGIS 3.44 / PyQt5 and 4.2 / PyQt6 (`packages/nsgeo-qgis`); pytest.

**Spec:** `docs/superpowers/specs/2026-11-24-nsgeo-radar-formats-design.md`, in particular §2 (MALÅ, with the 2026-11-25 measurements), §4 (C4–C7, C12, C13), §7 and **§14 (the calls this plan makes)**. §13 (M21a's calls) still holds.

**Branch:** `nsgeo-m21b-mala` in `.worktrees/nsgeo-m21b-mala`, branched from `nsgeo-m21-radar-formats` (M21a), whose walkthrough is pending. If M21a merges first, rebase onto `origin/main`. If M21a changes after its walkthrough, merge `nsgeo-m21-radar-formats` in before the next task. Do not start Task 2 on a branch whose M21a part is older than M21a's tip.

## Global Constraints

- **Core:** numpy and the standard library only. Runtime Python 3.9: no `kw_only` dataclasses, no `zip(strict=)`, no `match`, no PEP 604 unions outside annotations. `from __future__ import annotations` heads every new file. `tests/test_boundary.py` stays green.
- **DZT and DT1 behaviour does not change.** Every DZT and DT1 test passes **unedited**, except the three M21a assertions that spell out the full list of formats (`test_pure_lookup.py` lines 617 and 647, `test_plugin_import_dialog.py` line 362). Those gain MALÅ and nothing else. Any other edit to an existing test means the seam leaked: stop and report.
- **No schema change.** A MALÅ line saves as its data file's path and placement. Its header is re-read on open.
- **No `cast` and no `type: ignore` for a header.** The MALÅ reader joins the registry through `_checked`, as DT1 did.
- **Plugin:** Qt only through `qgis.PyQt`. Every Qt slot guards its own body. Code and tests run on QGIS 3.44 and 4.2. Local QGIS is 3.44 only, so check CI's `plugin-qgis (qgis/qgis:4.2)` job after every push.
- **Privacy:** no coordinate and no site name in any committed file, test, docstring, commit message or report. The sample survey is public, but call it only `mala` in anything committed. Its `.cor` files hold GPS fixes: nothing in this plan reads them, and no test opens one.
- **Shared-worktree safety:** reviewers and mutation probes work on a scratch copy, never on this worktree. Set `PYTHONDONTWRITEBYTECODE=1` for every run. Touch no other worktree, M21a's included.
- **Commits:** this laptop has no git identity. Commit as the repository's usual author with `git -c user.name=… -c user.email=…`, taking both from `git log -1 --format='%an%n%ae' origin/main`, never `git config`. End each message with a `Co-Authored-By:` line naming the model that wrote it. Push each commit to `origin nsgeo-m21b-mala` as it is made.

### Copy (exact)

- **The format's name** (`MalaHeader.format_name`, the picker, the facts line): `MALÅ`, with the ring.
- **Grid mode's picker:** `lookup.radar_file_filter()` returns exactly
  `All radar files (*.dzt *.DZT *.dt1 *.DT1 *.rd3 *.RD3 *.rd7 *.RD7);;GSSI DZT (*.dzt *.DZT);;Sensors & Software DT1 (*.dt1 *.DT1);;MALÅ (*.rd3 *.RD3 *.rd7 *.RD7);;All files (*)`.
  This comes from the registry with no code change in `lookup.py`.
- **Unsupported extension:** `… it reads .dzt, .dt1, .rd3, .rd7`, also from the registry.
- **MALÅ errors** (`MalaError`):
  - `no {stem}.rad beside it`
  - `its .rad has no {key}` (for `SAMPLES`, `FREQUENCY`, `LAST TRACE`)
  - `its .rad gives {key} as {value!r}, which is not a number`
  - `its .rad gives {key} as {value!r}, which is not a whole number above 0` (`SAMPLES`, `LAST TRACE`) and `… which is not a number above 0` (`FREQUENCY`)
  - `cannot read {rad.name}: {exc}` and `cannot read it: {exc}` (an `OSError` on the `.rad` or the data file)
  - `{size} bytes are not the {n} traces of {record} bytes its .rad gives: refusing to guess which is right`
  - `its .rad gives a {tw:g} ns TIMEWINDOW but {ns} samples at {f:g} MHz span {calc:g} ns: refusing to guess which is right`
  - `multichannel MALÅ files are not read yet: {name} is one channel of {base}` (a sibling channel on disk)
  - `multichannel MALÅ files are not read yet: its .rad gives {n} channels`
- **MALÅ notes** (`RadarHeader.notes`, no `"; "` in any):
  - `time zero is not read from a MALÅ .rad: set one with a Time zero step` (on every MALÅ line)
  - `its start and stop positions step {actual:.4g} m, not its DISTANCE INTERVAL {interval:g}: placed at the DISTANCE INTERVAL`
  - `distance-triggered with no DISTANCE INTERVAL: place it by hand`
- **The import row of a lesser file of a pair** (C4, §14): unticked, with the note
  `the same traces as {best.name}, which is also chosen: left unticked`. It can still be ticked by hand.
- **Facts line:** `From this file's header: MALÅ · antenna GX450 HDR (v.1) · sample interval …`. The format comes from M21a's `header_facts`, unchanged.
- **GPS mode:** unchanged. A MALÅ file reaching it through *All files* gets M21a's `no GPS log read for this format yet`.

### Before Task 1: the data (coordinator, once)

The virtualenvs from M21a (`.venv` and `.venv-qgis` in the main checkout) are reused. Create this worktree's own `.venv-tools` the same way as M21a's.

1. Copy the MALÅ survey's `data/` folder from `~/Documents/GitHub/sample_data/` into the **main checkout's** `packages/nsgeo-core/tests/data/local/mala/`: all eight lines `DAT_0320`–`DAT_0330`, every file of each (`.rad`, `.rd3`, `.rd7`, `.cor`, `.mrk`, `.srd`; about 190 MB). M21d will need the `.cor` files. `git status` in the main checkout must show nothing new afterwards.
2. Build a second folder, `mala-edge/`, beside it from copies of `DAT_0328` (the smallest line):
   - `DAT_0328.rd7` with **no** `.rad`, to test the missing companion.
   - `DAT_0327.rd3` and `DAT_0327.rd7` with their `.rad` renamed to upper case `DAT_0327.RAD`.
3. Symlink every entry of the main checkout's `tests/data/local/` (except `README.md`) into this worktree's, as M21a did. `ls -L` must show real files.

### Verification commands (from the worktree root)

These are M21a's commands, with M21a's tool paths. A real-data test that skips has validated nothing: the skip count must not rise, and the MALÅ real-data tests must **pass, not skip**, locally.

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider -p no:xonsh -rs`
- **qgis, the files a task touches:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src packages/nsgeo-qgis/scripts/qgis_tests.sh <files> -q -p no:cacheprovider`
- **qgis, real data:** `… qgis_tests.sh packages/nsgeo-qgis/tests/qgis -m real_data -q -p no:cacheprovider -rs`
- **lint:** `.venv-tools/bin/ruff check . && .venv-tools/bin/ruff format --check .`
- **types:** `.venv-tools/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo`
- **Baseline on this laptop:** `grid2` fails (9 failed and 9 errors in core, 5 in the QGIS real-data tier) because its links are broken here. Anything beyond that is a regression.

## Review Focus

These are the inputs most likely to bite. Each is pinned by a test in the task that owns the code.

1. **The 16-bit shift overflowing.** `np.int16` shifted left 16 bits wraps to 0. The `.rd3` must widen to `int32` before the shift. A synthetic `.rd3` holding −32768 and 32767 must read as −2,147,483,648 and 2,147,418,112. (Task 1)
2. **A `.rd7` that is really a renamed `.rd3`.** Its size divides into whole traces at 2 bytes, and into half as many at 4. The width comes from the extension, so the size check must refuse it, never read it as half the traces. (Task 1)
3. **The same stem in two folders.** MALÅ numbers files `DAT_0001`, `DAT_0002`, … in every survey, so `survey-1/DAT_0001.rd3` and `survey-2/DAT_0001.rd7` are different lines. The C4 grouping is by folder **and** stem. Within one folder, stems are matched as spelled. (Task 2)
4. **A preferred file that does not read.** When the `.rd7` of a pair is short or unreadable, the `.rd3` stays ticked and the `.rd7` row says why. (Task 2)
5. **The `.rad` as written:** CRLF endings, a space after the colon (`DISTANCE INTERVAL: 0.496293`), values containing `=` or `:` (`ANTENNAS:GX450 HDR (v.1)=3`), and an upper-case `.RAD`. It is split at the **first** colon. (Task 1)
6. **Multichannel detected before the companion lookup.** `DAT_0001_A1.rd3` beside `DAT_0001_A2.rd3` and a single `DAT_0001.rad` is refused as multichannel, not as `no DAT_0001_A1.rad beside it`. (Task 1)
7. **Time zero.** No MALÅ line may come in with `position_ns` taken from `SIGNAL POSITION`. Real data pins it at 0, with the direct wave's peak at samples 43–58. (Task 1)

---

### Task 1: The MALÅ reader

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/io/mala.py`, `packages/nsgeo-core/tests/mala_data.py` (the synthetic writer), `packages/nsgeo-core/tests/test_mala.py`, `packages/nsgeo-core/tests/test_mala_real_files.py`
- Modify: `packages/nsgeo-core/src/nsgeo/io/formats.py` (`RadarFormat.prefer`; the MALÅ entry), `packages/nsgeo-core/src/nsgeo/io/__init__.py` (export `MalaError`, `MalaHeader`), `packages/nsgeo-core/README.md` (their rows; the `nsgeo.io` lead line names MALÅ), `packages/nsgeo-core/tests/real_data.py` (`MALA`, `MALA_EDGE`), `packages/nsgeo-core/tests/data/local/README.md` (`mala/` and `mala-edge/`, described by contents, not by site), `packages/nsgeo-core/tests/test_formats.py` (the `prefer` tests only)

**Interfaces:**
- `formats.RadarFormat` gains `prefer: tuple[str, ...] = ()` as its last field: extensions, lower case with the dot, that hold the same traces, best first. It is empty for DZT and DT1, and `(".rd7", ".rd3")` for MALÅ. MALÅ's `extensions` are `(".rd3", ".rd7")`, which is the picker's order.
- `class MalaError(RadarFileError)`.
- `@dataclass(frozen=True) class MalaHeader(RadarHeader)`, `format_name = "MALÅ"`, with its own fields: `rad_path: Path`, `n_traces: int` (`LAST TRACE`), `bytes_per_sample: int` (2 for `.rd3`, 4 for `.rd7`, **from the extension**), `distance_interval: float` (0 when absent), `trigger: str` (`"distance"`, `"time"` or `"other"`), `signal_position: float | None` (kept as read, unused, §2).
- `read_header(path) -> MalaHeader` reads the `.rad` and stats the data file. Nothing else.
  1. Multichannel by name. If the stem matches `^(.*)_A(\d+)$` (case-insensitive) and the folder holds another `{base}_A{m}` stem with the same extension (any case), raise the sibling message. Do this before step 2.
  2. Find the `.rad` with `companion(path, ".rad")`. If there is none, raise `no {stem}.rad beside it`.
  3. Parse the `.rad`. Decode as latin-1. Split every line holding `:` at its first `:`, strip both parts and upper-case the key. Read by key only.
  4. `CHANNELS` or `NUMBER OF CH` above 1: raise the `.rad` multichannel message.
  5. `n_samples = SAMPLES`, `dt_ns = 1000 / FREQUENCY`, `range_ns = n_samples × dt_ns`. If `TIMEWINDOW` is present and more than 1 % from `range_ns`, raise the copy's message.
  6. `n_traces = LAST TRACE`. The size must equal `n_traces × n_samples × bytes_per_sample`, or raise the size message.
  7. `position_ns = 0.0`, with the time-zero note always.
  8. `traces_per_metre`, per §14: distance-triggered (`DISTANCE FLAG` 1) with an interval above 0 gives `1 / interval`. The stop/start cross-check adds the copy's note when more than 1 % out, and is skipped for one trace. Distance-triggered with no interval gives 0 and that note. Otherwise 0 with no note: the import's time-triggered note covers it. `trigger` is `"distance"` when `DISTANCE FLAG` is 1, `"time"` when `TIME FLAG` is 1, else `"other"`.
  9. `n_channels = 1`, `epsr = 0.0`, `not_a_profile = ""`. `antenna` is `ANTENNAS` with a trailing `=\d+` removed and stripped, or `""` when absent.
- `trace_count(path, header) -> int`: re-stats the file and repeats step 6's check.
- `read_samples(path, header=None) -> np.ndarray`, shape `(1, n_samples, n_traces)`, `int32`. Read with `np.fromfile` (`<i2` or `<i4`) and reshape `(n_traces, n_samples)`, then transpose. An `.rd3` is widened to `int32` and **then** shifted left 16 bits (§14).
- `tests/mala_data.py`:
  - `write_mala(path, data, *, frequency=5120.0, interval=0.5, distance_flag=1, time_flag=0, timewindow="auto", antenna="GX450 HDR (v.1)=3", signal_position=102.734375, rad_suffix=".rad", rad_extra=(), drop_keys=(), last_trace=None, start=0.0, stop="auto") -> Path`. `data` is `(n_samples, n_traces)` and is written as `<i2` or `<i4` by the path's extension, refusing values that do not fit. The `.rad` is written with CRLF endings and the real files' key order, including keys the reader ignores. `timewindow` and `stop` are computed from the other arguments unless overridden, and `None` drops either.
  - `write_mala_pair(stem_path, data32, **kw) -> tuple[Path, Path]` writes `.rd7 = data32`, `.rd3 = data32 >> 16` and one `.rad`.
- `tests/real_data.py`: `MALA = radar_files(DATA / "mala", ".rd7")`, `MALA_RD3 = radar_files(DATA / "mala", ".rd3")` and `MALA_EDGE = DATA / "mala-edge"`.

- [ ] **Step 1: Write the failing synthetic tests** in `test_mala.py`:

```python
def test_an_rd7_round_trips_its_samples_and_header(tmp_path):
    data = np.arange(-3000, 3000, dtype=np.int32).reshape(100, 60) * 1000
    p = write_mala(tmp_path / "DAT_0001.rd7", data, interval=0.5)
    h = read_header(p)                      # nsgeo.io's dispatcher
    assert isinstance(h, MalaHeader) and h.format_name == "MALÅ"
    assert (h.n_samples, h.n_traces, h.bytes_per_sample) == (100, 60, 4)
    assert h.dt_ns == pytest.approx(1000 / 5120) and h.position_ns == 0.0
    assert h.traces_per_metre == pytest.approx(2.0) and h.antenna == "GX450 HDR (v.1)"
    assert h.notes == ("time zero is not read from a MALÅ .rad: set one with a Time zero step",)
    s = read_samples(p, h)
    assert s.dtype == np.int32 and s.shape == (1, 100, 60)
    np.testing.assert_array_equal(s[0], data)

def test_an_rd3_reads_on_its_rd7s_scale(tmp_path):
    data32 = np.array([[-2**31, 2**31 - 1, -1, 0, 65535, 65536]] * 4, dtype=np.int64).T.astype(np.int32)
    rd7, rd3 = write_mala_pair(tmp_path / "DAT_0002", data32)
    a, b = read_samples(rd3), read_samples(rd7)
    np.testing.assert_array_equal(a, b & ~np.int32(0xFFFF))
    assert a.min() == -2**31 and a.max() == 32767 << 16    # Review Focus 1

def test_the_rad_is_read_by_key_with_crlf_and_colons_in_values(tmp_path): ...
    # rad_extra=("COMMENT:Wheel (30cm)=2", "TIME:12:04:33"), keys reordered, an upper-case .RAD
def test_a_missing_rad_is_refused_by_name(tmp_path): ...
def test_a_missing_or_non_numeric_key_is_refused_by_name(tmp_path): ...   # parametrized over the three keys
def test_a_timewindow_that_disagrees_is_refused(tmp_path): ...
@pytest.mark.parametrize("cut", [1, 2 * 100, 4 * 100 + 2])
def test_a_short_file_is_refused_not_truncated(tmp_path, cut): ...
def test_an_rd3_renamed_rd7_is_refused(tmp_path): ...                     # Review Focus 2
def test_spacing_by_trigger(tmp_path): ...
    # distance with interval -> 1/interval; distance, no interval -> 0 + note;
    # time flag -> 0, no spacing note; stop/start disagreeing by 2 % -> the note
def test_multichannel_is_refused(tmp_path): ...
    # DAT_0001_A1.rd3 + DAT_0001_A2.rd3 + DAT_0001.rad -> the sibling message (Review Focus 6);
    # a lone DAT_0005_A1.rd3 with its own .rad reads; a .rad with CHANNELS:4 -> the .rad message
def test_signal_position_is_never_time_zero(tmp_path): ...               # Review Focus 7
def test_a_mala_line_opens_loads_and_takes_a_processing_step(tmp_path): ...
    # Line.open + load() + a dewow step, as test_dt1's last test
```

  Add to `test_formats.py`: MALÅ's `prefer` is `(".rd7", ".rd3")`, and every other format's is `()`. Every `prefer` entry is one of its format's `extensions`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** `mala.py` and the writer. Register MALÅ last in `FORMATS` through `_checked`, add `prefer`, and export the two names.
- [ ] **Step 4: Run the synthetic tests to pass.** Then run core and pure: every DZT and DT1 test passes unedited (`test_public_api.py` passes once the core README names the exports).
- [ ] **Step 5: Write the real-data tests** in `test_mala_real_files.py`. Each skips with a reason naming `tests/data/local` when its data is absent. They assert only counts, intervals, sample indices and metres:

```python
COUNTS = {"DAT_0320": 7567, "DAT_0321": 1283, "DAT_0323": 5301, "DAT_0326": 1959,
          "DAT_0327": 973, "DAT_0328": 950, "DAT_0329": 2549, "DAT_0330": 1217}

@pytest.mark.skipif(not MALA, reason="no mala survey in tests/data/local")
def test_mala_lines_read_with_their_counts_spacing_and_interval():
    assert {p.stem: read_header(p).n_traces for p in MALA} == COUNTS
    for p in MALA + MALA_RD3:
        h = read_header(p)
        assert trace_count(p, h) == h.n_traces and h.n_samples == 1511
        assert h.dt_ns == pytest.approx(1000 / 5120) and h.range_ns == pytest.approx(295.117188, abs=1e-4)
        assert h.traces_per_metre == pytest.approx(1 / 0.496293) and h.trigger == "distance"
        assert len(h.notes) == 1     # time zero only: the stop/start cross-check agrees

@pytest.mark.skipif(not MALA, reason="no mala survey in tests/data/local")
@pytest.mark.parametrize("stem", ["DAT_0327", "DAT_0328"])   # the two smallest
def test_an_rd3_reads_as_its_rd7_less_its_low_16_bits(stem): ...

@pytest.mark.skipif(not MALA, reason="no mala survey in tests/data/local")
def test_the_direct_wave_is_well_below_the_first_sample():
    # every line: the mean |amplitude| envelope peaks at sample 40-62 (measured 43-58)
    ...

@pytest.mark.skipif(not MALA_EDGE.is_dir(), reason="no mala-edge in tests/data/local")
def test_mala_edge_cases_on_real_files(): ...
    # DAT_0328.rd7 alone: "no DAT_0328.rad beside it"; DAT_0327 with DAT_0327.RAD reads, rad_path spelled .RAD
```

- [ ] **Step 6: Run the real-data tests locally. They must pass, not skip.** Then run core and pure, lint and types.
- [ ] **Step 7: Commit and push** (`feat(core): read MALÅ .rd3/.rd7 lines with their .rad (M21b)`).

---

### Task 2: The import prefers `.rd7` and lists MALÅ

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/lookup.py` (`plan_import` applies `prefer` after building its rows)
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_lookup.py`, `tests/pure/test_pure_gps_import.py`, `tests/qgis/test_plugin_import_dialog.py`, a new `tests/qgis/test_plugin_mala.py`. `plugin_testing.py` gains `synthetic_mala(folder, name, n_traces=60, n_samples=500, **kw)` and `synthetic_mala_pair(folder, stem, …)`, thin wrappers over the core's writers.

**Interfaces:**
- In `plan_import`, after the row loop and before `recompute_offsets`, apply a private `_prefer(rows)`. It groups rows whose format (`format_for`, skipping unsupported extensions) has a non-empty `prefer`, by `(path.parent, path.stem)`. In each group with more than one row, the best extension whose row read (`n_traces is not None`) is kept. Every other row in the group that read gets `include = False` and the copy's note. An unreadable row keeps its own note and nothing more. `recompute_offsets` never re-ticks a placeable row, so check that this holds.

- [ ] **Step 1: Write the failing tests.**
  - pure, lookup:
    - The two format-list strings (lines 617 and 647) gain MALÅ, per the copy.
    - `plan_import` over a pair `DAT_0001.rd3` / `.rd7`: the `.rd7` is ticked and placeable. The `.rd3` is unticked, placeable, and carries the note.
    - Replanning with `recompute_offsets` twice neither re-ticks the `.rd3` nor duplicates its note. Ticking the `.rd3` by hand and then replanning keeps it ticked.
    - The same stem in two folders keeps both ticked (Review Focus 3).
    - A short `.rd7` leaves its `.rd3` ticked (Review Focus 4).
    - A lone `.rd3` is ticked.
    - Every MALÅ row carries the time-zero note beside the dielectric note.
  - pure, GPS: a `.rd7` with a `.cor` and a `.DZG`-named file beside it is refused with `NO_GPS_FORMAT`.
  - qgis, import dialog: the filter string (line 362) gains MALÅ. Choosing a DZT, a DT1 and a MALÅ pair fills four rows, three of them ticked, and importing puts three lines on grid A.
  - qgis, `test_plugin_mala.py`, modelled on `test_plugin_dt1.py`:
    - A MALÅ line draws its profile from its own header (`t0_ns == 0`).
    - It takes a dewow step, saves and reopens with the same samples and steps.
    - With its `.rad` moved away, the site refuses to open with `no LINE01.rad beside it`, as a DT1 does.
    - `header_facts` begins `From this file's header: MALÅ · antenna GX450 HDR (v.1)`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement `_prefer`.**
- [ ] **Step 4: Run the touched files, the pure tier and the real-data tier to pass,** then lint and types.
- [ ] **Step 5: Commit and push** (`feat(m21b): import MALÅ lines; of a chosen .rd3/.rd7 pair only the .rd7 is ticked`).

---

### Task 3: The documentation

**Files:**
- Modify: `README.md` (the lead paragraph names MALÅ beside DZT and DT1; "A note on survey data" names `.rad`, `.rd3`, `.rd7`, `.cor`, `.mrk`, `.srd`), `docs/guide/getting-started.md` (Step 3: a MALÅ line is its `.rd3` or `.rd7` with the `.rad` kept beside it; choosing both ticks only the `.rd7`, which holds the same traces in more detail; a MALÅ line comes in without a time zero, so add a Time zero step first; GPS placement of MALÅ lines comes later).

- [ ] **Step 1:** Make the edits. Name no site, and keep the guide's voice: what the user does, then what they see.
- [ ] **Step 2:** Run `tests/pure/test_release_docs.py` and lint; both pass.
- [ ] **Step 3: Commit and push** (`docs: MALÅ lines in the README and the guide (M21b)`).

---

## After the tasks

- The coordinator runs `qgis_tests.sh full` once and reads CI on both QGIS versions. If M21a has moved, the coordinator merges it in, or rebases onto `origin/main` if M21a has merged. Then the coordinator updates the README roadmap's M21 entry (M21b built, awaiting its walkthrough) in its own `docs(roadmap):` commit.
- **The walkthrough** runs on its own QGIS profile, `ns_geo_m21b`, deployed with `scripts/dev_link.py` from this worktree. The data goes in `~/nsgeo-m21b-walk/mala/`: copies of the four shortest lines, `DAT_0321`, `DAT_0327`, `DAT_0328` and `DAT_0330` (471–636 m), with all their files. These lines were not recorded as a parallel grid, so slices will look sparse.
  1. In Grid mode, open Add data ▾ ▸ GPR… on a new grid at least 650 m long. The picker lists *MALÅ* fourth. Choose all eight data files through *All radar files*. Expect eight rows: the four `.rd7` ticked, and the four `.rd3` unticked with `the same traces as DAT_….rd7, which is also chosen: left unticked`. Every row carries the time-zero and dielectric notes.
  2. Import, then open `DAT_0327`. The direct wave sits about 8–11 ns below the top. Add a Time zero step, and the wave moves to zero.
  3. Add dewow and gain steps, slice the grid, and cut across the slice.
  4. On a second grid, import `DAT_0328.rd3` on its own and compare it with the `.rd7` line from step 1. The pictures and amplitudes should match.
  5. Save, close and reopen. Lines, steps and slices come back.
  6. In GPS mode, choose `DAT_0327.rd7` through *All files*. It is refused with `no GPS log read for this format yet`.
- Merging waits for the user's go after the walkthrough, and after M21a's.
