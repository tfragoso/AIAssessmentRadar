"""Load the YAML config files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Config:
    root: Path
    employers: list[dict]
    keywords: dict
    regions: dict
    llm: dict

    @property
    def families(self) -> dict:
        return self.keywords["families"]


def load(root: Path) -> Config:
    cfg = root / "config"
    read = lambda name: yaml.safe_load((cfg / name).read_text(encoding="utf-8")) or {}  # noqa: E731
    employers = read("employers.yaml").get("employers", [])
    manual = read("manual.yaml").get("postings", []) if (cfg / "manual.yaml").exists() else []

    # Hand-added postings become one synthetic "manual" source per employer.
    by_emp: dict[str, list] = {}
    for p in manual:
        by_emp.setdefault(p["employer"], []).append(p)
    known = {e["name"]: e for e in employers}
    for name, posts in by_emp.items():
        base = known.get(name, {"name": name, "segment": "other"})
        employers.append({**base, "ats": "manual", "postings": posts, "source": f"{name} (manual)"})

    llm = read("llm.yaml") if (cfg / "llm.yaml").exists() else {}
    return Config(root=root, employers=employers, keywords=read("keywords.yaml"), regions=read("regions.yaml"), llm=llm)
