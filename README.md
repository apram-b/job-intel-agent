# Job Intel Agent

A multi-agent job intelligence pipeline built with [LangGraph](https://github.com/langchain-ai/langgraph) and Claude. Given a resume PDF and a target location, it automatically identifies relevant companies, scrapes their career pages, and surfaces matching job listings.

## How it works

The pipeline runs three agents in sequence:

```
Resume PDF → parse_resume → find_companies → scrape_careers → Job Listings
```

1. **`parse_resume`** — Extracts structured data from your resume PDF: name, current role, years of experience, skills, tech stack, inferred field, and seniority level.
2. **`find_companies`** — Uses the resume profile to search for companies in the target location that are likely hiring for your background.
3. **`scrape_careers`** — Visits each company's careers page and extracts relevant job listings, persisting them to a local SQLite database.

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

# Set your API key
echo "ANTHROPIC_API_KEY=your_key_here" > .env
```

## Usage

```bash
uv run python main.py --resume path/to/resume.pdf --location "London"
```

Example output:

```
=== Job Intel  |  resume='resume.pdf'  location='London' ===

=== Parsed Resume ===
  Name            : Jane Doe
  Current role    : MLOps Engineer
  Experience      : 4.0 year(s)
  Inferred field  : MLOps Engineering
  Seniority       : mid
  Skills          : Python, Docker, Kubernetes, ...
  Stack           : AWS, MLflow, Airflow, ...

=== 8 Companies Targeted ===
  • Monzo
  • Revolut
  ...

=== 5 Relevant Job Listing(s) ===

  [Monzo]  Senior MLOps Engineer
  Location    : London, UK
  URL         : https://monzo.com/careers/...
  Description : We're looking for an MLOps engineer to ...
```

Results are also saved to `job_intel.db` (SQLite) for querying later.

## Project structure

```
job_intel/
├── agents/
│   ├── resume_parser.py   # Parses resume PDF with Claude
│   ├── company_finder.py  # Finds target companies via web search
│   └── career_scraper.py  # Scrapes job listings from career pages
├── core/
│   ├── graph.py           # LangGraph pipeline definition
│   └── state.py           # Shared AgentState TypedDicts
└── db/
    └── store.py           # SQLite persistence layer
main.py                    # CLI entry point
```

## Tech stack

| Layer | Library |
|---|---|
| Agent orchestration | LangGraph |
| LLM | Claude (via `langchain-anthropic`) |
| PDF parsing | pdfplumber |
| Web scraping | Playwright |
| Web search | DDGS (DuckDuckGo) |
| Persistence | SQLite via `sqlite-utils` |

## License

MIT
