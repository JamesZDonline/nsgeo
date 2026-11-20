# #227: a 3D Analysis drop-down on the toolbar — design

**Issue:** #227, raised at M16 Plan D's walkthrough (G1, 2026-11-19). **Approved:** 2026-11-20.
**Size:** a small change, so this is the short design.

## Why

**Surface from picks…** and **3D view** sit on the toolbar with Pick, Velocity and Cut, but they
aren't picking tools. **ParaView…** sits on the Slices panel, which isn't where you'd look for
3-D rendering. The toolbar's groups should say what their tools do, and the 3-D tools should
be in one place, with room for later ones.

## Goals

- The toolbar gets another divider after Cut, and after it a **3D Analysis** drop-down holding,
  in this order, **Surface from picks…**, **3D view** and **Export for ParaView…**.
- **ParaView…** leaves the Slices panel. **Save cube…** and **Export GeoTIFF…** stay.
- The guide says where the controls now are.

## Non-goals

- No change to what any of the three does. Surface from picks… still works on the picks
  selected on the map. 3D view still shows the Slices panel's grid. The export dialog still
  opens on the Slices panel's grid and still offers the others.
- Session S's other issues (#228, #218, #219, #203, #204) are not part of this.

## Anti-goals

- A drop-down that hides a tool's purpose. Each entry keeps its tooltip, and the list shows
  tooltips, so the 3D view still says which grid it shows.
- A split button whose main half does something. The Panels button rejected that, and so
  does this one.

## Constraints

- Follow the established drop-down: a `QToolButton` of the plugin's own, holding a `QMenu` and
  set to `InstantPopup`, added with `toolbar.addWidget`. Panels (#84) and Add data (M17b) are
  built this way.
- With no site open the **whole button** greys out, as Add data does. With a site open, all
  three entries are on, as the two toolbar buttons and the ParaView… button are today.
- Toolbar order: `… Add grid… Add data ▾ | Pick Velocity Cut | 3D Analysis ▾ | Panels ▾`.
- Unloading the plugin tidies away the button, its menu and its entries, as it does for Add data
  and Panels.

## Approaches

1. **An instant-popup button, like Panels and Add data (chosen).** One click opens the list.
   It matches the two drop-downs already on the toolbar.
2. **A split button**, where the main half runs the last entry used. The Panels button rejected
   this: a main half that does something people don't expect.
3. **A 3D Analysis menu in QGIS's menu bar.** That isn't where the user looks or asked for, and
   nsgeo's tools all live on its toolbar.

The user approved approach 1 with this design.

## Decided

- **Entry names:** "Surface from picks…", "3D view" and "Export for ParaView…". The last is
  the export dialog's own title.
- **Which grid:** unchanged, as above. This settles the issue's "which grid" question.
- **The button's tooltip** says what the drop-down is for. The exact text is the builder's.
- **Guide** (`docs/guide/getting-started.md`):
  - The toolbar table's two rows (Surface from picks…, 3D view) become one **3D Analysis ▾**
    row.
  - The "stay greyed out until a site is open" sentence names **3D Analysis**.
  - Step 9's opening and step 1, **The 3D view**'s first line, and **Making a surface from
    picks** step 2 say where the controls are now.
  - The `paraview` folder row says **Export for ParaView…** writes it again.
- **Tests:** existing tests find the controls in their new place. One new test pins the
  button: its text, instant popup, the entries in order, its place between Cut and Panels,
  greying with the site, and tidying on unload.

## Left to the builder

- Whether the plugin keeps `act_surface` and `act_view3d` as names for the menu entries. They
  are no longer toolbar actions, but tests and slots use them.
- Whether Panels, Add data and 3D Analysis share one small helper that builds a drop-down. It
  is worth doing if it stays small.
- What happens to the Slices panel's `paraview_requested` signal. It goes with the button
  unless something else needs it.
