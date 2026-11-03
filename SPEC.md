# Swiss AI Validation Jobs Monitor — Specification

Nov 3, 2026 · @Tiago

## Purpose and background

A GitHub repo that rebuilds itself every week. It lists open Swiss roles in AI validation, model risk, AI evaluation and adjacent data science, and keeps a history showing how demand, seniority, language requirements and offshoring shift month to month.

- **Why:** automates a manual check of how the market for these roles is moving.
- **Inspiration:** [Epidemiology-RWE-and-HEOR-Jobs](https://github.com/mehek-builds/Epidemiology-RWE-and-HEOR-Jobs). It is rebuilt every Monday from employers' own job boards (via the Litos aggregator) and publishes README tables plus CSVs. The repo holds only generated output, no code, and closed roles drop off.
- **What this version adds:** a persistent history, enrichment fields (language, seniority, years required, contract type), an offshoring flag, and an auto-generated monthly trend report.
- **Out of scope:** scraping LinkedIn or Indeed, applying to jobs, and drafting outreach.

## Scope

Five role families are tracked across Switzerland. Data science roles count only in Bern and Romandie; pharma roles are kept as a control group to show whether that market recovers.

| Role family | Title / text keywords (EN · DE · FR) | Geography |
| --- | --- | --- |
| AI validation and assurance | AI validation, model validation, AI assurance, AI governance, responsible AI, trustworthy AI, AI risk · KI-Validierung, KI-Governance · validation de modèles, gouvernance IA | All of Switzerland |
| Model risk | model risk, MRM, model governance, validation quant · Modellrisiko · risque de modèle | All of Switzerland |
| AI evaluation | LLM evaluation, AI evaluation, evals, benchmark, red teaming | All of Switzerland |
| Data science core | data scientist, statistician, machine learning engineer · Data Scientist, Statistiker · scientifique des données, statisticien | Bern and Romandie only |
| Pharma control | biostatistician, psychometric, clinical outcome assessment, HEOR, COA | All of Switzerland |

**Region tags:** Bern, Romandie (GE, VD, NE, FR, VS, JU), Zurich, Basel, Other CH, Abroad. Roles abroad are fetched only from tracked employers, and only to set the offshoring flag.

**Seed employers** (each one's job-board system is identified during the build):

| Segment | Employers |
| --- | --- |
| Big Four assurance | EY, PwC, KPMG, Deloitte |
| Insurers | Zurich Insurance, Swiss Re, Helvetia Baloise, Vaudoise, Groupe Mutuel, Mobiliar |
| Banks | UBS, Julius Baer, PostFinance, ZKB, BCV, Pictet, Lombard Odier |
| Regulators and public sector | FINMA, SNB, federal administration (BFS and others) |
| AI governance startups | LatticeFlow, Calvin Risk, Modulos |
| Evaluation teams | Thomson Reuters (Zug), Grid Dynamics (Zug), Artificialy |
| Research institutes | Idiap, CSEM, ETH/EPFL (Apertus) |
| Pharma control | Roche, Novartis, Nestlé Research, Cytel |

Employers are added or removed by editing one config file; no code change is needed.

## Data sources and connectors

All roles come from employers' own job boards through the public feeds their applicant-tracking systems (ATS) publish, never from LinkedIn or Indeed. Each ATS gets one adapter that returns a common record. The endpoint shapes below are from memory and must be confirmed against live responses when each adapter is written.

| Adapter | Typical users | Endpoint shape (verify) | Effort |
| --- | --- | --- | --- |
| Greenhouse | Tech companies, startups | `GET boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | Low |
| Lever | Startups | `GET api.lever.co/v0/postings/{company}?mode=json` | Low |
| Ashby | Startups | `GET api.ashbyhq.com/posting-api/job-board/{name}` | Low |
| SmartRecruiters | Mid-size firms | `GET api.smartrecruiters.com/v1/companies/{id}/postings` | Low |
| Workday | Large banks, insurers, pharma | `POST {tenant}.wd{n}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` with a JSON body (`limit`, `offset`, `searchText`), then a GET per posting | Medium |
| VC portfolio boards (Getro) | Startups listed on investor boards (e.g. jobs.b2venture.vc) | Board pages or the API behind them | Medium |
| Generic career page | SuccessFactors, Avature and custom sites | schema.org `JobPosting` JSON-LD on each posting page; HTML fallback | High; per-site |
| Manual | Anything else | A row in `manual.yaml` or a GitHub issue form | None |

**Rules for fetching:**

- Respect each site's robots.txt and terms.
- One request per second per host, with retries and backoff.
- Use a generic client name as the User-Agent, with no personal email in it.
- Cache raw responses for the run, so a failure doesn't trigger refetching.
- A broken adapter logs a warning and the run continues; the README shows which sources failed that week.

The first build task is to identify which ATS each seed employer uses: open its careers page and look at the network calls or posting URLs.

## Data model and enrichment

Each posting is stored once and tracked across weeks by `first_seen` and `last_seen`. The enrichment fields carry the trend signals.

| Field | Type | Source |
| --- | --- | --- |
| `posting_id` | string | Hash of employer + ATS id (or of the URL) |
| `employer`, `segment` | string | Config |
| `title`, `url`, `description` | string | ATS |
| `location_raw`, `country`, `region` | string | ATS, normalized to the region tags |
| `remote` | onsite / hybrid / remote | ATS fields or text rules |
| `posted_date` | date | ATS, when given |
| `first_seen`, `last_seen`, `status` | date, date, open/closed | Pipeline; a posting is closed when absent for two runs |
| `role_family` | enum | Keyword match on title, then description |
| `seniority` | intern / junior / mid / senior / lead / director | Title rules, then the LLM |
| `years_required` | int | Rules ("5+ years", "mindestens 5 Jahre", "5 ans d'expérience"), then the LLM |
| `languages_required` | list of {lang, level, required/plus} | Rules ("Deutsch C1", "fluent German", "français courant"), then the LLM |
| `ad_language` | de / fr / en / it | Language detection on the description |
| `contract_type` | permanent / fixed-term / temporary-agency | Rules ("befristet", "CDD", "12 months", agency employers) |
| `workload` | string, e.g. 80–100% | Rules |
| `salary` | min, max, CHF | ATS or text, when listed |
| `key_skills` | list | The LLM, mapped to a fixed vocabulary (Python, PyTorch, LLM, agents, Bayesian, model validation, SR 11-7, FINMA …) |
| `offshore_match` | list of posting ids | Same employer and similar title outside Switzerland within 60 days |
| `desc_hash` | string | Detects edits; the LLM cache key |

**Enrichment order:** deterministic rules first, then one LLM call returning JSON against a fixed schema, through the provider set in config/llm.yaml (Gemini API free tier or Claude API), only for fields the rules leave empty. Results are cached by `desc_hash`, so each posting is classified once. Without an API key, the pipeline runs on rules alone.

**Offshoring match:** normalize titles (lowercase, strip gender tags like "(m/w/d)" and workload) and match on token Jaccard of at least 0.6 at the same employer. Embeddings can come later if that proves too noisy.

## Pipeline and scheduling

A single GitHub Actions job runs the whole pipeline weekly and commits the results; no server is needed.

&#91;embedded content: weekly pipeline · 8 steps\]

The merge step is the main departure from the reference repo: closed roles are marked closed, not deleted, so trends can be computed.

- **Schedule:** `.github/workflows/weekly.yml`, cron `0 5 * * 1` (Mondays 05:00 UTC), plus manual `workflow_dispatch`. The first run of each month also renders the monthly report.
- **Secrets:** an optional `GEMINI_API_KEY` or `ANTHROPIC_API_KEY`, matching the provider in `config/llm.yaml`, for the LLM enrichment pass; without it, the pipeline runs on rules only.
- **Runtime target:** under 10 minutes. Actions minutes are free on public repos; private repos get a monthly free quota.
- **Failure handling:** the job summary lists the sources that failed. A source that fails two weeks running opens a GitHub issue automatically.

## Outputs

Each weekly run commits four outputs. The monthly report is the one that answers "is the market moving away from me?".

| Output | Path | Contents |
| --- | --- | --- |
| README | `README.md` | Headline counts (open roles, new this week, closed this week, sources that failed), then one table per role family: Company · Role (linked) · Region · Languages · Seniority · Years · Contract · Posted · Offshore flag |
| Current lists | `csv/{family}.csv`, `csv/all.csv` | Open roles only, same columns as the README |
| History | `data/postings.csv` | Every posting ever seen, one row each, with `first_seen`, `last_seen`, `status`; CSV so diffs are readable on GitHub |
| Weekly snapshots | `data/snapshots/YYYY-MM-DD.csv` | Posting ids open that week; enough to rebuild any past state |
| Monthly report | `reports/YYYY-MM.md` | Trend tables and charts, compared with the previous month |

**The monthly report answers these questions:**

1. Open roles by family × region, against last month and three months ago.
2. New versus closed roles, and the median number of days a role stays open, by family.
3. Share of roles requiring German, and share requiring French, by family and region.
4. Seniority mix and the distribution of years required. Are AI-specific roles asking for fewer years than classic model risk?
5. Contract mix: permanent versus fixed-term or agency.
6. Offshoring: every Swiss role with an abroad match, and the count of abroad-only roles at tracked employers.
7. Top skills by family, with month-on-month change (e.g. LLM, agents, Bayesian, PyTorch).
8. Pharma control group: the same counts, as the early-warning baseline.

Charts are matplotlib PNGs embedded in the report: one line per family over time, and a stacked bar for language requirements.

## Build plan

Python 3.12, managed with uv, with no database: CSV files in the repo are the store. Build in five milestones, each usable on its own.

**Repo layout**

```
swiss-ai-validation-jobs/
├─ config/
│  ├─ employers.yaml      # name, segment, ats, board token / tenant / url
│  ├─ keywords.yaml       # role families → EN/DE/FR terms
│  ├─ llm.yaml            # provider: gemini | claude, model, monthly cap
│  └─ manual.yaml         # hand-added postings
├─ src/jobwatch/
│  ├─ adapters/           # greenhouse.py, lever.py, ashby.py, workday.py, jsonld.py …
│  ├─ normalize.py        # common record, region tagging
│  ├─ filter.py           # keyword + geography
│  ├─ enrich/             # rules.py, llm.py (cached), offshore.py
│  ├─ history.py          # merge, first/last seen, snapshots
│  └─ render/             # readme.py, csv.py, report.py
├─ data/  csv/  reports/
├─ tests/fixtures/        # recorded ATS responses
└─ .github/workflows/weekly.yml
```

**Config example**

```yaml
- name: LatticeFlow
  segment: ai-governance-startup
  ats: unknown        # set during M1 discovery
- name: Julius Baer
  segment: bank
  ats: workday
  tenant: TBD         # verify
  fetch_abroad: true  # needed for the offshore flag
```

**Testing:** recorded responses per adapter as fixtures; unit tests for every enrichment rule in EN, DE and FR; a `--dry-run` that renders without committing; a CI check that fails if fewer than half the sources return data.

**Milestones**

1. **Discovery and easy adapters:** identify each seed employer's ATS; Greenhouse, Lever and Ashby adapters; keyword filter; README and CSVs.
2. **Big-employer adapters:** Workday and JSON-LD; the banks, insurers and Big Four.
3. **History and enrichment:** `postings.csv`, snapshots, rule-based enrichment, then the cached LLM pass.
4. **Monthly report:** trend tables and charts.
5. **Offshoring flag:** fetch abroad roles for tracked employers and match titles.

**Open questions**

- Public or private repo? A public one works as a portfolio piece; a private one keeps the employer list to yourself.
- Which employers use Workday, and which need per-site scraping (decided in M1)?
- Budget for the LLM pass: it runs only on new or edited postings, so it should be small, but it needs a cap. Start on the Gemini API free tier; switch to Claude only if it extracts more accurately on a hand-labelled sample of 100 postings.

## Sources

- [mehek-builds/Epidemiology-RWE-and-HEOR-Jobs](https://github.com/mehek-builds/Epidemiology-RWE-and-HEOR-Jobs) (the reference repo, inspected 2026-11-03)
