# Jobs Monitor — LLM Layer Instructions for Claude Code

Nov 3, 2026 · @Tiago

## Brief

Build the LLM enrichment layer (`src/jobwatch/enrich/llm.py` and friends) of the Swiss AI Validation Jobs Monitor. It turns each job posting's free text into structured, verifiable labels, and comes with an evaluation harness that measures how accurate those labels are.

- **Read first:** the main spec, "Swiss AI Validation Jobs Monitor — Specification" (repo layout, data model, pipeline). This doc only adds the LLM layer and its evaluation.
- **Input:** one normalized posting record (title, employer, location, description in EN/DE/FR), plus the fields the rule-based pass has already filled.
- **Output:** a JSON object per posting (schema below), cached by `desc_hash` and merged into `data/postings.csv`.
- **Who uses it:** the owner. The labels feed a weekly shortlist and a monthly trend report. Accuracy matters more than coverage: an empty field is better than a wrong one.

## Design rules

The LLM labels, matches and summarises; deterministic code does all counting. Follow these rules in every task:

1. **Rules first.** Run the regex pass before the LLM. The LLM fills only the fields the rules left empty, and is never asked to overwrite a rule-based value.
2. **Evidence for every label.** Each extracted value carries `evidence`: the exact quote from the posting it came from. A value without a quote that occurs verbatim in the description is discarded (set to null).
3. **Null over guess.** If the posting doesn't say, return null. The prompt must say this explicitly.
4. **Fixed vocabularies.** Seniority, contract type, skills and language levels come from enums defined in config, never free text.
5. **Schema-validated output.** Parse every response with Pydantic; one retry on a validation failure, then store nulls and log the posting id.
6. **Cache once.** The cache key is `desc_hash` + task name + prompt version. Bumping the prompt version invalidates only that task.
7. **Deterministic settings.** Temperature 0, pinned model id, prompt templates versioned in `prompts/`.
8. **Budget cap.** A monthly token cap in `config/llm.yaml`. On reaching it, skip the LLM pass and say so in the run summary.
9. **Provider-agnostic.** One `LLMClient` interface with Gemini and Claude implementations, selected in config.
10. **No numbers from the LLM.** Counts, shares and trends in reports are computed in pandas. The digest task (task 8) may only restate numbers passed into it.

## The eight tasks

Tasks 1, 2 and 5 make the trend data reliable and are built first; task 3 is the weekly time-saver. Each task is a separate prompt and a separate cache entry.

| # | Task | Output | Acceptance check |
| --- | --- | --- | --- |
| 1 | **Field extraction**: fill what the rules missed | `years_required`, `languages_required` (lang, level, required/preferred), `contract_type`, `workload`, `seniority`, `remote` | Each field ≥ 90% accuracy on the labelled sample; every value has verbatim evidence |
| 2 | **Required vs preferred**: split the requirements list | `requirements[]`: {text, category, strength: required / preferred} | Strength agrees with labels on ≥ 85% of requirements |
| 3 | **Profile fit**: score against `config/profile.yaml` | `fit_score` 0–5, `strengths[]`, `gaps[]`, `blockers[]` (hard constraint broken, e.g. fixed-term, German C1 required) | Blockers never missed on the sample; owner agrees with the score ±1 on ≥ 80% |
| 4 | **Vocabulary bridge**: map requirements to the owner's experience | `mappings[]`: {requirement, owner\_experience, owner\_term} using the bridge table in profile.yaml | Spot-checked by the owner; no invented experience (each mapping cites a profile entry) |
| 5 | **Skill normalisation**: map free text to the fixed skill list | `key_skills[]` from `config/skills.yaml` | Precision ≥ 90%; synonyms ("GenAI", "foundation models") map to one tag |
| 6 | **Duplicate and repost detection**: same job from several agencies, or reposted | `duplicate_of`: posting id or null, `confidence` | Run only on candidate pairs pre-filtered by employer/client, region and title similarity; precision ≥ 90% |
| 7 | **Offshore twin match**: same function abroad at the same employer | `offshore_twin_of`: posting id or null, `rationale` | Run only on pairs pre-filtered by employer and date window; owner-verified sample |
| 8 | **Monthly digest**: plain-language summary | `reports/YYYY-MM-digest.md`, 150–250 words | Every number in the text appears in the report tables passed in (checked by a script) |

**Tasks 6 and 7 never compare every pair.** Code builds the candidate pairs (same employer, ±60 days, title token Jaccard ≥ 0.3), and the LLM only judges those.

## Schema and profile

Define the output as Pydantic models in `src/jobwatch/enrich/schema.py` and export the JSON Schema for the provider's structured-output mode. The core of task 1:

```json
{
  "years_required": {"value": 5, "evidence": "mindestens 5 Jahre Erfahrung"},
  "languages_required": [
    {"lang": "de", "level": "C1", "strength": "required", "evidence": "sehr gute Deutschkenntnisse (C1)"},
    {"lang": "fr", "level": null, "strength": "preferred", "evidence": "French is a plus"}
  ],
  "contract_type": {"value": "fixed-term", "evidence": "12-month assignment"},
  "seniority": {"value": "senior", "evidence": "Senior Model Risk Specialist"},
  "workload": {"value": "80-100%", "evidence": "80-100%"},
  "remote": {"value": null, "evidence": null}
}
```

