# Task 1 report: nsgeo.slices.site

## Implemented
`packages/nsgeo-core/src/nsgeo/slices/site.py` (~370 lines), exports added to `slices/__init__.py`,
tests in `packages/nsgeo-core/tests/test_slices_site.py` (39 tests, 4 on real data, which RAN).

Choices where the brief left one:
- `covering`: integer pixel indices with `to_north_up`'s scale-aware epsilon (`64*eps*max(1,|coord|)/pixel`) applied to floor (west/south) and ceil (east/north); `x0 = ix0*pixel`, `y1 = iy1*pixel`, width/height = index differences (min 1).
- `background_level`: weakest `ceil(0.75*n - 1e-9)` cells, at least 1 (n=1 keeps itself, n=8 keeps 6). Non-finite magnitudes dropped.
- `site_axis`: union is the envelope (min start, max end); single-level result (hi == lo) returns `ZAxis(lo, dz, 1)` since `from_range` rejects equal ends; hi < lo or no bounds returns None.
- `grid_axis` also clips to the site axis (k in 0..nz-1).
- Connected components: small union-find. Seam terms naming grids not in `levels` are ignored.
- `edge_match_solve`: a multi-grid group with no known level keeps its minimum-norm lstsq solution (mean-zero in the group, so relative balancing survives; only singletons get exactly 1.0). Brief says "keeps gain 1.0"; true for lone grids, ambiguous for such groups.
- `normalise("background")` = `edge_match_solve(levels, [])`, so it shares the anchoring/renormalisation code. `"edge"` drops seams whose strip level is None and weights by `min(mask_a.sum(), mask_b.sum())`.
- Histogram: `np.std` (population), pooled over every grid's populated finite cells.
- Real tests: lines keep world positions `y = 0.25 + i*0.5`; A origin (0,0), B origin (0,2.6), nx=100 ny=13 cell 0.2, windows k0 = 10+20k thickness 18 levels, k = 0..4, `amp_envelope` transform. Mixed azimuth test: B rotated 2 deg clockwise about its origin (0, 2.6); line world coords = origin + lx*x_hat + (y-2.6)*y_hat.
- Test design notes: the chain edge test uses a field constant along x (a random field makes the two strips differ by sampling noise, so exact recovery is impossible); the test file defines its own `FILES`/`needs_real_files` (needs >= 10 files) rather than the module-level skip in test_real_files.py.

## Tests
- Core + pure tier: `./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q` -> 585 passed, 2 skipped (the two pre-existing schema skips). New file alone: 39 passed, none skipped.
- QGIS tier: see bottom.
- ruff check, ruff format --check, mypy: all clean.

## TDD
RED: with `site.py` and the exports absent, `pytest packages/nsgeo-core/tests/test_slices_site.py -q` -> `ImportError: cannot import name 'NORMALISATION_METHODS' from 'nsgeo.slices'`, "1 error" at collection (expected: nothing exists yet).
GREEN: first run after implementing 38 passed, 1 failed (my chain test used a random field; fixed the test, not the code, as described above); then `39 passed`.

## Mutants (PYTHONDONTWRITEBYTECODE=1; each reverted, 39 passed afterwards)
| # | mutant | failing tests |
|---|---|---|
| 1 | background over all populated cells | background_level three_quarters; ignores_unpopulated; measures_magnitude (3) |
| 2 | values not abs | background_level_measures_magnitude_on_signed_data |
| 3 | arithmetic site mean | an_isolated_grid_takes_its_background_gain |
| 4 | edge sign flipped | edge_match_recovers_known_gains_along_a_chain; spreads_a_loop_closure_error; real_split_background_and_edge[edge] |
| 5 | anchoring removed | background_gains_have_geometric_mean_one; each_connected_group_is_anchored; isolated_grid; real_split[background] |
| 6 | lattice_pixel always cell | rotated_frame_loses_no_cell_at_half_pitch x4; lattice_pixel_is_the_cell_for_right_angles; real_halves_at_different_azimuths |
| 7 | covering anchored at min xmin | lattice_is_anchored_on_whole_multiples_of_the_pixel |
| 8 | window_on without 1e-6 snap | window_on_agrees_with_the_site_axis_at_every_slider_position |
| 9 | compose keeps first layer | compose_averages_overlaps_and_leaves_uncovered_pixels_nodata |

Note: mutant 3 is caught only by the isolated-grid test: the final geometric-mean renormalisation hides it elsewhere. Mutants 1-3 are invisible to the real-data ratio tests by design (a multiplicative perturbation scales every statistic).

## Files
- packages/nsgeo-core/src/nsgeo/slices/site.py (new)
- packages/nsgeo-core/src/nsgeo/slices/__init__.py (re-exports)
- packages/nsgeo-core/tests/test_slices_site.py (new)

## Self-review
Nothing outstanding. `_distance_to_footprint` is private helper beyond the brief. Concern: none blocking.

## QGIS tier
`QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh` -> 723 passed in 361.81s (run started before a type-only refactor of edge_match_solve for mypy; core/pure tier re-run after it, 585 passed).

## Fix round 1
Changes: (1) real split test now asserts edge's unperturbed a_B/a_A equals the strips' S_AB/S_BA (a test-local helper `_strip_ratio` that computes the 75% level itself from `seam.mask_a/mask_b`, independent of `background_level`) and differs from background's ratio (rel 1e-4; the gap is only 0.4% in window 0, so the exact strip equality is the real guard). (2) `Seam` is `@dataclass(frozen=True, eq=False)`; new `test_a_seam_compares_and_hashes_without_raising`. (3) new `test_real_chain_edge_match_recovers_gains_and_equals_the_pairwise_solve`: A ny=8 lines 0-2, B origin (0,1.6) ny=7 lines 3-5, C origin (0,3.0) ny=11 lines 6-9, five windows, g_B = 0.5*exp(-k/4), g_C = 1.6*exp(-k/3); find_seams gives exactly A-B and B-C (no A-C); both gains recovered; global equals pairwise via independently computed strip levels. Geometry and the 20-cell minimum worked as specified; nothing bent.
Mutants (PYTHONDONTWRITEBYTECODE=1): mask-ignoring `background_level` -> FAILS test_background_level_ignores_unpopulated..., test_real_split...[edge], test_real_chain...; Seam with default eq -> FAILS the new Seam test. Both revert to green.
Results: `pytest packages/nsgeo-core/tests/test_slices_site.py` 41 passed; core+pure tier 587 passed, 2 skipped; ruff check, ruff format --check, mypy clean. QGIS tier not re-run, per instruction.
