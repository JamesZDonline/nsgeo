# nsgeo processing help pages, chunk 1 — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Help button on the Processing panel that opens a finished dewow page in the browser,
plus the frame every later page plugs into: the page contract and its tests, the figure script,
the sources file, and the checking page.

**Architecture:** There are three parts:

- **The plugin** gains a Qt-free lookup (`nsgeo_qgis/help_pages.py`), a `help/` folder of static
  HTML that ships inside the package, and one button.
- **A dev-only package**, `packages/nsgeo-qgis/help_tools/`, that never ships. It parses pages and
  checks them against the step registry and the sources file. It also builds the data for the
  checking page.
- **A matplotlib script** in `scripts/` that draws each page's figures by running nsgeo's own code
  on a real campus line.

The pure-test tier enforces the contract in CI. Tasks 1–5 go to subagents. Task 6 is the
controller's, because it publishes an Artifact.

**Tech Stack:** Python 3.9+, `qgis.PyQt`, stdlib `html.parser`, matplotlib (script only), numpy,
pytest. Pages are static HTML, CSS and MathML.

**Spec:** `docs/superpowers/specs/2026-10-15-nsgeo-help-pages-design.md` is binding, and its
attachments are in `docs/superpowers/specs/2026-10-15-nsgeo-help-pages/`. Read §3–§6 and §9
before starting. This plan is chunk 1 of §10.

---

## Before Task 1: the workspace

Work in `.worktrees/help-pages`. **Never `git switch` in the main checkout**, because other
sessions use it. From the worktree:

```bash
git switch -c nsgeo-help-pages            # branches from docs/help-pages-design (spec + this plan)
python3 -m venv .venv && ./.venv/bin/python -m pip install -e "packages/nsgeo-core[dev]"
python3 -m venv --system-site-packages .venv-qgis && ./.venv-qgis/bin/python -m pip install pytest
./.venv/bin/python -c "import nsgeo; print(nsgeo.__file__)"   # must name .worktrees/help-pages
for f in /home/jameszd/Documents/Github/archaeo_geophysics/packages/nsgeo-core/tests/data/local/*; do
  [ "$(basename "$f")" = README.md ] || ln -sf "$f" packages/nsgeo-core/tests/data/local/
done
ls packages/nsgeo-core/tests/data/local/FILE__007.DZT     # the campus line every figure uses
```

`.venv-qgis` uses the system Python, which carries QGIS and matplotlib. `.venv` has neither.

## Global Constraints

Every task's requirements implicitly include this section.

- **Python floor 3.9.** Every module starts `from __future__ import annotations`. Use
  `list`/`dict`/`X | None`, never `typing.List`/`Optional`.
- **`ruff.toml`:** line length 100, target py39, lint select `["E","F","I","UP","B","SIM"]`.
  `ruff check .` and `ruff format --check .` both pass. `docs/` is excluded.
