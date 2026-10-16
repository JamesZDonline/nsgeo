# nsgeo processing help pages — design

A **Help** button on the Processing panel opens a page in the browser that explains the selected
step. It starts with a plain-language overview, moves to the textbook method, and ends with
nsgeo's exact computation. Every source the pages cite is tracked on a checking page, so the
user can confirm each one by hand.

Attachments, in `2026-10-15-nsgeo-help-pages/`:

- `dewow-draft.html` and its three figures make up the dewow page drafted during design. The user
  reviewed it and said it "honestly looks great", so it is the reference for look, voice and depth.
  Its top band, "Review notes, not part of the page", is review scaffolding and does not ship.
- `dock_top.png`, `dock_bottom.png` and `dock_q.png` are the three button placements that were
  compared. `dock_bottom.png` was chosen.
- `dewow_images.py`, `dewow_response.py` and `dock_shots.py` are the throwaway scripts that made
  those images. They are a starting point for the real figure script, not code to keep as is.

Decisions are marked **(user)** where the user made them and **(design call)** where they were
made during design and can still be overridden. Anything marked neither is left to the builder
(§11).

---

## 1. What this is for

The reader is **the person processing the GPR data (user)**. They are in the Processing panel and
want one of two things:

- to decide whether a step is the right tool for what they are trying to do with *their* data, or
- to understand exactly what a step does to it.

The page's job is to give them the information to **decide for themselves (user)**. Some general
guidance is fine. Prescribing is not: no "always run X before Y", and no recommended chains.

Help is reached only from a step **already in the list (user)**. If the page shows the tool is
wrong for the job, the user removes the step. The Add step menu gets no Help entry.

## 2. Goals, non-goals, anti-goals

**Goals**

- One Help button that opens a page for the selected step.
- One page per registered step. There are twelve today (§10).
- Every page builds up in three layers: plain words, the textbook method, nsgeo's exact
  computation.
- Pictures made from real survey data by running nsgeo's own code.
- Every outside source can be checked by hand, with the checking tracked.

**Non-goals**

- **Changing any processing code (user: "I want this to be a purely documentation session").**
  The only code this project adds is the Help button, the figure script, and the tests that keep
  pages and code in step. A bug found while writing a page is filed as a GitHub issue. The page
  describes what the code does today and links the issue (design call for the link). Issue #40
  is the first case (§8).
- Help from the Add step menu (see §1).
- Help for anything other than processing steps (docks, slices, picking).
- A help viewer inside QGIS. Pages open in the system browser.
- Translation.

**Anti-goals.** Each of these is a failure even if the feature works:

- **A source that doesn't exist, or doesn't say what the page claims.** The user raised this
  directly: "hallucinations can be a problem with sources, so let's be careful with that."
- Prescriptive voice: "you should", "always", "best practice is", recommended orders.
- A math section that describes the textbook version but not what nsgeo actually computes.
- A page that needs internet to read. Only the outbound links may need it.
- Numbers on a page that were estimated rather than measured or derived from the code.

---

## 3. The button

- A `QPushButton("Help")` goes in the Processing dock's **bottom row, immediately after Presets
  (user, option B)**. The other two options are in the attachments. Option A ("Help" in the top
  row) raised the dock's minimum width from 458 to 544 px. Option C ("?" in the top row) raised
  it to 488 px. Option B leaves it at 458.
- **Disabled when no step is selected (design call).** Also disabled if the selected step has no
  page, although the test in §9 means that can't happen in a release.
- The page for a step is found by its **registry name** (`dewow` → `dewow.html`), never from a
  hardcoded list. This matches the dock's rule that "steps come from the registry".
- Clicking opens the page with `QDesktopServices.openUrl(QUrl.fromLocalFile(...))`.
- Tooltip: "Open a page explaining the selected step" (design call).

## 4. The page

### 4.1 Sections, in order (user for the three-layer build-up; design call for the rest)

The draft's section ids are the contract, because the tests in §9 read them.

| id | Heading label | Contents |
|---|---|---|
| `plain` | In plain words | **One paragraph at about an 8th-grade reading level (user)**: what the step does, in everyday words, with an analogy where it helps. No symbols and no jargon. If a technical word is unavoidable, explain it in the same sentence. |
| `pictures` | What it does to a line | The figures (§5). |
| `method` | The method | **The textbook description (user)**: what the problem is, the standard approach, the general formula, with links to Wikipedia and other sources where they help understanding. It may mention other ways the same job is done, as information only. |
| `settings` | Settings | One block per setting in the step's `schema()`: what it controls, its unit and default, and what raising or lowering it does to the result. Include valid ranges and refusals (e.g. "must be at least one sample long or the step will not run"). Where a setting maps to a measurable effect, add a small table of measured values, as the dewow draft does for window → cutoff. |
| `know` | Things to know | **Side effects and limits, stated as facts (user approved)**: what else the step changes, what it cannot distinguish, edge behaviour. This is the section that most helps someone decide, and it must still not prescribe. |
| `related` | Related steps | Only for steps in a family (§10): one line per sibling on how it differs. **(design call)**: this helps people choose without telling them which to pick. |
| `nsgeo` | How nsgeo does it | **nsgeo's exact computation (user)**, "for those who really want to dig deep": the formulas as implemented, with indices, rounding, edge handling, dtype and any choice the code makes that the textbook formula doesn't. It ends with the source file path(s). |
| `refs` | Further reading | Every outside source the page uses (§6). |

