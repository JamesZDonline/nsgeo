# #227 final review (whole branch, 0255dbd..056afe7)

Reviewer: a fresh Opus subagent, read-only, running tests from a scratch copy (`git archive` of 056afe7).

**Verdict:** ready to merge once CI is green on both QGIS versions and the walkthrough passes. Both happened: CI run 44780088624 passed every job, and the walkthrough passed T1, E1, E2 and E3 (G1 skipped).

**Critical:** none. **Important:** none.

**Review Focus, all five hold:**
1. Export for ParaView… in Whole site scope opens the dialog.
2. It refuses while a GeoTIFF export runs.
3. The button and all three entries grey out together. The reviewer also checked that the QToolButton widget itself greys and comes back.
4. Unload, then initGui, leaves exactly one button and one menu.
5. Add data and Panels are unchanged after the helper refactor.

**Scratch runs:**
- `test_plugin_analysis3d_menu.py` plus three scratch checks: 7 passed.
- The ParaView dialog, Panels, Add data toolbar and New surface tests: 64 passed.
- ruff: clean.

**Minors, deferred** (the user's call; not fixed):
- Some test names and docstrings still say "toolbar action" or "button" for the moved entries:
  - `test_plugin_new_surface_dialog.py`: lines 1, 32, 39 and 62.
  - `test_plugin_scene3d.py`: lines 600 and 609.
  - `test_plugin_panels_menu.py`: line 313. Its greying test now duplicates the new one.
- `SURFACE_TIP` is the one entry tooltip no test pins.
- The greying test could also assert the QToolButton widget's `isEnabled()`.
- The 3D Analysis divider is added in `initGui`, while Panels adds its own inside its builder. This is as the plan asked.

**Set aside by the reviewer, and the rulings on them, are in `progress.md`:**
- `features.vtp` is missing from the guide's ParaView folder table. This predates #227.
- The move needs a line in the next release notes.
