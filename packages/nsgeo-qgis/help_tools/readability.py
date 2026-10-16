"""A deterministic Flesch-Kincaid grade estimate for the help pages.

This is a guard rail, not a precise reading level: the syllable counter is a
vowel-run heuristic. It is stable, so a page that passes keeps passing until
its text changes.
"""

from __future__ import annotations

import re

FK_LIMIT = 9.0

_WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")
_SENTENCE_END = re.compile(r"[.!?]+(?=\s|$)")
_VOWEL_RUN = re.compile(r"[aeiouy]+")


def syllables(word: str) -> int:
    """Count syllables as vowel runs, less a silent final ``e`` (but not ``le``)."""
    w = re.sub(r"[^a-z]", "", word.lower())
    count = len(_VOWEL_RUN.findall(w))
    if w.endswith("e") and count > 1 and not w.endswith("le"):
        count -= 1
    return max(1, count)


def fk_grade(text: str) -> float:
    """Flesch-Kincaid grade level of ``text``."""
    words = _WORD.findall(text)
    if not words:
        return 0.0
    sentences = max(1, len(_SENTENCE_END.findall(text)))
    n_syl = sum(syllables(w) for w in words)
    return 0.39 * len(words) / sentences + 11.8 * n_syl / len(words) - 15.59
