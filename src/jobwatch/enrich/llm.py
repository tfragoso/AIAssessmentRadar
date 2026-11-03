"""LLM pass: one structured call per ad (cached by desc_hash), filling only what the rules left empty."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx

from ..models import Posting

log = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
FATAL_STATUS = {400, 401, 402, 403, 404}  # bad key / billing / unknown model: stop calling for this run

PROMPT = """You extract structured facts from a job advertisement (it may be in English, German, French or Italian).
Only report what the ad states or clearly implies; use null / empty lists when it doesn't say.

- seniority: intern, junior, mid, senior, lead (team lead, manager, principal, expert) or director (head, director, VP).
- years_required: the minimum years of professional experience asked for, as an integer.
- languages: each spoken language the ad asks for (de, fr, en, it) with a CEFR level when stated or implied
  ("fluent"/"verhandlungssicher"/"courant" = C1, "native" = C2, "good" = B2, "basic" = B1, else "?"), and whether it is
  "required" or a "plus" (advantage, nice to have, von Vorteil, un atout).
- contract_type: permanent, fixed-term (befristet, CDD, a fixed number of months, internship with an end date) or
  temporary-agency (staffing agency, external payroll, interim).
- key_skills: the skills the role needs, mapped onto this list only (pick at most 8, most important first):
  {vocabulary}

Job title: {title}
Employer: {employer}

