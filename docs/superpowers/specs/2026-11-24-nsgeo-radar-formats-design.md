# nsgeo M21: radar formats beyond GSSI — design

2026-11-24. The author's direction: "a general import functionality with type specific derivatives
makes sense"; all of these formats eventually, "and more as I come across them"; the order is
Claude's call.

nsgeo reads one radar format, GSSI `.DZT`. This adds Sensors & Software (`.DT1` + `.HD`), MALÅ
(`.rd3`/`.rd7` + `.rad`) and SEG-Y as written by RadExplorer. It does that by putting a
format-neutral header and a small format registry under the one reader there is now, so that each
later format is one module and one registry entry, not a pass through the plugin.

## 1. What this is for

The author has collected radar data from other instruments and from public datasets, and expects
to keep finding more. Today every one of those files fails at `read_header` with a `DztError`.

**Success.** Each sample file in §2 imports onto a grid through the existing import dialog, draws a
profile that looks like radar (a direct wave near time zero, reflections below it, no banding or
wrap-around), takes processing steps, and slices with the rest of its grid. Reopening the project
reopens the line. A fifth format, when one arrives, needs a new module in `nsgeo.io`, an entry in
the registry, a synthetic writer for tests, and a section of this spec, and nothing in the plugin.

## 2. What the files contain (measured 2026-11-24)

Measured on the files in `~/Documents/GitHub/sample_data/`, outside the repository. They are
copied into `packages/nsgeo-core/tests/data/local/<format>/` for real-data tests (§9). No
coordinate from any of them appears in this spec. Every trace count below divides exactly and
matches its header.

### Already readable: GSSI DZT

- `file6/23/38/51.dzt`: the pulseEKKO-exported 16-bit variant fixed in #191. They load with the
  current reader: 256 samples, 2,532–2,560 traces, 50 traces/m.
- `our_other_data/FILE__004/016.DZT` (+ `.DZX`): SIR-4000 32-bit, HS350 antenna, 512 samples,
  100 traces/m. They load with the current reader.

Nothing in this design changes how a DZT reads. These files go into the real-data tests as two
more DZT cases.

### Sensors & Software pulseEKKO: `.DT1` + `.HD`

Seven lines from two surveys (pulseEKKO PRO, 100 MHz, 2012 and 2014), plus one CMP sounding.

- **`.HD` is text**, one `KEY = value` per line after a few free lines (a `1234` magic line, the
  instrument, a date). Keys used: `NUMBER OF TRACES`, `NUMBER OF PTS/TRC`, `TIMEZERO AT POINT`,
  `TOTAL TIME WINDOW` (ns), `STARTING POSITION`, `FINAL POSITION`, `STEP SIZE USED`,
  `POSITION UNITS`, `NOMINAL FREQUENCY` (MHz), `ANTENNA SEPARATION`, `SURVEY MODE`. Some files add
  more keys (odometer calibration, serial numbers, battery voltages); one says it is a merge of two
  other lines. Reading must be by key, never by line number.
- **`.DT1` is fixed-size records:** per trace, a 128-byte header (25 little-endian float32 values
  then 28 bytes of comment) followed by `NUMBER OF PTS/TRC` little-endian `int16` samples.
  Trace header value 0 is the trace number (1, 2, 3, ...), 1 the position in `POSITION UNITS`,
  2 the samples per trace, 3 the topography, 6 the time window, 7 the stack count.
- **Time zero is trustworthy.** `TIMEZERO AT POINT` is a sample index, and it matches the measured
  first break to within a sample: 131.46 against 131 on `LINE00`, 64.89 against 65 on `yyline3`.
  *(Checked on every line while building M21a: the direct wave's envelope peak follows it by
  0.5–3.5 samples on all six profiles. A 30 % threshold on the envelope's rise is not a steady
  mark: on one line, whose wave rises slowly, it falls 6.5 samples early.)*
  The sample interval is `TOTAL TIME WINDOW / NUMBER OF PTS/TRC` (400 / 1000 = 0.4 ns).
- **Spacing is even.** Every per-trace position step is exactly `STEP SIZE USED` (0.25 m), and the
  position runs from `STARTING POSITION` to `FINAL POSITION`.
- **Samples clip.** Values sit at both int16 limits in more than 1 % of samples on most lines.
  That is the data as recorded, not a reading error.
- **`CMP.HD` says `SURVEY MODE = CMP/WARR`.** It is a common-midpoint velocity sounding: each
  trace is a different antenna separation at one place, not a step along a line. Its positions run
  17–36.5 m in 0.5 m steps, which are separations, not distances.
