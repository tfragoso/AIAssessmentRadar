"""Text normalisation and term matching shared by filtering, regions and rules."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache


def fold(text: str, keep_hyphens: bool = False) -> str:
    """Lowercase, strip accents (ü->u, é->e, ß->ss), map -_/ and apostrophes to spaces, collapse whitespace.
    keep_hyphens is for place names ("Grenzach-Wyhlen" must not match "Grenzach" ... or "Baden")."""
    text = unicodedata.normalize("NFKD", text or "").replace("ß", "ss")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[_/’'`]" if keep_hyphens else r"[-_/’'`]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=None)
def term_regex(term: str) -> re.Pattern:
    t = fold(term)
    body = re.escape(t).replace(r"\ ", r"\s+")
    tail = r"(?!\w)" if len(t) <= 4 else ""
    return re.compile(rf"(?<!\w){body}{tail}")


@lru_cache(maxsize=None)
def place_regex(place: str) -> re.Pattern:
    """Whole-word match for place names, where '-' is part of the word."""
    body = re.escape(fold(place, keep_hyphens=True)).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![\w-]){body}(?![\w-])")


def find_terms(folded_text: str, terms: list[str]) -> list[str]:
    """Terms (as written in config) that occur in already-folded text."""
    return [t for t in terms if term_regex(t).search(folded_text)]


def has_term(folded_text: str, terms: list[str]) -> bool:
    return any(term_regex(t).search(folded_text) for t in terms)
