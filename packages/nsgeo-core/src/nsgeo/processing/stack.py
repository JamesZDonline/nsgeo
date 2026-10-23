"""An ordered, toggleable list of steps with cached intermediates.

Nothing here runs automatically. A stack starts empty, and every step is added
by an explicit user action.

Because steps are pure functions of (params, radargram), cache invalidation is
not a hard problem: editing anything at index i invalidates i onward, and that
is the entire rule.
"""

from __future__ import annotations

from typing import Any

from nsgeo.processing.base import Radargram, build_step, is_unipolar

_BYPASS_MEMO_SIZE = 2


class StepStack:
    def __init__(self) -> None:
        self._entries: list[tuple[Any, bool]] = []
        self._cache: list[Radargram] = []
        self._source: Radargram | None = None
        # Results of result_bypassing, keyed by the set of bypassed indices,
        # least recently used first. At most _BYPASS_MEMO_SIZE entries.
        self._bypassed: dict[frozenset[int], Radargram] = {}

    # ---- source -------------------------------------------------------
    @property
    def source(self) -> Radargram | None:
        return self._source

    @source.setter
    def source(self, rg: Radargram) -> None:
        self._source = rg
        self._cache = []
        self._drop_bypassed()

    # ---- inspection ---------------------------------------------------
    @property
    def entries(self) -> list[tuple[Any, bool]]:
        """A copy of the (step, enabled) list. The step OBJECTS are shared,
        not copied: mutating a step's attributes in place bypasses cache
        invalidation and makes `to_dicts()` disagree with the cached result.
        Edit steps with `replace_step(i, build_step(name, **params))`."""
        return list(self._entries)

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    @property
    def output_unipolar(self) -> bool:
        """Whether `result()` has no negative side.

        The last *enabled* step decides, because a disabled transform is
        not applied. Consulted by front ends choosing a colour table: a
        bipolar table on unipolar data wastes half its range.
        """
        for step, enabled in reversed(self._entries):
            if enabled:
                return is_unipolar(step)
        return False

    def __len__(self) -> int:
        return len(self._entries)

    # ---- mutation -----------------------------------------------------
    def _invalidate_from(self, index: int) -> None:
        del self._cache[index:]

    def _drop_bypassed(self, keep: int | None = None) -> None:
        """Forget remembered bypass results, except those that bypass `keep`:
        an edit confined to a bypassed step cannot change them."""
        if keep is None:
            self._bypassed.clear()
        else:
            self._bypassed = {k: v for k, v in self._bypassed.items() if keep in k}

    def append(self, step: Any) -> None:
        self._entries.append((step, True))
        self._drop_bypassed()
        # No invalidation: the existing prefix is still valid.

    def insert(self, index: int, step: Any) -> None:
        self._entries.insert(index, (step, True))
        self._invalidate_from(index)
        self._drop_bypassed()

    def remove(self, index: int) -> None:
        del self._entries[index]
        self._invalidate_from(index)
        self._drop_bypassed()

    def replace_step(self, index: int, step: Any) -> None:
        enabled = self._entries[index][1]
        self._entries[index] = (step, enabled)
        self._invalidate_from(index)
        self._drop_bypassed(keep=index)

    def move(self, src: int, dst: int) -> None:
        n = len(self._entries)
        if not (0 <= src < n and 0 <= dst < n):
            raise IndexError(f"move indices must be in 0..{n - 1}, got src={src}, dst={dst}")
        entry = self._entries.pop(src)
        self._entries.insert(dst, entry)
        self._invalidate_from(min(src, dst))
        self._drop_bypassed()

    def set_enabled(self, index: int, flag: bool) -> None:
        step, _ = self._entries[index]
        self._entries[index] = (step, bool(flag))
        self._invalidate_from(index)
        self._drop_bypassed()

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

    def result_bypassing(self, *indices: int) -> Radargram:
        """What `result()` would be with every step in `indices` switched off.

        Lets a front end show the data a step is about to hide (the part of
        the record a time cutoff removes) or hold the display steady while a
        gain curve is edited, without toggling anything. No indices is just
        `result()`. The prefix before the smallest index comes from the
        cache; everything after is run fresh, skipping the bypassed and the
        disabled steps, and NOT cached, because those intermediates belong to
        a chain the stack does not actually have. `result()` stays the real
        chain.

        The final result is remembered for the two most recently used index
        sets, so repeated calls return the same object. `replace_step(i, ..)`
        keeps the entries that bypass `i` (an edit confined to a bypassed step
        cannot change them, which is what a gain-curve drag needs); every
        other mutation drops them all.
        """
        n = len(self._entries)
        for i in indices:
            if not 0 <= i < n:
                raise IndexError(f"step index {i} out of range (0..{n - 1})")
        if not indices:
            return self.result()
        key = frozenset(indices)
        hit = self._bypassed.pop(key, None)
        if hit is not None:
            self._bypassed[key] = hit  # most recently used goes last
            return hit
        first = min(key)
        if first:
            current = self.intermediate(first - 1)
        else:
            if self._source is None:
                raise ValueError("stack has no source radargram")
            current = self._source
        for i in range(first, n):
            step, enabled = self._entries[i]
            if enabled and i not in key:
                current = step.apply(current)
        self._bypassed[key] = current
        while len(self._bypassed) > _BYPASS_MEMO_SIZE:
            del self._bypassed[next(iter(self._bypassed))]
        return current

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