- A coordinates file beside one survey (`coord/measured_coordinates.txt`) gives start, end and
  intermediate points per line in a projected CRS, which the existing tape placement can use as a
  grid. A pulseEKKO `.GPS` file (not present here) is the instrument's own GPS log.

### MALÅ: `.rad` + `.rd3` / `.rd7`

Eight lines from a GX450 HDR survey (an archived public dataset), each with `.rad`, `.rd3`, `.rd7`,
`.cor`, `.mrk` and `.srd`.

- **`.rad` is text**, one `KEY:value` per line. Keys used: `SAMPLES`, `FREQUENCY` (the *sampling*
  frequency in MHz, 5120 here), `TIMEWINDOW` (ns), `LAST TRACE` (the trace count), `DISTANCE FLAG`
  and `TIME FLAG` (which trigger), `DISTANCE INTERVAL` (m per trace), `ANTENNAS`,
  `ANTENNA SEPARATION`, `SIGNAL POSITION`, `STOP POSITION`.
- **No per-trace header.** `.rd3` is `SAMPLES` little-endian `int16` per trace, `.rd7` the same
  traces as `int32`. They hold identical traces at two resolutions (`.rd3` ±1.3e3, `.rd7` ±9e7);
  the sample interval is `1000 / FREQUENCY` ns (0.1953 ns), and `SAMPLES ×` that is `TIMEWINDOW`.
  *(Measured 2026-11-25, planning M21b: every `.rd3` sample is exactly its `.rd7` sample shifted
  right 16 bits, on all eight lines. The `.rd3` is the `.rd7`'s top half, not a rescaling.
  `LAST TRACE` is the trace count, not a last index: both files of every line hold exactly that
  many traces.)*
