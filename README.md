# Job Intel Agent

A local job-search assistant for senior Data Engineering, MLOps and ML Platform roles in India. It discovers employers, reads job postings, checks location eligibility, ranks evidence-backed matches and keeps application history between searches.

This version builds on [apram-b/job-intel-agent](https://github.com/apram-b/job-intel-agent), starting at `d112785`. It adds an OpenAI/Anthropic provider boundary and an optional authenticated public trial. It never submits applications or sends outreach.

## Start locally

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked
cp .env.example .env
# Set OPENAI_API_KEY or ANTHROPIC_API_KEY in .env, or enter a key in the UI.
uv run streamlit run app.py
```

Open http://127.0.0.1:8501. Local mode binds to loopback and refuses a non-loopback server configuration. A tunnel must **not** be pointed at local mode; use authenticated public mode for sharing.

The app asks for a text-based PDF (at most 5 MB and 10 pages). Edit your target roles, preferred/secondary cities and must-have skills. Supply verified Greenhouse or Lever board URLs for the most reliable results, or leave sources blank to discover supported employer boards. Aggregator search pages are excluded in code; automatic discovery does not spend model calls. Resume text goes to the chosen model provider only when a search starts. You can inspect the parsed profile afterwards; the CLI also accepts a manually corrected profile JSON.

Try a fictional offline example without a key:

```sh
uv run python main.py --demo --output data/demo-results.json --digest data/demo-digest.md
```

The demo uses `data/demo.db`, never a production database. It demonstrates persistence and repeat-run deduplication; its scores are recorded examples, not model evaluations.

## Run from the command line

```sh
uv run python main.py --resume resume.pdf --profile config/search-profile.json --provider openai --output data/results.json --digest data/digest.md
uv run python main.py --resume resume.pdf --location Gurgaon --provider anthropic
uv run python main.py --resume-json data/reviewed-resume.json --sources data/my-sources.json
uv run python main.py --history
uv run python main.py --job-id JOB_ID --status applied --notes "Applied on company website" --follow-up 2026-10-01
```

`config/sources.example.json` illustrates the source format; replace its placeholder before using it. A source is an employer name and an observed career URL. No board slugs or filtered URLs are invented by code. An optional read-only smoke-test source is supplied in `config/sources.smoke.json`; it is a connector test, not an employer endorsement.

Defaults prioritize Gurgaon/Gurugram and Delhi NCR, India-eligible remote roles, then Bangalore/Bengaluru, Hyderabad and Pune. A bare “Remote” does not prove India eligibility and goes to review. Salary and other absent facts remain unknown. The city rules are conservative heuristics, not a work-authorization determination.

Profiles, raw jobs, observations, scores, drafts and application statuses are saved in SQLite. Exported JSON contains the full run. Only qualified new/changed matches enter the Markdown digest. The CLI can be invoked by an external scheduler; no recurring job or notification delivery is installed automatically.

## What changed

- Automatic discovery searches Greenhouse and Lever postings and deduplicates employer boards. Search-engine results are validated even if the engine ignores its site filter.
- Generic extraction, available only for explicitly supplied local career sources, has a six-call allowance so it cannot consume the entire scoring budget.
- No deletion of jobs simply because a later search missed them. First/last seen dates and per-profile observations persist.
- IDs use board identity and source posting ID, with canonical URL identity for generic pages.
- Greenhouse reads full descriptions; Lever reads all pages up to a documented safety bound. Source errors remain distinct from empty boards.
- Actual search preferences reach scoring. Deterministic geography checks run before model scoring.
- Model output is validated. Every nonzero fit dimension must quote evidence from the posting. Invalid scores and unsupported claims fail validation rather than becoming a match.
- Scores are cached by job content, reviewed candidate profile, search preferences, model and scorer version. Applied/rejected/closed roles are excluded from new shortlists.
- Resume failures terminate dependent stages. Run outcomes are complete, partial or failed.
- Optional outreach is limited to qualified matches and remains a draft.
- Public mode offers three lifetime sponsored runs per verified identity, then bring-your-own-key. The allowance is not a browser counter.
- Dependencies are locked; regression and UI tests run without credentials.

## Models

OpenAI is the initial default, using the pinned `gpt-5-mini-2025-08-07` baseline through the Responses API with structured output. Anthropic remains available through a forced structured tool response using `claude-haiku-4-5-20251001`. Both responses undergo Pydantic validation.

Set `JOB_INTEL_PROVIDER`, `JOB_INTEL_OPENAI_MODEL`, or `JOB_INTEL_ANTHROPIC_MODEL` in `.env`. A model override must support the selected API and parameters; the OpenAI adapter currently sends `reasoning.effort=minimal`. No automatic provider fallback occurs, particularly when a visitor supplies a personal key.

See [model decision](docs/model-decision.md) for the rationale and the evaluation needed before claiming one provider is better.

## Structure

```text
app.py / main.py           UI and CLI
job_intel/core/
  models.py               Validated search/candidate/assessment schemas
  graph.py                Conditional LangGraph workflow
  pipeline.py             Shared runner and durable stage persistence
  matching.py             Location and role eligibility
  llm.py                  Provider adapters, isolated credentials, usage bounds
  access.py / public.py   Verified identity and atomic trial admission
job_intel/agents/          Parsing, discovery, collection, scoring, drafting
job_intel/sources/         Bounded HTTP reads and Greenhouse/Lever adapters
job_intel/db/store.py      SQLite history, scores and application state
config/                   Editable preference and source examples
 tests/                   Offline regression/integration/UI tests
```

The old `resumes`, `companies` and `job_listings` tables are left untouched if you point at an original database. They remain a legacy archive; they are not automatically imported into profile-scoped history.

## Public trial

Public mode is implemented but requires your OIDC credentials and persistent hosting configuration. See [public setup and abuse controls](docs/public-launch.md). Nothing has been deployed.

```sh
JOB_INTEL_MODE=public uv run streamlit run app.py --server.address 0.0.0.0
```

Do not run that command until authentication, HTTPS and persistent database storage are configured. Multiple independent replicas must not use independent SQLite files; use one persistent replica or migrate quota transactions to a shared database.

## Verification

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Tests mock external model and job-board calls. They cover failed searches preserving history, profile isolation, job identity, score validation/cache behavior, India location rules, pagination, redirect validation, provider-key isolation, trial concurrency/replay, and UI startup. See [validation notes](docs/validation.md) for what was and was not verified live.

## Remaining work

- Evaluate top-ten relevance on 50–100 user-labeled real postings, including experience and India-remote edge cases.
- Expand verified employer coverage; add Workday and other source-specific adapters. Generic fallback reads static HTML only and is explicitly partial. Dynamic JavaScript-only sites are unsupported in this version.
- Add salary/notice-period/remote-policy extraction with evidence, editable resume review in the UI, and better employment-interval calculation. Resume tenure is still model-extracted and needs user review.
- Add a durable background queue/checkpoints, scheduled delivery and actionable follow-up reminders. The current UI runs a bounded synchronous workflow.
- Before public launch, complete real OIDC and BYOK acceptance tests, establish retention/deletion procedures, test infrastructure limits and configure provider-level budgets.

License: MIT, as declared by the upstream README; see LICENSE.
