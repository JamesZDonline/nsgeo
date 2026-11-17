### Task 4: A project holding a refused setting still opens (spec §5, decisions 1 and 6)

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/model/survey.py` (`Site.load_notes`),
  `packages/nsgeo-core/src/nsgeo/project.py` (`_repair_steps`, `load_site`),
  `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (`open_site`)
- Test: `tests/test_project.py` (or a new `tests/test_project_repair.py`), `tests/test_schema.py`,
  `tests/test_presets.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py`

**Interfaces:**
- Consumes: `param_problem`, `ParamSpec.label` and `.required`, `get_step`, `step_title`,
  `build_step` (Task 3).
- Produces:
  - `Site.load_notes: list[str] = field(default_factory=list)`. It is never saved; comment it so.
  - `_repair_steps(entries: list[dict], where: str, notes: list[str]) -> list[dict]` in
    `project.py`. It returns new dicts and appends notes.
    - `where` is `f"Line {Path(entry['path']).name}"` or `f"Preset {name!r}"`.

- [ ] **Step 1: Write the failing core tests** (use `_write_project_with_stack` from
  `test_schema.py`, or an equivalent writer):

  - **A refused setting turns the step off.** AGC `eps=0.0` on the line: `load_site` succeeds, the
    stack's AGC is disabled with `eps == 1e-12`, and `site.load_notes` holds exactly this:
    `"Line L0.DZT: Automatic gain control is turned off. Its Epsilon was 0.0, which must be > 0.0; it is now 1e-12. Check the step and turn it back on."`
  - **A preset:** `background_sliding window_traces=1` in preset `"p"` comes back with the step
    disabled, `window_traces == 200`, and a note starting `"Preset 'p': "`.
  - **Review Focus 2:** `StepStack.from_dicts(site.presets["p"])` builds, and the stack runs on a
    random radargram.
  - **Review Focus 3:** `save_site`, then `load_site`. The step is still off, and `load_notes` is
    empty.
  - **Two refused settings on one step:** parametric gain `mode="bogus", alpha=8.0` gives one
    note naming both, and comes back `mode == "exponential"`, `alpha == 0.05`, off.
  - **Time zero stays on (decision 6):** `time_zero` with `sample=12.0` comes back
    **enabled** with `sample == 0`. Its note:
    `"Line L0.DZT: Time zero's Sample was 12.0, which must be a whole number; it is now 0. The step stays on, because turning Time zero off would move every time after it."`
  - **No default, so removed:**
    - bandpass with `low_mhz=nan` is removed, with a note containing
      `"Bandpass is removed"` and `"Low"`;
    - a gain curve with one point is removed. Rewrite
      `test_load_site_reports_an_invalid_stack_as_project_error` to expect this.
  - **A missing required setting:** bandpass without `high_mhz` is removed, with a note.
  - **Still refused:**
    - an unknown step name (the existing `test_invalid_preset_is_a_project_error`);
    - an unknown setting name (the existing `test_an_unknown_parameter_name_is_refused_rather_than_ignored`);
    - an entry that isn't an object.

    All three stay `ProjectError`.
  - **A constructor refusal the check doesn't know about:** monkeypatch a registered step's
    `__init__` to raise `ValueError("x")`. Loading removes the step with a note. Without this
    safety net, "still opens" would depend on every rule living in `param_problem`.

- [ ] **Step 2: Run them and confirm they fail.**

- [ ] **Step 3: Implement `_repair_steps` and wire it into `load_site`**, around current lines
  ~495 (line stacks) and ~520 (presets). Presets are stored repaired in `site.presets`. Other
  rules:
  - Structural faults keep raising, and the existing `try` turns them into `ProjectError`: a
    non-dict entry, a missing `"step"`, `params` not a dict, an unknown step or setting.
  - Note wording follows the examples above:
    - one sentence per refused setting: `Its <Label> was <repr>, which <reason>; it is now <repr>.`
    - then the ending: `Check the step and turn it back on.` for steps turned off, or the Time zero
      sentence;
    - removed steps: `"<where>: <Title> is removed. Its <Label> was <repr>, which <reason>, and <Label> has no default. Add it again with the settings you want."`
    - a missing required setting: `"<where>: <Title> is removed. It has no <Label>, which it needs. Add it again with the settings you want."`

- [ ] **Step 4: Write the failing QGIS test** in `test_plugin_survey_dock.py`:
  `test_opening_a_project_with_a_refused_setting_turns_the_step_off_and_says_so`. Use the
  `fake_iface`, `monkeypatch` and `message_log` fixtures, and `getOpenFileName` monkeypatched as in
  `test_open_site_discarding_abandons_the_old_site_without_saving_it`. The file holds AGC `eps=0`
  on a line. After `plugin.open_site()`:
  - the session is open;
  - `plugin.session.stack_for(key).entries[i][1] is False` for the AGC entry;
  - `message_log` contains the note text;
  - and it contains the summary:
    `"1 processing step in this project had settings that cannot work. It was turned off, reset or removed; the nsgeo log says what changed."`
    For n > 1: `"{n} processing steps … They were turned off, reset or removed; …"`.

- [ ] **Step 5: Implement** in `plugin.open_site`. After `self.session.open_site(...)` succeeds,
  if `self.session.site.load_notes` is not empty:
  - log each note with `QgsMessageLog.logMessage(note, "nsgeo", Qgis.MessageLevel.Warning)`;
  - then `self.message(summary, Qgis.MessageLevel.Warning)`.

  Nothing marks the session dirty. The repair reaches the file at the next save.

- [ ] **Step 6: Run the core suite and the QGIS processing set.** Expected: all pass.

- [ ] **Step 7: Commit and push**

  `feat(project): a saved setting that cannot work turns its step off with a note, instead of blocking the project`

---