- **Documentation only (user).** Change no processing code under `packages/nsgeo-core/src/`.
  A bug found while writing goes to a GitHub issue (`gh issue create --label bug`, in the style of
  #40). The page then describes the current behaviour and links the issue.
- **Plugin boundary.** `tests/pure/test_plugin_boundary.py` forbids `matplotlib`, `scipy` and
  direct `PyQt5`/`PyQt6` under `nsgeo_qgis/`. `help_pages.py` imports no Qt at all.
  `help_tools/` and `scripts/` sit outside `nsgeo_qgis/`, so the boundary test doesn't scan them.
  `help_tools/` still imports no Qt and no matplotlib, so the pure tier can import it in CI.
- **Pages are offline.** A page has no `<script>` and no remote stylesheet, font or image. The
  only stylesheet is `style.css`. Equations are MathML.
- **Section contract (spec §4.1).** `<section>` ids in order:
  `plain, pictures, method, settings, know, nsgeo, refs`. `related` comes between `know` and
  `nsgeo` for the nine family steps (`gain_agc`, `gain_parametric`, `gain_curve`,
  `background_mean`, `background_sliding`, `background_svd`, `amp_abs`, `amp_square`,
  `amp_envelope`).
- **Reading level.** The first `<p>` in `#plain` scores `fk_grade(text) <= 9.0`.
- **Figures** come from `packages/nsgeo-core/tests/data/local/FILE__007.DZT`. Never commit a DZT,
  DZX or DZG file.
- **Commit trailer**, every commit: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
- **Push each commit** to `origin/nsgeo-help-pages` as it is made
  (`git push -u origin nsgeo-help-pages` the first time).
- **Every test that pins behaviour must be shown to discriminate.** Build the plausible wrong
  implementation the test exists to catch, run the test against it, and record in the task
  report that it FAILS there and PASSES on the real code. Each task names its mutants. Run with
  `PYTHONDONTWRITEBYTECODE=1`, because stale `.pyc` files fake survivors.

### Test commands (from the worktree root)

```bash
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
```

The second command runs the pure tier too, with matplotlib present. It is the only place the
figure test (Task 4) actually runs.

## Review Focus

These are inputs the spec implies but doesn't spell out, ordered most likely to bite first. Each
has a test in the task that owns the code.

1. **The plugin lives under a path with spaces or non-ASCII characters**, e.g. a Windows profile
   or a OneDrive "Documents - Vanderbilt". Help must still open the page (Task 1).
2. **The selected row holds a different step after a stack edit** (moved, or the one above
   removed). Help must open the page for the step that is there *now* (Task 1).
3. **An unchecked (disabled) step is selected.** Help still works, because the step is still
   in the list (Task 1).
4. **The page file is missing at click time** (a partial install, a sync tool). Nothing opens,
   and the status line says so (Task 1).
5. **Page HTML the parser finds awkward:** MathML, entities such as `&lt;`, or an unclosed `<p>`.
   The contract checker must still find sections, settings and claims, and must not crash
   (Task 3).

---

### Task 1: The Help button

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/help_pages.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py` (bottom row at ~155–181, and
  `_update_row_buttons` at ~248)
- Test: `packages/nsgeo-qgis/tests/pure/test_help_lookup.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py` (append)

**Interfaces:**
- Produces:
  - `help_pages.HELP_DIR: Path`, equal to `Path(__file__).parent / "help"`.
  - `help_pages.page_path(step_name: str) -> Path | None`. It returns
    `HELP_DIR / f"{step_name}.html"` when that file exists, otherwise `None`. It reads the
    module global `HELP_DIR` at call time, so tests can monkeypatch it.
  - `ProcessingDock.help_button: QPushButton`.
  - `ProcessingDock.open_help() -> None`.

- [ ] **Step 1: Write the failing tests**

`test_help_lookup.py` (pure):

```python
def test_help_dir_ships_inside_the_plugin_package():
    assert help_pages.HELP_DIR.parent == Path(nsgeo_qgis.__file__).parent

def test_page_path_finds_existing_pages_only(tmp_path, monkeypatch):
    (tmp_path / "dewow.html").write_text("x", encoding="utf-8")
    monkeypatch.setattr(help_pages, "HELP_DIR", tmp_path)
    assert help_pages.page_path("dewow") == tmp_path / "dewow.html"
    assert help_pages.page_path("bandpass") is None
```

Appended to `test_plugin_processing_dock.py`, using the existing `opened` fixture plus two new
ones:

- `help_dir`: `tmp_path / "Plug-ins dé test" / "help"` holding `dewow.html` and
  `background_mean.html`, with `help_pages.HELP_DIR` monkeypatched to it.
- `opened_urls`: monkeypatches `processing_dock.QDesktopServices.openUrl` to append its `QUrl`
  argument to a list and return `True`.

```python
def test_help_button_sits_right_after_presets(opened):
    _, dock, _ = opened
    row = next(dock.widget().layout().itemAt(i).layout()
               for i in range(dock.widget().layout().count())
               if dock.widget().layout().itemAt(i).layout() is not None
               and dock.widget().layout().itemAt(i).layout().indexOf(dock.presets_button) >= 0)
    assert dock.help_button.text() == "Help"
    assert row.indexOf(dock.help_button) == row.indexOf(dock.presets_button) + 1

def test_help_disabled_with_no_line_or_no_selection(qgis_app, opened, help_dir):
    assert not ProcessingDock(SiteSession()).help_button.isEnabled()
    _, dock, _ = opened
    dock.add_step("dewow"); dock.list.setCurrentRow(-1)
    assert not dock.help_button.isEnabled()

def test_help_enabled_only_for_steps_with_a_page(opened, help_dir):
    _, dock, _ = opened
    dock.add_step("dewow"); dock.add_step("gain_agc")
    dock.list.setCurrentRow(0); assert dock.help_button.isEnabled()
    dock.list.setCurrentRow(1); assert not dock.help_button.isEnabled()   # no gain_agc.html

def test_help_click_opens_that_steps_page(opened, help_dir, opened_urls):   # Review Focus 1
    _, dock, _ = opened
    dock.add_step("dewow"); dock.list.setCurrentRow(0)
    dock.help_button.click()
    assert [Path(u.toLocalFile()) for u in opened_urls] == [help_dir / "dewow.html"]

def test_help_follows_the_step_after_a_move(opened, help_dir, opened_urls):  # Review Focus 2
    session, dock, key = opened
    dock.add_step("dewow"); dock.add_step("background_mean")
    dock.list.setCurrentRow(1)                      # background_mean
    session.move_step(key, 1, 0)                     # rebuild keeps row 1, which is now dewow
    dock.help_button.click()
    assert [Path(u.toLocalFile()) for u in opened_urls] == [help_dir / "dewow.html"]

def test_help_works_for_an_unchecked_step(opened, help_dir, opened_urls):   # Review Focus 3
    session, dock, key = opened
    dock.add_step("dewow"); session.set_step_enabled(key, 0, False); dock.list.setCurrentRow(0)
    assert dock.help_button.isEnabled()
    dock.help_button.click()
    assert len(opened_urls) == 1

def test_help_with_the_page_gone_opens_nothing(opened, help_dir, opened_urls):  # Review Focus 4
    _, dock, _ = opened
    dock.add_step("dewow"); dock.list.setCurrentRow(0)
    (help_dir / "dewow.html").unlink()
    dock.help_button.click()
    assert opened_urls == []
    assert "dewow" in dock.status.text()
```

- [ ] **Step 2: Run them to make sure they fail.** Run the second test command. It is expected
  to fail with `AttributeError: ... 'help_button'` and `ModuleNotFoundError: nsgeo_qgis.help_pages`.

- [ ] **Step 3: Implement `help_pages.py` and the button**

  - `QPushButton("Help")` goes into the bottom row immediately after `presets_button` and
    before `addStretch`. Tooltip: `"Open a page explaining the selected step"`. Connect `clicked`
    through a lambda that drops `checked`, like `apply_button` does.
  - `_update_row_buttons` sets `help_button` enabled iff the current row is at least 0, a line is
    open, and `page_path(<name of the step at that row in session.stack_for(key).entries>)` is
    not `None`.
  - Take the step name from the session's entries, never from the list item text.
  - `open_help()` re-resolves the path at click time.
    - If the path is `None`, set `self.status` to `f"No help page for {name}."` and return.
    - Otherwise call `QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))`.
  - Imports: `QDesktopServices` from `qgis.PyQt.QtGui`, `QUrl` from `qgis.PyQt.QtCore`. Import
    the module as `from nsgeo_qgis import help_pages` and call `help_pages.page_path`, so the
    monkeypatch reaches it.

- [ ] **Step 4: Run the tests to confirm they pass.** Run all three commands.
- [ ] **Step 5: Prove discrimination.** Each mutant must fail at least one test:
  - the button placed in the top row;
  - enabled with `row >= 0` alone, ignoring the page;
  - `QUrl(str(path))` instead of `fromLocalFile`;
  - the name taken from row 0 instead of the current row;
  - no re-check in `open_help`.
- [ ] **Step 6: Commit and push.** Message: `feat(plugin): a Help button that opens the selected step's page`.

