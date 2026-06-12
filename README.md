# Job Intel Agent

A multi-agent job intelligence pipeline built with [LangGraph](https://github.com/langchain-ai/langgraph) and Claude. Given a resume PDF and a target location, it automatically identifies relevant companies, scrapes their career pages, scores and ranks matching job listings, and drafts personalised cold outreach messages. Comes with both a CLI and a Streamlit web UI.

## How it works

The pipeline runs five agents in sequence:

```
Resume PDF → parse_resume → find_companies → scrape_careers → score_jobs → draft_outreach
```

1. **`parse_resume`** — Extracts structured data from your resume PDF: name, current role, years of experience, skills, tech stack, inferred field, and seniority level.
2. **`find_companies`** — Uses the resume profile to search for companies in the target location that are actively hiring for your background. Prioritises local/remote-friendly employers and filters out companies known not to hire in the target region.
3. **`scrape_careers`** — Visits each company's careers page in parallel with Playwright, extracts job listings (with real listing URLs, locations, and descriptions), and persists them to SQLite. Falls back to a plain HTTP request for sites that block headless browsers.
4. **`score_jobs`** — Scores every listing against your profile on four dimensions (title match, skill overlap, location fit, seniority fit) and returns a ranked shortlist of the top 5.
5. **`draft_outreach`** — Writes a tailored ~150-word cold outreach message for each of the top 3 listings using Claude Sonnet.

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- An Anthropic API key

## Setup

```bash
# Clone the repo
git clone https://github.com/your-username/job-intel-agent.git
cd job-intel-agent

# Install dependencies
uv sync

# Install Playwright browsers (needed for career page scraping)
uv run playwright install chromium

# Copy the env template and add your API key
cp .env.example .env
# then edit .env and set ANTHROPIC_API_KEY=your_key_here
```

## Usage

### Web UI

```bash
uv run streamlit run app.py
```

Opens a browser UI at `http://localhost:8501` — upload your resume PDF, enter a target location, and watch the pipeline run stage-by-stage. Results render as ranked job cards with copyable outreach drafts.

### CLI

```bash
uv run python main.py --resume path/to/resume.pdf --location "Bangalore"
```

Optionally save the full results to a JSON file:

```bash
uv run python main.py --resume resume.pdf --location "Bangalore" --output results.json
```

### Example output

```
────────────── Job Intel | resume='resume.pdf' location='Bangalore' ──────────────

──────────────────────────── Parsed Resume ────────────────────────────
  Name            : Jane Doe
  Current role    : MLOps Engineer
  Experience      : 4.0 year(s)
  Inferred field  : MLOps Engineering
  Seniority       : mid
  Skills          : Python, Docker, Kubernetes, MLflow, ...
  Stack           : AWS, Airflow, Terraform, ...

──────────────────────── 10 Companies Targeted ────────────────────────
  • Flipkart  →  https://flipkart.com/careers
  • Swiggy    →  https://careers.swiggy.com
  ...

──────────────────────── Top Ranked Job Listing(s) ────────────────────

  [Flipkart]  MLOps Engineer  Score: 10/12
  Location    : Bangalore, India
  URL         : https://flipkart.com/careers/job/12345
  Description : Build and maintain ML infrastructure at scale ...
  Why         : Strong title and skill match; exact location; seniority aligns.

──────────────────────────── Outreach Draft(s) ────────────────────────

  [Flipkart]  MLOps Engineer

    I've spent the last 4 years building ML infrastructure ...
    ...
```

Results are also saved to `job_intel.db` (SQLite) for querying later.

## Project structure

```
job_intel/
├── agents/
│   ├── resume_parser.py    # Parses resume PDF with Claude
│   ├── company_finder.py   # Finds target companies via web search
│   ├── career_scraper.py   # Scrapes job listings from career pages (Playwright + httpx fallback)
│   ├── job_scorer.py       # Scores and ranks listings against the candidate profile
│   └── outreach_drafter.py # Drafts personalised cold outreach messages
├── core/
│   ├── graph.py            # LangGraph pipeline definition
│   └── state.py            # Shared AgentState TypedDicts
└── db/
    └── store.py            # SQLite persistence (resumes, companies, job listings)
main.py                     # CLI entry point
app.py                      # Streamlit web UI
.env.example                # Environment variable template
```

## Tech stack

| Layer | Library |
|---|---|
| Agent orchestration | LangGraph |
| LLM | Claude Haiku / Sonnet (via `langchain-anthropic`) |
| PDF parsing | pdfplumber |
| Web scraping | Playwright + httpx |
| Web search | DDGS (DuckDuckGo) |
| Persistence | SQLite via `sqlite-utils` |
| Terminal UI | Rich |
| Web UI | Streamlit |

## License

MIT
