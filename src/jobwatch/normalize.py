"""RawPosting -> Posting: ids, hashes, country and region tags."""

from __future__ import annotations

import hashlib
import html
import re

from .models import Posting, RawPosting
from .textutil import fold, place_regex

SWISS_COUNTRY = {"ch", "che", "switzerland", "schweiz", "suisse", "svizzera"}


class RegionTagger:
    def __init__(self, cfg: dict):
        self.canton_region: dict[str, str] = cfg["canton_region"]
        self.markers = [m for m in cfg["swiss_markers"] if m != "CH"]
        self.city_canton: dict[str, str] = {}
        for canton, cities in cfg["cities"].items():
            for c in cities:
                self.city_canton[c] = canton
        self.foreign = cfg["foreign"]
        self._canton_code = re.compile(r"\b(" + "|".join(sorted(self.all_cantons())) + r")\b")

    def all_cantons(self) -> set[str]:
        return set(self.city_canton.values()) | set(self.canton_region)

    def _has_marker(self, text: str) -> bool:
        return bool(re.search(r"\bCH\b", text)) or any(place_regex(m).search(fold(text, True)) for m in self.markers)

    def cantons(self, text: str) -> list[str]:
        """Swiss cantons named in a location string (via city names, or canton codes next to a Swiss marker)."""
        f = fold(text, keep_hyphens=True)
        found = [c for city, c in self.city_canton.items() if place_regex(city).search(f)]
        if self._has_marker(text):
            found += self._canton_code.findall(text)
        return sorted(set(found))

    def is_swiss(self, text: str) -> bool | None:
        """True if the text names a Swiss place, False if only foreign places, None if it can't tell."""
        if not text:
            return None
        if self._has_marker(text) or self.cantons(text):
            return True
        f = fold(text, keep_hyphens=True)
        if any(place_regex(p).search(f) for p in self.foreign):
            return False
        return None

    def tag(self, location: str, country: str, default_country: str = "") -> tuple[str, str]:
        """(country, region) where region is one or more tags joined by '; '."""
        c = fold(country)
        swiss = self.is_swiss(location)
        if c in SWISS_COUNTRY or swiss is True:
            regions = {self.canton_region.get(k, "Other CH") for k in self.cantons(location)}
            return "CH", "; ".join(sorted(regions)) or "Other CH"
        if c or swiss is False:
            return (country.upper() if len(country) <= 3 else country) or "?", "Abroad"
        if fold(default_country) in SWISS_COUNTRY:
            return "CH", "Other CH"
        return "?", "Abroad"


def posting_id(employer: str, ats_id: str) -> str:
    return hashlib.sha1(f"{employer}|{ats_id}".encode()).hexdigest()[:12]


def desc_hash(text: str) -> str:
    return hashlib.sha1(re.sub(r"\s+", " ", text or "").strip().encode()).hexdigest()[:12]


def to_posting(raw: RawPosting, emp: dict, tagger: RegionTagger) -> Posting:
    country, region = tagger.tag(raw.location_raw, raw.country, emp.get("default_country", ""))
    return Posting(
        posting_id=posting_id(emp["name"], raw.ats_id),
        employer=emp["name"],
        segment=emp.get("segment", ""),
        ats=emp["ats"],
        title=re.sub(r"\s+", " ", html.unescape(raw.title)).strip(),
        url=raw.url,
        location_raw=raw.location_raw,
        country=country,
        region=region,
        posted_date=raw.posted_date,
        desc_hash=desc_hash(raw.description),
        description=raw.description,
    )
