"""Adapters for ATSs with clean public JSON/XML feeds."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape

from ..models import RawPosting
from .base import Context, html_to_text, iso_date, register


@register("greenhouse")
def greenhouse(emp: dict, ctx: Context) -> list[RawPosting]:
    token = emp["token"]
    data = ctx.client.get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", params={"content": "true"})
    out = []
    for j in data.get("jobs", []):
        out.append(
            RawPosting(
                ats_id=str(j["id"]),
                title=j.get("title", "").strip(),
                url=j.get("absolute_url", ""),
                location_raw=(j.get("location") or {}).get("name", ""),
                description=html_to_text(unescape(j.get("content", ""))),
                posted_date=iso_date(j.get("first_published") or j.get("updated_at")),
            )
        )
    return out


@register("lever")
def lever(emp: dict, ctx: Context) -> list[RawPosting]:
    host = "api.eu.lever.co" if emp.get("region") == "eu" else "api.lever.co"
    data = ctx.client.get_json(f"https://{host}/v0/postings/{emp['token']}", params={"mode": "json"})
    out = []
    for j in data:
        cats = j.get("categories") or {}
        lists = "\n".join(f"{l.get('text', '')}\n{html_to_text(l.get('content', ''))}" for l in j.get("lists", []))
        created = j.get("createdAt")
        out.append(
            RawPosting(
                ats_id=j["id"],
                title=j.get("text", "").strip(),
                url=j.get("hostedUrl", ""),
                location_raw="; ".join(cats.get("allLocations") or [cats.get("location", "")]),
                country=j.get("country", "") or "",
                description="\n".join(
                    p for p in (j.get("descriptionPlain", ""), lists, j.get("additionalPlain", "")) if p
                ),
                posted_date=datetime.fromtimestamp(created / 1000, timezone.utc).date().isoformat() if created else "",
                remote_hint=j.get("workplaceType", "") or "",
                contract_hint=cats.get("commitment", "") or "",
            )
        )
    return out


@register("ashby")
def ashby(emp: dict, ctx: Context) -> list[RawPosting]:
    data = ctx.client.get_json(
        f"https://api.ashbyhq.com/posting-api/job-board/{emp['token']}", params={"includeCompensation": "true"}
    )
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location", "")] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        addr = ((j.get("address") or {}).get("postalAddress") or {})
        comp = (j.get("compensation") or {}).get("compensationTierSummary", "") or ""
        out.append(
            RawPosting(
                ats_id=j["id"],
                title=j.get("title", "").strip(),
                url=j.get("jobUrl", ""),
                location_raw="; ".join(l for l in locs if l),
                country=addr.get("addressCountry", "") or "",
                description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", "")),
                posted_date=iso_date(j.get("publishedAt")),
                remote_hint="remote" if j.get("isRemote") else (j.get("workplaceType") or ""),
                salary_hint=comp,
                contract_hint=j.get("employmentType", "") or "",
            )
        )
    return out


@register("smartrecruiters")
def smartrecruiters(emp: dict, ctx: Context) -> list[RawPosting]:
    cid = emp["token"]
    base = f"https://api.smartrecruiters.com/v1/companies/{cid}/postings"
    out, offset = [], 0
    while True:
        data = ctx.client.get_json(base, params={"limit": 100, "offset": offset})
        for j in data.get("content", []):
            loc = j.get("location") or {}
            loc_raw = ", ".join(p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p)
            if ctx.is_swiss(loc_raw) is False and not emp.get("fetch_abroad"):
                continue
            detail = ctx.client.get_json(f"{base}/{j['id']}")
            sections = (detail.get("jobAd") or {}).get("sections") or {}
            desc = "\n".join(html_to_text((s or {}).get("text", "")) for s in sections.values())
            out.append(
                RawPosting(
                    ats_id=str(j["id"]),
                    title=j.get("name", "").strip(),
                    url=detail.get("postingUrl") or f"https://jobs.smartrecruiters.com/{cid}/{j['id']}",
                    location_raw=loc_raw,
                    country=(loc.get("country") or "").upper(),
                    description=desc,
                    posted_date=iso_date(j.get("releasedDate")),
                    remote_hint="remote" if loc.get("remote") else "",
                    contract_hint=(j.get("typeOfEmployment") or {}).get("label", ""),
                )
            )
        offset += 100
        if offset >= data.get("totalFound", 0):
            return out


@register("personio")
def personio(emp: dict, ctx: Context) -> list[RawPosting]:
    host = emp.get("host") or f"{emp['token']}.jobs.personio.de"
    root = ET.fromstring(ctx.client.get_text(f"https://{host}/xml", params={"language": "en"}))
    out = []
    for pos in root.iter("position"):
        g = lambda tag: (pos.findtext(tag) or "").strip()  # noqa: E731
        offices = [g("office")] + [(o.text or "").strip() for o in pos.findall("additionalOffices/office")]
        desc = "\n".join(
            f"{(d.findtext('name') or '').strip()}\n{html_to_text(d.findtext('value') or '')}"
            for d in pos.iter("jobDescription")
        )
        out.append(
            RawPosting(
                ats_id=g("id"),
                title=g("name"),
                url=f"https://{host}/job/{g('id')}",
                location_raw="; ".join(o for o in offices if o),
                description=desc,
                posted_date=iso_date(g("createdAt")),
                contract_hint=g("employmentType"),
                workload_hint=g("schedule"),
            )
        )
    return out


@register("prospective")
def prospective(emp: dict, ctx: Context) -> list[RawPosting]:
    """Prospective careercenters (ohws.prospective.ch) - used by Helvetia, the federal administration, ..."""
    base = f"https://ohws.prospective.ch/public/v1/medium/{emp['medium_id']}/jobs"
    out, offset = [], 0
    while True:
        data = ctx.client.get_json(base, params={"lang": emp.get("lang", "de"), "limit": 100, "offset": offset})
        jobs = data.get("jobs", [])
        for j in jobs:
            s = j.get("szas") or {}
            desc = "\n".join(
                html_to_text(s.get(k, "") or "")
                for k in ("sza_introduction", "sza_tasks", "sza_requirements", "sza_offer", "sza_company_profil")
                if s.get(k)
            )
            lo, hi = s.get("sza_pensum.min"), s.get("sza_pensum.max")
            out.append(
                RawPosting(
                    ats_id=str(j["id"]),
                    title=(s.get("sza_title") or j.get("title", "")).strip(),
                    url=(j.get("links") or {}).get("directlink", ""),
                    location_raw=", ".join(
                        p for p in (s.get("sza_location.city"), s.get("sza_location.zip")) if p
                    ),
                    country=s.get("sza_location.country", "") or "",
                    description=desc,
                    posted_date=iso_date(j.get("start_date")),
                    workload_hint=f"{lo}-{hi}%" if lo and hi and lo != hi else (f"{hi}%" if hi else ""),
                    contract_hint=" ".join(str(v) for v in (s.get("sza_employment_type"), s.get("sza_pensum")) if v),
                )
            )
        offset += len(jobs)
        if not jobs or offset >= data.get("total", 0):
            return out


@register("manual")
def manual(emp: dict, ctx: Context) -> list[RawPosting]:
    """Rows come from config/manual.yaml; the loader injects them as emp['postings']."""
    out = []
    for p in emp.get("postings", []):
        out.append(
            RawPosting(
                ats_id=str(p.get("id") or p["url"]),
                title=p["title"],
                url=p["url"],
                location_raw=p.get("location", ""),
                country=p.get("country", ""),
                description=p.get("description", ""),
                posted_date=str(p.get("posted", "") or ""),
            )
        )
    return out
