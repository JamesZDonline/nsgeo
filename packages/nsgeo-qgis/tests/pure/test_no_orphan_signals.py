"""Spec §6: every declared signal has a consumer.

Plan 2 shipped three APIs with no consumer at all. The cost was not
theoretical: a manual tester went looking for a pick mode, found
`ProfileView.set_pick_mode`, and concluded the build was wrong rather than
that the feature was unbuilt.

A signal with no consumer reads exactly like a working feature from the
emitting side, so the check is to look for the `connect`, never the
`emit`. This lives in the pure tier because it reads source text and needs
no QGIS.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "nsgeo_qgis"

# Declared with no consumer anywhere, each with the reason it survives.
# Anything NOT listed here, and not in SHADOWED below, must have a connect.
#
# NOTE: spec §1's orphan table and §6's "the three existing orphans" are
# both wrong. `ProfileDock.pick_requested` gained its consumer in M8's
# Task 3 (plugin.py wires it to `_on_pick_requested`); `SiteSession.
# picks_changed` gained its in Task 4 (`ProfileDock._on_picks_changed`,
# see profile_dock.py) and has left this set entirely. What is left is
# `ParamForm.error` (invisible to a name-keyed check -- see SHADOWED,
# below) plus the three dead `SurveyDock` signals this set still holds.
KNOWN_UNCONSUMED = {
    # Dead API from Plan 2: plugin.py's toolbar actions do New, Open and
    # Save, and SurveyDock's own signals for them were never wired to
    # anything. Deleting them is Plan 2 cleanup, not M7 work -- pulling it
    # in here is the scope creep the 3-6 task rule exists to prevent.
    "new_site_requested",
    "open_site_requested",
    "save_requested",
}

# A signal name declared by more than one class cannot be judged by a
# name-keyed connect count: one class's connect satisfies the count while
# a *different* class's own signal of the same name stays genuinely
# unconsumed, invisible to `test_every_declared_signal_has_a_connect`.
# `pick_requested` was the first case found; `error` was a second,
# discovered only because Task 5's review generalised the check instead of
# special-casing the first one.
#
# Pinning only the connect count (an earlier round of this check did
# exactly that) leaves a gap one level up: nothing stops a THIRD class
# declaring the same name, unconnected, on top of an already-pinned entry
# -- the connect count the table already expects would not move, so the
# suite would stay green. Pinning `declared` (how many classes declare the
# name) alongside `connects` (how many connects exist) closes that: either
# number changing means the shadowing itself changed shape, which is
# exactly when someone needs to look. `test_every_shadowed_signal_name_is_pinned`
# is what stops a *new* shadowed name slipping in unpinned in the first
# place; `test_shadowed_signals_match_their_pinned_shape` is what stops an
# *already-pinned* one drifting undetected.
SHADOWED = {
    # ProfileView.pick_requested is connected (profile_dock.py wires it to
    # `_pick`). ProfileDock's own pick_requested is connected too as of
    # M8: plugin.py wires it to `_on_pick_requested`, which calls
    # session.add_pick. Both declarations now have a consumer, so this
    # entry no longer hides an orphan -- it stays pinned because a
    # name-keyed count still cannot tell the two apart, and dropping to
    # one connect again would mean one of them had been orphaned.
    "pick_requested": {"declared": 2, "connects": 2},
    # ProfileDock.error is connected (plugin.py wires it to `self.message`).
    # ParamForm's own error -- again a separate declaration sharing the
    # name -- is not: the real orphan, in a different file. ParamForm is
    # built by both ProcessingDock and AddStepDialog; neither connects it.
    "error": {"declared": 2, "connects": 1},
}


def _sources() -> dict[Path, str]:
    return {p: p.read_text(encoding="utf-8") for p in sorted(PACKAGE.rglob("*.py"))}


def _signal_call_name(value: ast.expr) -> str | None:
    if not isinstance(value, ast.Call):
        return None
    func = value.func
    return func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)


class _SignalVisitor(ast.NodeVisitor):
    """Records every `x = pyqtSignal(...)` / `x: T = pyqtSignal(...)`
    declaration, tagged with the class it was found in (or `<module>` for
    one declared outside any class, which none currently are, but a
    module-level sentinel is cheaper than assuming there never will be
    one).

    Two statement shapes are handled -- plain `Assign` (every declaration
    in this codebase today) and `AnnAssign` (`x: pyqtSignal = ...`) -- so a
    module that later adopts the annotated style does not quietly fall out
    of this check's view.
    """

    def __init__(self, path: Path, found: dict[str, list[tuple[str, Path]]]) -> None:
        self.path = path
        self.found = found
        self.class_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def _record(self, target: ast.expr, value: ast.expr) -> None:
        if _signal_call_name(value) != "pyqtSignal" or not isinstance(target, ast.Name):
            return
        owner = self.class_stack[-1] if self.class_stack else "<module>"
        self.found.setdefault(target.id, []).append((owner, self.path))

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._record(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._record(node.target, node.value)
        self.generic_visit(node)


def _declared_signals(sources: dict[Path, str]) -> dict[str, list[tuple[str, Path]]]:
    """name -> [(owning class name, file), ...], one entry per declaration
    site. A name with more than one entry is declared by more than one
    class and must be handled by SHADOWED, not by a plain connect-count
    check -- see its docstring."""
    found: dict[str, list[tuple[str, Path]]] = {}
    for path, text in sources.items():
        _SignalVisitor(path, found).visit(ast.parse(text, filename=str(path)))
    return found


def _connect_count(blob: str, name: str) -> int:
    return len(re.findall(rf"\.{re.escape(name)}\s*\.connect\s*\(", blob))


def test_every_declared_signal_has_a_connect() -> None:
    sources = _sources()
    blob = "\n".join(sources.values())
    orphans = {
        name: sites[0][1].name
        for name, sites in _declared_signals(sources).items()
        if name not in KNOWN_UNCONSUMED and name not in SHADOWED and not _connect_count(blob, name)
    }
    assert not orphans, (
        "signals declared with no consumer anywhere in the plugin: "
        f"{orphans}. A signal nothing connects to reads like a working "
        "feature from the emitting side. Either connect it, delete it, or "
        "-- if a later milestone adopts it -- add it to KNOWN_UNCONSUMED "
        "with the reason."
    )


def test_the_known_unconsumed_signals_are_still_unconsumed() -> None:
    """Keeps KNOWN_UNCONSUMED honest: once one is connected it must leave
    the list, or the list stops being a to-do and becomes a permanent
    exemption nobody rereads."""
    blob = "\n".join(_sources().values())
    stale = [name for name in KNOWN_UNCONSUMED if _connect_count(blob, name)]
    assert not stale, f"now consumed -- remove from KNOWN_UNCONSUMED: {stale}"


def test_every_shadowed_signal_name_is_pinned() -> None:
    """Any signal name declared by more than one class must appear in
    SHADOWED. This is what stops a second `pick_requested`-shaped
    duplicate slipping in unpinned and invisible, which is exactly how
    `error` got in undetected the first time this check existed."""
    sources = _sources()
    declared = _declared_signals(sources)
    shadowed = {name for name, sites in declared.items() if len({owner for owner, _ in sites}) > 1}
    missing = shadowed - set(SHADOWED)
    assert not missing, (
        f"signal names declared by more than one class must be pinned in SHADOWED: {missing}. "
        "A name-keyed connect count cannot tell two same-named signals "
        "apart, so one class's connect can hide the other's genuine orphan."
    )


def test_shadowed_signals_match_their_pinned_shape() -> None:
    """Keeps SHADOWED honest in both dimensions, not just the connect
    count.

    A round of this check that pinned only the connect count let a THIRD
    class declare an already-pinned name, unconnected, with the suite
    still green: the connect count the table already expected never
    moved, so nothing noticed a brand new orphan had joined the shadow.
    Checking `declared` (how many classes declare the name) alongside
    `connects` (how many connects exist) closes that -- either number
    changing means the shadowing itself changed shape, which is exactly
    when someone needs to look, the same way
    `test_the_known_unconsumed_signals_are_still_unconsumed` keeps
    KNOWN_UNCONSUMED honest.

    e.g. M8 wiring ProfileDock.pick_requested to session.add_pick raises
    that entry's `connects` from 1 to 2 and trips this test -- exactly the
    notification an allowlist entry would have given.
    """
    sources = _sources()
    declared = _declared_signals(sources)
    blob = "\n".join(sources.values())
    mismatched = {
        name: {
            "declared": (expected["declared"], len(declared.get(name, []))),
            "connects": (expected["connects"], _connect_count(blob, name)),
        }
        for name, expected in SHADOWED.items()
        if len(declared.get(name, [])) != expected["declared"]
        or _connect_count(blob, name) != expected["connects"]
    }
    assert not mismatched, (
        "shadowed signals no longer match their pinned shape, as (expected, actual) "
        f"pairs: {mismatched}. A `declared` mismatch means a class was added or "
        "removed for that name; a `connects` mismatch means a connect was added or "
        "removed. Either way the shadowing changed -- update SHADOWED and say why."
    )
