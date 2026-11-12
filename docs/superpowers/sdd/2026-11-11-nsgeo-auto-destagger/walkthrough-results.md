# #159 Measure walkthrough results

Run by the author on 2026-11-12, on a copy of the Nashville City Cemetery site
(profile `ns_geo_destagger`, branch at 24a94b9). The results come from the
walkthrough page's database; the notes are the author's own.

| Check | What | Result | Author's note |
|---|---|---|---|
| A1 | The Measure button | pass | |
| A2 | Measure Grid1 as walked | pass | About 10 seconds. The long status line made the dialog very wide, so OK was hard to reach: needs fixing. |
| A3 | Judge the wiggle | pass | It looks good. |
| A4 | Grid1 fitted | pass | At 13.4–18.2 ns the south-west blob looks wavy, so it may depend on what I was trying to focus on. It mostly comes together deeper. |
| B1 | Grid2 as walked | pass | |
| B2 | Grid2 fitted | pass | I should have saved GeoTIFFs of the unchanged ones, but I believe this one is better. It looks great! |
| C1 | Stop | pass | |
| C2 | Edit while it measures | pass | |
| C3 | A Destagger edit doesn't count | pass | |
| C4 | Measure twice | pass | |
| C5 | Close while it measures | pass | |
| C6 | Only the selected rows fill | question | Surprised it measured the whole grid when only ten lines were selected; asked why that is better or worse than measuring only those ten. |
| D1 | Grid4 has every line walked the same way | pass | Why read the whole grid first, instead of checking the directions before measuring? |
| E1 | Stop forgets what it read | pass | |
| E2 | No selected row on this grid | skip | |
| E3 | No file could be read | skip | |
| E4 | Values to the millimetre | pass | |
| E5 | Six names, then a count | pass | Doesn't like the "long info in a tooltip" model, but it's fine for now. |
| E6 | Cells show centimetres | pass | |
| E7 | Lines Measure can't use are named | skip | |
| E8 | The panel stays usable while measuring | pass | |

E2, E3 and E7 were skipped, so those cases are covered only by the automated
tests (`test_measure_with_every_selected_row_on_another_grid_starts_nothing`,
the all-unreadable summary in `test_summary_words`, and
`test_when_every_line_is_too_short_the_axis_says_none_could_be_measured`).

## What followed

- **A2:** the status line wraps (6d4733e). Re-checked by the author: good.
- **D1:** a grid walked one way is known from the placements alone, so it is
  not read (`one_way_result`, 6d4733e). Re-checked by the author: good.
- **C6:** explained: a line is judged against the lines beside it, and the
  grid value from all lines is about twice as certain as from ten. The author
  kept the whole-grid measure; the tooltip and the guide now say the selection
  only chooses which rows get filled (871eee8). Re-checked: fine. A "measure
  the selection on its own" option, for a grid walked in two sessions, was
  offered as a follow-up and not filed.
- **A4** is the cost of one shift per line at every depth, the author's own
  rule; such lines can be adjusted by hand.
- **E6** confirms Ruling 13: the Destagger column keeps two decimals.
