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
# Anything NOT listed here, and not in SHADOWED_CONNECT_COUNTS below, must
# have a connect.
#
# NOTE: spec §1's orphan table and §6's "the three existing orphans" are
# both wrong. The real set is SEVEN: the four below, plus
# `ProfileDock.pick_requested` and `ParamForm.error` (both invisible to a
# name-keyed check -- see SHADOWED_CONNECT_COUNTS) and
# `ProfileView.set_pick_mode`, an uncalled method rather than a signal, so
# it is outside what this automated check can see at all (spec §6's manual
# half -- Task 5's brief, Step 7).
KNOWN_UNCONSUMED = {
    # Adopted by M8, the pick tool (spec §4.1): session.add_pick emits it.
    "picks_changed",
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
# special-casing the first one. Every name pinned here is checked instead
# for an EXACT connect count, and `test_every_shadowed_signal_name_is_pinned`
# below is what stops a third one slipping in unpinned the way `error` did.
SHADOWED_CONNECT_COUNTS = {
    # ProfileView.pick_requested is connected (profile_dock.py wires it to
    # `_pick`). ProfileDock's own pick_requested -- a separate declaration
    # that happens to share the name -- is not: the real orphan.
    "pick_requested": 1,
    # ProfileDock.error is connected (plugin.py wires it to `self.message`).
    # ParamForm's own error -- again a separate declaration sharing the
    # name -- is not: the real orphan, in a different file. ParamForm is
    # built by both ProcessingDock and AddStepDialog; neither connects it.
    "error": 1,
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
    class and must be handled by SHADOWED_CONNECT_COUNTS, not by a plain
    connect-count check -- see its docstring."""
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
        if name not in KNOWN_UNCONSUMED
        and name not in SHADOWED_CONNECT_COUNTS
        and not _connect_count(blob, name)
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
    SHADOWED_CONNECT_COUNTS. This is the part that actually matters: it is
    what stops a second `pick_requested`-shaped duplicate slipping in
    unpinned and invisible, which is exactly how `error` got in undetected
    until this review."""
    sources = _sources()
    declared = _declared_signals(sources)
    shadowed = {name for name, sites in declared.items() if len({owner for owner, _ in sites}) > 1}
    missing = shadowed - set(SHADOWED_CONNECT_COUNTS)
    assert not missing, (
        "signal names declared by more than one class must be pinned in "
        f"SHADOWED_CONNECT_COUNTS with their current connect count: {missing}. "
        "A name-keyed connect count cannot tell two same-named signals "
        "apart, so one class's connect can hide the other's genuine orphan."
    )


def test_shadowed_connect_counts_match_reality() -> None:
    """Keeps SHADOWED_CONNECT_COUNTS honest, the same way
    test_the_known_unconsumed_signals_are_still_unconsumed keeps
    KNOWN_UNCONSUMED honest: if a pinned count changes, the shadowed
    signal's orphan status just changed and someone needs to say so, not
    have this check quietly stop meaning anything.

    e.g. M8 wiring ProfileDock.pick_requested to session.add_pick raises
    that entry's count from 1 to 2 and trips this test -- exactly the
    notification an allowlist entry would have given.
    """
    blob = "\n".join(_sources().values())
    mismatched = {
        name: (expected, _connect_count(blob, name))
        for name, expected in SHADOWED_CONNECT_COUNTS.items()
        if _connect_count(blob, name) != expected
    }
    assert not mismatched, (
        f"connect counts changed for shadowed signal names (expected, actual): "
        f"{mismatched}. If a new connect appeared, that shadowed signal's "
        "orphan may have just been adopted -- update the expected count and "
        "say so; if one disappeared, something was deleted or renamed."
    )
