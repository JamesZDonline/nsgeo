## Review Focus

1. **The author's own site already holds dz 0.001 ns** from the accident: in the grid's
   remembered resolution, the site resolution, and possibly a saved cube. Opening it must show
   0.2165, build a normal cube and leave every record still saying 0.001. Pinned in Task 3,
   one test per record kind.
2. **A site mixing radars**, for example a grid with 1,024 samples over the same 110.86 ns beside
   the 512-sample grids. The dz floor is the finest interval, and the seeded defaults are never
   refused, whichever grid comes first. Pinned in Task 3, both orders.
3. **A Warnings entry appearing or going while a Resolution box has focus**, with the panel
   scrolled to the bottom so its range shrinks. Focus and the typed value stay; the panel moving
   is not a user scroll. Pinned in Task 2.
4. **Keyboard users.**
   - Tab into dz while it is scrolled out of view: the panel scrolls it into view and dz keeps focus.
   - Arrow keys on the scroll bar count as a user scroll and do let go.
   - Pinned in Task 1, through `ensureWidgetVisible` and `triggerAction`.
5. **Qt 6.** Two behaviours must be checked in the `qgis/qgis:4.2` image, not only locally:
   - an ignored wheel event propagating to the scroll area;
   - `QgsCollapsibleGroupBox` folding while hidden.

   Task 5 runs the wheel, fold and width test files there.

