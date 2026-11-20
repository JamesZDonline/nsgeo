### Task 2: The guide

**Files:**
- Modify: `docs/guide/getting-started.md`. Lines as of 0255dbd:
  - the toolbar table, 98–118;
  - Step 9, 837–847;
  - Making a surface from picks step 2, ~926;
  - The 3D view, ~959;
  - the `paraview` folder row, ~1003.

**Interfaces:**
- Consumes: Task 1's copy. The guide writes a menu choice as the Add data rows do: "Click **3D Analysis ▾**, then **Export for ParaView…**".

- [ ] **Step 1: Make the edits.**
  - **Toolbar table:** the **Surface from picks…** and **3D view** rows become one row, `| **3D Analysis ▾** | The 3-D tools. … |`. It holds each entry's current description in its own sentence, with its existing link, and adds **Export for ParaView…** with a link to `#step-9-export-for-paraview`.
  - **The greyed-out sentence** under the table becomes: "**Save site**, **Add grid…**, **Add data**, **Cut** and **3D Analysis** stay greyed out until a site is open, and **Pick** and **Velocity** until a line is open."
  - **Step 9's opening** says the export is **3D Analysis ▾ → Export for ParaView…** on the nsgeo toolbar, instead of a button on the Slices panel beside Save cube… and Export GeoTIFF…. It keeps the rest: on whenever a site is open, in either scope, with no prepared slice source needed, and never changing what the Slices panel shows.
  - **Step 9's step 1:** "Click **3D Analysis ▾**, then **Export for ParaView…**. The dialog opens on the Slices panel's grid."
  - **Making a surface from picks, step 2:** "Click **3D Analysis ▾**, then **Surface from picks…**."
  - **The 3D view's first line:** "Click **3D Analysis ▾**, then **3D view**, to open …".
  - **The `paraview` folder row:** "**Export for ParaView…** writes it again."

- [ ] **Step 2: Check.**
  - Run: `grep -n "ParaView…\*\*\|Click \*\*3D view\|Click \*\*Surface from" docs/guide/getting-started.md`. Expected: only the new menu-path wording, with no bare **ParaView…** button left.
  - Run: `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_release_docs.py`, from the main checkout's venv. Expected: PASS.

- [ ] **Step 3: Commit and push.**

```bash
git add docs/guide/getting-started.md
git commit -m "docs(guide): the 3D Analysis drop-down in the toolbar table, Step 9, surfaces and the 3D view (#227)"
git push origin nsgeo-3d-menu
```
