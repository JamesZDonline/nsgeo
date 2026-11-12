# What identifies a Line (#89): short design

2026-11-12. Small change. Approach chosen by the user ("go with your recommendation").

## Intent

M13 gave `Line` a `velocity_fits` dict, so the hash Python generates for a frozen dataclass now
raises `TypeError` and a `Line` can't go in a set or serve as a cache key. Nothing hashes one
today, but the README roadmap puts this before M17 for a sharper reason. M17 stores GPS fixes on
a line's placement. If those are numpy arrays, the generated `==` between two versions of the
same line raises `ValueError`, because the truth value of an array comparison is ambiguous.
Settle what "the same line" means before that lands.

## Goals, non-goals, anti-goals

- **Goal:** `Line` is hashable, and its `==` never inspects field values, so no field type
  (dict, array) can break it.
- **Non-goal:** `TrackPlacement`'s own equality. That belongs to M17 (see Follow-up).
- **Non-goal:** how the plugin keys lines. The session already names a line by
  `project.line_key(path, root)` and finds objects by key or `id()`; none of that changes.
- **Anti-goal:** an equality under which an edited line equals its old self. Every "did anything
  change?" check would then pass vacuously.

## What the code does today (measured)

The core, pure and QGIS test tiers were run with `Line.__eq__` instrumented: 1,501 + 2,234 passed.
There were 175 comparisons in all:

- 174 came from `site.lines.index(line)` in `session.py` (`_replace_line`, `set_line_velocity`,
  `add_velocity_fit`). Each compared different files and stopped at `path`, the first field. The
  matching element is always the very object passed, which `list.index` finds by identity before
  it calls `__eq__`.
- 1 compared two versions of the same line:
  `test_plugin_velocity_dialog.py::test_cancel_changes_nothing`
  (`assert s.line_for_key(key) == before`).

## Approaches

1. **Identity: `eq=False` (chosen).** Equality and hash are the object's. It's hashable, M17's
   arrays can't break it, and it matches `Profile` in the same module ("Equality is identity
   (`eq=False`): comparing sample arrays is a test concern"). The session code is unchanged:
   `list.index` still finds the object. Cost: a test that compares two separately built lines must
   compare their fields. The one existing same-line test gets stricter, since Cancel must now
   leave the very same object in place, not merely an equal one.
2. **Same file: `__eq__` and `__hash__` on `path`.** Reads naturally, but it breaks the
   anti-goal. It also names a line by `Line.path`, while the session names it by `line_key`
   (relative to the project root), so two spellings of one file could disagree.
3. **Same contents (today), with fits as a tuple.** Restores hashing but not M17 safety, and it
   reverses M13's keyed-by-id choice for `velocity_fits`, which matches `cubes` and `presets`.

## Design

- `packages/nsgeo-core/src/nsgeo/model/survey.py`: `@dataclass(frozen=True, eq=False)` on `Line`.
  The docstring says equality and hash are identity; across saves a line is named by its file
  (`project.line_key`); comparing two lines' contents is a test concern, done field by field.
  `frozen` stays.
- Core tests pin the behaviour:
  - a line is hashable with fits stored (a set and a dict of lines work);
  - a `dataclasses.replace` copy with identical fields is not equal to the original;
  - a line equals itself;
  - `site.lines.index(line)` finds the object it was given when a copy with identical fields
    stands earlier in the list.
- `test_cancel_changes_nothing` stays as written; it now asserts identity. An explicit `is`
  makes that intent readable.

## Left to the builder

Test names and which test file holds them.

## Follow-up (not this change)

M17 (`TrackPlacement`): `Line` equality no longer reaches the placement, so array fixes are safe
there. `TrackPlacement`'s own `==` is still generated, though, and `edit_lines` compares
placements (`current != edit.seen`, `same_placement`). Today that only happens behind an
`isinstance(..., GridPlacement)` check. Before M17 widens those checks to GPS lines, it has to
give `TrackPlacement` an equality that doesn't compare arrays. That belongs in M17a's plan.
