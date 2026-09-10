"""An ordered, toggleable list of steps with cached intermediates.

Nothing here runs automatically. A stack starts empty, and every step is added
by an explicit user action.

Because steps are pure functions of (params, radargram), cache invalidation is
not a hard problem: editing anything at index i invalidates i onward, and that
is the entire rule.
"""

from __future__ import annotations

from typing import Any

from nsgeo.processing.base import Radargram, build_step


class StepStack:
    def __init__(self) -> None:
        self._entries: list[tuple[Any, bool]] = []
        self._cache: list[Radargram] = []
        self._source: Radargram | None = None

    # ---- source -------------------------------------------------------
    @property
    def source(self) -> Radargram | None:
        return self._source

    @source.setter
    def source(self, rg: Radargram) -> None:
        self._source = rg
        self._cache = []

    # ---- inspection ---------------------------------------------------
    @property
    def entries(self) -> list[tuple[Any, bool]]:
        return list(self._entries)

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    def __len__(self) -> int:
        return len(self._entries)

    # ---- mutation -----------------------------------------------------
    def _invalidate_from(self, index: int) -> None:
        del self._cache[index:]

    def append(self, step: Any) -> None:
        self._entries.append((step, True))
        # No invalidation: the existing prefix is still valid.

    def insert(self, index: int, step: Any) -> None:
        self._entries.insert(index, (step, True))
        self._invalidate_from(index)

    def remove(self, index: int) -> None:
        del self._entries[index]
        self._invalidate_from(index)

    def replace_step(self, index: int, step: Any) -> None:
        enabled = self._entries[index][1]
        self._entries[index] = (step, enabled)
        self._invalidate_from(index)

    def move(self, src: int, dst: int) -> None:
        n = len(self._entries)
        if not (0 <= src < n and 0 <= dst < n):
            raise IndexError(f"move indices must be in 0..{n - 1}, got src={src}, dst={dst}")
        entry = self._entries.pop(src)
        self._entries.insert(dst, entry)
        self._invalidate_from(min(src, dst))

    def set_enabled(self, index: int, flag: bool) -> None:
        step, _ = self._entries[index]
        self._entries[index] = (step, bool(flag))
        self._invalidate_from(index)

    # ---- evaluation ---------------------------------------------------
    def _ensure(self, upto: int) -> None:
        if self._source is None:
            raise ValueError("stack has no source radargram")
        while len(self._cache) <= upto:
            i = len(self._cache)
            previous = self._cache[i - 1] if i else self._source
            step, enabled = self._entries[i]
            self._cache.append(step.apply(previous) if enabled else previous)

    def result(self) -> Radargram:
        if self._source is None:
            raise ValueError("stack has no source radargram")
        if not self._entries:
            return self._source
        self._ensure(len(self._entries) - 1)
        return self._cache[-1]

    def intermediate(self, index: int) -> Radargram:
        """State after applying step `index`."""
        if not 0 <= index < len(self._entries):
            raise IndexError(f"step index {index} out of range (0..{len(self._entries) - 1})")
        self._ensure(index)
        return self._cache[index]

    def difference(self, index: int) -> Radargram:
        """What step `index` removed: the input minus the output.

        Nearly free, because both sides are already cached. Diagnoses
        over-removal of genuine flat-lying features by background steps.
        """
        if not 0 <= index < len(self._entries):
            raise IndexError(f"step index {index} out of range (0..{len(self._entries) - 1})")
        after = self.intermediate(index)
        before = self._cache[index - 1] if index else self._source
        assert before is not None
        if before.data.shape != after.data.shape:
            step = self._entries[index][0]
            raise ValueError(
                f"step {index} ({step.name}) changes the sample count "
                f"({before.n_samples} -> {after.n_samples}); a difference view is "
                f"undefined for it"
            )
        return after.replace(data=before.data - after.data)

    # ---- serialisation ------------------------------------------------
    def to_dicts(self) -> list[dict[str, Any]]:
        return [{"step": s.name, "params": s.params, "enabled": e} for s, e in self._entries]

    @classmethod
    def from_dicts(cls, dicts: list[dict[str, Any]]) -> StepStack:
        stack = cls()
        for entry in dicts:
            step = build_step(entry["step"], **entry.get("params", {}))
            stack._entries.append((step, bool(entry.get("enabled", True))))
        return stack
