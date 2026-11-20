### Task 1: Read DZG files (nsgeo-core)

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/io/dzg.py`
- Modify: `packages/nsgeo-core/src/nsgeo/io/__init__.py` (export the five names below, sorted)
- Create: `packages/nsgeo-core/tests/dzg_data.py`, `test_dzg.py`, `test_dzg_real_files.py`
- Modify: `packages/nsgeo-core/README.md` (a short DZG paragraph under the io section, naming each public name in backticks)

**Interfaces (produced):**

```python
# nsgeo/io/dzg.py
RTK_FIXED: int = 4
class DzgError(ValueError): ...

@dataclass(frozen=True)
class DzgFix:
    trace: int                # 0-based DZT trace index, from the $GSSIS before the GGA
    utc_s: float | None       # GGA time, seconds of the UTC day
    lat: float                # degrees, S negative; NaN when the GGA has no position
    lon: float                # degrees, W negative; NaN likewise
    quality: int              # GGA fix quality: 4 RTK fixed, 5 float, 1 GPS, 2 DGPS, 0 none
    n_sats: int | None
    hdop: float | None
    alt_m: float | None       # antenna altitude above mean sea level (GGA field 9)
    geoid_m: float | None     # geoid separation (GGA field 11)

@dataclass(frozen=True)
class DzgLog:
    fixes: tuple[DzgFix, ...]    # in file order; traces strictly rising
    bad_checksum: int
    unpaired: int
    @property
    def n_fixed(self) -> int: ...   # fixes with quality == RTK_FIXED

def dzg_for(path: str | Path) -> Path | None: ...   # the .DZG beside a .DZT, either case; dzx.sidecar_for's directory-listing rule
def read_dzg(path: str | Path, n_traces: int | None = None) -> DzgLog: ...   # P2; checks the trace range only when n_traces is given
```

- [ ] **Step 1: Write the failing tests.**
  - `tests/dzg_data.py` is a helper.
    - `write_dzg(path: Path, fixes: Sequence[tuple[int, float, float, int]], *, talker: str = "GN", alt_m: float = 120.0, geoid_m: float = 47.5) -> Path` writes, for each `(trace, lat, lon, quality)`:
      - `$GSSIS,{trace},-1`;
      - then a `${talker}GGA` with the real files' field layout. For a made-up fix that is `$GNGGA,163915.40,4512.3456789,N,01030.1234567,E,4,22,0.6,120.000,M,47.500,M,1.4,0000*hh`, where `hh` is the computed checksum: 7 decimals of minutes, satellites, HDOP, altitude and geoid separation each followed by `M`, correction age, station id. The time steps 1.0 s per fix from 163915.40. Never copy a sentence from a real file into a test or a doc.
      - CRLF line ends, as the real files have.
    - It also has `local_xy(lat0: float, lon0: float)`, which returns a `(lon, lat) -> (x, y)` function: a local equirectangular projection in metres about that point. Real-data tests use it so that they assert relative distances only. It is Task 2's `ToXY` shape; Task 1 only defines it.
  - `test_dzg.py`:
    - `test_reads_gssis_and_gga_pairs_in_order`: fixes at traces 13, 26, 47 round-trip with their quality, `alt_m`, `geoid_m`, `n_sats` and `hdop`. `lat` and `lon` decode ddmm.mmmmmmm with the hemisphere: `4512.3456789,N` gives `45 + 12.3456789/60`, `01030.1234567,E` gives `10 + 30.1234567/60`, and an `S` or `W` hemisphere is negative. `utc_s` of `163915.40` is `16*3600 + 39*60 + 15.4`.
    - `test_any_talker_reads_as_gga`: `talker="GP"` reads the same fixes.
    - `test_other_sentences_are_ignored`: a `$GNRMC,…` line between two pairs changes nothing.
    - `test_a_bad_checksum_drops_the_sentence_and_counts_it`: one GGA's checksum is altered. That fix is missing, `bad_checksum == 1`, and `unpaired == 1` (its `$GSSIS`).
    - `test_a_gga_with_no_preceding_gssis_is_unpaired`.
    - `test_a_gga_with_no_position_reads_as_nan_with_its_quality`: `$GNGGA,163916.40,,,,,0,0,,,M,,M,,*hh` gives `quality == 0` with NaN lat/lon and `None` for the rest.
    - `test_trace_numbers_that_do_not_rise_are_refused`: traces 40 then 12 raise `DzgError` matching `r"x\.DZG: trace numbers must rise, but 40 is followed by 12"`. 40 then 40 is refused the same way.
    - `test_a_trace_beyond_the_dzt_is_refused`: `read_dzg(p, n_traces=50)` on a fix at trace 50 matches `r"names trace 50, but the DZT has 50 traces"`. With `n_traces=None` it reads.
    - `test_dzg_for_finds_either_case_and_none_when_absent`: `a.DZT` with `a.dzg` beside it gives `…/a.dzg`. With nothing beside it, None.
  - `test_dzg_real_files.py`, using `GPS_LINES` and `GRID2_LINES` from `tests/real_data.py`, each test skipping on an empty list:
    - `test_every_gps_line_has_a_dzg_that_reads_cleanly`: for every DZT in both lists, `dzg_for` finds the DZG, `read_dzg(dzg, trace_count(...))` succeeds, and `bad_checksum == unpaired == 0`.
    - `test_the_first_survey_is_rtk_fixed_throughout`: 2,999 fixes over the 60 lines, all quality 4.
    - `test_the_second_survey_has_float_fixes_on_two_lines`: 2,523 fixes. The non-4 fixes, keyed by file name within `GRID2_LINES`, are exactly `{"FILE__039.DZG": [190, 212, 239], "FILE__042.DZG": [1753, 1754]}`, all quality 5.
- [ ] **Step 2: Run them and see each fail** (import error first).
- [ ] **Step 3: Implement `nsgeo/io/dzg.py`** to P2. The checksum is the XOR of every character between `$` and `*`.
- [ ] **Step 4: Run core + pure, lint and types.** All pass, and the skip count is unchanged.
- [ ] **Step 5: Commit** (`feat(core): read GSSI DZG GPS logs (#134)`) and push.

---