- **`SIGNAL POSITION` is not time zero.** It is 102.73 on every line, but the measured first break
  is at sample 36–47 (7–9 ns). 102.73 matches neither as samples (20 ns) nor as ns.
  *(The direct wave's envelope peak is at sample 43–58, 8.4–11.3 ns, measured 2026-11-25.)*
- **Spacing:** `DISTANCE FLAG:1` with `DISTANCE INTERVAL` 0.496 m; `STOP POSITION / LAST TRACE`
  agrees.
- **`.cor` is a GPS log:** tab-separated, one row per fix, about every other trace: trace number,
  date, UTC time, latitude and hemisphere, longitude and hemisphere, altitude and unit, quality.
  It plays the part a `.DZG` plays for GSSI. *Measured 2026-11-25:* ten columns on every row of
  all eight; latitude and longitude in **decimal degrees** (not NMEA ddmm); about one fix a
  second, every 3–5 traces; trace numbers rise and **count from 1** (the last row of three lines
  names trace `LAST TRACE` itself), where a DZG counts from 0. **Quality is 1 (GPS) or 2 (DGPS)
  on every fix: none is RTK.** The fixes scatter about 1.4–2.4 m (median distance from the
  midpoint of the fixes five either side). Along the track thinned to fixes at least 5 m apart,
  five lines run 7–11 % longer by GPS than by the wheel, and DAT_0320, 0321 and 0323 run 28–49 %
  longer. The lines wind: they are not a parallel grid.
- **`.mrk` holds marks** (`trace, ?, ?, label` rows after a version line). **`.srd`** is a text
  table of time, wheel position and trace number.
- MALÅ also writes multichannel files as `DAT_0001_A1.rd3`, `_A2`, ...; none are in hand.

### SEG-Y from RadExplorer: `.sgy` (+ `.sgy.vm`)

18 lines from one survey, exported by RadExplorer. Below they are LINE01–LINE18, in the order of
their file names; the local copies are renamed so, because the names carry the site.

- **Big-endian SEG-Y**: a 3,200-byte EBCDIC text header, a 400-byte binary header, then
  per trace a 240-byte header and `IEEE float32` samples (format code 5). The binary header's
  revision word (bytes 3501–3502) is 0, and its only other non-zero words are the sample
  interval, the sample count and the format code. Every trace has the binary header's sample
  count. Trace sequence numbers count from 0.
- **The text header documents RadExplorer's departures from the standard.** Measured
  2026-11-25, two of them hold as written and two do not:
  1. Sample interval and delay are in **picoseconds** (406 ps here), not microseconds. Read as
     standard SEG-Y, every time is a million times too long. Holds.
  2. Marks are in trace-header bytes 239–240, flagged by 0x55 in 237–238. **Not as written:**
     five lines carry marks (1–5 each), and their flag is 1 and their number counts from 1,
     both **little-endian**, like item 4. No trace has 0x55.
  3. Coordinates in bytes 73–88 are metres or arc-seconds (coordinate units, bytes 89–90, is 1:
     length). Here X is distance along the line in mm (scalar −1000) and Y is 0. Holds. The
     step is 68 or 69 mm (integer millimetres), 68.44 mm on average in every line. One line
     (LINE04 below) has two jumps, 0.274 m and 3.149 m, before its 491st and 586th traces. One
     line's X starts at 10.471 m, not 0.
  4. **Geographic coordinates** are in bytes 229–236 as degrees × 10^6, flagged by 1 in 227–228.
     **These fields are little-endian inside an otherwise big-endian file**: the flag reads 256
     big-endian and 1 little-endian on every trace of every line, and only the little-endian
     reading gives plausible positions (hundreds of distinct fixes per line, about 0.1 m apart).
- **The files are static-shifted exports, which the text header does not say.** Trace-header
  bytes 101–102 (group static) hold a per-trace number of nanoseconds, and each trace's samples
  are pushed down by that much and padded with exact zeros above and below. Underneath, every
  trace is one unbroken run of non-zero samples, exactly **344** long in the first seven lines
  and **424** in the other eleven. The run's first sample is `static / 0.406 ns` down to within
  5.1 samples. The static is stored in whole nanoseconds (±1.2 samples), and the rest of the
  drift grows with the static, about 0.22 % of it, which suggests the true interval is nearer
  0.4069 ns than the 406 ps stored.
- **Trace 0's static is bogus** in 17 of the 18 lines: 644–836 ns, where the other traces' are
  0–122 ns. That one trace is why the stored sample counts are so large (2,006–2,478) and
  differ between lines: the window was stretched to fit it.
- **Time zero is the delay, below the first sample.** Each trace's delay word (bytes 109–110)
  is 11,766 ps (11,765 in two lines, 9,766 in one), and lag B (bytes 107–108) is exactly its
  negative. With each trace's live run moved back to the top, the mean trace's first break (the
  first sample past 10 % of its peak) is 11.4–13.8 ns down in every line, the 9,766-ps line
  included. So the first sample is the delay *before* time zero: `position_ns = −delay`, which
  puts the first break at −0.4 to +2.0 ns (+2.8 in the 9,766-ps line). Read as `+delay`, the
  first break would be about 24 ns after time zero.
- **No antenna is named** anywhere in the file.
- **The geographic fields** (item 4), read little-endian as degrees × 10^6, longitude then latitude
  (*measured 2026-11-25*): the documented order is the only one that gives a latitude within
  ±90°. Every trace has a position, none is 0, and there is no quality, time or altitude. A
  position repeats over runs of traces; the change points are 100–1,006 a line, most one trace
  apart, so the receiver updates at about the trace rate, quantised to 10^-6 degrees (about
  0.1 m). They scatter about 0.3–0.7 m. **On every line the GPS track is 2.0–2.4× longer than
  the wheel's along-line coordinate** (LINE12: 176 m end to end against 83 m), whatever the
  line's heading, so it is not an east-west scale error. Which of the two is right is not known.
- `.sgy.vm` files are RadExplorer display settings (a colour scheme, a font). Not read.

### Not yet identified

Four `.gpr` files in `tests/data/local/` (magic `GPR\x01`, 195-byte records, 8-bit samples; see
the first spec's §6a). They stay unread until their instrument is known, but the registry is where
they will go.

## 3. Decisions taken by the author

1. **A general import with format-specific readers.** One header type and one way in for every
   radar format, with a reader per format behind it.
2. **All of these formats, and more later.** The design is judged on how cheap the next format is.
3. **Order is Claude's call** (§8).

## 4. Claude's calls (check these)

- **C1. `RadarHeader` is the base, and `DztHeader` is a subclass of it.** A frozen dataclass in
  `nsgeo/io/header.py` with the fields every consumer reads: `n_samples`, `n_channels`,
  `range_ns`, `position_ns`, `traces_per_metre`, `epsr`, `antenna`, and the `dt_ns` property
  (`range_ns / n_samples`, as now). Measured on main at `f8374ed4`: outside `io/dzt.py`, those are the only
  header fields any code reads; `data_offset`, `bits`, `dtype` and `bytes_per_sample` are read only
  by the DZT reader itself. Each format subclasses it with what its own reader needs (`DztHeader`
  keeps `tag`, `bits`, `zero`, `data_offset`, `samples_per_second`). Why subclass, not wrap:
  - Every `line.header.epsr`-style read keeps working unchanged.
  - `Placement`, `GridPlacement`, `TrackPlacement`, `MeasureLine`, `destagger_job` and
    `add_step_dialog.header_facts` annotated `DztHeader`. *(Corrected 2026-11-24, building
    M21a: this said the annotations could stay, "true for DZT lines and harmless for the rest".
    They are not harmless: once `Line.header` is a `RadarHeader`, mypy rejects passing it where a
    `DztHeader` is declared, and a cast or ignore would hide the hole the registry's type check
    closes. M21a retypes them all as `RadarHeader`. They read only the shared fields. The cost is
    a small conflict on those signature lines in `placement.py` for whichever of M21a and M19
    merges second.)*
  - Python 3.9 is supported, so `kw_only` dataclasses are not available. The base therefore has
    no defaulted fields, so subclasses can add required ones. The format's name is a `ClassVar`
    on each subclass, not a field.
- **C2. A registry in `nsgeo/io/formats.py`.** Each format is a `RadarFormat`: a name, its data
  file extensions, and three functions with the signatures `dzt.py` already has: `read_header`,
  `trace_count` and `read_samples`. Module-level functions `read_header(path)` and friends
  dispatch on the extension, case-insensitively, and raise `UnsupportedFormat` (a
  `RadarFileError`) naming the supported extensions. `nsgeo.io`'s existing exports keep their
  names and become the dispatching versions, so `from nsgeo.io import read_header` reads any
  format. The DZT module's own functions stay for tests.
- **C3. A line is its data file.** `.DT1`, `.rd3`/`.rd7`, `.sgy`/`.segy` are the paths a line
  keeps, and `project.line_key` names it by that path as now. The header companion (`.HD`, `.rad`)
  is found beside it by stem, matched against the real directory entries the way `sidecar_for` and
  `dzg_for` do. A missing companion is a `RadarFileError` naming the file it looked for. The header
  is not saved in the project (verified on main: `project.py` holds none), so it is re-read on
  open and **no schema change** is needed. That should be re-verified on the merged main before
  planning.
- **C4. `.rd7` over `.rd3`.** When both of a stem are chosen, the import keeps the `.rd7` (32-bit,
  same traces) and lists the `.rd3` unticked with a note. Either imports on its own.
- **C5. The samples contract:** `read_samples` returns `(n_channels, n_samples, n_traces)` with
  raw amplitudes, `int32` for integer formats, `float32` for float formats, and no scaling. The
  only per-format decoding allowed is what DZT already does: removing an offset-binary centre,
  zeroing samples that are known not to be radar. Nothing downstream may assume an integer dtype;
  the builder greps for it (`np.iinfo`, integer `dtype` checks, `//` on amplitudes) before
  SEG-Y lands.
- **C6. Time zero (`position_ns`, the time of the first sample) by format:**
  - DT1: `-TIMEZERO AT POINT × dt_ns`. Measured to match (§2).
  - MALÅ: `0`. `SIGNAL POSITION` does not match the data, so it is not used; the existing
    time-zero step sets it, as for any line. The import note says so.
  - SEG-Y (RadExplorer): `+delay`, the standard meaning. Unverified: the walkthrough checks it
    against the profile, and if it is wrong the fix is one line in one reader.
- **C7. Spacing (`traces_per_metre`) by format.** 0 means "not distance-triggered", as for DZT,
  which the import already handles (the row is unticked with a note):
  - DT1: `1 / STEP SIZE USED` when `POSITION UNITS` is metres, cross-checked against the
    per-trace positions; a disagreement is a note, not a refusal.
  - MALÅ: `1 / DISTANCE INTERVAL` when `DISTANCE FLAG` is 1, else 0.
  - SEG-Y: from the per-trace along-line coordinate when its steps are even to within 5 %; else 0
    with a note. Uneven spacing is M17b's "profiles at true distance", not this milestone.
- **C8. CMP and WARR files are listed, unticked, with a note** ("a CMP/WARR velocity sounding,
  not a profile"), from DT1's `SURVEY MODE`. Velocity analysis from a CMP is not built.
- **C9. Only recognised SEG-Y flavours are read.** SEG-Y from other software uses other units and
  fields, and a GPR file read with the standard's microseconds gives times a million times too
  long. The SEG-Y reader recognises RadExplorer by its text header. Any other SEG-Y is refused,
  quoting the first line of its text header, until a sample of that flavour is in hand. Each new
  flavour is a named variant inside `segy.py`, not a new format.
- **C10. GPS comes last, as its own plan (M21d).** M17a and M17b have merged: `track_from_log`
  builds a `TrackPlacement` from a `DzgLog`, and `gps_import._plan_one` finds the log with
  `dzg_for`. A new format joins GPS placement by turning its own log into a `DzgLog`: MALÅ `.cor`
  rows, RadExplorer's little-endian geographic trace fields, and a pulseEKKO `.GPS` when one
  arrives. Each format names its GPS companion through the registry (an optional `gps_for` beside
  the header functions), and `_plan_one` asks the registry instead of calling `dzg_for`. Fix
  quality differs by source (`.cor` has its own quality column; RadExplorer's fields have none),
  so how each maps onto `RTK_FIXED` is a call for M21d's plan, made against the data. Until M21d,
  the new formats place on a grid by tape, and Add data's GPS mode refuses them with "no GPS log
  read for this format yet".
- **C11. No marks in this milestone** (`.mrk`, SEG-Y mark words, DT1 comments). Marks come with
  the `.DZX` equivalent for each format, as a follow-up.
- **C12. One error base.** `RadarFileError` in `nsgeo/io/header.py`. `DztError` and each new
  reader's error subclass it, and the plugin catches the base wherever it catches `DztError` now
  (`lookup.plan_import`, `gps_import._plan_one`, `destagger_job`).
- **C13. Multichannel MALÅ files are refused** with a message saying multichannel MALÅ is not yet
  read, until one is in hand. Single-channel files are what the survey has.
- **C14. The `.gitignore` grows first.** By extension, case-insensitive: `.HD`, `.GPS`, `.mrk`,
  `.srd`, `.sgy`, `.segy`. A SEG-Y file can carry per-trace GPS (§2), and `.cor` is already
  covered. This is the first change of the first plan, before any real file is copied in.

## 5. The core (`nsgeo-core`, numpy only)

```
nsgeo/io/
  header.py    RadarHeader, RadarFileError
  formats.py   RadarFormat, the registry, dispatching read_header / trace_count / read_samples,
               supported_extensions(), companion lookup shared by every reader
  dzt.py       DztHeader(RadarHeader); otherwise unchanged
  dt1.py       Dt1Header(RadarHeader): survey_mode, step_m, timezero_point
  mala.py      MalaHeader(RadarHeader): bits (16 or 32), trigger
  segy.py      SegyHeader(RadarHeader): variant, n_traces, per-trace along-line distance summary
```

- **`model/survey.py`** imports `read_header`, `read_samples` and `trace_count` from
  `nsgeo.io.formats` instead of `nsgeo.io.dzt`, and annotates `Line.header` and `Profile.header`
  as `RadarHeader`. `Line.open` and `_load_profiles` are otherwise unchanged.
- **`trace_count` stays cheap.** DT1 and MALÅ derive it from file size and check it against the
  header's count; a disagreement is an error, by the rule DZT already follows (a non-integer count
  means a wrong header, and truncating would misalign the data). SEG-Y derives it from size when
  every trace has the binary header's sample count, which is the case here; a file with varying
  per-trace counts is refused (C9's rule: not until one is in hand).
- **The boundary test is unchanged:** none of this imports anything beyond numpy and the standard
  library. EBCDIC decodes with the standard `cp500` codec.

## 6. The plugin

- **Add data ▾ ▸ GPR…, both modes.** The Grid mode (`ui/import_dialog.py`) and the GPS mode
  (`ui/gps_import_dialog.py`, whose `FILE_FILTER` is DZT-only) build their file filters from
  `supported_extensions()`: one "All radar files" entry, then one per format, then "All files".
  The title becomes "Select radar files".
- **`gps_import._plan_one`** reads headers through the dispatcher, catches `RadarFileError`, and
  until M21d refuses a non-DZT file with C10's reason.
- **`lookup.plan_import`** reads headers through the dispatcher and catches `RadarFileError`. The
  `.DZX` sidecar read stays DZT-only. New row notes come from C4, C6 (MALÅ), C7 and C8.
- **`add_step_dialog`'s header line** names the format next to the antenna.
- **Everything else is unchanged.** Every other plugin read of a header uses the C1 fields.

## 7. Adding a format later

The checklist this design exists to keep short:

1. Get real files. Measure them and write their section in §2 (or a new spec, for a big format),
   with no coordinate in it.
2. Add the extensions to `.gitignore` before copying files into `tests/data/local/<format>/`.
3. Write `nsgeo/io/<format>.py`: a `RadarHeader` subclass and the three functions.
4. Add one entry to the registry.
5. Write a synthetic writer in `tests/` and round-trip tests, plus real-data tests that skip when
   the files are absent.
6. Walk through it: import, profile, a processing step, a slice, reopen.

A format that needs something the base header cannot carry (uneven spacing, GPS, multichannel
geometry) is a design change, not a checklist run.

## 8. Plans and order

Each plan is 3–5 tasks and has its own walkthrough.

- **M21a: the seam and DT1.** `.gitignore` (C14); `RadarHeader`, `RadarFileError`, the registry;
  `DztHeader` as a subclass with every DZT test still passing unchanged; `dt1.py`; the plugin
  changes in §6; CMP detection. DT1 goes first because its header is the most explicit and its
  time zero is verified, so it proves the seam with the fewest open questions.
- **M21b: MALÅ.** `mala.py`, `.rd7` preferred over `.rd3`, time zero at 0 with the note,
  multichannel refused.
- **M21c: SEG-Y (RadExplorer).** `segy.py` with the variant check, picosecond times,
  little-endian extension fields read but not yet used, spacing from the trace coordinate, float
  samples (and the C5 grep), and the time-zero check in the walkthrough.
- **M21d: GPS for the new formats** (C10). `.cor` and RadExplorer fixes into a `DzgLog`, the
  registry's `gps_for`, and `_plan_one` asking the registry. After M21b and M21c, so both of its
  sources have readers.

**Other work in flight** (measured 2026-11-24 against main at `f8374ed4`). M17c changes none of
M21a's files. M19 (unmerged) changes `placement.py` (+29), `model/survey.py` (+36) and two lines
of `import_dialog.py`. M21a touches `survey.py`'s imports and annotations, not its body, and only
the header annotations in `placement.py` (C1), so whichever merges second has a small rebase. Nothing has to merge
before M21a starts.

## 9. Testing

- **Synthetic writers**, one per format, in `tests/`, generate files with known headers and
  samples for round-trip tests, as the DZT writer does. They prove self-consistency only.
- **Real-data tests** read the §2 files from `tests/data/local/dt1/`, `mala/` and `segy/`, and
  skip when those are absent. They pin the measured facts: trace counts, sample intervals, the DT1
  time zero against the first break, the MALÅ `.rd3`/`.rd7` agreement, the SEG-Y spacing and the
  little-endian geographic flag (as a flag value, never as coordinates).
- **The DZT tests run unchanged.** Any DZT test that needs editing for M21a is a sign that C1 has
  leaked.
- **Privacy.** No real coordinate goes into any committed file: from a `.cor`, from a SEG-Y trace
  header, from the DT1 survey's coordinates file. A test that needs a coordinate uses a synthetic
  one.

## 10. Follow-up (not this milestone)

- **A pulseEKKO `.GPS` reader**, when a file arrives (M21d covers `.cor` and RadExplorer).
- **Marks** per format (C11).
- **More formats:** the `.gpr` files once their instrument is known; ReflexW, IDS `.dt`, Impulse
  Radar and Utsi when files arrive; other SEG-Y flavours (C9).

## 11. Out of scope

Writing any of these formats; converting between them; CMP velocity analysis; multichannel 3-D
arrays; uneven trace spacing.

## 12. Left to the builder

File and test names; where the shared companion lookup lives; whether `nsgeo.io.dzt`'s own
`read_header` stays public; the wording of each import note.

## 13. M21a's calls (2026-11-24, with its plan)

- **Two more base fields.** `RadarHeader` also carries `notes: tuple[str, ...]` (facts a reader
  wants the user told at import, such as a DT1 with no time zero in its header) and
  `not_a_profile: str` (empty for a profile; otherwise why the file is not one, such as C8's CMP
  sounding). The import shows the notes on the file's row, and a non-empty `not_a_profile` makes
  the row unticked and not placeable. Every reader fills both, so no format needs special handling
  in the plugin.
- **GPS mode keeps its DZT-only file filter until M21d**, revising §6. Offering DT1 in a picker
  that then refuses every DT1 would be a trap. A non-DZT file that reaches GPS mode anyway
  (through "All files") is refused with "no GPS log read for this format yet", not
  "no DZG beside it".
- **DT1 sample width comes from the file size.** `(size / NUMBER OF TRACES − 128) /
  NUMBER OF PTS/TRC` must be 2 or 4, and trace-header value 5 (bytes per point) must agree with it
  when it is non-zero. Both sample files are 2. pulseEKKO also writes 4-byte DT1s.
- **DT1 spacing is cross-checked cheaply**, from the first and last trace headers only, so
  `read_header` stays a stat and three small reads. A mismatch of more than 1 % adds a note, and
  the line is placed at the header's step.
- **Feet are converted:** `POSITION UNITS` of `ft` gives `1 / (step × 0.3048)` traces per metre.
  Any other unit gives 0, which the import already treats as time-triggered.

## 14. M21b's calls (2026-11-25, with its plan)

- **An `.rd3` reads as its samples shifted left 16 bits**, revising C5's "no scaling" for this one
  case. §2's measurement shows the `.rd3` is the `.rd7` with its low 16 bits dropped, so the
  shift puts both files of a line on one amplitude scale, and an `.rd3` line and an `.rd7` line on
  one grid slice together without a 65,536× stripe. The values fit `int32` (32,767 × 65,536 <
  2³¹). An `.rd3` with no `.rd7` (older RAMAC systems write only `.rd3`) loses nothing: every
  amplitude is multiplied by the same constant.
- **The time axis comes from `SAMPLES` and `FREQUENCY`.** `range_ns = SAMPLES × 1000 / FREQUENCY`.
  `TIMEWINDOW`, when present, must agree to within 1 %, or the file is refused: a wrong time axis
  would be silent everywhere downstream.
- **Spacing:** `DISTANCE FLAG` 1 and `DISTANCE INTERVAL` above 0 give `1 / DISTANCE INTERVAL`.
  `(STOP POSITION − START POSITION) / (LAST TRACE − 1)` is cross-checked, and more than 1 % apart
  adds a note, as DT1's positions do. Distance-triggered with no interval gives 0 with a note. Any
  other trigger gives 0, which the import already calls time-triggered.
- **C4 is a registry field, not MALÅ code in the plugin.** `RadarFormat.prefer` lists extensions
  that hold the same traces, best first (MALÅ: `.rd7`, `.rd3`). When one stem in one folder is
  chosen in more than one of them, the import leaves all but the best unticked with a note, and
  any of them can be ticked by hand. A preferred file that cannot be read does not untick the
  other.
- **Multichannel (C13) is detected two ways, neither verified against a real file**, since none is
  in hand: a `.rad` with a `CHANNELS` or `NUMBER OF CH` key above 1, or a stem ending `_A<n>` with
  another `_A<m>` of the same stem and extension beside it. The second is checked before the
  `.rad` is looked for, because a multichannel set may have one `.rad` for all its channels. A
  lone `…_A1.rd3` with its own single-channel `.rad` reads as one channel.
- **Antenna** is `ANTENNAS` with MALÅ's trailing `=<n>` code removed (`GX450 HDR (v.1)`).
  `epsr` is 0: the `.rad` has none, and the import's dielectric note asks for a velocity.
- **GPS mode stays DZT-only**, and the `.cor`, `.mrk` and `.srd` are not read (C10, C11).

## 15. M21c's calls (2026-11-25, with its plan)

- **The static shift is undone**, revising C5's "no per-format decoding" for a second case. §2's
  measurement shows RadExplorer moved each trace down by its static and padded it with zeros, so
  the samples as stored are not the samples recorded, and a time slice through them would cut
  each trace at a different time. When any trace's static (bytes 101–102) is non-zero, each
  trace is read from its first non-zero sample, and the line has as many samples as its longest
  run of samples from first non-zero to last non-zero (344 or 424 here, not 2,006–2,478). The
  shift comes from the zeros, not the static, because the static is rounded to whole
  nanoseconds. The static is the cross-check instead: a trace whose zeros disagree with it by
  more than 4 samples plus 1 % of the shift is refused (the real traces come within 2.6 samples plus the drift, at most 0.87 of a 3-sample allowance, too close), since a trace whose real data begins
  with exact zeros would otherwise be cut. The topography the statics carried is not used (no
  milestone reads elevation yet), and a note says the shift was undone. Bogus trace-0 statics
  need no special case: that trace's zeros undo it like any other.
- **Time zero is `−delay`**, revising C6's `+delay` against §2's measurement. The delay must
  be the same on every trace, or the file is refused.
- **Spacing is the mean of the regular steps, and jumps are a note**, revising C7's "else 0
  with a note". A step is the distance between consecutive traces' (X, Y), with the coordinate
  scalar applied. It is regular when within 5 % of the median step. `traces_per_metre` is 1 over
  the mean regular step (68.44 mm here, where integer millimetres make the median 68). Any
  irregular step adds a note naming how many and the largest, and the line is placed at the
  even step. C7's 0 would untick a wheel-triggered line as if it were timed, and one 3 m jump
  near the end of a 40 m line does not make it timed. Placing the traces at their true distances
  is M17b's work. Coordinates that do not move at all give 0 with no note (the import's
  time-triggered note covers it). Arc-second coordinates (units 2) give 0 with a note. The
  coordinates themselves are never kept in the header: X and Y may be real eastings and
  northings, so only the step and the jump count are.
- **What makes a file RadExplorer:** `RadExplorer` in its text header, decoded as EBCDIC (or
  as Latin-1 when its first byte is an ASCII `C`). Then format code 5, read big-endian, no
  extended text headers, every trace with the binary header's sample count and interval, and a
  file size of whole traces. Anything else is refused by name. The revision word is not
  checked: these files say 0 and follow the 1975 layout.
- **The little-endian geographic flag is counted, not used.** `SegyHeader.geographic_traces` is
  how many traces have it set (all of them here). The coordinates are not read until M21d, and
  M21d reads them from the data file itself, not from a companion, so C10's `gps_for` will need
  to allow that.
- **Marks are not read** (C11). §2's correction (little-endian flag 1, not 0x55) is for the
  marks follow-up.
- **The sample interval is the stored 406 ps**, though §2 suggests 0.4069 ns. 0.22 % is 0.4 ns
  at the bottom of a 424-sample trace, and correcting it would be a guess.
- **`read_header` reads the whole file** when the traces are static-shifted, because the line's
  sample count depends on every trace's zeros. The largest sample file is 10.9 MB. `trace_count`
  stays a stat.
- **Antenna** is empty and `epsr` 0: the file names neither. The facts line shows `antenna ?`.
- **GPS mode stays DZT-only** (C10).

## 16. M21d's calls (2026-11-25, with its plan)

- **Lines without RTK are placed on their raw fixes, with an option to smooth** (the author's
  call, 2026-11-25), revising M17a's RTK-only rule for these lines. Neither new source has an RTK
  fix (§2), so without this nothing in hand would place.
  - `TrackPlacement` gains `anchor_on` (`"rtk"`, the default, or `"all"`) and `smooth_m`
    (0, the default, is as recorded). `"all"` anchors on every fix with a position.
  - `track_from_log` chooses: at least two RTK-fixed positions anchor on those, as now; fewer
    anchor on all. A line with any two RTK fixes behaves exactly as before.
  - **This reaches DZT lines too.** A DZT whose log never reached two RTK fixes was refused
    (`no RTK-fixed position`, `only one RTK-fixed position`) and is now placed on its fixes, with
    the same note as any other format. A GSSI log without RTK is the same situation as a MALÅ
    one, and treating them differently by format would be arbitrary. The M17 tests that pin
    those two refusals change, and only those.
  - `smooth_m` replaces each anchor's position with the mean of the anchors within
    `smooth_m / 2` of it along the anchors' own path, the window shrinking at the ends. It
    applies to `"all"` tracks only: an RTK track is already centimetric, and smoothing it would
    cut corners. 0 is off.
  - The GPS import has one smoothing setting for every line it places without RTK, and the Edit
    lines dialog changes it per line afterwards. The raw fixes are always kept, so smoothing can be
    changed or undone.
  - **Schema:** both fields are written only when not the default. A site with any line that has
    them saves as a new version, `TRACK_ANCHOR_SCHEMA_VERSION`, so an older build refuses it
    rather than failing to place the line. M19 (unmerged) also adds version 5; whichever merges
    second chains its constant from the other's.
- **A note on each row placed without RTK**, naming how many fixes, and the smoothing when it is
  on. The import's RTK columns stay as they are (`0 of 283` fixes, no bridge).
- **GPS length against the wheel.** Whenever the line has a wheel spacing, the import compares
  the wheel's length with the GPS track thinned to fixes at least 5 m apart. More than 20 % apart
  adds a note naming both, on any format. On the data in hand that flags all 18 SEG-Y lines
  (2.0–2.4×) and three of the eight MALÅ lines (1.28–1.49×). nsgeo does not pick one: GPS
  placement uses the GPS, and grid placement uses the wheel.
- **Each format names its GPS source through the registry** (C10): `RadarFormat.read_gps(path,
  header, n_traces) -> DzgLog`, or `None` for a format with none (DT1, until a `.GPS` arrives).
  A line with no log raises `NoGpsLog(RadarFileError)` with its own reason: `no DZG beside it`,
  `no DAT_0001.cor beside it`, or `its traces carry no GPS positions`. C10 assumed a companion
  file; SEG-Y's fixes are inside the data file, which this signature allows.
- **MALÅ `.cor` into a `DzgLog`:** one fix per row, trace number minus 1, quality as given, the
  altitude kept, no geoid. Trace numbers must rise and lie in 1–`LAST TRACE`, or the log is refused,
  as a DZG's are.
- **SEG-Y geographic fields into a `DzgLog`:** one fix at the first trace of each run of equal
  positions (repeats would otherwise bunch traces up and then jump), only when the trace's flag
  is 1, quality `QUALITY_UNKNOWN` (−1, a new constant beside `RTK_FIXED`), no time or altitude.
- **GPS mode reads every format with a GPS source**, revising §13: its picker lists them from the
  registry, and a MALÅ pair chosen in GPS mode keeps only the `.rd7`, by the same `prefer` rule as
  Grid mode. DT1 still gets `no GPS log read for this format yet`.
- **Privacy:** no real coordinate in any committed file. Real-data tests assert counts, quality
  values, trace numbers, scatter and length ratios only.
