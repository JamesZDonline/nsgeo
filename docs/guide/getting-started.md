# Getting started with nsgeo

nsgeo is a QGIS plugin for processing GPR surveys in their map context. You import
GSSI DZT files into a grid placed on the map, then view and process each profile
while the map shows where you are on the line. You can also pick reflections and
build time and depth slices across a grid.

This guide covers nsgeo 0.1.0, the first release. It is **experimental**, so keep
backups of your site folders. You need QGIS 3.40 to 3.44, or QGIS 4.x. You do not
need to install anything else.

1. [Install](#1-install)
2. [The toolbar and the four panels](#2-the-toolbar-and-the-four-panels)
3. [A first session](#3-a-first-session)
4. [Where your data lives](#4-where-your-data-lives)
5. [Known issues in 0.1.0](#5-known-issues-in-010)
6. [Reporting a problem](#6-reporting-a-problem)

---

## 1. Install

### Windows

1. Download `nsgeo_qgis-0.1.0.zip` from the
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
   bar above the map should show `plugin 0.1.0 · core 0.1.0 · build`, followed by
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
you download, or use another browser. nsgeo 0.1.0 has not been tried on a Mac.
If you try it, please report what happens, whether it works or not (see
[Reporting a problem](#6-reporting-a-problem)).

### Linux

The steps are the same. Every release is checked by installing its zip into
QGIS 3.40, QGIS 3.44 and QGIS 4.2 on Linux.

### Upgrading

Install the new zip exactly as above. QGIS replaces the old version. Then
**restart QGIS** and check **Plugins → nsgeo → About nsgeo** for the new
version number. Upgrading does not touch your site folders.

### Uninstalling

Open **Plugins → Manage and Install Plugins… → Installed**, select **nsgeo**,
and click **Uninstall Plugin**. This removes the plugin only. Your site folders
stay exactly where they are.

---

## 2. The toolbar and the four panels

### The nsgeo toolbar

| Button | What it does |
|---|---|
| **New site…** | Starts a new site in a folder you choose. |
| **Open site…** | Opens an existing site by its `survey.nsgeo.json` file. |
| **Save site** | Saves the site (see [Where your data lives](#4-where-your-data-lives)). |
| **Add grid…** | Places a new grid on the map. |
| **Import DZT…** | Imports DZT files into a grid. |
| **Pick** | Turns pick mode on and off. Click the profile to make a pick. |

**Save site**, **Add grid…** and **Import DZT…** stay greyed out until a site is
open, and **Pick** until a line is open.

### The panels

QGIS docks the four panels around the map. You can drag, float or close them like
any other QGIS panel.

- **nsgeo Survey** (left) lists the site, its grids and the lines in each grid.
  Click a line to open it. Right-click a grid for **Edit grid…**, **Import DZT
  files…**, **Set velocity…** and **Remove grid**, which removes the grid along
  with its lines. Right-click a line for **Open** and **Remove line from site**.
  To remove several lines at once, Ctrl-click (⌘-click on a Mac) or Shift-click
  to select them, then press Delete or right-click the selection. Removing never
  deletes the DZT files, and the site file isn't changed until you choose
  **Save site**.
- **nsgeo Profile** (bottom) shows the open line's radargram. Its title names the
  line and its trace count. The **Display gain** slider and the colour table
  change only how the profile looks, never the data. **Fit** fits the whole line
  in the panel, and **1:1** shows one trace per screen pixel. The mouse wheel
  zooms, and dragging with the middle button pans.
- **nsgeo Processing** (right) holds the processing steps for the open line:
  **Add step**, **Remove**, **↑** and **↓**, **Difference**, **Apply to grid…** and
  **Presets**.
- **nsgeo Slices** (right) builds time and depth slices across a grid. The first
  time nsgeo starts, it sits as a tab behind **nsgeo Processing**.

If you close a panel, reopen it from **View → Panels**. The toolbar is under
**View → Toolbars → nsgeo**.

In 0.1.0, **Set velocity override…** on a line's right-click menu is not
available yet. It only shows a message. Set the velocity on the grid instead
(right-click the grid, then **Set velocity…**).

---

## 3. A first session

This walks through a whole session once: site, grid, lines, profile,
processing, a pick and slices.

### Before you start

- Make a new, empty folder for the site. Everything nsgeo writes goes into it.
- Grids use a projected coordinate reference system (CRS) in metres, such as your
  UTM zone, never latitude and longitude or feet. You do not have to choose one:
  the grid window picks a suitable one for you (see Step 2), starting from the
  project's CRS. To choose it yourself, set the project's CRS first: click the CRS
  shown at the bottom right of the QGIS window.

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
     a nearby point (such as a GPS point) and then to a vertex, and **from** names
     what it snapped to, for example `G4 · gps`, or `free click` when there was
     nothing close. Right-click or **Esc** cancels.
   - **Pick all** walks the four corners in order. Right-click skips a corner and
     leaves its row as it was. **Esc** stops and keeps what you have picked.
   - **Fill** from a polygon. Choose a polygon **Layer** and **Feature** (or
     click **Pick on map** and click the polygon), then **Fill**. The polygon must
     have four corners. nsgeo gives them their roles so the grid is the right way
     round, with the origin at the corner whose +Y edge points closest to north.
     **from** shows each one as, for example, `v2 NE`.
   - **⟳ Rotate** moves every role one corner round the polygon, if the origin
     landed on the wrong corner. Four presses return to the start.
   - **Clear** empties the table.

   Picking and filling never fit the grid by themselves.
3. Click **Fit**. It needs at least two corners next to each other. The fit
   fixes rotation and position, never scale, and sets **Origin E, N** and
   **Azimuth**. It also fills **Size X, Y (m)** from the distances between your
   corners, unless you typed a size yourself. The status line gives the *rigid fit
   RMS*, which is 0 for exact corners. A large value can mean the corners were not
   surveyed square, or that two of the rows are swapped. nsgeo refuses corners
   that run the wrong way round, and says so.
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
6. Enter **Velocity (m/ns)**. It is required, and it sets the depth scale for the
   grid's profiles and slices. A working estimate is fine, because you can change
   it later with **Set velocity…**.
7. Click **OK**. It stays greyed out until the Id, CRS, size and velocity are all
   usable.

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
site folder's name.

### Step 3: Import DZT files

Click **Import DZT…** (or right-click the grid, then **Import DZT files…**).

1. Choose the **Target grid**, and say which way **Lines run along** (the grid's
   Y or X axis).
2. Set **Spacing across** (the line spacing), **First line at** (the offset of
   the first line), **Start along** (where a line run in the + direction
   begins), and the **Direction**: **alternate (zigzag)**, **all +1** or
   **all -1**.
3. Click **Add files…** and choose the DZT files. Each file gets a row, with
   nsgeo's guess at its offset and direction.
4. Correct the table where the field day did not go to plan. Untick the box at
   the left of a row to leave out an abandoned line, and edit a row's **Label**,
   **Offset (m)** or **Dir**. Use **↑** and **↓** to fix the order. Leaving out
   a redone line moves the later files up into its place, unless you have edited
   them by hand.
5. Click **Import**. The lines appear on the map and under the grid in **nsgeo
   Survey**.

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

In **nsgeo Processing**, click **Add step** and choose a step. The steps are
`time_zero`, `dewow`, `background_mean`, `background_sliding`,
`background_svd`, `bandpass`, `gain_parametric`, `gain_agc`, `gain_curve`,
`amp_abs`, `amp_envelope` and `amp_square`. A step marked *(needs values)* asks
for them first. For example, `bandpass` needs its cut-off frequencies.

- Select a step to see and change its settings below the list.
- Untick a step to switch it off without removing it. Use **↑** and **↓**, or
  drag, to change the order. **Remove** deletes the selected step.
- **Difference** shows what the selected step removed, rather than the result.
- Select a `gain_curve` step, and a strip beside the profile lets you drag its
  control points. It works on its own, without `gain_agc` before it. The
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
  [Known issues](#5-known-issues-in-010) before you do.
- Do not drag a pick to a new place on the map. It keeps the trace, time and
  distance it was made at, so the point and its record would no longer agree.
  To move a pick, delete it and pick again on the profile.

### Step 7: Build slices

Open the **nsgeo Slices** tab, next to **nsgeo Processing**.

1. Under **Source**, choose the **Grid** and a **Preset**. The preset's steps are
   applied to every line before slicing. Optionally, choose a **Transform**
   (`amp_abs`, `amp_envelope` or `amp_square`) for amplitude slices. Preparing
   starts by itself, and the status line reads *prepared* when it is done.
   **Choose…** sets which of the grid's lines are included.
2. Under **Position**, move the slider to step down through the record. The
   current slice is drawn on the map. The readout gives the window in
   nanoseconds, plus metres of depth from the grid's velocity. **Thickness** and
   **Step** set the window and how far each step moves it. You can also hold
   Shift and use the mouse wheel over the map to step through the slices.
3. **Resolution** sets the **Cell size**, the vertical spacing (**dz**), the top
   and bottom of the volume (**z0**, **z1**), and the **Fill radius** for cells
   no line crossed. Hover over each control for an explanation.
4. **Display** sets the **Stretch** and **Palette**. **Show coverage** shows how
   many traces fell in each cell, rather than the amplitude.
5. **Save cube…** keeps the prepared volume in the site folder (click **Save
   site** afterwards so the site remembers it). **Export GeoTIFF…** writes every
   slice as one multi-band GeoTIFF and adds it to the map.

### Step 8: Save, and next time

Click **Save site** before you close QGIS. nsgeo also asks before **New site…**
or **Open site…** would discard unsaved changes. Next time, click **Open site…**
and choose the site's `survey.nsgeo.json`.

---

## 4. Where your data lives

Everything for a site lives in its site folder:

| In the site folder | What it holds |
|---|---|
| `survey.nsgeo.json` | The site itself: its grids, its lines and where their DZT files are, each line's processing steps, the presets, and the saved cubes. **Save site** writes it. |
| `site.nsgeo.gpkg` | A GeoPackage with the map layers: **grids**, **lines**, **marks** and **picks**. |
| `slices` | Saved cubes (`.npz`), and exported GeoTIFFs unless you save them elsewhere. |
| your DZT files | Read by nsgeo, never changed. |

**Picks are different from everything else.** nsgeo redraws the grids, lines and
marks layers from `survey.nsgeo.json` and your DZT and DZX files whenever it
needs to, so those layers are read-only. The **picks** layer is your own work,
and its only copy is in `site.nsgeo.gpkg`. It cannot be regenerated, so back up
the site folder.

A few things to know:

- **Keep DZT files inside the site folder.** If they are elsewhere, **Save site**
  asks whether to record them by their full path, and the site will then open
  only on a computer where that path exists.
- **A pick's map position is fixed when you make it.** If you later move, resize
  or rotate its grid with **Edit grid…**, the line is redrawn in its new place but
  the pick stays where it was. nsgeo shows a warning when this happens. The
  warning says to see "the Picking section of the README"; this paragraph is
  what it means. So finish placing a grid before you start picking on its lines.
- **Move, copy or back up the whole site folder, with QGIS closed.** Never move
  `site.nsgeo.gpkg` on its own (see
  [#23](https://github.com/JamesZDonline/nsgeo/issues/23) below). Renaming the
  site folder is fine, because nsgeo finds its files inside it by their fixed
  names.

---

## 5. Known issues in 0.1.0

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

[Issue #40](https://github.com/JamesZDonline/nsgeo/issues/40). `dewow` and
`background_sliding` subtract a running mean. If the window is one sample (or
one trace) wide, they subtract each value from itself, and the profile goes
blank. With **Difference** on, the whole profile then shows as removed. `gain_agc`
has the same edge case with a different symptom. At a one-sample window, every
value becomes plus or minus the **Target RMS**, so all the amplitude information
is lost. Nothing warns you in either case.

**Workaround:** keep each window at least two samples wide.

- `dewow`: **Window (ns)** at least twice the sample interval.
- `background_sliding`: **Window (traces)** at least 2.
- `gain_agc`: **Window (ns)** at least twice the sample interval.

The sample interval is the time range divided by the samples per trace. For
example, 512 samples over 50 ns is about 0.1 ns, so the shortest safe window is
about 0.2 ns. The default windows (4 ns for `dewow`, 200 traces for
`background_sliding` and 20 ns for `gain_agc`) are safe unless your sample
interval is longer than 2 ns. If a profile goes blank, select the step and widen
its window. Your DZT files are untouched.

---

## 6. Reporting a problem

1. Choose **Plugins → nsgeo → About nsgeo**. A line like `plugin 0.1.0 · core
   0.1.0 · build` followed by a 12-character code appears on the message bar
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
