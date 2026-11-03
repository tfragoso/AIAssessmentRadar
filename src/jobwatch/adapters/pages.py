"""Adapters that read HTML career sites: SuccessFactors career sites, generic listing pages, Oracle HCM."""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..models import RawPosting
from .base import Context, html_to_text, iso_date, page_fallback, parse_jobposting, register

log = logging.getLogger(__name__)


def _detail(ctx: Context, url: str) -> dict:
    page = ctx.client.get_text(url)
    return parse_jobposting(page) or page_fallback(page)


def _raw_from_detail(ats_id: str, url: str, d: dict, title: str = "", loc: str = "") -> RawPosting:
    return RawPosting(
        ats_id=ats_id,
        title=(d.get("title") or title).strip(),
        url=url,
        location_raw=d.get("location") or loc,
        country=d.get("country", ""),
        description=d.get("description", ""),
        posted_date=d.get("posted", ""),
        remote_hint=d.get("remote", ""),
        contract_hint=d.get("employment_type", ""),
    )


@register("sfcareer")
def sfcareer(emp: dict, ctx: Context) -> list[RawPosting]:
    """SAP SuccessFactors Career Site Builder (careers.swissre.com, careers.ey.com/ey, ...).
    Uses the public /search/ pages (the RSS under /services/ is disallowed by robots.txt)."""
    base = emp["base"].rstrip("/")
    country = emp.get("locationsearch", "Switzerland")
    hits: dict[str, tuple[str, str]] = {}  # url -> (title, location)

    def run(q: str, loc: str, max_rows: int):
        """Page through one search. Page size varies by site (10 or 25), so advance by rows seen."""
        start = 0
        while start < max_rows:
            html = ctx.client.get_text(f"{base}/search/", params={"q": q, "locationsearch": loc, "startrow": start})
            new = 0
            rows = HTMLParser(html).css("tr.data-row")
            for row in rows:
                a = row.css_first("a.jobTitle-link")
                if a is None:
                    continue
                url = urljoin(base + "/", a.attributes.get("href", ""))
                locn = row.css_first(".jobLocation")
                if url not in hits:
                    new += 1
                    hits[url] = (a.text().strip(), locn.text().strip() if locn else "")
            total = re.search(r"of\s*<b>([\d,.']+)</b>", html)
            start += len(rows)
            if not rows or not new or (total and start >= int(re.sub(r"\D", "", total.group(1)))):
                return

    # Every Swiss posting (q is OR-matched on words, so keyword searches add little here).
    run("", country, max_rows=2000)
    swiss_urls = set(hits)
    if emp.get("fetch_abroad"):  # global keyword searches, first rows only; kept on a title match
        for term in ctx.search_terms:
            run(term, "", max_rows=50)

    out = []
    for url, (title, loc) in hits.items():
        # Detail pages cost a request each: only for titles that could belong to a family.
        if url in swiss_urls:
            if not ctx.maybe_match(title):
                continue
        elif not ctx.title_match(title):
            continue
        m = re.search(r"/(\d+)/?$", url)
        try:
            d = _detail(ctx, url)
        except Exception as e:
            log.warning("sfcareer %s: detail failed for %s: %s", base, url, e)
            continue
        raw = _raw_from_detail(m.group(1) if m else url, url, d, title, loc)
        if url in swiss_urls and not raw.country:
            raw.country = "CH"
        out.append(raw)
    return out


@register("htmllist")
def htmllist(emp: dict, ctx: Context) -> list[RawPosting]:
    """A listing page with links to postings; each posting page parsed via JSON-LD / microdata / <h1>.
    Config: listing (url or list of urls), link_pattern (regex on href), prefilter (title match on link text)."""
    listings = emp["listing"] if isinstance(emp["listing"], list) else [emp["listing"]]
    pattern = re.compile(emp["link_pattern"])
    links: dict[str, str] = {}
    for listing in listings:
        tree = HTMLParser(ctx.client.get_text(listing))
        for a in tree.css("a[href]"):
            href = a.attributes.get("href") or ""
            if pattern.search(href):
                url = urljoin(listing, href).split("#")[0]
                links.setdefault(url, a.text(separator=" ").strip())

    out = []
    for url, text in links.items():
        if emp.get("prefilter") and text and not ctx.title_match(text):
            continue
        try:
            d = _detail(ctx, url)
        except Exception as e:
            log.warning("htmllist %s: detail failed for %s: %s", emp["name"], url, e)
            continue
        out.append(_raw_from_detail(url, url, d, text, emp.get("default_location", "")))
    return out


@register("oracle")
def oracle(emp: dict, ctx: Context) -> list[RawPosting]:
    """Oracle Recruiting Cloud candidate experience (*.fa.*.oraclecloud.com)."""
    host, site = emp["host"].rstrip("/"), emp.get("site_number", "CX_1")
    api = f"{host}/hcmRestApi/resources/latest"
    reqs, offset = [], 0
    while True:
        finder = f"findReqs;siteNumber={site},limit=25,offset={offset},sortBy=POSTING_DATES_DESC"
        data = ctx.client.get_json(
            f"{api}/recruitingCEJobRequisitions",
            params={"onlyData": "true", "expand": "requisitionList.secondaryLocations", "finder": finder},
        )
        item = (data.get("items") or [{}])[0]
        batch = item.get("requisitionList") or []
        reqs += batch
        offset += 25
        if not batch or offset >= item.get("TotalJobsCount", 0):
            break

    out = []
    for r in reqs:
        locs = [r.get("PrimaryLocation", "")] + [s.get("Name", "") for s in r.get("secondaryLocations") or []]
        loc_raw = "; ".join(l for l in locs if l)
        country = r.get("PrimaryLocationCountry", "")
        if ctx.is_swiss(f"{loc_raw}; {country}") is not True and not (
            emp.get("fetch_abroad") and ctx.title_match(r.get("Title", ""))
        ):
            continue
        detail = ctx.client.get_json(
            f"{api}/recruitingCEJobRequisitionDetails",
            params={"onlyData": "true", "expand": "all", "finder": f'ById;Id="{r["Id"]}",siteNumber={site}'},
        )
        d = (detail.get("items") or [{}])[0]
        desc = "\n".join(
            html_to_text(d.get(k) or "")
            for k in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")
        )
        out.append(
            RawPosting(
                ats_id=str(r["Id"]),
                title=r.get("Title", "").strip(),
                url=f"{host}/hcmUI/CandidateExperience/en/sites/{emp.get('site', site)}/job/{r['Id']}",
                location_raw=loc_raw,
                country=country,
                description=desc.strip(),
                posted_date=iso_date(r.get("PostedDate")),
                remote_hint=r.get("WorkplaceType", "") or "",
                contract_hint=" ".join(v for v in (d.get("JobSchedule"), d.get("ContractType")) if v),
            )
        )
    return out
