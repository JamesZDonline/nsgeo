### Task 6: Docs, roadmap, guide

**Files:**
- Modify: `docs/guide/getting-started.md`: the export step (the dialog, export cell and pixel,
  background progress, the style file) and a plain coverage explanation (#157 item 6, cheap to do
  here).
- Modify: `README.md`:
  - add #157 to the Wishlist (Slices group);
  - in the PR, "Whole site at fine cells: the export" moves to Done (next release).

- [ ] **Step 1:** Write the guide text in plain words. Mention the style file loading in other QGIS
  projects, and that other GIS software reads the values but chooses its own colours.
- [ ] **Step 2:** Update the README.
- [ ] **Step 3: Commit:** `docs: the export dialog and background export in the guide; roadmap`.

---

## After the tasks (coordinator)

- **Whole-branch review** (opus), then one fix wave.
- **Deploy to a new profile and walk through spec §8.2** (a human gate) on the real ten-grid site:
  - export at 0.025 m, and at 0.05 m with a 0.025 m pixel;
  - cancel one mid-way;
  - keep using the panel during an export;
  - open the files in a fresh QGIS project, where the style applies, and step through depths;
  - if available, open one in another GIS.
- **The build record** and the README roadmap go in the PR.