Advertisement:
{text}"""


def _schema(vocabulary: list[str]) -> dict:
    return {
        "type": "OBJECT",
        "properties": {
            "seniority": {"type": "STRING", "enum": ["intern", "junior", "mid", "senior", "lead", "director"],
                          "nullable": True},
            "years_required": {"type": "INTEGER", "nullable": True},
            "languages": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                "lang": {"type": "STRING", "enum": ["de", "fr", "en", "it"]},
                "level": {"type": "STRING", "enum": ["A1", "A2", "B1", "B2", "C1", "C2", "?"]},
                "need": {"type": "STRING", "enum": ["required", "plus"]},
            }, "required": ["lang", "level", "need"]}},
            "contract_type": {"type": "STRING", "enum": ["permanent", "fixed-term", "temporary-agency"],
                              "nullable": True},
            "key_skills": {"type": "ARRAY", "items": {"type": "STRING", "enum": vocabulary}},
        },
        "required": ["seniority", "years_required", "languages", "contract_type", "key_skills"],
    }


@dataclass
class LLMStats:
    calls: int = 0
    cached: int = 0
    skipped_cap: int = 0
    errors: int = 0
    disabled: str = ""  # reason the pass didn't run / stopped
    model: str = ""

    def summary(self) -> str:
        if self.disabled and not (self.calls or self.cached):
            return f"LLM pass off: {self.disabled}"
        s = f"LLM pass ({self.model}): {self.calls} new, {self.cached} from cache"
        if self.skipped_cap:
            s += f", {self.skipped_cap} skipped (monthly cap)"
        if self.disabled:
            s += f"; stopped: {self.disabled}"
        return s


class LLMEnricher:
    def __init__(self, cfg: dict, cache_path: Path, run_date: str, http: httpx.Client | None = None):
        self.cfg = cfg
        self.cache_path = cache_path
        self.month = run_date[:7]
        self.run_date = run_date
        self.vocab = cfg.get("skills_vocabulary", [])
        self.stats = LLMStats(model=cfg.get("model", ""))
        self.cache: dict[str, dict] = {}
        self.calls_this_month = 0
        if cache_path.exists():
            for line in cache_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self.cache[rec["desc_hash"]] = rec
                    self.calls_this_month += rec.get("date", "")[:7] == self.month
        self.key = os.environ.get(cfg.get("api_key_env", "GEMINI_API_KEY"), "")
        if cfg.get("provider", "gemini") != "gemini":
            self.stats.disabled = f"provider '{cfg.get('provider')}' not implemented"
        elif not self.key:
            self.stats.disabled = f"no {cfg.get('api_key_env', 'GEMINI_API_KEY')} in environment"
        self.http = http or httpx.Client(timeout=90)
        self._new: list[dict] = []

    # -- public ------------------------------------------------------------------------------
    def enrich(self, p: Posting) -> None:
        if not p.desc_hash or len(p.description) < 200:
            return
        if self.cfg.get("swiss_only", True) and p.region == "Abroad":
            return
        rec = self.cache.get(p.desc_hash)
        if rec is not None:
            self.stats.cached += 1
        else:
            rec = self._call(p)
            if rec is None:
                return
        apply_result(p, rec["result"])

    def save(self) -> None:
        if not self._new:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_path.open("a", encoding="utf-8", newline="\n") as fh:
            for rec in self._new:
                fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
        self._new = []

    # -- internals --------------------------------------------------------------------------------
    def _call(self, p: Posting) -> dict | None:
        if self.stats.disabled:
            return None
        if self.calls_this_month >= self.cfg.get("monthly_cap", 400):
            self.stats.skipped_cap += 1
            return None
        prompt = PROMPT.format(vocabulary=", ".join(self.vocab), title=p.title, employer=p.employer,
                               text=p.description[: self.cfg.get("max_chars", 12000)])
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json",
                                 "responseSchema": _schema(self.vocab)},
        }
        url = GEMINI_URL.format(model=self.cfg["model"])
        delay = 5.0
        for attempt in range(4):
            try:
                r = self.http.post(url, json=body, headers={"x-goog-api-key": self.key})
            except httpx.HTTPError as e:
                err = str(e)
            else:
                if r.status_code == 200:
                    try:
                        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                        result = json.loads(text)
                    except (KeyError, IndexError, ValueError) as e:
                        self.stats.errors += 1
                        log.warning("LLM: unparseable answer for %s: %s", p.posting_id, e)
                        return None
                    self.calls_this_month += 1
                    self.stats.calls += 1
                    rec = {"desc_hash": p.desc_hash, "date": self.run_date, "model": self.cfg["model"],
                           "result": result}
                    self.cache[p.desc_hash] = rec
                    self._new.append(rec)
                    time.sleep(self.cfg.get("min_interval", 1.0))
                    return rec
                try:
                    msg = r.json()["error"]["message"]
                except (ValueError, KeyError, TypeError):
                    msg = r.text
                err = f"HTTP {r.status_code}: {' '.join(str(msg).split())[:160]}"
                if r.status_code in FATAL_STATUS:
                    self.stats.disabled = err
                    log.warning("LLM disabled for this run: %s", self.stats.disabled)
                    return None
            if attempt < 3:
                time.sleep(delay)
                delay *= 2
        self.stats.errors += 1
        log.warning("LLM: giving up on %s: %s", p.posting_id, err[:200])
        if err.startswith("HTTP 429"):  # quota exhausted: retrying every posting would only burn time
            self.stats.disabled = "rate limit / quota (HTTP 429)"
        return None


def apply_result(p: Posting, r: dict) -> None:
    """Fill only empty fields; key_skills always comes from the LLM."""
    if not p.seniority and r.get("seniority"):
        p.seniority = r["seniority"]
    if not p.years_required and isinstance(r.get("years_required"), int) and 0 < r["years_required"] <= 25:
        p.years_required = str(r["years_required"])
    if not p.languages_required and r.get("languages"):
        order = {"de": 0, "fr": 1, "en": 2, "it": 3}
        best: dict[str, tuple[str, str]] = {}
        for l in r["languages"]:
            lang, lv, need = l.get("lang"), l.get("level") or "?", l.get("need") or "required"
            if lang in order and (lang not in best or (best[lang][1] == "plus" and need == "required")):
                best[lang] = (lv, need)
        p.languages_required = "; ".join(f"{l}:{best[l][0]}:{best[l][1]}" for l in sorted(best, key=order.get))
    if not p.contract_type and r.get("contract_type"):
        p.contract_type = r["contract_type"]
    if r.get("key_skills"):
        p.key_skills = "; ".join(dict.fromkeys(r["key_skills"]))
