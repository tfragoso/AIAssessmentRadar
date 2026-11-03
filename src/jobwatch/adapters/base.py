"""Adapter registry and helpers shared across adapters."""

from __future__ import annotations

import html as htmllib
import json
import re
from dataclasses import dataclass, field
from typing import Callable

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..http import Client
from ..models import RawPosting


@dataclass
class Context:
    """What an adapter may need beyond its own config."""

    client: Client
    search_terms: list[str] = field(default_factory=list)  # for ATSs with server-side search
    title_match: Callable[[str], bool] = lambda t: True  # title alone puts it in a family
    maybe_match: Callable[[str], bool] = lambda t: True  # title could still match via the description
    is_swiss: Callable[[str], bool | None] = lambda t: None  # True / False / None (unknown)


Adapter = Callable[[dict, Context], list[RawPosting]]
REGISTRY: dict[str, Adapter] = {}


def register(name: str):
    def deco(fn: Adapter) -> Adapter:
        REGISTRY[name] = fn
        return fn

    return deco


# --- text helpers --------------------------------------------------------------------

_BLOCK_TAGS = re.compile(r"(?i)<\s*(br|/p|/div|/li|/h[1-6]|/tr|li)\b[^>]*>")


def html_to_text(html: str) -> str:
    """HTML fragment -> readable plain text with line breaks."""
    if not html:
        return ""
    html = _BLOCK_TAGS.sub("\n", html)
    tree = HTMLParser(html)
    for bad in tree.css("script, style"):
        bad.decompose()
    text = tree.text(separator=" ") if tree.body is None else tree.body.text(separator=" ")
    text = htmllib.unescape(text)
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def iso_date(s: str | None) -> str:
    if not s:
        return ""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(s))
    return m.group(1) if m else ""


# --- schema.org JobPosting extraction ---------------------------------------------------


def _iter_ld(obj):
    if isinstance(obj, list):
        for o in obj:
            yield from _iter_ld(o)
    elif isinstance(obj, dict):
        if "@graph" in obj:
            yield from _iter_ld(obj["@graph"])
        yield obj


def _loc_text(loc) -> str:
    out = []
    for l in loc if isinstance(loc, list) else [loc]:
        if not isinstance(l, dict):
            out.append(str(l))
            continue
        a = l.get("address", l)
        if isinstance(a, str):
            out.append(a)
            continue
        country = a.get("addressCountry", "")
        if isinstance(country, dict):
            country = country.get("name", "")
        parts = [a.get("addressLocality", ""), a.get("addressRegion", ""), country]
        out.append(", ".join(p for p in parts if p))
    return "; ".join(o for o in out if o)


def parse_jobposting(page_html: str) -> dict | None:
    """Return {title, description, location, country, posted, employment_type} from JSON-LD,
    falling back to schema.org microdata. None if the page has neither."""
    tree = HTMLParser(page_html)
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text(deep=True, strip=False).strip(), strict=False)
        except (json.JSONDecodeError, ValueError):
            continue
        for obj in _iter_ld(data):
            t = obj.get("@type")
            if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                loc = obj.get("jobLocation") or []
                country = ""
                for l in loc if isinstance(loc, list) else [loc]:
                    if isinstance(l, dict) and isinstance(l.get("address"), dict):
                        c = l["address"].get("addressCountry", "")
                        country = c.get("name", "") if isinstance(c, dict) else c
                        break
                et = obj.get("employmentType", "")
                return {
                    "title": htmllib.unescape(str(obj.get("title", ""))).strip(),
                    "description": html_to_text(htmllib.unescape(str(obj.get("description", "")))),
                    "location": _loc_text(loc),
                    "country": country,
                    "posted": iso_date(obj.get("datePosted")),
                    "employment_type": ", ".join(et) if isinstance(et, list) else str(et),
                    "remote": "remote" if obj.get("jobLocationType") == "TELECOMMUTE" else "",
                }

    def prop(name: str) -> str:
        n = tree.css_first(f'[itemprop="{name}"]')
        if n is None:
            return ""
        return n.attributes.get("content") or n.text(separator=" ").strip()

    if tree.css_first('[itemprop="title"]') is not None:
        desc = tree.css_first('[itemprop="description"]')
        loc = ", ".join(p for p in (prop("addressLocality"), prop("addressRegion"), prop("addressCountry")) if p)
        return {
            "title": prop("title"),
            "description": html_to_text(desc.html) if desc else "",
            "location": loc,
            "country": prop("addressCountry"),
            "posted": iso_date(prop("datePosted")),
            "employment_type": prop("employmentType"),
            "remote": "",
        }
    return None


def page_fallback(page_html: str) -> dict:
    """Last resort for pages with no structured data: <h1> + main text."""
    tree = HTMLParser(page_html)
    h1 = tree.css_first("h1")
    main = tree.css_first("main") or tree.body
    for bad in (main.css("script, style, nav, header, footer") if main else []):
        bad.decompose()
    return {
        "title": h1.text(separator=" ").strip() if h1 else "",
        "description": html_to_text(main.html) if main else "",
        "location": "",
        "country": "",
        "posted": "",
        "employment_type": "",
        "remote": "",
    }