---

### Task 2: Reading level and the sources file

**Files:**
- Create: `packages/nsgeo-qgis/help_tools/__init__.py` (a docstring only: dev tooling for the
  help pages, never shipped)
- Create: `packages/nsgeo-qgis/help_tools/readability.py`, `packages/nsgeo-qgis/help_tools/sources.py`
- Create: `packages/nsgeo-qgis/help_tools/sources.json` containing exactly
  `{"checking_page": null, "sources": {}, "claims": {}}`
- Test: `packages/nsgeo-qgis/tests/pure/test_help_tools.py`

`tests/conftest.py` already puts `packages/nsgeo-qgis` on `sys.path`, so `import help_tools`
works in both tiers.

**Interfaces:**
- Produces:
  - `readability.FK_LIMIT = 9.0`
  - `readability.syllables(word: str) -> int`
  - `readability.fk_grade(text: str) -> float`
  - `sources.SOURCES_PATH: Path` (the JSON beside the module)
  - `sources.load_sources(path: Path = SOURCES_PATH) -> Sources`. It raises `ValueError` whose
    message lists **every** problem, one per line.
  - `Sources(checking_page: str | None, sources: dict[str, Source], claims: dict[str, ClaimEvidence])`
  - `Source(id, citation, url: str | None, checked_via, checked_on, note)`
  - `ClaimEvidence(id, evidence, look, quote)`
  - All dataclasses are frozen.

JSON shape, per spec §6:

```json
{"checking_page": null,
 "sources": {"annan2009": {"citation": "...", "url": null,
                           "exists": {"checked_via": "https://...", "checked_on": "2026-10-15",
                                      "note": "page range not confirmed"}}},
 "claims":  {"dewow-wow-origin": {"evidence": "memory", "look": "Annan 2009, Ch. 1", "quote": ""}}}
```

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("word,n", [("the", 1), ("time", 1), ("water", 2), ("radar", 2),
                                    ("table", 2), ("average", 3), ("a", 1)])
