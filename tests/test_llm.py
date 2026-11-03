import json

import httpx

from jobwatch.enrich.llm import LLMEnricher
from jobwatch.models import Posting

CFG = {"provider": "gemini", "model": "m", "api_key_env": "TEST_KEY", "monthly_cap": 10, "min_interval": 0,
       "skills_vocabulary": ["Python", "model validation"]}
ANSWER = {"seniority": "senior", "years_required": 5, "contract_type": "permanent", "key_skills": ["Python"],
          "languages": [{"lang": "en", "level": "C1", "need": "required"}, {"lang": "de", "level": "?", "need": "plus"}]}


def posting(**kw):
    base = dict(posting_id="a", employer="E", segment="s", ats="x", title="Model Validator", url="u", region="Zurich",
                desc_hash="h1", description="x" * 300)
    return Posting(**{**base, **kw})


def client(status=200, answer=ANSWER, calls=None):
    def handler(request: httpx.Request):
        if calls is not None:
            calls.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, text='{"error": "nope"}')
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(answer)}]}}]})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fills_only_empty_fields_and_caches(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "k")
    calls = []
    e = LLMEnricher(CFG, tmp_path / "c.jsonl", "2026-11-03", http=client(calls=calls))
    p = posting(seniority="lead")  # set by rules: must stay
    e.enrich(p)
    e.save()
    assert p.seniority == "lead" and p.years_required == "5" and p.contract_type == "permanent"
    assert p.languages_required == "de:?:plus; en:C1:required" and p.key_skills == "Python"
    assert len(calls) == 1 and calls[0]["generationConfig"]["responseMimeType"] == "application/json"

    e2 = LLMEnricher(CFG, tmp_path / "c.jsonl", "2026-11-10", http=client(calls=calls))
    p2 = posting()
    e2.enrich(p2)
    assert len(calls) == 1 and e2.stats.cached == 1 and p2.seniority == "senior"  # served from cache


def test_billing_error_disables_pass(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "k")
    calls = []
    e = LLMEnricher(CFG, tmp_path / "c.jsonl", "2026-11-03", http=client(status=402, calls=calls))
    e.enrich(posting())
    e.enrich(posting(desc_hash="h2"))
    assert len(calls) == 1 and "402" in e.stats.disabled and "stopped" not in e.stats.summary()


def test_monthly_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "k")
    e = LLMEnricher({**CFG, "monthly_cap": 1}, tmp_path / "c.jsonl", "2026-11-03", http=client())
    e.enrich(posting())
    e.enrich(posting(desc_hash="h2"))
    assert e.stats.calls == 1 and e.stats.skipped_cap == 1


def test_no_key_and_abroad_skip(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_KEY", raising=False)
    e = LLMEnricher(CFG, tmp_path / "c.jsonl", "2026-11-03", http=client())
    p = posting()
    e.enrich(p)
    assert not p.key_skills and "no TEST_KEY" in e.stats.summary()
    monkeypatch.setenv("TEST_KEY", "k")
    calls = []
    e = LLMEnricher(CFG, tmp_path / "c.jsonl", "2026-11-03", http=client(calls=calls))
    e.enrich(posting(region="Abroad"))
    assert not calls
