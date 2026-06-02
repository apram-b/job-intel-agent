"""Agent: find top 15 companies for a field using web search + a single Claude call."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import List

from ddgs import DDGS
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from job_intel.core.state import AgentState, Company
from job_intel.db.store import save_companies

_log = logging.getLogger(__name__)

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)
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
    text = re.sub(r"```(?:json)?", "", text).strip()
    match = _JSON_ARRAY_RE.search(text)
    if not match:
        return []
    try:
        items = json.loads(match.group())
    except json.JSONDecodeError:
        return []

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


def find_companies_node(state: AgentState) -> dict:
    """LangGraph node: discover top 15 companies and their career-page URLs."""
    field = state["resume_data"]["inferred_field"]
    location = state["location"]

    _log.info("Searching for '%s' companies in '%s'...", field, location)
    search_results = _gather_search_results(field, location)

    llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)

    prompt = f"""You are a job-market researcher helping a {field} professional find companies that actively hire in {location} or fully Remote.

Below are web search results. Use them to identify the 15 BEST companies to target.

STRICT RULES:
- Prioritise companies with offices or engineering teams in {location} or that hire remote employees in India.
- Include a healthy mix: 5 established tech companies, 5 high-growth startups, 5 mid-size product companies.
- EXCLUDE companies that are well-known to not hire {field} roles in India or that primarily hire only in the US/EU with no remote option (e.g. Figma, Stripe, Uber Eats, Lyft).
- Prefer companies actively hiring right now based on the search snippets.
- For each company, provide its careers/jobs page URL. If not directly shown, infer it (e.g. company.com/careers).

SEARCH RESULTS:
{search_results}

Output ONLY a JSON array with exactly 15 entries — no prose, no markdown fences:
[
  {{"name": "Company Name", "career_url": "https://company.com/careers"}},
  ...
]"""

    try:
        msg = llm.invoke([HumanMessage(content=prompt)])
        raw = msg.content if isinstance(msg.content, str) else ""
        companies = _parse_companies(raw)
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