def test_syllables(word, n):
    assert syllables(word) == n

def test_fk_grade_is_the_published_formula():
    # 6 words, 1 sentence, 6 syllables -> 0.39*6 + 11.8*1 - 15.59
    assert fk_grade("The cat sat on the mat.") == pytest.approx(-1.45)

def test_fk_grade_counts_sentences():
    # 6 words, 2 sentences, 6 syllables -> 0.39*3 + 11.8 - 15.59
    assert fk_grade("The cat sat. The dog ran.") == pytest.approx(-2.62)

def test_load_sources_reports_every_problem_at_once(tmp_path):
    bad = {"checking_page": None,
           "sources": {"x": {"citation": "", "url": None, "exists": {}}},
           "claims": {"c1": {"evidence": "guess", "look": "", "quote": ""},
                      "c2": {"evidence": "read", "look": "p. 3", "quote": ""}}}
    p = tmp_path / "s.json"; p.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError) as e:
        load_sources(p)
    msg = str(e.value)
    for needle in ("x: citation", "x: exists.checked_via", "c1: evidence", "c2: quote"):
        assert needle in msg

def test_the_committed_sources_file_loads():
    assert isinstance(load_sources(), Sources)
```

- [ ] **Step 2: Run them to make sure they fail** (`ModuleNotFoundError: help_tools`).
- [ ] **Step 3: Implement**

  Syllables: lowercase the word and keep letters only. Count runs of `[aeiouy]+`. Subtract one
  when the word ends in `e`, the count is above 1, and the word does not end in `le`. The minimum
  is 1.

  `fk_grade`:
  - words are `re.findall(r"[A-Za-z]+(?:['’][A-Za-z]+)?", text)`;
  - sentences are `max(1, len(re.findall(r"[.!?]+(?=\s|$)", text)))`;
  - grade = `0.39*words/sentences + 11.8*syllables/words - 15.59`.

  Document in `readability.py` that this is a deterministic guard rail, not a precise reading
  level.

  `load_sources` validation:
  - each source needs a non-empty `citation` and `exists.checked_via`;
  - `evidence` must be in `{"read", "memory"}`;
  - `"read"` requires a non-empty `quote`.

- [ ] **Step 4: Run all three commands.**
- [ ] **Step 5: Prove discrimination.** The mutants:
  - no silent-`e` rule;
  - `le` not exempted;
  - sentences counted as 1;
  - `load_sources` raising on the first problem only;
  - `"read"` accepted with no quote.
- [ ] **Step 6: Commit and push.** Message: `feat(help): reading-level estimate and the sources file`.

---

### Task 3: The page contract

**Files:**
- Create: `packages/nsgeo-qgis/help_tools/pages.py`
- Test: `packages/nsgeo-qgis/tests/pure/test_help_tools.py` (append: checker unit tests)
- Create: `packages/nsgeo-qgis/tests/pure/test_help_pages.py` (the contract over the real `help/`)

**Interfaces:**
- Consumes:
  - `help_pages.HELP_DIR` (Task 1);
  - `load_sources`, `Sources`, `fk_grade`, `FK_LIMIT` (Task 2);
  - `nsgeo.processing.get_step(name).schema()`, `available_steps()`.
- Produces:
  - `SECTIONS = ("plain", "pictures", "method", "settings", "know", "nsgeo", "refs")`
  - `FAMILIES: dict[str, tuple[str, ...]]`, with keys `"gains"`, `"background"`, `"amplitude"`
    holding the step names in the Global Constraints.
  - `expected_sections(step_name: str) -> list[str]`
  - `Claim(id: str, sources: tuple[str, ...], text: str, section: str)`, frozen. `text` is the
    element's text with whitespace collapsed.
  - `Link(href: str, source: str | None, text: str, section: str)`, frozen. It covers only
    `<a href>` with an `http`/`https` scheme.
  - `PageInfo(name, section_ids: list[str], params: list[str], claims: list[Claim],
    links: list[Link], ref_sources: list[str], images: list[str], stylesheets: list[str],
    scripts: int, plain_text: str)`
  - `parse_page(path: Path) -> PageInfo`
  - `check_page(page: PageInfo, help_dir: Path, sources: Sources) -> list[str]`
  - `check_site(pages: list[PageInfo], sources: Sources) -> list[str]`

  Every problem string starts `f"{page.name}: "` (or `"sources.json: "`) and names the
  offending id, setting, path or href.

Markup the parser reads, per spec §6.3:

- `<section id>`;
- `data-param="<setting>"` on an element inside `#settings`;
- `data-claim="<id>" data-source="<id> [<id> ...]"` on the element holding the claim (claims don't
  nest);
