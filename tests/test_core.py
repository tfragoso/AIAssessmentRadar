from pathlib import Path

import pytest

from jobwatch import history
from jobwatch.config import load
from jobwatch.filter import FamilyMatcher
from jobwatch.models import Posting
from jobwatch.normalize import RegionTagger

ROOT = Path(__file__).resolve().parents[1]
CFG = load(ROOT)
TAGGER = RegionTagger(CFG.regions)
MATCHER = FamilyMatcher(CFG.families)


@pytest.mark.parametrize(
    "location, country, expected",
    [
        ("Zurich", "", ("CH", "Zurich")),
        ("Zürich, ZH, CH", "", ("CH", "Zurich")),
        ("Lausanne, VD, CH", "", ("CH", "Romandie")),
        ("Genève", "", ("CH", "Romandie")),
        ("Bern; Basel", "", ("CH", "Basel; Bern")),
        ("Kaiseraugst", "", ("CH", "Other CH")),
        ("Rotkreuz", "Switzerland", ("CH", "Other CH")),
        ("Fribourg", "", ("CH", "Romandie")),
        ("Paris, FR", "", ("?", "Abroad")),
        ("Hyderabad (Office)", "", ("?", "Abroad")),
        ("Grenzach-Wyhlen", "", ("?", "Abroad")),
        ("Cambridge (USA)", "US", ("US", "Abroad")),
        ("London; Zurich", "GB", ("CH", "Zurich")),
        ("Ittigen", "Schweiz", ("CH", "Bern")),
        ("Somewhere", "", ("?", "Abroad")),
    ],
)
def test_region_tag(location, country, expected):
    assert TAGGER.tag(location, country) == expected


def test_default_country():
    assert TAGGER.tag("", "", default_country="CH") == ("CH", "Other CH")


@pytest.mark.parametrize(
    "title, desc, regions, family",
    [
        ("AI Governance Lead", "", ["Zurich"], "ai_validation"),
        ("KI-Governance Spezialist:in", "", ["Bern"], "ai_validation"),
        ("Model Validation Quant", "", ["Zurich"], "model_risk"),
        ("Spécialiste risque de modèle", "", ["Romandie"], "model_risk"),
        ("Senior Quantitative Analyst", "Experience with SR 11-7 and model risk management", ["Zurich"], "model_risk"),
        ("Market Risk Controller", "Collaborate with Model Validation", ["Zurich"], None),
        ("Marketing Manager", "Our AI governance framework...", ["Zurich"], None),  # no title context
        ("LLM Evaluation Engineer", "", ["Zurich"], "ai_evaluation"),
        ("Red Team Operator (Penetration Testing)", "", ["Zurich"], None),
        ("Benchmark Administrator - Index", "", ["Zurich"], None),
        ("Senior Biostatistician", "", ["Basel"], "pharma_control"),
        ("Data Scientist", "", ["Zurich"], None),  # data science only counts in Bern / Romandie
        ("Data Scientist", "", ["Romandie"], "data_science"),
        ("Statistiker/in", "", ["Bern"], "data_science"),
        ("Coach", "", ["Basel"], None),  # "coa" must not match inside "coach"
        ("Data Scientist", "", ["Abroad"], "data_science"),  # abroad rows kept for the offshore flag
    ],
)
def test_classify(title, desc, regions, family):
    assert MATCHER.classify(title, desc, regions) == family


def _p(pid, employer="E", **kw):
    kw = {"title": "t", **kw}
    return Posting(posting_id=pid, employer=employer, segment="s", ats="x", url="u", **kw)


def test_history_lifecycle():
    h = {}
    new, closed = history.merge(h, [_p("a"), _p("b")], "2026-11-02", {"E"})
    assert {p.posting_id for p in new} == {"a", "b"}
    new, closed = history.merge(h, [_p("a")], "2026-11-09", {"E"})
    assert h["b"].status == "open" and h["b"].missed_runs == 1  # one miss: still open
    new, closed = history.merge(h, [_p("a")], "2026-11-16", {"E"})
    assert h["b"].status == "closed" and [p.posting_id for p in closed] == ["b"]
    assert h["b"].last_seen == "2026-11-02"
    new, closed = history.merge(h, [_p("a"), _p("b")], "2026-11-23", {"E"})
    assert h["b"].status == "open" and h["b"].first_seen == "2026-11-02" and not new  # reopened, not new


def test_history_failed_source_does_not_age():
    h = {}
    history.merge(h, [_p("a")], "2026-11-02", {"E"})
    history.merge(h, [], "2026-11-09", set())
    history.merge(h, [], "2026-11-16", set())
    assert h["a"].status == "open" and h["a"].missed_runs == 0


def test_history_same_day_rerun_counts_once():
    h = {}
    history.merge(h, [_p("a")], "2026-11-02", {"E"})
    history.merge(h, [], "2026-11-09", {"E"})
    history.merge(h, [], "2026-11-09", {"E"}, new_run=False)
    assert h["a"].status == "open"


def test_history_roundtrip(tmp_path):
    h = {"a": _p("a", first_seen="2026-11-02", last_seen="2026-11-02", missed_runs=1, region="Zurich")}
    history.save(tmp_path / "p.csv", h)
    back = history.load(tmp_path / "p.csv")
    assert back["a"].missed_runs == 1 and back["a"].region == "Zurich"


def test_render_readme_and_csv(tmp_path):
    from jobwatch.render.tables import SourceStatus, render_readme, write_csvs

    p = _p("a", region="Zurich", role_family="model_risk", status="open", first_seen="2026-11-02",
           languages_required="de:C1:required; fr:?:plus", title="Model | Risk")
    abroad = _p("b", region="Abroad", role_family="model_risk", status="open")
    h = {"a": p, "b": abroad}
    md = render_readme(h, CFG.families, "2026-11-02", [p], [], [SourceStatus("E", "E", "workday", True, 5, 1),
                                                                 SourceStatus("F", "F", "workday", False, error="boom")],
                       [{"name": "UBS", "ats": "blocked", "note": "403"}])
    assert "| 1 | 1 | 0 | 1 | 1 |" in md  # abroad row not counted
    assert "Model \| Risk" in md and "DE C1, (FR)" in md and "F (boom)" in md and "not covered: 403" in md
    write_csvs(tmp_path, h)
    assert (tmp_path / "model_risk.csv").read_text(encoding="utf-8").count("\n") == 2  # header + one Swiss row
