"""Workday candidate-experience API (myworkdayjobs.com/wday/cxs/...).

Swiss postings: if the board exposes a country facet with "Switzerland", list all of them;
otherwise run one search per keyword term and keep hits that look Swiss.
Abroad postings (fetch_abroad): keyword searches, keep non-Swiss hits whose title matches a family.
"""

from __future__ import annotations

import logging

from ..models import RawPosting
from .base import Context, html_to_text, iso_date, register

log = logging.getLogger(__name__)

PAGE = 20
MAX_PAGES_PER_TERM = 5  # results are relevance-ranked; 100 hits per term is plenty
SWITZERLAND_ID = "187134fccb084a0ea9b4b95f23890dbe"  # Workday's global country id
# Boards without a country facet: find Swiss postings by searching for Swiss places.
SWISS_PLACE_SEARCHES = ["Switzerland", "Zurich", "Zürich", "Basel", "Bern", "Geneva", "Genève", "Lausanne", "Zug",
                        "Lugano", "Kaiseraugst", "Schweiz", "Suisse"]


def _find_swiss_facet(facets: list) -> tuple[str, str] | None:
    def walk(f, param):
        for v in f.get("values", []):
            if "values" in v:
                hit = walk(v, v.get("facetParameter", param))
                if hit:
                    return hit
            elif v.get("id") == SWITZERLAND_ID or v.get("descriptor", "").strip().lower() == "switzerland":
                return param, v["id"]
        return None

    for f in facets:
        hit = walk(f, f.get("facetParameter"))
        if hit:
            return hit
    return None


@register("workday")
def workday(emp: dict, ctx: Context) -> list[RawPosting]:
    tenant, wd, site = emp["tenant"], emp.get("wd", "wd3"), emp["site"]
    host = f"https://{tenant}.{wd}.myworkdayjobs.com"
    api = f"{host}/wday/cxs/{tenant}/{site}"

    def search(text: str, facets: dict, max_pages: int):
        offset, total = 0, None
        for _ in range(max_pages):
            body = {"appliedFacets": facets, "limit": PAGE, "offset": offset, "searchText": text}
            data = ctx.client.post_json(f"{api}/jobs", body)
            if total is None:  # Workday only reports the total on the first page
                total = data.get("total", 0)
            yield data
            offset += PAGE
            if offset >= total:
                return

    # hits: externalPath -> (listing record, swiss_known)
    hits: dict[str, tuple[dict, bool | None]] = {}

    first_page = ctx.client.post_json(f"{api}/jobs", {"appliedFacets": {}, "limit": PAGE, "offset": 0, "searchText": ""})
    swiss_facet = _find_swiss_facet(first_page.get("facets", []))

    if swiss_facet:
        param, fid = swiss_facet
        for data in search("", {param: [fid]}, max_pages=50):
            for j in data.get("jobPostings", []):
                hits[j["externalPath"]] = (j, True)
    else:
        for place in emp.get("swiss_searches", SWISS_PLACE_SEARCHES):
            for data in search(place, {}, max_pages=50):
                for j in data.get("jobPostings", []):
                    if ctx.is_swiss(j.get("locationsText", "")) and j["externalPath"] not in hits:
                        hits[j["externalPath"]] = (j, True)
    if not swiss_facet or emp.get("fetch_abroad"):
        for term in ctx.search_terms:
            for data in search(term, {}, MAX_PAGES_PER_TERM):
                for j in data.get("jobPostings", []):
                    if j.get("externalPath") and j["externalPath"] not in hits:
                        hits[j["externalPath"]] = (j, None)

    out = []
    for path, (j, swiss) in hits.items():
        loc_text = j.get("locationsText", "")
        if swiss is True and not ctx.maybe_match(j.get("title", "")):
            continue  # a detail call per posting is the main cost; skip titles no family could claim
        if swiss is None:
            swiss = ctx.is_swiss(loc_text)
            # Abroad hits are only useful for the offshore flag: require a title match.
            if swiss is False and not (emp.get("fetch_abroad") and ctx.title_match(j.get("title", ""))):
                continue
            # Facet-less boards: an unknown location still needs a title match to be worth a detail call.
            if swiss is None and not ctx.title_match(j.get("title", "")):
                continue
        try:
            info = ctx.client.get_json(f"{api}{path}").get("jobPostingInfo", {})
        except Exception as e:  # one bad posting must not sink the board
            log.warning("workday %s: detail failed for %s: %s", tenant, path, e)
            continue
        locs = [info.get("location", "")] + list(info.get("additionalLocations") or [])
        country = ((info.get("jobRequisitionLocation") or {}).get("country") or {}).get("alpha2Code", "")
        if not country:
            country = (info.get("country") or {}).get("descriptor", "")
        out.append(
            RawPosting(
                ats_id=info.get("jobReqId") or path,
                title=info.get("title", j.get("title", "")).strip(),
                url=info.get("externalUrl") or f"{host}/{site}{path}",
                location_raw="; ".join(l for l in locs if l) or loc_text,
                country=country,
                description=html_to_text(info.get("jobDescription", "")),
                posted_date=iso_date(info.get("startDate")),
                contract_hint=info.get("timeType", "") or "",
            )
        )
    return out
