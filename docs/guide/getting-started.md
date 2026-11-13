# Getting started with nsgeo

nsgeo is a QGIS plugin for processing GPR surveys in their map context. You import
GSSI DZT files into a grid placed on the map, then view and process each profile
while the map shows where you are on the line. You can also pick reflections and
build time and depth slices across a grid.

This guide covers nsgeo 0.4.0. It is **experimental**, so keep
backups of your site folders. You need QGIS 3.40 to 3.44, or QGIS 4.x. You do not
need to install anything else.

1. [Install](#1-install)
2. [The toolbar and the five panels](#2-the-toolbar-and-the-five-panels)
3. [A first session](#3-a-first-session)
4. [Where your data lives](#4-where-your-data-lives)
5. [Known issues in 0.4.0](#5-known-issues-in-040)
6. [Reporting a problem](#6-reporting-a-problem)

---

## 1. Install

### Windows

1. Download `nsgeo_qgis-0.4.0.zip` from the
   [Releases page](https://github.com/JamesZDonline/nsgeo/releases). It is listed
   under **Assets**. Download that file, not the *Source code* downloads listed
   beside it, which will not install. Do not unzip it, because QGIS installs the
   zip file as it is.
2. In QGIS, open **Plugins → Manage and Install Plugins…** and choose **Install
   from ZIP** on the left.
3. Click the **…** button next to **ZIP file**, choose the zip, and click
   **Install Plugin**.
4. QGIS shows a **Security warning**: *"Installing a plugin from an untrusted
   source can harm your computer. Only continue if you received the plugin from a
   source you trust."* QGIS warns like this about plugins installed from a zip
   rather than from its own plugin list. Click **Yes** if the zip came from the
   Releases page above or from a colleague you trust.
5. When QGIS reports *Plugin installed successfully*, close the Plugins window
   and **restart QGIS**: close it completely and open it again.
6. To check the install, choose **Plugins → nsgeo → About nsgeo**. The message
   bar above the map should show `plugin 0.4.0 · core 0.4.0 · build`, followed by
   a 12-character code.

Restarting matters. Until QGIS restarts, it can keep parts of an earlier nsgeo
in memory, and old and new parts mixed together can misbehave in ways that are
hard to diagnose.

If the nsgeo toolbar is missing after the restart, open **Plugins → Manage and
Install Plugins… → Installed** and tick **nsgeo**.

### macOS (untested)

The steps are the same, from the **Plugins** menu inside QGIS. Safari unzips
downloads by itself, leaving a folder where QGIS needs the zip file, so turn off
**Open "safe" files after downloading** in Safari's **Settings → General** before
you download, or use another browser. nsgeo 0.4.0 has not been tried on a Mac.
If you try it, please report what happens, whether it works or not (see
[Reporting a problem](#6-reporting-a-problem)).

### Linux

The steps are the same. Every release is checked by installing its zip into
QGIS 3.40, QGIS 3.44 and QGIS 4.2 on Linux.

### Upgrading

Install the new zip exactly as above. QGIS replaces the old version. Then
**restart QGIS** and check **Plugins → nsgeo → About nsgeo** for the new
version number. Upgrading does not touch your site folders. The first time
nsgeo 0.4.0 opens a site, the picks table gains a `zero_ns` column. Nothing is
converted: a pick with no zero was measured on the radar's clock, and keeps
reading that way. If the site has picks, it also puts any pick that had drifted
off its line back onto it, with its depth at the line's current velocity, and
the message bar says how many picks it updated.

Two things stop an older version reading a site that 0.4.0 has saved:

- **After you open a site in 0.4.0, do not reopen it in 0.3.0.** 0.3.0 drops
  the picks table's `zero_ns` column. A pick made or moved on a profile that
  Time zero relabelled would then read 0.5 to 1.5 ns off.
- **A site with cuts saves as schema version 2, and 0.3.0 refuses to open it.**
  A site without cuts still saves as version 1.

A cube saved before 0.4.0, whose preset has a Time zero step, comes back
shifted by the median line zero when you restore it, so its slices sit at the
depths they showed before, and the Slices panel says so.

### Uninstalling

Open **Plugins → Manage and Install Plugins… → Installed**, select **nsgeo**,
and click **Uninstall Plugin**. This removes the plugin only. Your site folders
stay exactly where they are.

---

## 2. The toolbar and the five panels

### The nsgeo toolbar

| Button | What it does |
|---|---|
| **New site…** | Starts a new site in a folder you choose. |
| **Open site…** | Opens an existing site by its `survey.nsgeo.json` file. |
| **Save site** | Saves the site (see [Where your data lives](#4-where-your-data-lives)). |
| **Add grid…** | Places a new grid on the map. |
| **Import DZT…** | Imports DZT files into a grid. |
| **Pick** | Turns pick mode on and off. Click the profile to make a pick. |
| **Velocity** | Turns velocity mode on and off. Click a diffraction hyperbola on the profile to measure the radar velocity from it. |
| **Cut** | Turns cut mode on and off. Click points on a grid to draw a line, and the profile shows the vertical section beneath it (see [Step 8](#step-8-draw-a-cut)). |
| **Panels ▾** | Shows or hides each nsgeo panel, and switches layouts (see [The panels](#the-panels)). |

**Save site**, **Add grid…**, **Import DZT…** and **Cut** stay greyed out until a
site is open, and **Pick** and **Velocity** until a line is open.

### The panels

QGIS docks the five panels around the map. You can drag, float or close them like
any other QGIS panel.

- **nsgeo Survey** (left) lists the site, its grids and the lines in each grid.
  Click a line to open it. Right-click a grid for **Edit grid…**, **Edit
  lines…**, **Import DZT files…**, **Set velocity…** and **Remove grid**, which
  removes the grid along with its lines. **Edit lines…** is greyed out while the
  grid has no lines. Right-click a line for **Open**, **Edit line…**, **Set
  velocity override…**, **Move to grid** and **Remove line from site**. To work
  on several lines at once, Ctrl-click (⌘-click on a Mac) or Shift-click to
  select them. Press Delete to remove them, or right-click the selection. Lines
  on one grid offer **Edit N lines…**. Any lines offer **Move N lines to grid**
  and **Remove N lines from site**. Removing never deletes the DZT files, and
  the site file isn't changed until you choose **Save site**.
- **nsgeo Profile** (bottom) shows the open line's radargram. Its title names the
  line and its trace count. The **Display gain** slider and the colour table
  change only how the profile looks, never the data. Every line on a grid is
  drawn against the grid's length, with the low end on the left, so a line that
  was walked the other way is shown mirrored. A line shorter than the grid
  leaves hatched blank space. Zoom and pan stay on the same stretch of ground
  when another line on the same grid, parallel to it and walked in either
  direction, opens or is hovered on the map, and they come back after a glance
  at a cross-line. **Fit** shows the whole grid length, and **1:1** shows one trace
  per screen pixel. The arrow under the distance axis shows which way the line
  was walked. The mouse wheel zooms, and dragging with the middle button pans.
- **nsgeo Processing** (right) holds the processing steps for the open line:
  **Add step**, **Remove**, **↑** and **↓**, **Difference**, **Apply to grid…** and
  **Presets**.
- **nsgeo Slices** (right) builds time and depth slices across a grid. The first
  time nsgeo starts, it sits as a tab behind **nsgeo Processing**.
- **nsgeo Mag** (right) maps a magnetometer grid, or every magnetometer grid that
  holds a file. It starts closed: open it from **Panels ▾**, or click a
  magnetometer grid in **nsgeo Survey**. **This grid** and **Whole site** choose
  what is drawn. The map is drawn as the layer **Mag (live preview)**, and only
  while the panel is open. Closing the panel leaves the layer as it was last
  drawn.

**Panels ▾** on the nsgeo toolbar ticks each panel that is open, including one
sitting behind another tab. Tick a panel to bring it back in front, or untick it
to close it. Below the ticks are three layouts:

- **Profile work** keeps **nsgeo Survey** and **nsgeo Profile**, and closes
  Processing, Slices and Mag.
- **Slices work** keeps **nsgeo Survey** and **nsgeo Slices**, and closes Profile,
  Processing and Mag.
- **Show all** opens all five.

A layout only opens and closes panels: each one comes back at the size and in
the place you left it, and QGIS's own panels are left alone. **View → Panels**
works too. The toolbar is under **View → Toolbars → nsgeo**.

**Set velocity override…** on a line's right-click menu sets or clears that line's
own velocity. It also lists the velocity fits you have measured on the line, and
you can apply one of them as the override. Without an override, the line uses its
grid's velocity (right-click the grid, then **Set velocity…**). If the grid has
none either, it uses the dielectric in its file header. The profile names the
source next to the velocity, for example `v = 0.080 m/ns (header ε 14)`.

---

## 3. A first session

This walks through a whole session once: site, grid, lines, profile,
processing, a pick and slices.

### Before you start

- Make a new, empty folder for the site. Everything nsgeo writes goes into it.
- Grids use a projected coordinate reference system (CRS) in metres, such as your
  UTM zone, never latitude and longitude or feet. You do not have to choose one:
  the grid window picks a suitable one for you (see Step 2), starting from the
  project's CRS. To choose it yourself, pick it in the grid window's **CRS** box.
  (If the site already has grids, their CRS comes before the project's.)

### Step 1: New site

Click **New site…** and choose the empty folder. nsgeo writes `survey.nsgeo.json`
into it, and the site appears in **nsgeo Survey** under the folder's name.

Now copy your DZT files into the site folder. A subfolder is fine. Keep each
file's DZX file beside it, so its marks are read too. Keeping the DZT files inside
the site folder lets the whole site move as one folder (see
[Where your data lives](#4-where-your-data-lives)).

### Step 2: Place a grid

nsgeo imports lines into a grid, so place the grid first. Click **Add grid…**
(or right-click the site in **nsgeo Survey**). The **New grid** window opens. It
stays open while you work on the map, and the map shows what you have entered so
far (see [What the map shows](#what-the-map-shows)).

1. Type an **Id** for the grid.
2. Fill the **Corners** table. It has four rows: **origin**, **+X**, **+X+Y** and
   **+Y**. Fill as many as you have, and any of these ways in any mix:
   - **Type** a corner's two coordinates. Choose the CRS they are in with
     **Corners in** first (it can be latitude and longitude, such as GPS
     readings). The **from** column says `typed`.
   - **Pick** a corner on the map. The window hides, and the message bar names the
     corner to click. Click the map, and the window comes back. The click snaps to
     a nearby point (such as a GPS point) or, failing that, to a vertex, and **from** names
     what it snapped to, for example `G4 · gps`, or `free click` when there was
     nothing close. Right-click or **Esc** cancels.
   - **Pick all** walks the four corners in order. Right-click skips a corner and
     leaves its row as it was. **Esc** stops and keeps what you have picked.
   - **Fill** from a polygon. Choose a polygon in the layer list and the feature
     list (or click **Pick on map** and click the polygon), then click **Fill**. The polygon must
     have four corners. nsgeo gives them their roles so the grid is the right way
     round, with the origin at the corner whose +Y edge points closest to north.
     **from** shows each one as, for example, `v2 NE`.
   - **⟳ Rotate** moves the roles one corner round, however the rows were filled,
     if the origin landed on the wrong corner. The two **Size** boxes swap with
     them. Four presses return to the start.
   - **Clear** empties the table.

   Picking and filling never fit the grid by themselves.
3. Click **Fit**. It needs at least two corners next to each other. The fit
   fixes rotation and position, never scale, and sets **Origin E, N** and
   **Azimuth**. It also fills **Size X, Y (m)** from the distances between your
   corners, unless you typed a size yourself. The status line gives the *rigid fit
   RMS*, which is 0 for exact corners. A large value means the corners are not quite
   square: look at **off by** to see which corner is furthest out. nsgeo refuses
   corners that run the wrong way round or, with three or more, have rows swapped, and
   corners that are only centimetres apart (usually degrees typed under a metric
   **Corners in**, or the wrong **Corners in**), and it says so. It also refuses
   while a row holds text that is not a number. A refused Fit changes nothing.
4. Check the numbers, and change any you like. **off by** in the table shows, for
   each corner, how far in metres it is from the matching corner of the grid as
   the form describes it now. It is blank until that grid can be drawn: the
   origin must not be (0, 0), both sizes must be above 0, and the CRS must be
   usable there.
5. **Size.** A size you type is kept, and the grid extends from the origin by
   that amount. If the corners measure something different, a note under the size
   says so, for example `the corners measure 20.41 × 19.87 m · your size is kept`.
   Click **Use these** to take the measured size instead. Check **Default spacing
   (m)** too. The azimuth is measured clockwise from north to the grid's +Y axis.
6. **Velocity (m/ns)** is optional. Left at **from line headers**, each line
   uses the dielectric in its own file header for depths. The note beside the
   box shows what the headers give, for example `header ε 14 ≈ 0.0801 m/ns`.
   The header value is only the instrument's setting, not a measurement, so
   enter a velocity when you have a better one, for example from a fit. You can
   change it, or set it back to 0 to clear it, later with **Set velocity…**.
7. Click **OK**. It stays greyed out until the Id, CRS and size are all usable.

**The grid's CRS picks itself.** The grid needs a projected CRS in metres. Until
you choose one yourself, nsgeo uses the first of these that suits the map's
location: the CRS of the site's earlier grids, the project CRS, or the UTM zone
under the map centre. When you click **Fit**, it decides again from your corners.
If it picked a UTM zone for you, the note under the CRS says so and why, for
example `picked for you: the project CRS (EPSG:4326) is in degrees`. So corners
in latitude and longitude, in a project set to latitude and longitude, give a
grid in the right UTM zone with no conversion by hand. If you choose a CRS
yourself, nsgeo keeps it, and converts the origin and azimuth into it. A note
under the CRS explains anything that stops a CRS being used.

#### What the map shows

While the window is open, even while it is hidden for a pick, the map shows:

- each filled corner as a magenta dot with a tag naming its role (`origin`, or
  `origin · v0 SW` for a polygon corner);
- the polygon you chose, outlined;
- the grid as the form describes it now, as a blue dashed outline with a magenta
  arrow from the origin along +Y. It follows the form as you type, with no Fit
  needed, and appears once the origin, sizes and CRS can be drawn.

Everything on the map goes away when the window closes. Nothing is added to the
project's layers.

The grid appears on the map in a layer group named **nsgeo ·** followed by the
site folder's name. The group goes in at the top of the Layers panel, above any
imagery already open, with picks over marks over lines over grid outlines. If
you move the group, it stays where you put it.

### Step 3: Import DZT files

Click **Import DZT…** (or right-click the grid, then **Import DZT files…**).
The toolbar button opens on the grid selected in **nsgeo Survey**, or the grid
of the selected lines, or the grid of the line that is open. The dialog's title
and its **Import** button name the grid the lines will go into.

1. Choose the **Target grid**, and say which way **Lines run along** (the grid's
   Y or X axis).
2. Set **Spacing across** (the line spacing), **First line at** (the offset of
   the first line), **Start along** (where a line run in the + direction
   begins), and the **Direction**: **alternate (zigzag)**, **all +1** or
   **all -1**. **First line at** starts at half the spacing, so the first line
   sits in the middle of its strip like the others, and follows **Spacing
   across** until you type a value of your own. Tick **Stretch or compress each
   line to the grid's length** if your lines were walked edge to edge but the
   wheel read long or short; it greys out **Start along**, because a fitted line starts
   on the grid's edge. It is off by default, so lines run long or short on
   purpose stay as recorded.
3. Click **Add files…** and choose the DZT files. Each file gets a row, with
   nsgeo's guess at its offset and direction.
4. Correct the table where the field day did not go to plan. Untick the box at
   the left of a row to leave out an abandoned line, and edit a row's **Label**,
   **Offset (m)** or **Dir**. Use **↑** and **↓** to fix the order. Leaving out
   a redone line moves the later files up into its place, unless you have edited
   them by hand. The **Note** column flags a file whose header dielectric is
   outside 1–81, which no soil has. Such a line still imports, but its depths
   need a grid or line velocity.
5. Click **Import**. The lines appear on the map and under the grid in **nsgeo
   Survey**. They are drawn as thin dashed lines in the grid's colour, and are
   hidden when you zoom out far enough that they would run together (beyond
   1:400 at 0.5 m spacing). Grid outlines and picks stay at every scale.

#### Fixing lines after import

If a line went in with the wrong start, offset, direction or grid, right-click
the grid and choose **Edit lines…**. A table opens with every line on the grid,
in survey order. You can change a line's **Label**, **Offset (m)**, **Dir**,
**Start (m)** and **Grid**. Use **↑** and **↓** to set the order the Survey
panel shows.

The panel under the table changes every selected line at once. Type a start and
press **Set**, press **Snap to grid edge**, type an amount and press **Shift**
to move the offsets, press **Flip** to reverse the direction, or choose a grid
and press **Move**.

The **Note** column flags a line that starts off its edge, or that lies outside
the grid's width. Nothing changes until you click **OK**, and then everything
changes as one step. Picks move with their lines.

Changing a grid's length in **Edit grid…** moves its reversed lines with the far
edge. The message bar tells you how many moved.

A wheel on rough ground, or one that is slightly out of calibration, makes a
line read longer or shorter than the grid. **Scale** is the number that corrects
it: the grid metres for each metre the wheel recorded. Type a value in a row, or
select lines and press **Fit to grid edges** to put each line's first and last
trace on the grid's two edges. The recorded file is not touched, so setting
**Scale** back to 1 undoes the stretch (after **Fit to grid edges**, **Start**
has moved too, so reset that as well). A fitted line stays fitted when you
change the grid's length in **Edit grid…**. The **Note** column flags a scale
more than 20% from 1, so a deliberately short line caught in a selection stands
out before you click **OK**.

Fit lines before you measure velocity. A velocity fitted on a line before its
scale changes keeps the value measured at the old spacing, so refit it
afterwards. Migration still uses the trace spacing recorded in the file, not the
fitted one. A site with corrections opened in nsgeo 0.3.0 draws the lines
uncorrected, and drops the corrections if that version saves it.

Stagger shows as a feature that jumps back and forth between lines walked out
and back. **Destagger (m)** moves every trace of a line forward along that
line's own direction of travel. If features on lines walked one way sit behind
the same features on lines walked the other way, increase it. Set it on every
line first (select all, type an amount, press **Set**), then adjust single
lines. Start is not changed: it stays where the line was recorded to begin.

Fit a grid's lines before you destagger them. Fitting removes the squeeze a
wheel that reads short or long puts on each line, and that squeeze looks like
stagger itself, so the destagger a grid needs can change sign once its lines
are fitted. On one real grid, unfitted lines looked best at +0.15 m and the
same lines fitted at −0.15 m.

**Measure** works the amount out from the data instead. Select the lines to fill
and press it. Whatever is selected, it compares every line on the grid with its
neighbours walked the other way, over the whole record: a line is judged against
the lines beside it, and the grid's value is steadier from all of them. The
selection only chooses which rows get filled. The first press reads every line,
about 10 seconds for 60 lines; the dialog keeps what it read, so pressing again is
quick. The grid's value goes in the Destagger box, and each selected row
gets its own line's value (a line that changes partway along, or matches nothing,
gets the grid's value and is named on the status line). Nothing changes until you
press OK, and the numbers are a starting point: look at the lines, then adjust.
Lines Measure cannot use are left as they were and named in the status, with the
reason. While it runs the button reads **Stop**, and pressing it changes nothing.

### Step 4: Open a line and use the map

Click a line in **nsgeo Survey**, or select it on the map with QGIS's select tool
(**Select Features by Area or Single Click**). Its radargram opens in **nsgeo
Profile**.

- Move the pointer along that line on the map, and the profile cursor follows.
- Move the pointer over the profile, and an orange cross on the map shows where
  that trace was recorded. Drag across the profile to select a range of traces;
  the range is drawn on the map too.
- Hover a *different* line on the map, and the profile shows a preview of it. The
  panel title shows **PREVIEW:** before the line's name. A preview is for looking
  only. Processing and picks stay with the line you opened. To work on the
  previewed line, select it on the map or click it in **nsgeo Survey**.

The map link never takes over the map. Pan, zoom, identify and select keep
working as usual.

### Step 5: Process the profile

In **nsgeo Processing**, click **Add step** and choose a step. The menu lists
them in the usual processing order, in four groups:

- **Time:** Time zero, Time cutoff
- **Filters:** Dewow, Bandpass
- **Background:** Background removal (mean), Background removal (sliding),
  Remove leading components (SVD)
- **Gain:** Gain curve, Automatic gain control, Parametric gain

A step whose name ends in **…** asks for values first. For example, **Bandpass…**
needs its cut-off frequencies. Hover over a step in the list to see its short
name (such as `gain_agc`), which is what the survey file stores.

- Select a step to see and change its settings below the list.
- Untick a step to switch it off without removing it. Use **↑** and **↓**, or
  drag, to change the order. **Remove** deletes the selected step.
- **Difference** shows what the selected step removed, rather than the result.
- Select a **Gain curve** step, and a strip beside the profile lets you drag its
  control points. It works on its own, without **Automatic gain control** before it. The
  profile's brightness is measured as if the gain curve were switched off, so
  raising part of the curve brightens only that part, and pushing too far turns
  it solid black and white. Under the curve, the grey band shows how loud the
  loudest parts of the line are at each depth, and the black line is the trace
  under the cursor. The dotted lines are the limits of what the profile can
  show. Anything past them is drawn red, and is solid black or white on the
  profile.

Nothing runs unless you add it. Your DZT files are only ever read and never
changed, so any step can be undone.

When the steps look right:

- **Presets → Save current stack as…** saves them under a name. **Presets →**
  *name* applies a saved preset to the open line. You need a saved preset to build
  slices (Step 7).
- **Apply to grid…** copies the open line's steps onto every other line in the
  same grid. It asks first.
- Click **Save site** to keep the steps and presets.

### Step 6: Make a pick

Turn on **Pick** in the toolbar and click the profile, or Shift+click the profile
with **Pick** off. Each pick becomes a point in the **picks** layer on the map.
The point records the trace and the two-way time, plus the distance along the
line, the depth and the velocity.

- A pick is written to disk the moment you make it, so there is nothing to save.
- Picks go on the line you opened, never on a preview. Shift+clicking a preview
  tells you so.
- Select a pick on the map, and its line opens with the cursor on the pick's
  trace.
- The picks layer can be edited with QGIS's ordinary editing tools, to add a
  note or delete a pick. Read
  [#22](https://github.com/JamesZDonline/nsgeo/issues/22) under
  [Known issues](#5-known-issues-in-040) before you do.
- A pick follows its line, so dragging it on the map does not move it: it goes
  back onto its line when you save the layer's edits. To move a pick along its
  line, delete it and pick again on the profile.

### Step 7: Build slices

Open the **nsgeo Slices** tab, next to **nsgeo Processing**.

1. Under **Source**, choose the **Grid** and a **Preset**. The preset's steps are
   applied to every line before slicing. **Transform** starts on **Square of the
   amplitude**. Choose **Absolute value** or **Envelope** for other amplitude
   slices, or **None** for the signed mean. These transforms are only offered
   here, not in **Add step**. Preparing starts by itself, and the status line
   reads *prepared* when it is done.
   **Choose…** sets which of the grid's lines are included. With every line
   ticked, lines you import onto the grid later are included too.
2. Under **Position**, move the slider to step down through the record. The
   current slice is drawn on the map. The readout gives the window in
   nanoseconds, plus metres of depth from the grid's velocity. **Thickness** and
   **Step** set the window and how far each step moves it. You can also hold
   Shift and use the mouse wheel over the map to step through the slices.
3. **Resolution** sets the **Cell size**, the vertical spacing (**dz**), and the
   top and bottom of the volume (**z0**, **z1**). Hover over each control for an
   explanation. A grid starts at a 0.2 m cell, or half the line spacing if that
   is smaller. Each grid remembers the resolution you set for it, and saving the
   site saves it.
4. **Interpolation** decides what is drawn in the cells no line crossed, and
   whether the slice is smoothed. The same box appears for **Whole site**, with
   its own settings.
   - **Method** chooses how blank cells are filled from the cells around them.
     Pick **Kriging**, the default, for most data. Pick **Inverse distance
     (IDW)** for a fill that never goes beyond the values around it: nearer
     cells count more, and a filled cell always lies within the range of the
     cells it is filled from, where kriging can overshoot a little beside a
     strong contrast. Pick **Minimum curvature** for the smoothest surface
     through the lines, the method Surfer users often know. Past the outermost
     lines it carries on the trend of the data, out to the max distance. So a
     grid's edges, the sides of a skipped line, and the seams between grids in
     **Whole site** can show values higher or lower than any line recorded,
     even below zero on an amplitude slice. It can also overshoot a little
     beside a strong contrast between lines. It is solved for each slice, so it
     is slower.
     At a fine cell you see kriging while the depth moves, and minimum
     curvature replaces it a moment after the depth rests. A short note on the
     same line as the depth readout says which: **Kriging preview**,
     **Refining…**, or **Colour stretch…**. The colour stretch
     can shift once more when minimum curvature has measured it. An export
     always uses minimum curvature, shows its progress, and can be cancelled.
     Pick **None (binned only)** to see only the cells a line crossed.
   - **Max distance to data** is how far from a line a blank cell may be and
     still be filled. It is set in line spacings (for a grid its metres are
     shown beside the box; for the whole site, hover over the box). Cells
     farther from any line stay blank, so a missing line or the edge of the
     survey is never filled in. It starts at 0.75. Each line is drawn on the
     cells it crossed, and those can sit up to half a cell off the line itself,
     so half a spacing would leave thin blank stripes between lines that never
     strayed. Three quarters closes every gap between neighbouring lines, with
     room for a line that wandered a little. Lower it toward 0.5 to fill less,
     or raise it if a line strayed and left a blank stripe. It does nothing
     when the method is **None**.
   - **Smoothing X** and **Smoothing Y** blur the slice along the grid's X or Y
     axis, by a distance in metres. They start at 0, which is off. Smoothing is
     the only setting that changes the cells a line crossed.

   Each grid remembers its own settings, and so does the whole site. nsgeo
   prepares the fill again when you change the cell size, the method or the
   max distance; at a fine cell that can take a few seconds, and it shows a
   wait cursor while it does. Stepping through the slices, the smoothing and
   **dz**, **z0** and **z1** reuse the fill already prepared.

   Each picture blends the cells around every pixel, so it is drawn smooth when
   you zoom in. **Whole site** can cover more ground than a fine cell allows at
   full detail. Past a size it draws a preview at a coarser pixel and says so in
   the panel. An export is not limited by the preview: it works out its own
   cells at the size you choose (see step 6).
5. **Display** sets how the slice is coloured. **Colours** offers two choices:
   - **nsgeo colours** uses the **Stretch** and **Palette** below it.
   - **my own colours** keeps whatever you set on the slice layer's
     **Symbology** page in QGIS. The **Symbology…** button beside the choice
     opens that page, where you can pick a colour ramp, type a min and max, or
     use a cumulative cut. Your colours start from what nsgeo was showing.
     Numbers you type stay the same at every depth. A computed range (Min /
     max, Cumulative cut, Mean ± standard deviation) is worked out again for
     each slice, so a dim deep slice still uses the whole ramp. **Stretch** is
     greyed out while your own colours are on.

   This grid and Whole site each keep their own colours, and the site remembers
   them; a saved cube keeps them too. **Palette** still colours cuts and the
   coverage view.

   **Show coverage** shows how many traces fell in each cell, rather than the
   amplitude, always in nsgeo's colours: turn it off and your own colours come
   back. The number in a cell
   is how many traces fell in it. A blank cell had no line through it. What counts
   as a low number depends on the cell size: at a fine cell, one or two traces a
   cell is normal, because a cell holds only a few traces along the line. Compare a
   cell with its neighbours, or with the line spacing and the cell size, and
   look for the cells that stand out as low.
   Use it to spot gaps and thin coverage between lines before you trust a slice
   in that spot. With **Show coverage** ticked, an export also writes the
   counts as a second file beside it, named like the export with
   `_coverage` added (`name_coverage.tif`), and adds it to the map.
6. **Save cube…** keeps the prepared volume in the site folder (click **Save
   site** afterwards so the site remembers it). **Export GeoTIFF…** writes every
   slice as one multi-band GeoTIFF and adds it to the map. It works for **This
   grid** and for **Whole site**, and opens a dialog first:
   - **Save to** is the file. **…** lets you browse for it.
   - **Export cell** is how finely nsgeo works out each grid for the file. It
     starts at the cell you are viewing and can go no finer than every grid
     allows. A finer cell gives more detail, and more memory and time.
   - **Export pixel** is how finely the file is written. It starts at the cell
     and can be finer, never coarser. A finer pixel makes a smoother picture
     when you zoom in, in any GIS, without working out the grids again.
   - **What will be written** lists the bands, the picture size, the grids, how
     the slices are made, the normalisation, the memory the export needs (and
     the most it is allowed) and the file size.
   - **Export** is greyed out, with the reason shown in the box, when the
     export would need more memory than it is allowed, or more free disk space
     than there is. The message says which cell or pixel would fit.
   - If the file, or its style or coverage file, is already open in the project,
     the dialog asks whether to **Replace** it. The old layer comes off the
     map while the export runs. If you cancel the export, or it fails, the old
     layer is put back from the file, which is untouched, with its time
     slider setting where the file records it (files from older versions do
     not, and nsgeo says so). If the picture was written but its coverage file
     could not be, nsgeo says so, adds the new layer and puts back only the
     coverage layer.

   The export runs in the background. Its progress, the band and the grid it is
   on, shows in QGIS's task list at the bottom right, and you can keep working
   meanwhile. Cancel it from the task list. A cancelled or failed export leaves
   any file already there as it was. Only one export runs at a time, and closing
   the site cancels the one running.

   At a finer cell, normalisation is measured again on the export's own data,
   so its factors can differ slightly from the ones on screen. Manual
   multipliers carry over as you typed them.

   **Stepping through depths.** With nsgeo installed and enabled, an exported
   file steps one band at a time in QGIS's Temporal Controller, however it gets
   into the project: straight after an export, when you reopen a saved project,
   or when you add it yourself with **Layer → Add Layer → Add Raster Layer**.
   Layers already in the project when you enable nsgeo are set up too. nsgeo
   reads the band times from the file and sets the controller to match. Open it
   with **View → Panels → Temporal Controller**, or its clock button, then press
   play or drag the slider. Adding one of these files replaces whatever the
   controller was set to.

   If you point a layer at its file again after opening a project (**Handle
   Unavailable Layers**, or **Change Data Source**), it picks its band times up
   the next time you open the project, or when you remove it and add it again.

   The times it shows are nanoseconds written as seconds after midnight on
   1 January 1970, so 00:00:05 is 5 ns. Times before 0 ns show as the last
   seconds of 31 December 1969, so -1.8 ns is 23:59:58.

   Where nsgeo is not installed and enabled, the file carries no time setting
   for QGIS. A project saved with nsgeo and opened without it keeps QGIS's own
   band times, rounded to whole seconds, so the controller there skips some
   bands and repeats others. In both cases step through the bands with the band
   choice in the layer's **Symbology**, or with another GIS's band list.

   Beside the GeoTIFF nsgeo writes a style file with the same name and a `.qml`
   ending. Any QGIS project that opens the file draws it with the same colours,
   stretch and smooth drawing when zoomed in. Other GIS software, ArcGIS and
   the rest, reads the values but chooses its own colours. With **my own
   colours** on, the style file holds your colours as they were on screen when
   the export started. The file keeps one range for every depth: the export
   does not work a computed range out again band by band.

### Step 8: Draw a cut

A line you recorded shows what the radar saw along that one path. A **cut** is
a line you draw yourself, anywhere on a grid. The profile then shows the
vertical section beneath it, read from the same volume as the slices. Use it to
follow a feature across the lines you recorded, or to see a slice's reflection
from the side.

1. Show the grid in the **nsgeo Slices** panel first (Step 7). A cut reads the
   panel's volume, and uses the panel's **Interpolation** settings and
   **Palette**, so it looks like the slice, cut another way. Until the grid is
   shown the profile tells you which grid to show.
2. Turn on **Cut** in the toolbar. Click inside a grid to start, click to add
   points, and right-click or press Enter to finish. Backspace removes the last
   point, and Esc cancels. The cut goes on the grid you first clicked in. It
   appears in the **cuts** layer on the map, and under its grid in **nsgeo
   Survey**, where a right-click renames or deletes it.
3. The profile opens it. Its title reads **nsgeo Profile · cut:**, followed by
   the name, the grid and the length. The distance along the cut runs left to
   right from where you started. The depth axis is the grid's. The pale blue
   band shows the slice you are looking at in **nsgeo Slices**, so you can see
   which reflection a slice is made from. Blank stretches are places the cut
   passes outside the grid, or farther than the **Max distance to data** from
   any line.

If the grid is being prepared again, the profile says so and redraws the cut
when it is ready. A grid whose volume is too large to hold in memory cannot be
cut: use a coarser cell or a shorter depth range in **nsgeo Slices**.

With **Minimum curvature** chosen, a cut shows the **Kriging** fill at first,
and the title says so: *Kriging preview · minimum curvature n of N depths*,
where N is how many depths the section has and n how many are finished so far.
The finished section replaces it a depth at a time, starting at the slice you
are looking at, and the title then reads *Minimum curvature*. It can take up to
a minute or two for a long cut at a fine cell, and longer when **Max distance
to data** is more than half the line spacing, because each depth
is then solved over the whole grid. Move the slice window and the work turns to
the new depth once the window has rested. Change a setting while it works and
it starts again; changing the palette or renaming the cut does not. Only the
cut you have opened is finished: hovering another one shows its kriging
preview.

The map works on cuts while the **cuts** layer is the current layer, and on
lines otherwise. With **cuts** current, moving the pointer along a cut moves the
profile cursor, and hovering a cut previews it. Selecting a cut with QGIS's
Select tool opens it, and so does clicking its name in **nsgeo Survey**. Choose
another layer, and the map goes back to following your recorded lines.

**Pick** works on a cut as it does on a line: click the profile, and the pick
lands on the cut's path on the map. A pick on a cut records its distance along
the cut and its time, with a note of how the section was made. If you pick while
the section is still the kriging preview, the pick says so. Picks on a cut use
the grid's velocity, or its first line's if the grid has none, and a cut is not
processed: the steps in **nsgeo Processing** belong to recorded lines.

A cut's times are on the clock of the volume it was cut from. If you turn the
preset's **Time zero** step on or off after making picks on a cut, those picks
no longer fit the new section, so the profile leaves them out and its title
counts them (*1 picks on another clock*). They stay on the map and in the picks
table, and they come back when you turn the setting back.

### Step 9: Save, and next time

Click **Save site** before you close QGIS. nsgeo also asks before **New site…**
or **Open site…** would discard unsaved changes. Next time, click **Open site…**
and choose the site's `survey.nsgeo.json`.

---

## 4. Where your data lives

Everything for a site lives in its site folder:

| In the site folder | What it holds |
|---|---|
| `survey.nsgeo.json` | The site itself: its grids, its lines and where their DZT files are, each line's processing steps, your cuts, the presets, and the saved cubes. **Save site** writes it. |
| `site.nsgeo.gpkg` | A GeoPackage with the map layers: **grids**, **lines**, **cuts**, **marks** and **picks**. |
| `slices` | Saved cubes (`.npz`), and exported GeoTIFFs unless you save them elsewhere. |
| your DZT files | Read by nsgeo, never changed. |

**Picks are different from everything else.** nsgeo redraws the grids, lines,
cuts and marks layers from `survey.nsgeo.json` and your DZT and DZX files
whenever it needs to, so those layers are read-only. The **picks** layer is your own work,
and its only copy is in `site.nsgeo.gpkg`. It cannot be regenerated, so back up
the site folder.

A few things to know:

- **Keep DZT files inside the site folder.** If they are elsewhere, **Save site**
  asks whether to record them by their full path, and the site will then open
  only on a computer where that path exists.
- **A pick follows its line.** Editing a grid or a line moves its picks too, and
  dragging a pick on the map does not move it.
- **A cut follows its grid.** Move or turn a grid and its cuts move with it, and
  so do the picks on them. If you make a grid smaller, a cut that runs past its
  edge stays, and shows blank where it is outside.
- **A pick on a deleted cut stays on the map.** Deleting a cut never deletes its
  picks, so they remain in the **picks** layer, where you can see them and
  remove them yourself. The pick's note still says which cut it was made on.
  Removing a grid deletes its cuts too, and asks first.
- **A site with cuts does not open in nsgeo 0.3.0 or earlier.** Those versions
  would drop the cuts the next time you saved, so they refuse to open it. They
  say the site's file declares schema version 2, but that they read version 1.
  A site with no cuts still opens in them. Update nsgeo on every computer that
  opens the site.
- **Move, copy or back up the whole site folder, with QGIS closed.** Never move
  `site.nsgeo.gpkg` on its own (see
  [#23](https://github.com/JamesZDonline/nsgeo/issues/23) below). Renaming the
  site folder is fine, because nsgeo finds its files inside it by their fixed
  names.

---

## 5. Known issues in 0.4.0

These three can lose work or give a wrong-looking result without a warning. Each
has a simple way around it.

### Unsaved edits in the picks layer can be lost (#22)

[Issue #22](https://github.com/JamesZDonline/nsgeo/issues/22). nsgeo keeps its
map layers in the CRS of the site's first grid. When that CRS changes, nsgeo
rebuilds the **picks** layer. Editing, removing or adding a grid can each do
this, including adding a grid in a new CRS after you have removed the last one.
If you have the picks layer in editing mode with changes not yet saved (a note
typed in its attribute table, say), the rebuild throws those changes away without
a warning. Picks that were already saved are kept.

**Workaround:** save or discard your picks-layer edits before you use any grid
command: **Add grid…**, **Edit grid…**, **Set velocity…** or **Remove grid**. If
**picks** shows a pencil icon in the Layers panel, select it, choose
**Layer → Toggle Editing**, and then **Save** (or **Discard**) when QGIS asks.

### Moving the GeoPackage on its own can lose data (#23)

[Issue #23](https://github.com/JamesZDonline/nsgeo/issues/23). While QGIS has a
site open, the most recent changes to `site.nsgeo.gpkg` can sit in companion
files beside it, ending in `-wal` and `-shm`. Those files belong to the
GeoPackage's current name and place. Move or rename the `.gpkg` alone, and the
changes they hold are lost. The GeoPackage may then not open at all. Closing QGIS
writes those changes back into the GeoPackage itself.

**Workaround:** close QGIS first. Then move, rename, copy or back up the **whole
site folder**, never `site.nsgeo.gpkg` on its own. A cloud-synced folder copies
files one at a time while you work, so either keep active sites outside one, or
let it sync only while QGIS is closed.

### A one-sample window blanks the profile (#40)

[Issue #40](https://github.com/JamesZDonline/nsgeo/issues/40). **Dewow** and
**Background removal (sliding)** subtract a running mean. If the window is one sample (or
one trace) wide, they subtract each value from itself, and the profile goes
blank. With **Difference** on, the whole profile then shows as removed. **Automatic gain control**
has the same edge case with a different symptom. At a one-sample window, every
value becomes plus or minus the **Target RMS**, so all the amplitude information
is lost. Nothing warns you in either case.

**Workaround:** keep each window at least two samples wide.

- **Dewow**: **Window (ns)** at least twice the sample interval.
- **Background removal (sliding)**: **Window (traces)** at least 2.
- **Automatic gain control**: **Window (ns)** at least twice the sample interval.

The sample interval is the time range divided by the samples per trace. For
example, 512 samples over 50 ns is about 0.1 ns, so the shortest safe window is
about 0.2 ns. The default windows (4 ns for Dewow, 200 traces for
Background removal (sliding) and 20 ns for Automatic gain control) are safe unless your sample
interval is longer than 2 ns. If a profile goes blank, select the step and widen
its window. Your DZT files are untouched.

---

## 6. Reporting a problem

1. Choose **Plugins → nsgeo → About nsgeo**. A line like `plugin 0.4.0 · core
   0.4.0 · build` followed by a 12-character code appears on the message bar
   above the map. If it says `development checkout` instead of a build code,
   the copy you are running did not come from a release zip.
2. The message bar clears itself after a few seconds. To copy the text, open
   **View → Panels → Log Messages** and choose its **nsgeo** tab. The About line
   is there, together with any error messages from nsgeo.
3. Write down:
   - the About line;
   - your QGIS version (**Help → About**) and whether you use Windows, macOS or
     Linux;
   - what you did, what you expected, and what happened instead;
   - any error text from the **nsgeo** tab of Log Messages.
4. Open a new issue at
   [github.com/JamesZDonline/nsgeo/issues](https://github.com/JamesZDonline/nsgeo/issues)
   (you need a free GitHub account), or email it to the person who gave you the
   plugin.

GitHub issues are public. Do not attach DZT files, coordinates, or screenshots of
the map that would show where a site is. Error text often includes the names of
your files and folders. Before you post it, replace any name that would identify
a site with a made-up one such as `SITE`, or email the report instead.
