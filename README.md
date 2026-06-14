# Job Intel Agent

A multi-agent job intelligence pipeline built with [LangGraph](https://github.com/langchain-ai/langgraph) and Claude. Given a resume PDF and a target location, it identifies relevant companies, scrapes their career pages, scores each listing against your profile, and drafts personalised cold-outreach messages for the best matches.

Runs from the command line or as a Streamlit web app.

## How it works

The pipeline runs five agents in sequence, orchestrated as a LangGraph state machine:

```
Resume PDF
   │
   ▼
parse_resume ──► find_companies ──► scrape_careers ──► score_jobs ──► draft_outreach
   │                  │                   │                 │               │
 profile          target list        job listings     ranked top 5     outreach drafts
```

1. **`parse_resume`** — Extracts structured data from your resume PDF: name, current role, years of experience, skills, tech stack, inferred field, and seniority level.
2. **`find_companies`** — Uses the resume profile to search (DuckDuckGo) for companies in the target location likely to be hiring for your background.
3. **`scrape_careers`** — Visits each company's careers page with Playwright, extracts job listings, and persists them to a local SQLite database.
4. **`score_jobs`** — Asks Claude to score every listing on four dimensions — **title match, skill overlap, location fit, and seniority fit** (0–3 each, 0–12 total) — then returns a ranked **top-5** shortlist with a one-line rationale per listing. Scoring runs concurrently across listings.
5. **`draft_outreach`** — Generates a concise (~150-word) personalised cold-outreach message for each of the **top 3** ranked listings, written to directly reference the role and the candidate's matching skills.

## Model strategy

The pipeline uses two Claude models, chosen per task and configurable via environment variables (so a model upgrade never touches agent code):

| Role | Default model | Used for |
| ---- | ------------- | -------- |
| `fast` | Claude Haiku | Resume extraction, company search, scoring |
| `writer` | Claude Sonnet | Outreach prose generation |

Override with `JOB_INTEL_FAST_MODEL` and `JOB_INTEL_WRITER_MODEL` in your `.env`.

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- An Anthropic API key

## Setup

```bash
# Clone the repo
git clone https://github.com/apram-b/job-intel-agent.git
cd job-intel-agent

# Install dependencies
uv sync

# Install Playwright browsers (needed for career-page scraping)
uv run playwright install chromium

# Set your API key
echo "ANTHROPIC_API_KEY=your_key_here" > .env
```

## Usage

### CLI

```bash
uv run python main.py --resume path/to/resume.pdf --location "Bangalore"

# Optionally save results to JSON
uv run python main.py --resume resume.pdf --location "Bangalore" --output results.json
```

Example output:

```
=== Job Intel  |  resume='resume.pdf'  location='Bangalore' ===

=== Parsed Resume ===
  Name            : Jane Doe
  Current role    : MLOps Engineer
  Experience      : 4.0 year(s)
  Inferred field  : MLOps Engineering
  Seniority       : mid
  Skills          : Python, Docker, Kubernetes, ...
  Stack           : AWS, MLflow, Airflow, ...

=== 8 Companies Targeted ===
  • Company A
  • Company B
  ...

=== Top 5 Ranked Listings ===
  [11/12]  Company A  —  Senior MLOps Engineer  (Bangalore)
           Strong title and stack overlap; one level up on seniority.
  [9/12]   Company B  —  ML Platform Engineer   (Remote)
  ...

=== Outreach Drafts (top 3) ===
  → Company A — Senior MLOps Engineer
    "I noticed your team is scaling its ML platform..."
  ...
```

Results are also saved to `job_intel.db` (SQLite) for querying later.

### Streamlit app

```bash
uv run streamlit run app.py
```

Upload a resume, enter a location, and watch the five stages run live. (The hosted build includes a per-session run cap for public visitors.)

## Project structure

```
job_intel/
├── agents/
│   ├── resume_parser.py     # Parses resume PDF with Claude
│   ├── company_finder.py    # Finds target companies via web search
│   ├── career_scraper.py    # Scrapes job listings from career pages
│   ├── job_scorer.py        # Scores & ranks listings (4 dimensions)
│   └── outreach_drafter.py  # Drafts cold-outreach messages
├── core/
│   ├── graph.py             # LangGraph pipeline definition
│   ├── state.py             # Shared AgentState TypedDicts
│   └── llm.py               # Model selection & JSON extraction utils
└── db/
    └── store.py             # SQLite persistence layer
app.py                       # Streamlit web app
main.py                      # CLI entry point
```

## Tech stack

| Layer               | Library                            |
| ------------------- | ---------------------------------- |
| Agent orchestration | LangGraph                          |
| LLM                 | Claude — Haiku + Sonnet (via `langchain-anthropic`) |
| Web UI              | Streamlit                          |
| PDF parsing         | pdfplumber                         |
| Web scraping        | Playwright                         |
| Web search          | DDGS (DuckDuckGo)                  |
| Persistence         | SQLite via `sqlite-utils`          |

## License

MIT