- `data-source` on each `#refs` item and on each outbound `<a>`;
- `<img src>`, `<link rel="stylesheet" href>`, `<script>`;
- the first `<p>` in `#plain` gives `plain_text`.

`check_page` reports:

- sections that are not exactly `expected_sections(name)`;
- a schema setting not in `params`, and a `params` entry not in the schema;
- any `<script>`;
- stylesheets other than exactly `["style.css"]`;
- an image whose `src` is remote or doesn't exist relative to `help_dir`;
- an outbound link with no `data-source`;
- a `data-source` (on a claim, link or ref) missing from `sources.sources`;
- a claim id missing from `sources.claims`;
- a claim with no source;
- `fk_grade(plain_text) > FK_LIMIT`, with the grade in the message.

`check_site` reports:

- a claim id used on two pages, or twice on one page;
- a `sources.sources` id that no page uses;
- a `sources.claims` id that no page has.

- [ ] **Step 1: Write the failing tests**

  The unit tests build a valid fixture page for `dewow`. It has every section in order, a
  `data-param="window_ns"` block, one claim `data-claim="t-claim" data-source="t-src"`, one
  outbound link with `data-source="t-src"`, a `#refs` item with `data-source="t-src"`, an
  existing image, `style.css`, and a short, easy `#plain` paragraph. A matching `Sources` is
  built in the test.

  ```python
  def test_a_valid_page_has_no_problems(...):  assert check_page(page, d, src) == []
  ```

  Then one test per mutation of the fixture, each asserting a problem that names the right thing:

  - remove `#know` → `"know"`;
  - swap `method` and `settings` → `"sections"`;
  - drop `data-param` → `"window_ns"`;
  - add `data-param="bogus"` → `"bogus"`;
  - add `<script>` → `"script"`;
  - add a remote stylesheet → its href;
  - point `img src` at a missing file → that path;
  - an `<a href="https://x.org">` without `data-source` → `"https://x.org"`;
  - a `data-source="nope"` → `"nope"`;
  - a claim id absent from `sources.claims` → that id;
  - a `#plain` paragraph of polysyllabic run-on prose → `"grade"`;
  - the same page saved as `gain_agc.html` with no `related` section → `"related"`.

  `check_site` gets three tests: a duplicated claim id, an unused source, and an orphaned
  `claims` entry.

  ```python
  def test_parser_survives_mathml_entities_and_an_unclosed_p(tmp_path):     # Review Focus 5
      # a #nsgeo section holding <math display="block"><mi>x</mi><mo>&lt;</mo>...</math>,
      # a <p> never closed before the next <section>, and &amp; in a claim's text
      page = parse_page(path)
      assert page.section_ids == list(SECTIONS) and page.params == ["window_ns"]
      assert page.claims[0].text == "Wow & flutter"
  ```

  `test_help_pages.py`, the contract over the real pages:

  ```python
  PENDING = {"time_zero", "dewow", "bandpass", "gain_agc", "gain_parametric", "gain_curve",
             "background_mean", "background_sliding", "background_svd",
             "amp_abs", "amp_square", "amp_envelope"}   # shrinks to empty by the last chunk

  def test_every_registered_step_has_a_page_unless_pending():
      pages = {p.stem for p in HELP_DIR.glob("*.html")}
      assert pages == set(available_steps()) - PENDING
      assert PENDING <= set(available_steps())

  def test_every_page_meets_the_contract():
      src = load_sources()
      problems = [p for f in sorted(HELP_DIR.glob("*.html"))
                  for p in check_page(parse_page(f), HELP_DIR, src)]
      assert problems == []

  def test_pages_and_sources_file_agree():
      assert check_site([parse_page(f) for f in sorted(HELP_DIR.glob("*.html"))],
                        load_sources()) == []
  ```

- [ ] **Step 2: Run them to make sure they fail** (`ModuleNotFoundError: help_tools.pages`).
- [ ] **Step 3: Implement `pages.py` with `html.parser.HTMLParser`** (`convert_charrefs=True`).
  - Keep a stack of open tags.
  - Pop to the matching tag on an end tag.
  - Treat void elements (`img`, `link`, `meta`, `br`, `hr`, `input`, `mspace`) as never opened.
  - A `<section>` start closes any `<p>` still open.
  - Record the innermost enclosing section id for each claim and link.
- [ ] **Step 4: Run all three commands.** The real-pages tests pass vacuously while `help/` is
  empty and all twelve steps are pending.