The header carries the display name, the registry name in `code`, the settings in brief, and a
contents line linking each section.

### 4.2 Voice

- **Plain, but professional (user, 2026-10-16).** The bandpass draft compared the filter to a
  stereo's tone control and called frequencies "wiggle speeds". The user said it "reads a little
  silly, make it a bit more professional." The paragraph should read like a good field manual or
  museum label, not a children's book:
  - use the real term once, with a plain gloss;
  - use at most one analogy, and only a precise one;
  - no invented substitute words and no slang.
- **Plain words.** Short sentences. Measure the paragraph with the Flesch–Kincaid grade formula
  (§9). The dewow draft's paragraph scored **9.7** on the crude in-repo estimator used during
  design, so it needs shortening to meet the bar too.
- **Inform, don't prescribe.** "Below about 190 MHz, more than half the power is removed" is
  fine. "Use a 4 ns window for 350 MHz antennas" is not.
- **Describe the user's own data honestly.** If the campus line shows little effect, say so (the
  dewow draft does: "this line has almost no drift to begin with").
- Every number is measured by running nsgeo, or derived from the code, and the page says which.
  The dewow response figure is captioned "Measured, not drawn from the formula".

### 4.3 Look

The look follows the dewow draft: a serif body, sans-serif labels, a 780 px measure, light and
dark modes via `prefers-color-scheme`, and figures on a white background in dark mode.

- **One shared stylesheet**, `help/style.css`, so all pages match (design call).
- **No scripts, no CDN, no web fonts.** The page must render from disk with the network
  unplugged.
- **Equations are MathML (design call).** Current browsers draw it natively, so nothing is
  bundled or downloaded. Committed pages contain MathML, not LaTeX that needs a runtime renderer.

---

## 5. Pictures (user: "That'd be great"; real campus data approved for publication)

- **Data.** The pictures come from the campus training run: ten GSSI SIR-4000 files (HS350US
  antenna) in `packages/nsgeo-core/tests/data/local/`, which is gitignored. The user approved
  publishing images made from these lines inside the plugin, including in a public release zip.
  The user picked no particular line, so **`FILE__007` was chosen at random (design call)**, and
  the user expects the choice may change later.
- **One line for every page (design call).** The three gains, three background removals and
  three amplitude transforms can then be compared on identical data.
- **The DZT files themselves are never committed.** Only rendered PNGs are, and they carry no
  coordinates, file names or site details. The footer gives the instrument and "campus training
  line".
- **Produced by one script.** It runs nsgeo's own code: `StepStack`, the registry, and
  `nsgeo.render` with the plugin's default colormap and clip. The pictures therefore show exactly
  what the plugin would show, and changing the line means re-running one command. It needs
  matplotlib, which the system Python and `.venv-qgis` already have. It can't run in CI because
  the data is local.
- **What each page shows.** Usually three panels: before, after, and the **difference exactly as
  `StepStack.difference` computes it** (input minus output). That is the same view the dock's
  Difference button shows. Add a single-trace plot or a response curve wherever it explains the
  step better, as the dewow draft does.
  - Where `StepStack.difference` refuses (a step that changes the sample count, e.g. possibly
    `time_zero`), the page omits that panel.
  - **The `amp_*` steps** (design call, to revisit with the user at the amplitude chunk): the
    Profile panel does *not* use `is_unipolar`. It draws every radargram through
    `RadargramImage` with `PercentileClip` and the two-sided `grey_black_high` scale, so
    `amp_*` output appears with zero at mid-grey, using half the scale. The pictures match what
    the Profile panel shows, and the caption says so. Only the Slices panel uses
    `UnipolarClip` and the `amp_*` colour tables.
- **Later steps run on processed input (design call).** For a step that normally runs after
  others (gains, background removal, amplitude transforms), "before" is the line after those
  earlier steps. The caption lists exactly which steps ran and with what settings.
- **Steps with REQUIRED settings (design call).** `bandpass` and `gain_curve` cannot run without
  values. Their figure values appear in the caption as "values used for this picture", never as
  a suggestion.
- Captions state the scaling, e.g. "each panel scaled on its own (99th-percentile clip)", so no
  panel misleads by contrast.

