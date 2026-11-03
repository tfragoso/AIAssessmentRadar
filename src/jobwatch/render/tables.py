"""README.md and csv/ outputs (open Swiss roles only)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ..models import FAMILIES, Posting

CSV_COLUMNS = ["family", "company", "segment", "role", "url", "region", "location", "languages", "seniority",
               "years", "contract", "workload", "remote", "salary_chf", "skills", "posted", "first_seen", "offshore",
               "posting_id"]


@dataclass
class SourceStatus:
    source: str
    employer: str
    ats: str
    ok: bool
    fetched: int = 0
    kept: int = 0
    error: str = ""


def open_swiss(history: dict[str, Posting]) -> list[Posting]:
    rows = [p for p in history.values() if p.status == "open" and p.region != "Abroad"]
    fam = {f: i for i, f in enumerate(FAMILIES)}
    return sorted(rows, key=lambda p: (fam.get(p.role_family, 99), p.employer.lower(), p.title.lower()))


def fmt_languages(s: str) -> str:
    out = []
    for item in filter(None, (x.strip() for x in s.split(";"))):
        lang, level, need = (item.split(":") + ["", ""])[:3]
        txt = lang.upper() + (f" {level}" if level and level != "?" else "")
        out.append(f"({txt})" if need == "plus" else txt)
    return ", ".join(out)


def _row(p: Posting) -> dict:
    sal = f"{int(p.salary_min):,}-{int(p.salary_max):,}".replace(",", "'") if p.salary_min else ""
    return {
        "family": p.role_family, "company": p.employer, "segment": p.segment, "role": p.title, "url": p.url,
        "region": p.region, "location": p.location_raw, "languages": fmt_languages(p.languages_required),
        "seniority": p.seniority, "years": p.years_required, "contract": p.contract_type, "workload": p.workload,
        "remote": p.remote, "salary_chf": sal, "skills": p.key_skills, "posted": p.posted_date, "first_seen": p.first_seen,
        "offshore": "yes" if p.offshore_match else "", "posting_id": p.posting_id,
    }


def write_csvs(folder: Path, history: dict[str, Posting]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    rows = open_swiss(history)
    for name, subset in [("all", rows)] + [(f, [p for p in rows if p.role_family == f]) for f in FAMILIES]:
        with (folder / f"{name}.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, lineterminator="\n")
            w.writeheader()
            w.writerows(_row(p) for p in subset)


def _md(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ")


def render_readme(
    history: dict[str, Posting],
    families: dict,
    run_date: str,
    new: list[Posting],
    closed: list[Posting],
    statuses: list[SourceStatus],
    uncovered: list[dict],
    llm_summary: str = "",
) -> str:
    rows = open_swiss(history)
    new_ch = [p for p in new if p.region != "Abroad"]
    closed_ch = [p for p in closed if p.region != "Abroad"]
    failed = [s for s in statuses if not s.ok]
    new_ids = {p.posting_id for p in new}

    L = [
        "# Swiss AI Validation Jobs Monitor",
        "",
        "Open Swiss roles in AI validation, model risk and AI evaluation, plus data science (Bern, Romandie, Zurich, Basel)"
        " and a pharma control group. Rebuilt every Monday from employers' own job boards.",
        "",
        f"**Last update:** {run_date}",
        "",
        "| Open roles | New this week | Closed this week | Sources OK | Sources failed |",
        "|---:|---:|---:|---:|---:|",
        f"| {len(rows)} | {len(new_ch)} | {len(closed_ch)} | {len(statuses) - len(failed)} | {len(failed)} |",
        "",
    ]
    if llm_summary:
        L += [f"_{_md(llm_summary)}_", ""]
    if failed:
        L += ["**Failed sources this week:** " + ", ".join(f"{s.source} ({_md(s.error)[:80]})" for s in failed), ""]

    L += ["## Contents", ""]
    for f in families:
        n = sum(p.role_family == f for p in rows)
        L.append(f"- [{families[f]['label']}](#{f.replace('_', '-')}) ({n})")
    L += ["- [Sources](#sources)", ""]

    for f, spec in families.items():
        subset = [p for p in rows if p.role_family == f]
        L += [f'<a id="{f.replace("_", "-")}"></a>', f"## {spec['label']}", ""]
        if not subset:
            L += ["_No open roles._", ""]
            continue
        L += [
            "| Company | Role | Region | Languages | Seniority | Years | Contract | Posted | Offshore |",
            "|---|---|---|---|---|---:|---|---|---|",
        ]
        for p in subset:
            star = " 🆕" if p.posting_id in new_ids else ""
            L.append(
                f"| {_md(p.employer)} | [{_md(p.title)}]({p.url}){star} | {_md(p.region)} | "
                f"{fmt_languages(p.languages_required)} | {p.seniority} | {p.years_required} | {p.contract_type} | "
                f"{p.posted_date or p.first_seen} | {'⚠️' if p.offshore_match else ''} |"
            )
        L.append("")

    L += [
        "## Sources",
        "",
        "Languages: `(FR)` = a plus, not required. Years = minimum years of experience asked."
        " Blank cells mean neither the rules nor the LLM pass could tell. Skills are in the CSVs.",
        "",
        "| Source | ATS | Status | Postings fetched | Kept |",
        "|---|---|---|---:|---:|",
    ]
    for s in sorted(statuses, key=lambda s: s.source.lower()):
        L.append(f"| {_md(s.source)} | {s.ats} | {'ok' if s.ok else 'failed'} | {s.fetched} | {s.kept} |")
    for e in sorted(uncovered, key=lambda e: e["name"].lower()):
        L.append(f"| {_md(e['name'])} | {e.get('ats', '')} | not covered: {_md(e.get('note', ''))} | | |")
    L += [
        "",
        "Data: [`csv/`](csv/) (open roles), [`data/postings.csv`](data/postings.csv) (full history),"
        " [`data/snapshots/`](data/snapshots/) (weekly open sets).",
        "",
        "## How it works",
        "",
        "- Postings come only from employers' own applicant-tracking systems (Workday, SuccessFactors, Prospective,"
        " Oracle, career pages with schema.org data), never from LinkedIn or Indeed. robots.txt is respected and"
        " each host gets at most one request per second.",
        "- Role families are keyword matches (EN/DE/FR) on the title, or on the description when the title is"
        " related; see [`config/keywords.yaml`](config/keywords.yaml). Employers are listed in"
        " [`config/employers.yaml`](config/employers.yaml); hand-added roles go in"
        " [`config/manual.yaml`](config/manual.yaml).",
        "- Seniority, years, languages, contract type and workload come from deterministic rules on the ad text;"
        " an LLM pass ([`config/llm.yaml`](config/llm.yaml)) fills what the rules leave empty and maps key skills"
        " onto a fixed list. Each ad is sent once (cached by text hash in `data/llm_cache.jsonl`).",
        "- A role is marked closed after it is missing from two successful weekly runs; closed roles stay in the"
        " history.",
        "",
    ]
    return "\n".join(L)
