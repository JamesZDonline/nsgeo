# SDD ledger — plan: docs/superpowers/plans/2026-11-20-nsgeo-3d-analysis-menu.md

Executor: executing-plans (native), chosen by the user 2026-11-20.
Spec: docs/superpowers/specs/2026-11-20-nsgeo-3d-analysis-menu-design.md

Pre-flight: Task 2 consumes Task 1's copy (entry names "Surface from picks…", "3D view", "Export for ParaView…"; button "3D Analysis"). Task 1 produces exactly those strings (plan Copy). No conflict.

Task 1: Ruling: added a SURFACE_TIP constant beside ANALYSIS_3D_TIP/PARAVIEW_TIP for Surface from picks…'s existing tip text (unchanged wording) — keeps the three entry tips together — costs nothing if wrong.
Task 1: Ruling: Step 5's "grep paraview_button|paraview_requested prints nothing" matches only the new test that asserts the button is gone (test_plugin_analysis3d_menu.py) — the check's intent (no production use left) holds — none.
Task 1: Ruling: mypy not run — none of ci.yml's mypy files changed (plugin.py and slices_dock.py are not in its list) — none.
Task 1: note: wider QGIS run (8 files) 520 passed, 1 failed: test_plugin_slices_dock.py::test_a_refine_for_a_window_left_behind_never_draws under load 6.8 on 4 cores (pure/core ran alongside); passed 3/3 alone. Known flake, issue #196. Pure+core 2103 passed, 9 skipped, 19 xfailed. real_data 52 passed. ruff check/format clean (local 0.16.7).
Task 1: complete (commits d2044b3..54daba1, tests: packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/test_plugin_analysis3d_menu.py packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_dialog.py packages/nsgeo-qgis/tests/qgis/test_plugin_panels_menu.py packages/nsgeo-qgis/tests/qgis/test_plugin_add_data_dialog.py packages/nsgeo-qgis/tests/qgis/test_plugin_new_surface_dialog.py -q --no-header -p no:cacheprovider → 104 passed in 125.60s (0:02:05))
Task 2: complete (commits 54daba1..056afe7, tests: <main checkout>/.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_release_docs.py -q --no-header -p no:cacheprovider -p no:xonsh → 5 passed in 0.04s)

Final review: opus reviewer, range 0255dbd..056afe7. No Critical, no Important; all five Review Focus items checked and passing in its scratch runs. Verdict: ready to merge once CI is green on both QGIS versions and the walkthrough passes.
Final: minor (deferred): test names/docstrings still say "toolbar action"/"button" for the moved entries (new_surface_dialog :1 :32 :39 :62; scene3d :600 :609; panels_menu :313, whose greying test now duplicates the new one).
Final: minor (deferred): SURFACE_TIP is the one entry tooltip no test pins (test_plugin_analysis3d_menu.py:34-35 pins the other two).
Final: minor (deferred): the greying test could also assert the QToolButton widget's isEnabled(), not only the widget action's (Qt propagates it; reviewer checked).
Final: minor (deferred): the 3D Analysis separator is added in initGui while Panels adds its own inside its builder (as the plan asked; helper docstring states it).
Final: Ruling: features.vtp missing from the guide's ParaView folder table — predates #227, not in this spec's guide edits — a reader of Step 9 doesn't learn one file's name; worth a line in #228 or the next guide pass.
Final: Ruling: 3D view says "Add a grid first" with no site open — unreachable now the entry greys with no site — none.
Final: Ruling: own-QToolButton look in icon-only toolbars / overflow — same as Add data and Panels already on main — a layout oddity on a narrow window, shared by all three.
Final: Ruling: which grid the export opens on in Whole site — unchanged by spec non-goal — none.
Final: Ruling: release notes for the move — no unreleased notes file yet; belongs to the release — the move must be named when the next release notes are written.
Final: Ruling: README roadmap — kept on main, already lists #227 in progress — none.
Final: Ruling: local ruff 0.16.7 vs CI 0.17.1 — CI's lint job is the check — a lint failure shows in CI, fixed then.
Final: Ruling: Surfaces panel's "New from selected picks…" second route — pre-existing, outside this spec — none.
Ruling: keep this workspace until the walkthrough is done — the user's practice commits the ledger as the decision record at merge (memory: retire ledgers before removing a worktree) — none.

Walkthrough round 1: T1 E1 E2 E3 pass, G1 skip (see walkthrough-results.md). T1 note asks about the ellipses; put to the user.