## 6. Sources

### 6.1 Rules for citing

- **Prefer sources the user can read for free online** (open-access papers, software
  documentation, government reports, Wikipedia). Both the writer and the user can then check
  the claim, not just the existence of the source. Paywalled books are allowed and expected:
  Jol (2009) and Conyers (2013) are the field's standards.
- **Every outside link and every reference is a ledger entry (§6.3).** This includes Wikipedia
  links.
- **Every citation records how the writer knows the claim.** There are two kinds:
  - *read*: the writer actually read the passage. Record a short quote and the URL or the
    page/section.
  - *from memory*: the source's existence is confirmed but its content isn't. The user has to
    check the claim.

  Nothing is labelled *read* unless it was.
- **Existence is confirmed before a source goes on a page:** a library catalogue, publisher page,
  DOI resolver or ISBN record, with the URL recorded. Details that can't be confirmed (e.g. a
  chapter's page range) are left out, not guessed.
- **Measured claims cite no outside source.** They point to the script and the inputs that
  produced them.
- **Never link to unauthorized copies.** During design a full PDF of Jol (2009) turned up on a
  university website; it must not be linked.

Confirmed during design, for the dewow page:

- Cassidy, "Ground penetrating radar data processing, modelling and analysis", and Annan,
  "Electromagnetic principles of ground penetrating radar". These are Chapters 5 and 1 of
  H. M. Jol (ed.), *Ground Penetrating Radar: Theory and Applications*, Elsevier 2009, ISBN
  978-0-444-53348-7 (table of contents at vufind.techlib.cz/Record/001809382/TOC). Page ranges
  were not confirmed.
- Conyers, *Ground-Penetrating Radar for Archaeology*, 3rd ed., AltaMira / Rowman & Littlefield,
  2013.
- The dewow draft's claims about what Cassidy and Annan *say* are **from memory**.

### 6.2 Unchecked claims hold nothing up (user, "for now")

Chunks merge and ship whether or not the user has ticked "says this" on their claims. Pages
carry no "unverified" mark. Tick state lives only in the checking page's database. Nothing in the
repo or the release build reads it. If that changes later, the claim ids are already in place.

### 6.3 The ledger and the checking page (user: "a page in the browser"; not lavish)

There are three layers:

1. **Claims are marked in the pages.** A sentence or paragraph that relies on a source carries a
   stable claim id and the source id(s), e.g. `data-claim="dewow-wow-origin"
   data-source="annan2009"`. Each reference list item and each outbound link carries
   `data-source`. The pages are the source of truth for *what is claimed*.
2. **The bibliography lives in a sources file in the repo, one entry per source id.** It holds
   the full citation, identifiers (ISBN/DOI/URL), the existence-check record (where and when it
   was confirmed), and for each claim the evidence kind (*read* + quote, or *from memory*) and
   where in the source to look. The file's format and exact location are left to the builder.
3. **The checking page is a private claude.ai Artifact with the `db` capability.** It works like
   the walkthrough pages. Lavish was rejected by the user: "it's clunky for that sort of record
   keeping". The page lists every claim, grouped by source:
   - the page and section it's on, and the exact sentence;
   - the evidence kind;
   - two checks: **"exists as cited"**, pre-filled with the writer's catalogue record, which the
     user may confirm, and **"says this"**, the user's;
   - a notes field.

   Ticks and notes persist in the artifact's database, keyed by claim id, so they survive
   republishing and the user can work across many sittings. Claude publishes the page from the
   repo's data with the Artifact tool. It is not part of the plugin and is not built by code. When
   pages change, Claude republishes it. When the user flags a claim, Claude reads the database
   with ArtifactData and fixes the page.

## 7. Where things live (design call)

- `packages/nsgeo-qgis/nsgeo_qgis/help/`: `<registry name>.html` for each step, `style.css`, and
  the figures in a subfolder. They live inside the plugin package so they ship with it. When M9
  builds the release zip, it must include `help/` (a note for M9, not work for this project).
- The figures go in a dev-only package, `packages/nsgeo-qgis/help_tools/figures/`, with one module
  per step. This was amended by the chunk 1 plan so pages can be written in parallel; it was
  originally a single script in `scripts/`.
- The sources file and the code that turns pages plus sources into the checking page's data:
  placement is the builder's call, kept out of the shipped `help/` folder unless there's a reason.

## 8. Facts measured during design

These were measured on campus line `FILE__007` (512 samples, Δt = 0.21653 ns, 635 traces), with
the scripts in the attachments folder:

- Dewow at the default 4 ns window uses **18 samples (3.90 ns)**. That removes more than half the
  power below about **193 MHz** and **boosts** frequencies near **366 MHz by about 21%**, close
  to the HS350US centre frequency.
  - At 2 ns: 9 samples, half-power about 389 MHz, peak 1.227 near 737 MHz.
  - At 8 ns: 37 samples, about 95 MHz, peak 1.218 near 179 MHz.
  - The rules of thumb are half-power ≈ 0.75 / W and peak ≈ 1.43 / W.
