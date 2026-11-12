### Task 4: Review, deploy and walkthrough (coordinator and author; a human gate)

- [ ] Run the full QGIS tier, then a whole-branch review (opus). Then do a fix wave if needed.
- [ ] Deploy to a new profile `ns_geo_destagger`. Copy `ns_geo` with `cp -a`, then run `packages/nsgeo-qgis/scripts/dev_link.py` pointed at this worktree.
- [ ] Publish a walkthrough Artifact with a `db` capability for results, covering spec §10's walkthrough list:
  - Grids 1 and 2, unfitted and fitted;
  - judging the wiggle at 14.9–19.7 ns;
  - cancel mid-measure;
  - editing during a measure;
  - pressing Measure twice;
  - a one-direction grid.
- [ ] Stop and wait for the author's results. Update the README roadmap ("In progress": built, walkthrough pending). Merging asks first.