- [ ] **Step 5: Prove discrimination.** Every mutation test above is itself a discrimination
  check. Additionally, mutate `check_page` to skip the schema comparison and to compare
  sections as sets; both must fail.
- [ ] **Step 6: Commit and push.** Message: `feat(help): the page contract, enforced over every page`.

---

### Task 4: The figure script

**Files:**
- Create: `packages/nsgeo-qgis/scripts/make_help_figures.py`
- Test: `packages/nsgeo-qgis/tests/pure/test_help_figures.py`. Put `pytest.importorskip("matplotlib")`
  at the top, so it runs under `.venv-qgis` only. The script is not a package, so load it with
  `importlib.util.spec_from_file_location`.

Start from the throwaway scripts in the spec's attachments folder (`dewow_images.py`,
`dewow_response.py`). Same pictures, cleaned up.

**Interfaces:**
- Produces:
  - `DEFAULT_DATA = <repo>/packages/nsgeo-core/tests/data/local/FILE__007.DZT`
  - `DEFAULT_OUT = HELP_DIR / "img"`
  - `load_radargram(dzt: Path) -> tuple[Radargram, DztHeader]`: channel 0 of
    `read_samples`, `dt_ns=header.dt_ns`, `t0_ns=header.position_ns`. This mirrors
    `Radargram.from_profile`.
  - `RECIPES: dict[str, Callable[[Radargram, DztHeader, Path], list[Path]]]`, which for now holds
    only `"dewow"`.
  - `make_figures(dzt: Path, out_dir: Path, steps: list[str] | None = None) -> list[Path]`.
    `None` means every recipe.
  - `measure_dewow(dt_ns: float, windows_ns: tuple[float, ...] = (2.0, 4.0, 8.0)) -> list[dict]`.
    Each dict has the keys `window_ns`, `samples`, `used_ns`, `half_power_mhz`, `peak_gain`,
    `peak_mhz`.
  - `main(argv: list[str] | None = None) -> int`, taking `--data`, `--out`, `--step`
    (repeatable) and `--report` (prints `measure_dewow(dt)` as JSON and writes nothing).

  Run it as `./.venv-qgis/bin/python packages/nsgeo-qgis/scripts/make_help_figures.py`. The
  script puts `packages/nsgeo-qgis` on `sys.path` and imports `nsgeo_qgis` first, which runs the
  core path shim.

The dewow recipe writes three PNGs at dpi 150, matching the draft's:

- **`dewow_trace.png`** shows trace `n_traces // 2` with time on the x axis, up to 40 ns.
  - Upper panel: the recorded trace in grey, with the running mean in red.
  - Lower panel: the result.
  - The running mean is **`StepStack.difference(0)`** at that trace, so no `_util` import is
    needed.
- **`dewow_panels.png`** has three panels: "Before", "After dewow (window 4 ns)" and "What dewow
  removed".
  - They come from a `StepStack` with source set and `dewow` appended: `source`,
    `intermediate(0)` and `difference(0)`.
  - Each panel is scaled on its own: `PercentileClip(99).limit`, `colormap(DEFAULT_COLORMAP)`,
    `to_rgb8`.
  - The y axis is two-way time down to 50 ns. The x axis is distance from `traces_per_metre`, or
    trace number when that is 0.
- **`dewow_response.png`** shows `|rfft|` of the default dewow applied to a unit spike: 8192
  samples at the file's `dt_ns`, plotted up to 1000 MHz.
  - A dashed line marks 1, and a dotted line marks 1/√2.
  - A red dotted marker sits at the antenna's nominal frequency, parsed as the first 2–4 digit
    run in `header.antenna` ("HS350US" → 350). Leave the marker out when there is none.

- [ ] **Step 1: Write the failing tests**

```python
def test_measure_dewow_matches_the_design_measurements():     # spec §8, campus Δt
    rows = {r["window_ns"]: r for r in measure_dewow(0.21653111279010773)}
    assert rows[4.0]["samples"] == 18 and rows[4.0]["used_ns"] == pytest.approx(3.898, abs=1e-3)
    assert rows[4.0]["half_power_mhz"] == pytest.approx(193, abs=4)
    assert rows[4.0]["peak_gain"] == pytest.approx(1.214, abs=0.01)
    assert rows[4.0]["peak_mhz"] == pytest.approx(366, abs=6)
    assert rows[2.0]["samples"] == 9 and rows[8.0]["samples"] == 37

def test_make_figures_writes_three_pngs_for_dewow(tmp_path):
    dzt = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    paths = make_figures(dzt, tmp_path / "img", ["dewow"])
    assert sorted(p.name for p in paths) == ["dewow_panels.png", "dewow_response.png", "dewow_trace.png"]
    assert all(p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" for p in paths)
    assert {p.parent for p in paths} == {tmp_path / "img"}

def test_unknown_step_is_refused(tmp_path):
    with pytest.raises(KeyError, match="time_zero"):
        make_figures(synthetic_dzt(tmp_path, "F.DZT"), tmp_path, ["time_zero"])
```

