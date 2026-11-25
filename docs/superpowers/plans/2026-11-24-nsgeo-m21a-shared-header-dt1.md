# M21a: the shared radar header and Sensors & Software DT1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** nsgeo reads any radar format through one header type and one dispatcher, and Sensors & Software pulseEKKO `.DT1` lines (with their `.HD`) import onto a grid, draw, process, slice and reopen exactly as DZT lines do.

**Architecture:** A frozen `RadarHeader` base in `nsgeo.io.header` with the seven fields every consumer reads, plus `notes` and `not_a_profile`. `DztHeader` becomes a subclass and otherwise does not change. A registry in `nsgeo.io.formats` maps file extensions to a format's `read_header` / `trace_count` / `read_samples`, and `nsgeo.io`'s existing `read_header`, `trace_count` and `read_samples` become the dispatching versions. The plugin already imports those three from `nsgeo.io`, so it reads DT1 with no reader-specific code. Its changes are the file picker, the row notes, and the error type it catches.

**Tech Stack:** Python 3.9+ numpy core (`packages/nsgeo-core`); QGIS plugin on QGIS 3.44 / PyQt5 and 4.2 / PyQt6 (`packages/nsgeo-qgis`); pytest.

**Spec:** `docs/superpowers/specs/2026-11-24-nsgeo-radar-formats-design.md`, in particular §2 (Sensors & Software), §4 (C1–C3, C5–C8, C12, C14), §5, §6, §7, §9 and **§13 (the calls this plan makes)**.

## Global Constraints

- **Core:** numpy and the standard library only. Runtime Python 3.9: no `kw_only` dataclasses, no `zip(strict=)`, no `match`, no PEP 604 unions outside annotations. `from __future__ import annotations` heads every new file. `tests/test_boundary.py` stays green.
- **DZT behaviour does not change.** Every existing DZT test passes **unedited**. If a DZT test needs editing, C1 has leaked: stop and report rather than adjust the test. The DZT modules' own functions (`nsgeo.io.dzt.read_header` and friends) keep their names and signatures.
- **No schema change.** The header is not saved in the project; a DT1 line saves as its path and placement, like a DZT line. A site with only DZT lines saves byte-for-byte as before.
- **Retype, do not cast:** every `DztHeader` annotation outside `nsgeo.io` becomes `RadarHeader` (`placement.py`, `track.py`, `destagger/measure.py`, `destagger_job.py` in Task 1; `add_step_dialog.py` in Task 3). They read only the shared fields. No `cast` and no `type: ignore` for a header anywhere (spec C1, corrected while building Task 1). Leave `dzx.py` and `dzg.py` alone: their own `*_for` lookups stay as they are.
- **Plugin:** Qt only through `qgis.PyQt`. Every Qt slot guards its own body (`except Exception as exc:  # noqa: BLE001 -- a slot …`). Code and tests run on QGIS 3.44 and 4.2: compare Qt enums to enums. Local QGIS is 3.44 only, so CI's `plugin-qgis (qgis/qgis:4.2)` job is the Qt 6 check: read it after every push.
- **Privacy:** no coordinate and no site name in any committed file, test, docstring, commit message or report. The sample files came from public sources, but their folder names name sites: refer to them only as `dt1-a` and `dt1-b` (below). The DT1 survey's coordinates file is not read by anything in this plan.
- **Shared-worktree safety:** reviewers and mutation probes work on a scratch copy, never on this worktree. `PYTHONDONTWRITEBYTECODE=1` for every run. Touch no other worktree.
- **Commits:** this laptop has no git identity. Commit as the repository's usual author with `git -c user.name=… -c user.email=…`, taking both from `git log -1 --format='%an%n%ae' origin/main`, never `git config`. End each message with a `Co-Authored-By:` line naming the model that wrote it. Push each commit to `origin nsgeo-m21-radar-formats` as it is made.

### Copy (exact)

- **Grid mode's Add files… picker:** title `Select radar files`; filter from `lookup.radar_file_filter()`, which after this plan returns exactly
  `All radar files (*.dzt *.DZT *.dt1 *.DT1);;GSSI DZT (*.dzt *.DZT);;Sensors & Software DT1 (*.dt1 *.DT1);;All files (*)`.
  The function builds it from the registry: one entry per format in registry order, each extension in lower then upper case.
