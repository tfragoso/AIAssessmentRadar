"""Common records shared by adapters, enrichment, history and renderers."""

from __future__ import annotations

from dataclasses import dataclass, field, fields


@dataclass
class RawPosting:
    """What an adapter returns: the ATS facts, untouched by our rules."""

    ats_id: str
    title: str
    url: str
    location_raw: str = ""
    country: str = ""  # when the ATS gives it explicitly
    description: str = ""  # plain text
    posted_date: str = ""  # ISO date
    remote_hint: str = ""  # ATS workplace field, if any
    salary_hint: str = ""
    workload_hint: str = ""
    contract_hint: str = ""


@dataclass
class Posting:
    posting_id: str
    employer: str
    segment: str
    ats: str
    title: str
    url: str
    location_raw: str = ""
    country: str = ""
    region: str = ""  # one or more region tags joined by "; "
    remote: str = ""
    posted_date: str = ""
    first_seen: str = ""
    last_seen: str = ""
    status: str = "open"
    missed_runs: int = 0
    role_family: str = ""
    seniority: str = ""
    years_required: str = ""
    languages_required: str = ""  # e.g. "de:C1:required; fr:fluent:plus"
    ad_language: str = ""
    contract_type: str = ""
    workload: str = ""
    salary_min: str = ""
    salary_max: str = ""
    key_skills: str = ""  # LLM pass (later build)
    offshore_match: str = ""  # offshore pass (later build)
    desc_hash: str = ""
    description: str = field(default="", repr=False)  # stored separately, not in postings.csv

    @classmethod
    def csv_fields(cls) -> list[str]:
        return [f.name for f in fields(cls) if f.name != "description"]


# Display order of role families (keys in keywords.yaml).
FAMILIES = ["ai_validation", "model_risk", "ai_evaluation", "data_science", "pharma_control"]
REGIONS = ["Bern", "Romandie", "Zurich", "Basel", "Other CH", "Abroad"]
