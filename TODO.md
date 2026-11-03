# TODO — where to pick up

_State at end of 2026-11-03._ Build 1 is live: 20 sources, rule-based enrichment, history and snapshots, and the
weekly GitHub Action (green). The data-science family now also covers Zurich and Basel. A stopgap Gemini pass
exists (`src/jobwatch/enrich/llm.py`), but the Gemini project has no prepaid credits (HTTP 402), so it has never
produced output.

Next up is the LLM layer described in [LLM_LAYER.md](LLM_LAYER.md), on top of [SPEC.md](SPEC.md).

## Start the next session with

> Read SPEC.md, LLM_LAYER.md and TODO.md. Confirm the plan for step 1, list anything ambiguous, then implement
> step 1 only.

## Owner actions (blockers)

- [ ] Top up Gemini credits in AI Studio, **or** add an `ANTHROPIC_API_KEY` repo secret for the Claude provider.
      Without one of them, no LLM step produces anything.
- [ ] Rotate the Gemini key (it was pasted in a chat), then update the secret:
      `gh secret set GEMINI_API_KEY -R tfragoso/AIAssessmentRadar`.
- [ ] Write `config/profile.yaml` (keys described in LLM_LAYER.md; the full example is in the Drive copy), needed for tasks 3 and 4. It must stay private: it
      will be gitignored, and CI will get it from an encrypted `PROFILE_YAML` secret written to disk at run time.
- [ ] After step 2: hand-label 100 postings with `jobwatch label` (about 40 EN / 35 DE / 25 FR, all families). The
      history has about 85 postings today, so let a few weekly runs accumulate or include abroad postings.
- [ ] Answer the open questions below.

## Build order (from LLM_LAYER.md; each step ends with tests passing)

| Step | Work | Estimate |
|---|---|---|
| 1 | **Scaffold.** `enrich/schema.py` (Pydantic models, an `evidence` quote per value, enums from config) with JSON-Schema export; an `LLMClient` interface with Gemini and Claude implementations (check current SDK docs for structured output first); a cache keyed by `desc_hash` + task + prompt version; a monthly token-cap guard; `prompts/extract_v1.md`; new `config/llm.yaml` and `config/skills.yaml`; fake-client unit tests; add `pydantic`. **Replace the stopgap `enrich/llm.py`.** It breaks several design rules: no evidence, a call cap not a token cap, a cache key without task/version, Gemini only, inline prompt, no workload/remote. There is no cached data to migrate. | 1.5–2 h |
| 2 | **Labelling CLI.** `jobwatch label` writing `eval/labels.jsonl`, plus stratified sampling (by ad language and family) and 3 postings held out as prompt examples. | 1 h |
| 3 | **Task 1 extraction + evidence check + `jobwatch eval`.** Adds workload and remote. Drops values whose quote isn't verbatim in the description. `eval/report.md`: rules only vs rules + LLM. Set up the CI regression on a frozen 30-posting subset with recorded responses (fails on a drop of more than 5 points). | 2 h + labels |
| 4 | **Task 2 (required/preferred requirements) and task 5 (skills normalisation)**, with list-field metrics (precision/recall) in the eval. | 1.5 h |
| 5 | **Task 3 profile fit + weekly shortlist.** Private output only (never the public README). | 1.5 h |
| 6 | **Tasks 6 and 7.** Code-built candidate pairs (same employer, ±60 days, title token Jaccard ≥ 0.3), then LLM judgement for duplicates and offshore twins. Completes spec milestone M5. | 2 h |
| 7 | **Task 4 vocabulary bridge.** Private per-posting mapping using the profile's bridge table. | 1 h |
| 8 | **Task 8 monthly digest + number-check script.** Needs spec milestone M4 (monthly trend report computed in pandas, matplotlib charts), which is not built yet. Do M4 here or earlier. | 2–3 h incl. M4 |
| 9 | **Provider comparison.** Gemini vs Claude on the full sample, per field and per ad language, plus cost per 100 postings; set the default provider. | 1 h + API cost |

Total: roughly 13–16 hours of build time, plus the owner's labelling.

## Open questions for the owner

- [ ] Which Claude model for the comparison run?
- [ ] Monthly token cap: the doc suggests 2,000,000. Keep it?
- [ ] Where do private outputs (shortlist, bridge, fit scores) go: a private repo, an Actions artifact, or an email?
- [ ] OK to add `pandas` and `matplotlib` (for M4 and the eval)?

## Smaller loose ends from build 1

- Novartis answered a Cloudflare 520 to the GitHub runner on the first CI run. 52x is now retried; check the
  next Monday run.
- 15 seed employers aren't covered (see the README's Sources table). Add their roles by hand in
  `config/manual.yaml` if wanted.
- Greenhouse, Lever and Ashby are tested on recorded responses only, since no seed employer uses them. Personio
  is tested only against a hand-written sample, because every live Personio board tried was empty.
  SmartRecruiters' robots.txt disallows the API.
- Keyword tuning: the families are strict to avoid noise; review the first few weekly READMEs for misses.
