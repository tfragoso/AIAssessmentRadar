"""Role-family classification and geography rules."""

from __future__ import annotations

from .models import Posting
from .textutil import fold, has_term


class FamilyMatcher:
    def __init__(self, families: dict):
        self.families = families

    def title_family(self, title: str) -> str | None:
        """First family whose title terms match (ignores geography). Used as a cheap pre-filter."""
        t = fold(title)
        for name, f in self.families.items():
            if has_term(t, f["title"]) and not has_term(t, f.get("exclude") or []):
                return name
        return None

    def maybe(self, title: str) -> bool:
        """Could this title end up in a family once the description is read? Used to skip detail requests."""
        if self.title_family(title):
            return True
        t = fold(title)
        return any(f.get("description") and has_term(t, f.get("title_context") or []) for f in self.families.values())

    def classify(self, title: str, description: str, regions: list[str]) -> str | None:
        t, d = fold(title), None
        for name, f in self.families.items():
            if has_term(t, f.get("exclude") or []):
                continue
            hit = has_term(t, f["title"])
            if not hit and f.get("description") and has_term(t, f.get("title_context") or []):
                d = d if d is not None else fold(description)
                hit = has_term(d, f["description"])
            if hit and self._region_ok(f, regions):
                return name
        return None

    @staticmethod
    def _region_ok(f: dict, regions: list[str]) -> bool:
        allowed = f.get("regions", "all")
        if "Abroad" in regions and len(regions) == 1:
            return True  # abroad rows are kept for the offshore flag; renderers leave them out
        return allowed == "all" or any(r in allowed for r in regions)


def apply(p: Posting, matcher: FamilyMatcher) -> bool:
    """Set p.role_family; return False if the posting is out of scope."""
    fam = matcher.classify(p.title, p.description, [r.strip() for r in p.region.split(";") if r.strip()])
    p.role_family = fam or ""
    return fam is not None