- **GPS mode's picker:** unchanged (`FILE_FILTER`, `Select DZT files`), §13.
- **GPS refusal for a readable non-DZT file:** `no GPS log read for this format yet` (a new `NO_GPS_FORMAT` beside `NO_DZG`).
- **Unsupported extension** (`UnsupportedFormat`, shown after the import's existing `cannot read header: ` prefix): `nsgeo does not read {suffix} files; it reads {list}`, where `{suffix}` is the file's own suffix as spelled (or `files with no extension` in place of `{suffix} files`) and `{list}` is `.dzt, .dt1`, from the registry.
- **DT1 errors** (`Dt1Error`):
  - `no {stem}.HD beside it`
  - `its .HD has no {key}` (for `NUMBER OF TRACES`, `NUMBER OF PTS/TRC`, `TOTAL TIME WINDOW`)
  - `its .HD gives {key} as {value!r}, which is not a number`
  - `its .HD gives {key} as {value!r}, which is not a whole number above 0` (trace and sample counts) and `… which is not a number above 0` (the time window)
  - `cannot read {hd.name}: {exc}` and `cannot read it: {exc}` (an `OSError` on the `.HD` or the `.DT1`)
  - `{size} bytes do not divide into the {n} traces its .HD gives: refusing to guess which is right`
  - `{k}-byte samples are not read; DT1 samples are 2 or 4 bytes`
  - `its trace headers say {a}-byte samples but the file size says {b}`
- **DT1 notes** (`RadarHeader.notes`):
  - `no time zero in its .HD; set one with a Time zero step`
  - `trace positions step {actual:g} {units}, not the .HD's {step:g}; placed at the .HD's step`
  - `position units {units!r} are not metres or feet; place it by hand` (with `traces_per_metre` 0)
- **`not_a_profile` for a CMP/WARR file:** `a CMP/WARR velocity sounding, not a profile`. The row is unticked and cannot be ticked, with this as its note.
- **Add step dialog's facts line:** `From this file's header: {format} · antenna {antenna or '?'} · sample interval …` (everything after `antenna` unchanged), with `{format}` the header's `format_name`, e.g. `GSSI DZT`, `Sensors & Software DT1`.
- **Survey panel's remove confirmation:** `The DZT file on disk is not touched, …` and `The DZT files on disk are not touched, …` become `The radar file on disk …` and `The radar files on disk …`.
- **DT1 antenna:** `{NOMINAL FREQUENCY:g} MHz` (e.g. `100 MHz`), or `""` when the key is absent.

### Before Task 1: the tools and the data (coordinator, once)

This laptop has none of the virtualenvs the commands below use.

1. In the main checkout, create `.venv` (core and pure tiers) and `.venv-qgis` (from the system `python3` that QGIS uses, `--system-site-packages`) as `packages/nsgeo-qgis/README.md` §Tests describes. In this worktree, create `.venv-tools` with `pip install ruff==0.17.1 mypy==2.4.0 numpy` (CI's versions). Add `.venv-tools/` to `.git/info/exclude` if it is not already covered.
2. Copy the two DT1 surveys from `~/Documents/GitHub/sample_data/` into the **main checkout's** `packages/nsgeo-core/tests/data/local/`, renamed:
   - `dt1-a/`: the 2014 survey's `rawGPR/` folder: `LINE00`–`LINE04` and `CMP`, each `.DT1` + `.HD`.
   - `dt1-b/`: the `sensors and software/` folder: `yyline3.DT1` + `.HD`, and a `CMP.DT1` with **no** `.HD` (kept on purpose, to test the missing companion).

   `tests/data/local/*` is ignored on every branch, so `git status` in the main checkout must show nothing new afterwards; check it.
3. Symlink every entry of the main checkout's `tests/data/local/` (except `README.md`) into this worktree's, as the other worktrees do. `ls -L` must show real files.

### Verification commands (from the worktree root)

The worktree uses the main checkout's virtualenvs with the worktree's core on `PYTHONPATH`. A real-data test that skips has validated nothing: the skip count must not rise, and the new DT1 real-data tests must **pass, not skip**, locally.

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider -p no:xonsh -rs`
- **qgis, the files a task touches:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src packages/nsgeo-qgis/scripts/qgis_tests.sh <files> -q -p no:cacheprovider`
- **qgis, real data:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis -m real_data -q -p no:cacheprovider -rs`
- **The whole qgis tier** runs only as `qgis_tests.sh full`, and only by the coordinator. CI runs it on 3.44 and 4.2 on every push.
- **lint:** `.venv-tools/bin/ruff check . && .venv-tools/bin/ruff format --check .` Never the main `.venv`'s ruff: it reformats `docs/superpowers`.
- **types:** `.venv-tools/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo`, as in `.github/workflows/ci.yml`.

## Review Focus

Inputs the spec implies that are most likely to bite, each pinned by a test in the task that owns the code:

1. **A DZT test edited to pass.** The diff of `packages/nsgeo-core/tests/test_dzt_*.py`, `test_real_files.py` and every plugin test that opens a DZT must be empty. (Task 1)
2. **Registering a reader that takes a narrower header.** `dzt.trace_count(path, header: DztHeader)` stored as `Callable[[Path, RadarHeader], int]` is a contravariance error under mypy. A `# type: ignore` hides a real hole: a DT1 header handed to the DZT reader would read garbage. The registry wraps each reader with a check that raises `RadarFileError` naming both formats. (Task 1)
3. **Case on case-insensitive filesystems.** `LINE00.dt1` with `LINE00.HD`, `line00.DT1` with `line00.hd`, and a directory holding both `.HD` and `.hd`. `companion` matches against `iterdir()` names, never `Path.exists()`, for the reason `sidecar_for` gives, and prefers upper case. (Tasks 1, 2)
4. **A DT1 whose size disagrees with its `.HD`:** too short (an interrupted recording), one byte long, a trace count that divides at 2 bytes and also at 4. It is refused with the copy's message, never truncated. Both widths matching is impossible for one size and count, but the test pins the arithmetic. (Task 2)
5. **A saved site with a DT1 line reopened** finds it through the dispatcher and draws the same profile; a DT1 whose `.HD` was moved away since is reported the way a missing DZT is, not raised. (Task 3)
6. **GPS mode handed a DT1** through "All files" says `no GPS log read for this format yet`, not `no DZG beside it`, and never reaches `read_dzg`. (Task 3)

---

### Task 1: The shared header, the registry, and DZT through it

**Files:**
- Modify: `.gitignore`: after the Sensors & Software block, add `*.[hH][dD]` and `*.[gG][pP][sS]` to it, a `*.[mM][rR][kK]` and `*.[sS][rR][dD]` pair to the MALA block, and a new `# SEG-Y` block with `*.[sS][gG][yY]` and `*.[sS][eE][gG][yY]` (C14).
- Create: `packages/nsgeo-core/src/nsgeo/io/header.py`, `packages/nsgeo-core/src/nsgeo/io/formats.py`
- Modify: `packages/nsgeo-core/src/nsgeo/io/dzt.py` (`DztError` and `DztHeader` subclass the base; `parse_header` passes the two new fields), `packages/nsgeo-core/src/nsgeo/io/__init__.py`, `packages/nsgeo-core/src/nsgeo/model/survey.py` (imports from `nsgeo.io.formats`; `Profile.header` and `Line.header` annotated `RadarHeader`), `geometry/placement.py`, `geometry/track.py`, `destagger/measure.py` and the plugin's `destagger_job.py` (their `DztHeader` annotations become `RadarHeader`, and nothing else changes), `packages/nsgeo-core/README.md` (the `nsgeo.io` table: one row per new public name, and the lead line `Radar readers (GSSI DZT, through one shared header), and the DZX and DZG readers.`)
- Test: `packages/nsgeo-core/tests/test_formats.py`

**Interfaces:**
- `nsgeo.io.header`:
  - `class RadarFileError(Exception)`: raised when a radar file is malformed, unsupported, or missing its companion.
  - `@dataclass(frozen=True) class RadarHeader`, with `format_name: ClassVar[str] = "radar"` and fields in this order, **none defaulted** (Python 3.9: subclasses add required fields): `n_samples: int`, `n_channels: int`, `range_ns: float`, `position_ns: float`, `traces_per_metre: float`, `epsr: float`, `antenna: str`, `notes: tuple[str, ...]`, `not_a_profile: str`. Property `dt_ns = range_ns / n_samples`.
- `nsgeo.io.dzt`: `class DztError(RadarFileError)`; `@dataclass(frozen=True) class DztHeader(RadarHeader)` with `format_name = "GSSI DZT"` and its own fields `tag, bits, data_offset, samples_per_second, zero`, plus its existing properties. `parse_header` passes `notes=()`, `not_a_profile=""`. Nothing builds a `DztHeader` positionally (measured), so the field order change is safe.
- `nsgeo.io.formats`:
  - `@dataclass(frozen=True) class RadarFormat: name: str; extensions: tuple[str, ...]; read_header: Callable[[Path], RadarHeader]; trace_count: Callable[[Path, RadarHeader], int]; read_samples: Callable[[Path, RadarHeader], np.ndarray]` (extensions lower case, with the dot).
  - `FORMATS: tuple[RadarFormat, ...]`: DZT only after this task, DT1 appended in Task 2.
  - `class UnsupportedFormat(RadarFileError)`.
  - `format_for(path) -> RadarFormat`, matched on `Path(path).suffix.lower()`; raises `UnsupportedFormat` with the copy's message.
  - `read_header(path) -> RadarHeader`, `trace_count(path, header) -> int`, `read_samples(path, header=None) -> np.ndarray`: dispatch through `format_for`. `read_samples` reads the header itself when given None.
  - `supported_extensions() -> tuple[str, ...]`: every format's extensions in registry order.
  - `companion(path, suffix: str) -> Path | None`: the file beside `path` with the same stem and `suffix` in upper then lower case, matched against `iterdir()` names; None for an unreadable directory.
  - Each registered reader is wrapped by a private `_checked(fmt_name, header_type, fn)` that raises `RadarFileError(f"{path.name}: a {type(header).format_name} header was given to the {fmt_name} reader")` for the wrong header type, so mypy needs no ignore.
- `nsgeo.io` exports, added to `__all__` (kept sorted): `FORMATS`, `RadarFileError`, `RadarFormat`, `RadarHeader`, `UnsupportedFormat`, `companion`, `format_for`, `supported_extensions`. Its `read_header`, `read_samples` and `trace_count` now come from `formats` (the dispatchers); `DztError` and `DztHeader` stay.

- [ ] **Step 1: `.gitignore`**, then `git status --ignored` on a scratch file of each new extension to see it ignored. Commit this alone first (`chore: ignore pulseEKKO .HD/.GPS, MALA .mrk/.srd and SEG-Y by extension (M21a)`), so no later step can stage a real file.
- [ ] **Step 2: Write the failing tests** in `test_formats.py`:

```python
def test_a_dzt_header_is_a_radar_header_with_empty_notes(tmp_path):
    p = tmp_path / "a.DZT"
    write_dzt(p, np.zeros((512, 10), dtype=np.int32))
    h = formats.read_header(p)
    assert isinstance(h, DztHeader) and isinstance(h, RadarHeader)
    assert h.notes == () and h.not_a_profile == "" and h.format_name == "GSSI DZT"

@pytest.mark.parametrize("name", ["a.DZT", "a.dzt", "a.Dzt"])
def test_dispatch_ignores_the_case_of_the_extension(tmp_path, name):
    p = tmp_path / name
    write_dzt(p, np.arange(512 * 4, dtype=np.int32).reshape(512, 4))
    h = formats.read_header(p)
    np.testing.assert_array_equal(formats.read_samples(p, h), dzt.read_samples(p, dzt.read_header(p)))
    assert formats.trace_count(p, h) == 4

@pytest.mark.parametrize("name, shown", [("a.xyz", ".xyz files"), ("noext", "files with no extension")])
def test_an_unknown_extension_is_refused_naming_what_is_read(tmp_path, name, shown):
    (tmp_path / name).write_bytes(b"\0" * 2048)
    with pytest.raises(UnsupportedFormat, match=f"nsgeo does not read {shown}; it reads .dzt"):
        formats.read_header(tmp_path / name)
    assert issubclass(UnsupportedFormat, RadarFileError) and issubclass(DztError, RadarFileError)

def test_the_wrong_header_type_is_refused_not_read(tmp_path): ...
    # a RadarHeader-subclass stand-in defined in the test, passed to formats.trace_count on a .DZT

def test_companion_returns_the_spelling_on_disk_and_prefers_upper_case(tmp_path):
    (tmp_path / "L.DT1").write_bytes(b""); (tmp_path / "L.hd").write_text("")
    assert formats.companion(tmp_path / "L.DT1", ".HD") == tmp_path / "L.hd"
    (tmp_path / "L.HD").write_text("")      # a case-sensitive filesystem holding both
    assert formats.companion(tmp_path / "L.DT1", ".HD") == tmp_path / "L.HD"
    assert formats.companion(tmp_path / "missing" / "L.DT1", ".HD") is None

def test_a_line_opens_and_loads_through_the_dispatcher(tmp_path): ...
    # Line.open(p, GridPlacement(...)) on a synthetic DZT: header is a DztHeader, load() as before
```

- [ ] **Step 3: Run them to see them fail** (`ModuleNotFoundError: nsgeo.io.formats`).
- [ ] **Step 4: Implement** `header.py`, `formats.py`, the `dzt.py` subclassing, `io/__init__.py` and `survey.py`'s imports and annotations. `survey.py` changes nothing else.
- [ ] **Step 5: Run core + pure. Every existing test passes unedited** (Review Focus 1), including `test_public_api.py` once the core README's table names the new exports. Then lint and types: mypy must pass with no new `type: ignore`.
- [ ] **Step 6: Commit and push** (`feat(core): one radar header and a format registry; DZT reads through it (M21a)`).

---

### Task 2: The DT1 reader

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/io/dt1.py`, `packages/nsgeo-core/tests/dt1_data.py` (the synthetic writer), `packages/nsgeo-core/tests/test_dt1.py`, `packages/nsgeo-core/tests/test_dt1_real_files.py`
- Modify: `packages/nsgeo-core/src/nsgeo/io/formats.py` (append the DT1 format), `packages/nsgeo-core/src/nsgeo/io/__init__.py` (export `Dt1Error`, `Dt1Header`), `packages/nsgeo-core/README.md` (their rows), `packages/nsgeo-core/tests/real_data.py` (two lists, below), `packages/nsgeo-core/tests/data/local/README.md` (the layout gains `dt1-a/` and `dt1-b/`, described by contents, not by site)

**Interfaces:**
- `class Dt1Error(RadarFileError)`.
- `@dataclass(frozen=True) class Dt1Header(RadarHeader)`, `format_name = "Sensors & Software DT1"`, own fields: `hd_path: Path`, `n_traces: int` (the `.HD`'s), `bytes_per_sample: int` (2 or 4), `step: float` and `units: str` (as the `.HD` gives them), `survey_mode: str`, `timezero_point: float | None`.
- `read_header(path) -> Dt1Header`: reads the `.HD` (via `formats.companion(path, ".HD")`; import it lazily or place `companion` in `header.py` to avoid a cycle, builder's choice), stats the `.DT1`, and reads the first and last 128-byte trace headers. Nothing else.
  - `.HD`: decoded as latin-1; every line holding `=` is split at the first `=`, key stripped and upper-cased, value stripped. Lines without `=` are ignored. Reading is by key, never by line number.
  - `n_samples = NUMBER OF PTS/TRC`, `range_ns = TOTAL TIME WINDOW`, `n_channels = 1`, `epsr = 0.0` (the `.HD` has none; the import's existing dielectric note asks for a velocity), `antenna` per the copy.
  - `position_ns = −TIMEZERO AT POINT × dt_ns` (verified, spec §2); key absent: 0.0 and the note.
  - `traces_per_metre`: `POSITION UNITS` `m`/`metres`/`meters` (case-insensitive) → `1 / step`; `ft`/`feet` → `1 / (step × 0.3048)`; otherwise, or a step ≤ 0 → 0.0 with the units note (no note when the unit is metres or feet and only the step is 0: that is a time-triggered line, which the import already notes).
  - Spacing cross-check (§13): `(last position − first position) / (n_traces − 1)` against `step`, more than 1 % apart → the note. Skipped for one trace.
  - `bytes_per_sample` from the file size (§13), checked against trace-header value 5 of the first trace when non-zero.
  - `not_a_profile`: the copy's text when `SURVEY MODE` contains `CMP` or `WARR` (case-insensitive), else `""`.
- `trace_count(path, header) -> int`: re-stats; the size must still equal `n_traces × (128 + n_samples × bytes_per_sample)`, else the size message.
- `read_samples(path, header=None) -> np.ndarray`: `(1, n_samples, n_traces)`, `int32`, raw (no centre to remove, no samples zeroed: DT1 trace headers are separate from the samples).
- `tests/dt1_data.py`: `write_dt1(path, data, *, step=0.25, window_ns=400.0, timezero_point=10.0, frequency=100.0, survey_mode="Reflection", units="m", bytes_per_sample=2, hd_suffix=".HD", hd_extra=(), drop_keys=(), positions=None) -> Path`. `data` is `(n_samples, n_traces)`. It writes the `.HD` with the free lines real files start with (`1234`, an instrument line, a date) and then `KEY = value` lines, and the `.DT1` with real-layout trace headers (value 0 the trace number from 1, value 1 the position, value 2 `n_samples`, value 5 `bytes_per_sample`, value 6 `window_ns`, value 7 a stack count).
- `tests/real_data.py`: `DT1_A = radar_files(DATA / "dt1-a", ".dt1")` and `DT1_B = radar_files(DATA / "dt1-b", ".dt1")`, with `radar_files(folder, suffix)` generalising `dzt_files` (which becomes `radar_files(folder, ".dzt")`).

- [ ] **Step 1: Write the failing synthetic tests** in `test_dt1.py`:

```python
def test_a_dt1_round_trips_its_samples_and_header(tmp_path):
    data = np.arange(-300, 300, dtype=np.int16).reshape(60, 10)
    p = write_dt1(tmp_path / "LINE01.DT1", data, timezero_point=12.0)
    h = read_header(p)              # nsgeo.io's dispatcher
    assert isinstance(h, Dt1Header) and h.format_name == "Sensors & Software DT1"
    assert (h.n_samples, h.n_traces, h.bytes_per_sample) == (60, 10, 2)
    assert h.dt_ns == pytest.approx(400.0 / 60)
    assert h.position_ns == pytest.approx(-12.0 * 400.0 / 60)
    assert h.traces_per_metre == pytest.approx(4.0) and h.antenna == "100 MHz"
    assert h.notes == () and h.not_a_profile == ""
    s = read_samples(p, h)
    assert s.dtype == np.int32 and s.shape == (1, 60, 10)
    np.testing.assert_array_equal(s[0], data)

def test_four_byte_samples_are_read_too(tmp_path): ...
def test_the_hd_is_read_by_key_whatever_its_order_and_extra_lines(tmp_path): ...
    # hd_extra=("ODOMETER CAL (t/m) = 979.6", "Start Rx Battery   = 12.71V", "THIS FILE IS A MERGING OF X AND Y")
def test_a_lower_case_hd_is_found_and_its_spelling_kept(tmp_path): ...
def test_feet_are_converted_and_other_units_are_noted(tmp_path): ...
def test_no_time_zero_reads_from_zero_with_a_note(tmp_path): ...
def test_trace_positions_that_disagree_with_the_step_add_a_note(tmp_path): ...

@pytest.mark.parametrize("mode", ["CMP/WARR", "CMP", "WARR", "cmp"])
def test_a_cmp_sounding_is_not_a_profile(tmp_path, mode):
    p = write_dt1(tmp_path / "CMP.DT1", np.zeros((50, 8), np.int16), survey_mode=mode)
    assert read_header(p).not_a_profile == "a CMP/WARR velocity sounding, not a profile"

def test_a_missing_hd_is_refused_by_name(tmp_path):
    p = write_dt1(tmp_path / "L.DT1", np.zeros((50, 8), np.int16))
    p.with_suffix(".HD").unlink()
    with pytest.raises(Dt1Error, match=r"no L\.HD beside it"):
        read_header(p)

@pytest.mark.parametrize("cut", [1, 128, 128 + 100])   # one byte, one trace header, part of a trace
def test_a_short_file_is_refused_not_truncated(tmp_path, cut): ...
def test_a_missing_or_non_numeric_key_is_refused_by_name(tmp_path): ...
def test_trace_headers_that_disagree_with_the_size_are_refused(tmp_path): ...
def test_a_dt1_line_opens_loads_and_takes_a_processing_step(tmp_path): ...
    # Line.open + load() + Radargram.from_profile + a dewow step: dx_m 0.25, t0 as the header gives
```

- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement `dt1.py` and the writer;** register DT1 in `FORMATS`. Read the two trace headers with one `open()`, `seek` and `read(128)` each; `np.frombuffer(..., "<f4", count=25)`.
- [ ] **Step 4: Run the synthetic tests to pass.**
- [ ] **Step 5: Write the real-data tests** in `test_dt1_real_files.py`, each skipping with a reason naming `tests/data/local` when its list is empty (so the `real_data` mark applies). They assert only counts, intervals, sample indices and metres (spec §9):

```python
A = {p.stem: p for p in DT1_A}

@pytest.mark.skipif(not DT1_A, reason="no dt1-a survey in tests/data/local")
def test_dt1_a_lines_read_with_their_counts_and_spacing():
    counts = {s: read_header(p).n_traces for s, p in A.items() if s.startswith("LINE")}
    assert counts == {"LINE00": 223, "LINE01": 46, "LINE02": 275, "LINE03": 360, "LINE04": 445}
    for stem, p in A.items():
        h = read_header(p)
        assert trace_count(p, h) == h.n_traces and h.bytes_per_sample == 2
        assert h.dt_ns == pytest.approx(0.4) and h.n_samples == 1000
        if stem.startswith("LINE"):
            assert h.traces_per_metre == pytest.approx(4.0) and h.notes == () and h.not_a_profile == ""

@pytest.mark.skipif(not DT1_A, reason="no dt1-a survey in tests/data/local")
def test_dt1_a_time_zero_is_just_before_the_direct_wave():   # every LINE, parametrized
    p = A["LINE00"]; h = read_header(p)
    env = np.abs(read_samples(p, h)[0].astype(float)).mean(axis=1)
    assert 0 <= int(np.argmax(env)) - (-h.position_ns / h.dt_ns) <= 4   # measured 0.5-3.5

@pytest.mark.skipif(not DT1_A, reason="no dt1-a survey in tests/data/local")
def test_dt1_a_cmp_is_a_sounding():
    assert read_header(A["CMP"]).not_a_profile

@pytest.mark.skipif(not DT1_B, reason="no dt1-b survey in tests/data/local")
def test_dt1_b_reads_its_merged_line_and_refuses_the_cmp_with_no_hd(): ...
    # yyline3: 391 traces of 500 samples, the direct wave's peak 0-4 samples after time zero;
    # CMP.DT1 raises Dt1Error matching "no CMP.HD beside it"
```

- [ ] **Step 6: Run the real-data tests locally; they must pass, not skip.** Then core + pure, lint and types.
- [ ] **Step 7: Commit and push** (`feat(core): read Sensors & Software DT1 lines with their .HD (M21a)`).

---

### Task 3: The plugin reads every registered format

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/lookup.py` (`radar_file_filter()`; `plan_import` catches `RadarFileError`, appends `header.notes` to the row's note, and makes a `not_a_profile` row unticked and not placeable), `packages/nsgeo-qgis/nsgeo_qgis/ui/import_dialog.py` (`_choose_files`: the copy's title and `radar_file_filter()`), `packages/nsgeo-qgis/nsgeo_qgis/gps_import.py` (`_plan_one` catches `RadarFileError` and refuses a readable non-DZT with `NO_GPS_FORMAT` before looking for a DZG), `packages/nsgeo-qgis/nsgeo_qgis/destagger_job.py` (catches `RadarFileError` in place of `DztError`), `packages/nsgeo-qgis/nsgeo_qgis/ui/add_step_dialog.py` (`header_facts` takes a `RadarHeader` and names its format), `packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py` (the two remove-confirmation strings)
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_lookup.py`, `tests/pure/test_pure_gps_import.py`, `tests/qgis/test_plugin_import_dialog.py`, `tests/qgis/test_plugin_param_form.py`, plus a new `tests/qgis/test_plugin_dt1.py` for the end-to-end checks below. `plugin_testing.py` gains `synthetic_dt1(folder, name, n_traces=60, n_samples=500, **kw)`, a thin wrapper over the core's `write_dt1`.

**Interfaces:**
- `ImportRow.placeable` becomes `traces_per_metre > 0 and n_traces is not None and not not_a_profile`, with `ImportRow` gaining `not_a_profile: str = ""`, set by `plan_import`. Wherever the table lets a row be ticked, a row that is not placeable already cannot be. Check that this holds for the new reason too, not just for `traces_per_metre == 0`.
- `NO_GPS_FORMAT = "no GPS log read for this format yet"` in `gps_import.py`, exported beside `NO_DZG`.

- [ ] **Step 1: Write the failing tests.**
  - pure, lookup: `radar_file_filter()` equals the copy's string exactly. `plan_import` over a DZT, a DT1, a CMP DT1, a DT1 with no `.HD` and an `.xyz` file reads the first two as placeable rows. The CMP row is unticked, not placeable, with the copy's note. The other two are unticked with `cannot read header: no X.HD beside it` and `cannot read header: nsgeo does not read .xyz files; it reads .dzt, .dt1`. A DT1 with no time zero carries that note beside the dielectric note, and a replan (`recompute_offsets` twice) does not duplicate it.
  - pure, GPS: a DT1 with a `.DZG`-named file beside it is still refused with `NO_GPS_FORMAT`; an unreadable DT1 is refused, not raised.
  - qgis, import dialog: `_choose_files` passes the copy's title and filter to `getOpenFileNames` (read from the `answer_modal` calls); choosing a DZT and a DT1 imports both onto grid A.
  - qgis, `test_plugin_dt1.py`: a site with a DT1 line opens its profile, adds a dewow step, saves, and reopens with the line and the same profile; with the `.HD` moved away before the reopen, the line is reported as unreadable the way a missing DZT is (find that path in `session.py` / `loader.py` and match its message); `header_facts` of a DT1 line begins `From this file's header: Sensors & Software DT1 · antenna 100 MHz`.
  - qgis, param form: the existing facts test gains `"GSSI DZT" in d.facts.text()`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** to the interfaces and copy. `lookup` and `gps_import` already import `read_header` and `trace_count` from `nsgeo.io`, which now dispatch: change only their `except` clauses and imports.
- [ ] **Step 4: Run the touched files, the pure tier and the real-data tier to pass;** grep the plugin's tests for the two survey-dock strings and update any that assert them. Lint, types.
- [ ] **Step 5: Commit and push** (`feat(m21a): import, process and reopen DT1 lines; the file picker lists every format`).

---

### Task 4: The documentation

**Files:**
- Modify: `README.md` (the lead paragraph's `Today it reads GSSI DZT files.` names DT1 too; the "A note on survey data" section names the new extensions), `docs/guide/getting-started.md` (Step 3: DT1 files are chosen the same way, with each `.HD` kept beside its `.DT1`; a CMP file is listed but not imported, and why), `packages/nsgeo-qgis/README.md` only if it names the DZT-only picker.

- [ ] **Step 1:** Make the edits. Name no site. Keep the guide's voice: what the user does, then what they see.
- [ ] **Step 2:** `tests/pure/test_release_docs.py` and lint pass.
- [ ] **Step 3: Commit and push** (`docs: DT1 lines in the README and the guide (M21a)`).

---

## After the tasks

- The coordinator runs `qgis_tests.sh full` once, reads CI on both QGIS versions, merges `origin/main` if it moved, and updates the README roadmap's M21 entry (M21a built, awaiting its walkthrough) in its own `docs(roadmap):` commit.
- **The walkthrough**, on its own QGIS profile `ns_geo_m21a`, deployed with `scripts/dev_link.py`. Check first that the data it needs exists on this laptop: the DT1 surveys from Before Task 1, step 2, and a DZT survey for the mixed-format step.
  1. Add data ▾ ▸ GPR… in Grid mode on a new grid: the picker lists *All radar files*, *GSSI DZT* and *Sensors & Software DT1*. Choose `dt1-a`'s six files: five rows ready, CMP unticked with its note, each with the dielectric note.
  2. Import; the five lines draw on the map at 0.25 m spacing; open `LINE00`: the direct wave sits at time zero, with clipped near-surface samples and reflections below.
  3. Add a dewow and a gain step; slice the grid; make a cut across it.
  4. Save, close, reopen: lines, steps and slices come back.
  5. A DZT line and a DT1 line in one site, each on its own grid, both drawn and processed.
  6. GPS mode with `dt1-b/yyline3.DT1` chosen through *All files*: refused with `no GPS log read for this format yet`.
- Merging waits for the user's go after the walkthrough.
