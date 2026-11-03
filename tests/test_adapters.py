"""Adapters parse recorded ATS responses (tests/fixtures) into RawPostings."""

import json
from pathlib import Path

from jobwatch.adapters import REGISTRY, Context
from jobwatch.config import load
from jobwatch.filter import FamilyMatcher
from jobwatch.normalize import RegionTagger

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]
CFG = load(ROOT)
TAGGER = RegionTagger(CFG.regions)
MATCHER = FamilyMatcher(CFG.families)


class FakeClient:
    """Serves fixture files by URL substring; records requests."""

    def __init__(self, routes: dict[str, object]):
        self.routes = routes
        self.calls: list[str] = []

    def _find(self, url, params=None, body=None):
        self.calls.append(url)
        key = url + json.dumps(params or {}) + json.dumps(body or {})
        for frag, resp in self.routes.items():
            if frag in key:
                return resp(url, params, body) if callable(resp) else resp
        raise AssertionError(f"unexpected request {url} {params} {body}")

    def get_text(self, url, params=None, headers=None):
        r = self._find(url, params)
        return r.read_text(encoding="utf-8") if isinstance(r, Path) else r

    def get_json(self, url, params=None, headers=None):
        r = self._find(url, params)
        return json.loads(r.read_text(encoding="utf-8")) if isinstance(r, Path) else r

    def post_json(self, url, body, headers=None):
        return self._find(url, None, body)


def ctx(client, terms=("model risk",)):
    return Context(client=client, search_terms=list(terms),
                   title_match=lambda t: MATCHER.title_family(t) is not None,
                   maybe_match=lambda t: True, is_swiss=TAGGER.is_swiss)


def test_greenhouse():
    out = REGISTRY["greenhouse"]({"name": "X", "token": "x"}, ctx(FakeClient({"greenhouse": FIX / "greenhouse.json"})))
    assert len(out) == 3 and all(p.title and p.url.startswith("http") and p.description for p in out)
    assert "<" not in out[0].description  # HTML stripped


def test_lever():
    out = REGISTRY["lever"]({"name": "X", "token": "x"}, ctx(FakeClient({"lever": FIX / "lever.json"})))
    assert len(out) == 3 and all(p.title and p.url and p.posted_date[:2] == "20" for p in out)


def test_ashby():
    out = REGISTRY["ashby"]({"name": "X", "token": "x"}, ctx(FakeClient({"ashbyhq": FIX / "ashby.json"})))
    assert out and all(p.title and p.url and p.description for p in out)


def test_personio():
    out = REGISTRY["personio"]({"name": "X", "token": "x"}, ctx(FakeClient({"personio": FIX / "personio.xml"})))
    (p,) = out
    assert p.title.startswith("AI Governance") and p.location_raw == "Zürich; Lausanne"
    assert "model validation" in p.description and p.posted_date == "2026-10-20"


def test_prospective():
    out = REGISTRY["prospective"]({"name": "X", "medium_id": 1}, ctx(FakeClient({"prospective": FIX / "prospective.json"})))
    assert len(out) == 3 and all(p.url.startswith("https://jobs.helvetia.com") for p in out)
    assert all(TAGGER.tag(p.location_raw, p.country)[0] == "CH" for p in out)


def test_oracle():
    fc = FakeClient({"recruitingCEJobRequisitionDetails": FIX / "oracle_detail.json",
                     "recruitingCEJobRequisitions": FIX / "oracle_list.json"})
    out = REGISTRY["oracle"]({"name": "X", "host": "https://h", "site": "s", "fetch_abroad": True}, ctx(fc))
    # the single fixture posting is abroad; with fetch_abroad it is kept only if its title matches a family
    assert len(out) <= 1
    for p in out:
        assert p.description and p.url.startswith("https://h/hcmUI/")


def test_sfcareer_and_microdata():
    fc = FakeClient({"/search/": FIX / "sfcareer_search.html", "/job/": FIX / "sfcareer_job.html"})
    out = REGISTRY["sfcareer"]({"name": "Swiss Re", "base": "https://careers.swissre.com"}, ctx(fc))
    assert len(out) >= 5
    p = out[0]
    assert p.title and p.description and p.country  # from schema.org microdata on the job page


def test_htmllist_jsonld():
    listing = '<a href="/offene-stellen/x/1">Model Risk Specialist</a><a href="/other">x</a>'
    fc = FakeClient({"offene-stellen/x/1": FIX / "jsonld_job.html", "jobs.finma.ch/": listing})
    out = REGISTRY["htmllist"]({"name": "FINMA", "listing": "https://jobs.finma.ch/",
                                "link_pattern": "offene-stellen/"}, ctx(fc))
    (p,) = out
    assert p.title and len(p.description) > 200 and p.url == "https://jobs.finma.ch/offene-stellen/x/1"


def test_workday_with_country_facet():
    listing = {
        "total": 2,
        "facets": [{"facetParameter": "Location_Country",
                    "values": [{"descriptor": "Switzerland", "id": "187134fccb084a0ea9b4b95f23890dbe", "count": 2}]}],
        "jobPostings": [
            {"title": "Model Risk Analyst", "externalPath": "/job/Zurich/A_r-1", "locationsText": "Zurich"},
            {"title": "Teller", "externalPath": "/job/Zurich/B_r-2", "locationsText": "Zurich"},
        ],
    }
    detail = lambda url, p, b: {"jobPostingInfo": {  # noqa: E731
        "title": "Model Risk Analyst" if "A_" in url else "Teller", "jobDescription": "<p>Desc</p>",
        "location": "Zurich", "startDate": "2026-10-01", "jobReqId": url[-3:], "externalUrl": "https://wd/" + url[-6:],
        "jobRequisitionLocation": {"country": {"alpha2Code": "CH"}}}}
    fc = FakeClient({"/jobs{": listing, "/job/": detail})
    out = REGISTRY["workday"]({"name": "JB", "tenant": "t", "site": "s"}, ctx(fc))
    assert {p.title for p in out} == {"Model Risk Analyst", "Teller"}  # every Swiss posting; filtering is later
    assert all(p.country == "CH" and p.description == "Desc" and p.posted_date == "2026-10-01" for p in out)