- On this line the raw data is already near zero-mean with little drift. Most of what dewow
  removes there is the low-frequency part of the radar pulse itself.
- **Dewow silently zeroes the line when the window rounds to one sample** (issue #40). On this
  line that is any window from about 0.11 to 0.32 ns. `background_sliding` with
  `window_traces=1` does the same. The draft's Settings sentence ("at least one sample long ...
  or the step will not run") is therefore wrong. The finished page describes the real behaviour
  and links #40.
- The Processing dock's minimum width is 458 px; option A would raise it to 544 px and option C
  to 488 px.

The dewow default may deserve a separate look. That is out of scope here; the help page just
states the facts.

## 9. Enforced by tests (design call)

These run in CI with no real data:

- Every name in `available_steps()` has `help/<name>.html`, and every page in `help/` belongs to a
  registered step. A new step, such as M13's, can't ship without a page.
- Every page has the section ids of §4.1 in order. `related` is required only for family members.
- Every setting in a step's `schema()` is documented in that page's `settings` section, matched by
  a `data-param="<name>"` marker. A new setting fails the test until it is documented.
- Every image a page references exists. Pages contain no `<script>` and no `http(s)` stylesheet,
  font or image.
- Every `data-source` on a page has a sources-file entry, and every sources-file entry is cited
  somewhere.
- The `plain` paragraph scores **at or below grade 9.0** on Flesch–Kincaid, computed by a small
  deterministic in-repo function. That is a guard rail for "about 8th grade", not a precise
  measure.
- Button tests:
  - It sits in the bottom row after Presets.
  - It is disabled with nothing selected and enabled with a step selected.
  - A click opens exactly that step's file, checked by monkeypatching `QDesktopServices.openUrl`.
  - Per the environment facts, assert on resulting state, since an exception in a slot doesn't
    reach the test.

Not testable in CI: whether the figures are current (no data), and whether the prose is right.
The second is what the checking page and the walkthrough are for.

## 10. The steps, and build order (design call; chunks of 3–6 tasks per the standing preference)

There are twelve steps, in five groups:

| Family | Steps | Settings (schema) |
|---|---|---|
| — | `time_zero` | mode (choice), sample, threshold |
| — | `dewow` | window_ns |
| — | `bandpass` | low_mhz *(required)*, high_mhz *(required)*, taper_frac |
| Gains | `gain_agc`, `gain_parametric`, `gain_curve` | window_ns, target, eps / mode, alpha, exponent / points *(required)* |
| Background removal | `background_mean`, `background_sliding`, `background_svd` | — / window_traces / n_components |
| Amplitude | `amp_abs`, `amp_square`, `amp_envelope` | none |

**Chunk 1, the frame plus one page.** This chunk:

- adds the button;
- builds `help/` with `style.css`;
- writes the figure script;
- sets up the sources file, claim markup and the checking-page data;
- adds the §9 tests, starting from the per-page checks that apply to dewow. The every-step-has-a-page
  test can't be green until the last chunk, so the builder decides how it is introduced (e.g.
  listing the pages still pending, with the list required to be empty by the end);
- finishes the dewow page from the draft, shortening its plain paragraph to meet the reading-level
  bar;
- publishes the checking page with dewow's claims.

It ends with a build to the `ns_geo` profile and a walkthrough, per the standing rule: press
Help, see the page.

**Then the other eleven pages, in parallel (user, 2026-10-15: "once we've got started I think we
can massively parallelize this because each help page is independent").** This replaces the
original family-by-family chunks.

- Chunk 1 lays the files out so that each page's work touches only files named for that page.
- One writer per page works in its own worktree.
- The controller integrates each page, then republishes the checking page.
- One walkthrough comes at the end.

The chunk 1 plan's closing section has the details.

Writing a page means reading the step's code first (for `nsgeo`), measuring before stating any
number, and confirming a source exists before citing it. Then the reviewer checks the `nsgeo`
section against the code line by line. The reviewer cannot check content claims against
paywalled sources, which is what the checking page is for.

## 11. Left to the builder

- The sources file's format and location, and how the checking-page data is generated.
- Whether pages are hand-written HTML or generated from a template. Either way, the committed
  output is plain HTML that renders offline.
- How MathML is authored, e.g. by hand or converted from LaTeX at write time with a tool. Any new
  tool is installed only after asking the user.
- The figure script's interface and image sizes. Keep the committed PNGs reasonably small; the
  dewow draft's three are about 250 KB together.
- Display names on the pages ("Dewow", "Automatic gain control", ...).
- The exact Flesch–Kincaid implementation, as long as it is deterministic and documented.