**`config/profile.yaml`** is used by tasks 3 and 4, and is filled in by the owner, not by Claude Code. It holds a
short `summary`, a `skills` list, `languages` with levels, `hard_constraints` (contract type, salary floor, regions,
maximum German level required) and a `bridge` table mapping employers' terms to the owner's experience. The
contents are private and are not reproduced here.

Keep the profile out of public output: the repo can stay public while `profile.yaml` lives in an encrypted secret or a private submodule.

## Prompting and providers

One prompt file per task in `prompts/{task}_v{n}.md`, each with a fixed structure.

- **Role and task:** one paragraph stating what to extract and why.
- **Rules:** quote evidence verbatim; null if not stated; use only the listed enum values; postings may be in German, French or English, and evidence stays in the original language.
- **Enums:** pasted in from config at render time.
- **Two or three worked examples:** a German, a French and an English posting, with the expected JSON, taken from the labelled sample (and excluded from the evaluation).
- **The posting:** title, employer, location, then the description, truncated to about 6,000 characters (keep the requirements section if it has to be cut).

**`config/llm.yaml`**

```yaml
provider: gemini            # gemini | claude
model: <pinned model id>    # small, cheap model first
temperature: 0
max_output_tokens: 1200
monthly_token_cap: 2000000
prompt_versions: {extract: 1, requirements: 1, fit: 1, bridge: 1, skills: 1, dedupe: 1, offshore: 1, digest: 1}
```

- **Gemini:** use the Gemini API via Google AI Studio (free tier first) with JSON output constrained by the exported schema; the key is the `GEMINI_API_KEY` secret.
- **Claude:** use the Anthropic API with structured output against the same schema; the key is the `ANTHROPIC_API_KEY` secret.
- Check the current SDK documentation for each provider's structured-output syntax before coding; don't rely on memory.
- Rate limits: sequential calls with backoff on 429s. Volume is a few dozen new postings a week, so concurrency is unnecessary.

## Evaluation harness

The harness is the portfolio piece: it shows each label's accuracy, with and without the LLM, per provider.

- **Labelled sample:** 100 postings in `eval/labels.jsonl`, hand-labelled by the owner with a small labelling CLI (`jobwatch label`) that shows one posting at a time and writes the schema fields. Stratify the sample: about 40 EN, 35 DE and 25 FR, across all role families. Hold out 3 postings as prompt examples.
- **Metrics, per field:** exact-match accuracy for categorical fields; absolute error for `years_required`; precision and recall for list fields (languages, skills, requirements); the evidence-validity rate (quotes found verbatim); and the null rate.
- **Agreement:** the owner re-labels 20 postings a week later. Report Cohen's kappa so the label noise ceiling is known.
- **Comparisons:** rules only, rules + Gemini, rules + Claude. Report per field and per ad language, plus cost per 100 postings.
- **Output:** `eval/report.md` with one table per comparison, regenerated by `jobwatch eval`.
- **CI:** a regression test on a frozen 30-posting subset with recorded LLM responses (no live API in CI). It fails if any field's accuracy drops more than 5 points from the stored baseline.

## Build order

Hand these to Claude Code one at a time, after milestone 3 of the main spec (history and rules enrichment) works. Each step ends with tests passing and a short summary from Claude Code.

1. **Scaffold:** Pydantic schemas, enums from config, the `LLMClient` interface with Gemini and Claude implementations, the cache keyed by `desc_hash` + task + prompt version, the token-cap guard. Unit tests with a fake client.
2. **Labelling CLI:** `jobwatch label` writing `eval/labels.jsonl`. Then the owner labels 100 postings; this is the only manual step.
3. **Task 1 (extraction) + evidence check + `jobwatch eval`:** first numbers for rules only versus rules + LLM.
4. **Tasks 2 and 5 (requirements, skills):** extend the eval to list metrics.
5. **Task 3 (profile fit):** add a "This week's shortlist" section to the README (top postings by fit, with gaps and blockers). Keep it out of the public README if the repo is public; write it to a private artifact or an emailed digest instead.
6. **Tasks 6 and 7 (duplicates, offshore twins):** code-built candidate pairs, then LLM judgement; add the flags to the report.
7. **Task 4 (vocabulary bridge):** per-posting mapping file in a private output.
8. **Task 8 (monthly digest):** plus the script that checks every number in the digest against the report tables.
9. **Provider comparison run:** Gemini versus Claude on the full sample; set the default provider in config from the results.

**Opening prompt for Claude Code:** "Read SPEC.md and LLM\_LAYER.md. Confirm the plan for step 1, list anything ambiguous, then implement step 1 only."

Save this doc and the main spec into the repo as `LLM_LAYER.md` and `SPEC.md` (export as Markdown), so Claude Code reads them from the working tree.