- [ ] **Step 2: Run them under `.venv-qgis` to make sure they fail.**
- [ ] **Step 3: Implement.** Use the `Agg` backend. `measure_dewow` uses `build_step("dewow",
  window_ns=W)` on the spike. The half-power frequency is the first frequency where
  `|H| >= 1/sqrt(2)`; the peak is the maximum of `|H|`.
- [ ] **Step 4: Run all three commands.** Then run the script for real on `FILE__007` into a
  scratch directory (never `help/img`; Task 5 does that). Look at the three PNGs and confirm
  they match the attachments.
- [ ] **Step 5: Prove discrimination.** The mutants:
  - spike FFT magnitude without `abs`;
  - `round` replaced by `int`, which gives 17 samples at 4 ns;
  - the half-power point taken as the first point with `|H| >= 0.5`.
- [ ] **Step 6: Commit and push.** Message: `feat(help): figure script — nsgeo's own steps on the campus line`.

---

### Task 5: The dewow page

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/help/style.css`
- Create: `packages/nsgeo-qgis/nsgeo_qgis/help/dewow.html`
- Create: `packages/nsgeo-qgis/nsgeo_qgis/help/img/dewow_{trace,panels,response}.png`, generated
  by Task 4's script
- Modify: `packages/nsgeo-qgis/help_tools/sources.json`
- Modify: `packages/nsgeo-qgis/tests/pure/test_help_pages.py`: remove `"dewow"` from `PENDING`

**Interfaces:**
- Consumes: the Task 3 contract, `make_help_figures.py --step dewow` and `--report`.

**The draft** is `docs/superpowers/specs/2026-10-15-nsgeo-help-pages/dewow-draft.html`. The user
reviewed it ("honestly looks great"), so keep its look, voice, sections and depth.

The changes:

1. **Drop the review band** (`<section class="review">` and its CSS). Move the page CSS into
   `style.css`, linked as `<link rel="stylesheet" href="style.css">`. Image sources become
   `img/dewow_*.png`.
2. **Shorten the `#plain` paragraph** until `fk_grade <= 9.0`. The draft scores about 9.7 and
   has 24-word sentences. Keep every idea: the pulse and recording, the slow drift called
   "wow", the boat analogy, subtracting a local average. Split the sentences; don't cut content.
