# M18: the rest of #75 (core `site.py`, survey memory, tooling)

Session H (#235, 3c66d1e) closed #75's Site engine, Site export and Whole
site UI sections. This batch takes the three sections still open. Every item
was first checked against main.

## Core: `nsgeo/slices/site.py`

1. **Seam weights.** Write a loop test through `edge_match_solve` (weights
   100, 1, 1) and one through `normalise("edge")`, where one seam's strips
   hold 200 and 2 cells. Each asserts every seam's share of the closure
   error. Run three mutants: sqrt(weight) ignored, weight with no square
   root, and max for min. The new tests must fail on each; the old tests
   must not catch them.
2. **"gain 1" docstring.** Rewrite it. Add a test where a grid with level
   None is moved by the final shift to 2^-1/4.
3. **`compose`.** Already gone: `compose` was retired in 0776c4d.
   `compose_footprints` reads through `resample._flat32`, which has raised on
   a shape mismatch since 305b824. Add a test pinning that.
4. **`background_level`.** Use `np.partition`. Firstmate's ruling: agreement
   with the full sort to rtol 1e-12, not bit-identity. Measured: at most a
   4 ulp difference, and 5x faster at 200k cells.
5. **`_snap_eps`.** Move it to `display.snap_eps`, shared by `frame_lattice`
   and `SiteLattice.covering`.
6. **Dead helper.** Remove `coverage(n_strip)`.

## Survey memory: all done in fb14a06

- The `_remember_source` docstring names `restore_cube`.
- `test_a_default_line_choice_picks_up_an_import_after_save_and_reopen` and
  `test_an_explicit_line_choice_does_not_pick_up_an_import_after_save_and_reopen`
  cover the save, reopen and import path.
- `test_opening_a_survey_that_has_saved_cubes_stays_clean` covers opening a
  survey that already has saved cubes.

## Tooling and docs

- `bench_site.py`: import the public names from `nsgeo.geometry` and
  `nsgeo.model`.
- `test_plugin_slice_export.py`: fb14a06 fixed the original 7 places.
  4 `ds = None` came back in later tests; give them an explicit `Close()`.
- `SliceLayer.update_north_up` docstring: left out. `nsgeo-m19-mag` rewrites
  `slice_layer.py`, so this waits until M19 merges. The PR says "Refs #75".
