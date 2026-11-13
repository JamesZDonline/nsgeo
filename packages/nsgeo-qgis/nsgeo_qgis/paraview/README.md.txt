# Your grid in ParaView: things to try

This folder is an export from nsgeo. Nothing here changes your survey.

**To open it,** run `open.sh` (Linux and macOS) or double-click `open.bat` (Windows). It starts ParaView with the scene set up, which takes a few seconds. If ParaView is installed somewhere else, edit the path in that file.

`export.json` records how the export was made: the source, fill and volume settings, the stretch, the coordinate system and the nsgeo version.

## What's in the scene

- **The cube** is your grid as the Slices panel builds it, prepared for 3-D: the energy is averaged over one full radar wave and square-rooted, lightly blurred sideways, and balanced against the depth trend. The settings are in `export.json`.
- **The axes:** x runs along the grid's X axis and y along its Y axis, in metres from the grid's corner. `export.json` gives the grid's real-world origin and azimuth.
- **Depth is stretched** by the factor in the title on screen, so layers are easier to see. The depth legend always shows true depth.
- **"Strength"** is each spot's amplitude divided by the typical amplitude at that depth. 1 means ordinary for its depth and 10 means ten times stronger than usual. Without this, the strong near-surface would drown everything else.
- **Your picks** are shown as balls, coloured by depth with the same colours as the isosurface.
- **Surfaces** are the ones you built from your picks, one item each, named "Surface: " and the name you gave it. They are hidden when the scene opens: click the eye next to one to show it. A surface is coloured by true depth with the same colours as the isosurface and the picks. One marked "(stale)" shows its last build: something it was built from has changed since, so rebuild it in nsgeo to bring it up to date. `features.vtp` holds them all (each point carries `true_depth_m`, `feature` and `stale`), and each pick in `picks.vtp` carries the `feature` it belongs to, or -1. `export.json` lists them with how many picks each used and how many of those it passes within 2 cm.
- **The survey lines** are drawn at ground level, with the grid outline. Where lines don't reach, the slices show a hole.

## Getting about

- **Turning things on and off:** the **Pipeline Browser** on the left lists everything in the scene. Click the eye next to an item to show or hide it.
- **Changing settings:** click an item, change its settings in the **Properties** panel, then press the green **Apply** button.
- **Moving the camera:**
  - left-drag rotates;
  - the scroll wheel zooms;
  - middle-drag (or Shift + left-drag) pans.
- **Getting the whole scene back:** the **Reset Camera** button on the toolbar.
- **Looking straight down or from a side:** the **+Z**, **-Y** and similar buttons on the toolbar.

## Things to try

1. **The cloud.** It's on when the scene opens. Strong spots glow and ordinary ground is see-through. Rotate it.
2. **Showing more or less of the cloud.**
   - Click **Cloud**.
   - Open **View > Color Map Editor**.
   - The upper graph is the see-through curve. Drag its points:
     - left to show more of the cloud;
     - right to show only the strongest spots.
3. **The isosurface.**
   - Hide **Cloud** and show **Isosurface**. It is a skin around everything stronger than one level, coloured by true depth.
   - In its Properties, change the value under **Isosurfaces** (it starts at the level in `export.json`), then press Apply. Each change takes a second or two.
   - Try a lower and a higher level. Lower levels join shapes up; higher ones leave fewer, tighter ones.
4. **Just part of the volume.**
   - Show **Isosurface inside a box** and hide **Isosurface**.
   - It keeps only what lies inside a box in the middle of the grid, which strips away the busy near-surface.
   - Drag the box's faces to change what it keeps, then press Apply.
5. **Slices in three directions.** Show them one at a time.
   - **Depth slice** is what you're used to. Drag the plane, or its arrow, to move it up and down.
   - **Slice along a line** stands in the direction of the survey lines, so it shows a radargram taken from the cube.
   - **Slice across the lines** is a section across all the lines, which no single line gives you.
   - Black is strong, as in the Slices panel.
6. **Picks against the data.** With the isosurface or a slice on, do your picks sit on the strong reflections?
7. **Saving a picture:** **File > Save Screenshot.**

## Worth noticing as you go

- Which of these showed you something you couldn't see in slices?
- Which would you want to show to someone who doesn't read slices?
- Which did nothing for you?