3. **Fix the Settings refusal sentence (spec §8, issue #40).**
   - A window that rounds to **zero** samples is refused.
   - A window that rounds to **exactly one** sample runs and removes everything. On the campus
     line that is about 0.11–0.32 ns. Link
     `https://github.com/JamesZDonline/nsgeo/issues/40`, with `data-source="nsgeo-issue-40"`.
4. **Regenerate the figures** into `help/img/` from `FILE__007`. Take the Settings table's
   numbers from `--report`, and replace the draft's numbers if they differ.
5. **Mark up** the page:
   - Add `data-param="window_ns"` on the Window block.
   - Each sentence in `#method` and `#know` that relies on an outside source gets a
     `data-claim` (ids `dewow-<slug>`) and its `data-source` ids.
   - Add `data-source` on every outbound link and every `#refs` item.
   - **Any factual statement that is neither measured, nor read from nsgeo's code, nor backed by
     a confirmed source is cut.** Example: the draft's "running median or a smooth curve"
     sentence, unless a free source for it is found and read.
6. **The sources file.** Use these ids:
   - `cassidy2009`, `annan2009`, `conyers2013`;
   - `wp-ground-penetrating-radar`, `wp-moving-average`, `wp-low-pass-filter`,
     `wp-high-pass-filter`, `wp-sinc-function`, `wp-dirichlet-kernel`, `wp-prefix-sum`;
   - `nsgeo-issue-40`.

   Confirm each one exists before entering it:
   - Wikipedia and the issue: check `curl -sIL <url>` ends in HTTP 200, then record the URL as
     `checked_via`.
   - The books: record the catalogue URLs from spec §6.1 and note "page range not confirmed".

   Evidence is `"memory"` unless the passage was actually read, in which case it's `"read"` with
   a quote. Never link the unauthorized Jol PDF (spec §6.1).
7. **Remove `dewow` from `PENDING`.**

- [ ] **Step 1: Remove `dewow` from `PENDING` and run the contract tests.** They are expected to
  FAIL because `dewow.html` is missing.
- [ ] **Step 2: Generate the figures and the report.**
- [ ] **Step 3: Write `style.css` and `dewow.html`, and fill `sources.json`** as above.
- [ ] **Step 4: Run all three commands.** Every contract test passes with one real page.
- [ ] **Step 5: Look at it.** Take a light-mode screenshot:
  `google-chrome --headless --disable-gpu --screenshot=/tmp/<scratch>/dewow.png
  --window-size=900,6000 file://$PWD/packages/nsgeo-qgis/nsgeo_qgis/help/dewow.html`.
  Check that the equations render as MathML (not raw tags) and that all three figures load.
  Record anything off in the report.
- [ ] **Step 6: Prove discrimination.** Against the real page, delete `data-param`, add
  `<script></script>`, and delete one `sources.json` entry. Each must fail
  `test_every_page_meets_the_contract` or `test_pages_and_sources_file_agree`. Revert all three.
- [ ] **Step 7: Commit and push.** Message: `docs(help): the dewow page`.

---

### Task 6 (controller): The checking page

This task needs the Artifact tool, so the controller does it.

**Files:**
- Create: `packages/nsgeo-qgis/help_tools/ledger.py`
- Create: `packages/nsgeo-qgis/help_tools/checking_page.html`, the template
- Modify: `help_tools/sources.json` (`checking_page` URL)
- Test: `tests/pure/test_help_tools.py` (append)

**Interfaces:**
- Produces:
  - `build_ledger(help_dir: Path, sources: Sources) -> dict`. It returns
    `{"items": [...], "sources": {id: {citation, url, checked_via, checked_on, note}}}`.
    Items are in page-name order, then document order:
    - claims become `{"id": claim.id, "kind": "claim", "page", "section", "text",
      "sources": [ids], "evidence", "look", "quote"}`;
    - links become one item per (page, source):
      `{"id": f"link-{page}-{source}", "kind": "link", "page", "section", "text": link text,
      "sources": [source]}`.
  - `render_checking_page(ledger: dict, template: Path) -> str`. It replaces the single
    `/*__LEDGER__*/null` token with the JSON, with `</` escaped as `<\/`.
  - `main(argv) -> int`: `python -m help_tools.ledger --html OUT`, run from
    `packages/nsgeo-qgis`.

- [ ] **Step 1: Write the failing tests.**
  - `build_ledger` on the Task 3 fixture page gives one claim item with the right page, section,
    text and evidence, and one `link-dewow-t-src` item.
  - Two calls give equal output.
  - A claim whose text contains `</script>` renders with it escaped.
- [ ] **Step 2: Implement `ledger.py`. Run the tests and confirm they pass.**
- [ ] **Step 3: Load the `artifact-capabilities` skill. Then write `checking_page.html`.**
  - It reads the embedded ledger and groups items by source, showing each source's citation and
    its "exists" record.
  - Per item it shows: page and section, the exact text, the evidence (with the quote if
    `read`), and where to look.
  - Each item has two three-state controls (`unchecked` / `ok` / `wrong`): **"exists as
    cited"**, labelled as pre-checked by Claude with the catalogue link, and **"says this"**.
    It also has a notes box.
  - The db capability is `{db: {}}`. Collection `checks`, doc id = item id, fields
    `{exists, says, note}`, written one doc at a time and only on change.
  - It shows a progress count, and renders read-only with a notice when `use("db")` is `null`.
  - Follow `artifact-design` for tokens and dark mode.
- [ ] **Step 4: Publish.** Run `python -m help_tools.ledger --html <scratch>/checking.html`, then
  publish it with `capabilities: {db: {}}`, title "Help Sources Check" and icon `checklist`.
  Check it with one `ArtifactData` `list` of `checks`. Record the URL in
  `sources.json["checking_page"]`.
- [ ] **Step 5: Run all three commands. Commit and push.** Message: `feat(help): the sources ledger and its checking page`.

Later chunks republish to the same URL. Ticks survive, because doc ids are claim ids.

---

## Chunk gate: build and walkthrough (human)

The standing rule applies: no merge proposal until this is done.

1. After the whole-branch review comes back clean, deploy with
   `./.venv/bin/python packages/nsgeo-qgis/scripts/dev_link.py --profile ns_geo`. This repoints
   the plugin symlink at this worktree.
2. Publish the walkthrough as an Artifact with `db`. It covers:
   - the Help button's place and its disabled and enabled states;
   - a click opening the page in the browser;
   - the page with the network off;
   - dark mode;
   - the equations and figures;
   - every link;
   - the checking page.
3. Wait for the user's results.
4. After the merge, repoint the symlink at `.worktrees/nsgeo-main` (memory: that detached
   worktree is the deploy target for main).
