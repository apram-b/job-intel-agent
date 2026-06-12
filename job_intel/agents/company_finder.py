"""Agent: find top 15 companies for a field using web search + a single Claude call."""
from __future__ import annotations

import logging
import time
from typing import List

from ddgs import DDGS

from job_intel.core.llm import extract_json_array, get_llm, invoke_text
from job_intel.core.state import AgentState, Company
from job_intel.db.store import save_companies

_log = logging.getLogger(__name__)

_SEARCH_DELAY = 0.6   # seconds between DuckDuckGo requests


def _search(query: str, n: int = 8) -> List[dict]:
    """Return up to n DuckDuckGo results as {title, url, snippet} dicts."""
    try:
        time.sleep(_SEARCH_DELAY)
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=n))
        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in raw
        ]
    except Exception as exc:
        _log.warning("DuckDuckGo search failed: %s", exc)
        return []


def _gather_search_results(field: str, location: str) -> str:
    """Run several targeted searches and return a single concatenated string."""
    queries = [
        f"top {field} companies hiring {location} 2025",
        f"best {field} employers {location} remote 2025",
        f"{field} startups {location} hiring engineers 2025",
        f"leading {field} companies careers India remote jobs",
    ]
    sections = []
    for q in queries:
        results = _search(q)
        block = f"Query: {q}\n" + "\n".join(
            f"  - {r.get('title','')} | {r.get('url','')} | {r.get('snippet','')[:200]}"
            for r in results
        )
        sections.append(block)
    return "\n\n".join(sections)


def _parse_companies(text: str) -> List[Company]:
    """Extract a JSON array of {name, career_url} from arbitrary LLM text."""
    items = extract_json_array(text) or []

    companies: List[Company] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("company") or ""
        url = (
            item.get("career_url")
            or item.get("careers_url")
            or item.get("url")
            or ""
        )
        if name and url:
            companies.append(Company(name=str(name).strip(), career_url=str(url).strip()))
    return companies


def _build_search_keywords(field: str, resume_data: dict) -> str:
    """Build a compact keyword string from the inferred field and top skills."""
    skills = resume_data.get("skills", [])
    # Pick a handful of the most role-defining skills
    role_skills = [s for s in skills if any(
        kw in s.lower() for kw in ("mlops", "ml", "data", "pipeline", "model", "llm", "ai")
    )][:3]
    parts = [field] + role_skills
    return " ".join(parts)


def find_companies_node(state: AgentState) -> dict:
    """LangGraph node: discover top 15 companies and their career-page URLs."""
    resume_data = state["resume_data"]
    field = resume_data["inferred_field"]
    location = state["location"]
    search_keywords = _build_search_keywords(field, resume_data)

    _log.info("Searching for '%s' companies in '%s'...", field, location)
    search_results = _gather_search_results(field, location)

    llm = get_llm()

    prompt = f"""You are a job-market researcher helping a {field} professional find companies that actively hire in {location} or fully Remote.

Below are web search results. Use them to identify the 15 BEST companies to target.

STRICT RULES:
- Prioritise companies with offices or engineering teams in {location} or that hire remote employees in India.
- Include a healthy mix: 5 established tech companies, 5 high-growth startups, 5 mid-size product companies.
- EXCLUDE companies that are well-known to not hire {field} roles in India or that primarily hire only in the US/EU with no remote option (e.g. Figma, Stripe, Uber Eats, Lyft).
- Prefer companies actively hiring right now based on the search snippets.

CAREER URL RULES (critical):
- Do NOT just link to the careers homepage. Provide a URL that goes DIRECTLY to filtered job search results.
- Include the search keywords "{search_keywords}" as query parameters wherever the ATS supports it.
- Use these known URL patterns as a reference:
    Google        → https://careers.google.com/jobs/results/?q=MLOps+Machine+Learning
    Microsoft     → https://jobs.microsoft.com/en-us/search?q=MLOps
    Amazon / AWS  → https://www.amazon.jobs/en/search?base_query=MLOps
    Greenhouse    → https://boards.greenhouse.io/{{company}}/jobs?q=MLOps
    Lever         → https://jobs.lever.co/{{company}}?q=MLOps
    Workday       → https://{{company}}.wd3.myworkdayjobs.com/en-US/{{company}}_Careers?q=MLOps
    Generic       → https://company.com/careers?q=MLOps  or  /jobs?search=MLOps
- If a company's ATS does not support URL-based search, link to the most relevant sub-page (e.g. /careers/engineering or /careers/data).

SEARCH RESULTS:
{search_results}

Output ONLY a JSON array with exactly 15 entries — no prose, no markdown fences:
[
  {{"name": "Company Name", "career_url": "https://careers.company.com/jobs?q=MLOps"}},
  ...
]"""

    try:
        companies = _parse_companies(invoke_text(llm, prompt))
    except Exception as exc:
        return {"companies": [], "errors": [f"company_finder error: {exc}"]}

    if not companies:
        return {
            "companies": [],
            "errors": ["company_finder: could not parse a company list from the LLM response."],
        }

    companies = companies[:15]
    _log.info("Found %d companies", len(companies))

    try:
        save_companies(companies)
    except Exception as exc:
        _log.warning("Failed to persist companies: %s", exc)

    return {"companies": companies}
