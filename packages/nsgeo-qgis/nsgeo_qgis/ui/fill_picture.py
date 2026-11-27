"""What Cancel takes back, and when a cancelled fill latches (#193).

Scope-generic, so This grid and Whole site share it: the scope wires it to its
own record (`slice_resolution` / `site_resolution`), its own widgets and its
own apply, through callbacks, and this class owns the picture's settings, the
take-back, and the one latch (it drives `FillFlow.latch`/`unlatch`).

The settings a fill is for are the fill fields only: the cell, the method and
the max distance (the search radius follows from it). Cancel puts back those,
each with its key presence in the record (present -> that value; absent ->
removed), and sets only their widgets. Every other field of the record (z
range, smoothing, ...) is left as the user has it now.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Hashable
from typing import Any

from nsgeo_qgis.slices_plan import FILL_CANCELLED_KEPT_NOTE, FILL_CANCELLED_NOTE, SliceFinish
from nsgeo_qgis.ui.fill_flow import FillFlow

#: The remembered-resolution fields a fill is made for.
FILL_FIELDS = ("cell", "method", "max_distance_spacings")


def fill_settings(cell: float, finish: SliceFinish) -> dict[str, float | str]:
    return {
        "cell": cell,
        "method": finish.method,
        "max_distance_spacings": finish.max_distance_spacings,
    }


class FillPicture:
    def __init__(
        self,
        flow: FillFlow,
        *,
        read_record: Callable[[], dict[str, Any]],
        restore_record: Callable[[dict[str, Any] | None], None],
        read_widgets: Callable[[], tuple[float, SliceFinish]],
        set_widgets: Callable[[float, SliceFinish], None],
        apply: Callable[[], None],
        changed: Callable[[], None],
    ) -> None:
        self._flow = flow
        self._read_record = read_record
        self._restore_record = restore_record
        self._read_widgets = read_widgets
        self._set_widgets = set_widgets
        self._apply = apply
        self._changed = changed
        #: `(owner, drawn fill settings, which of them the record held)`.
        self._picture: tuple[Hashable, dict[str, float | str], frozenset[str]] | None = None
        self._owner: Hashable | None = None
        #: The Warnings note the latch carries, or None.
        self._note: str | None = None

    # ---- the picture ------------------------------------------------------
    def record(self, owner: Hashable, cell: float, finish: SliceFinish) -> None:
        """An array was drawn at `cell` with `finish` (a preview counts)."""
        held = frozenset(k for k in FILL_FIELDS if k in self._read_record())
        self._picture = (owner, fill_settings(cell, finish), held)

    def forget(self) -> None:
        """Nothing is drawn now."""
        self._picture = None

    # ---- the latch ---------------------------------------------------------
    @property
    def noted(self) -> bool:
        """Whether the Warnings note is to be shown."""
        return self._note is not None

    @property
    def note(self) -> str | None:
        """The Warnings note to show, or None."""
        return self._note

    def check_owner(self, owner: Hashable) -> None:
        """A latch made for another owner (grid) is dropped."""
        if self._flow.latched and self._owner != owner:
            self.unlatch()

    def unlatch(self) -> None:
        """A fill setting changed, or the survey or scope did: draw again."""
        self._flow.unlatch()
        self._owner = None
        if self._note is not None:
            self._note = None
            self._changed()

    # ---- cancel ------------------------------------------------------------
    def cancelled(self, owner: Hashable, *, picture_held: bool = False) -> None:
        """Cancel was pressed while a fill was worked out. With a picture drawn
        at other fill settings, those go back (record, widgets, applied: which
        can show the working line again if the picture's own fill was slow).
        Otherwise there is nothing to go back to: the settings stay, the note
        is shown, and the flow latches. `picture_held`: the picture on the map
        is at these very settings and still holds its own fills, so the
        cancelled fill was for something it lacks (a grid outside it, which
        the shared stretch reads): the note says the picture stays (#236),
        not that none was drawn."""
        cell, finish = self._read_widgets()
        picture = self._picture
        drawn = picture is not None and picture[0] == owner
        if drawn and picture is not None and picture[1] != fill_settings(cell, finish):
            self._take_back(picture)
            return
        kept = drawn and picture_held
        self._note = FILL_CANCELLED_KEPT_NOTE if kept else FILL_CANCELLED_NOTE
        self._owner = owner
        self._flow.latch()
        self._changed()

    def _take_back(self, picture: tuple[Hashable, dict[str, float | str], frozenset[str]]) -> None:
        _, drawn, held = picture
        record = {k: v for k, v in self._read_record().items() if k not in FILL_FIELDS}
        record.update({k: drawn[k] for k in FILL_FIELDS if k in held})
        self._restore_record(record or None)
        cell, finish = self._read_widgets()
        self._set_widgets(
            float(drawn["cell"]),  # type: ignore[arg-type]
            dataclasses.replace(
                finish,
                method=str(drawn["method"]),
                max_distance_spacings=float(drawn["max_distance_spacings"]),  # type: ignore[arg-type]
            ),
        )
        self._apply()
