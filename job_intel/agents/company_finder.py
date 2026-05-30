"""Agent 1a: find top 15 companies for a field using web search + a single Claude call."""
from __future__ import annotations

import json
import re
import time
from typing import List

from ddgs import DDGS
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from job_intel.core.state import AgentState, Company

_JSON_ARRAY_RE = re.compile(r"\[.*?\]", re.DOTALL)
_SEARCH_DELAY = 0.6   # seconds between DuckDuckGo requests


def _search(query: str, n: int = 6) -> List[dict]:
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
        return [{"error": str(exc)}]


def _gather_search_results(field: str, location: str) -> str:
    """Run several targeted searches and return a single concatenated string."""
    queries = [
        f"top {field} companies hiring 2025",
        f"best {field} employers {location}",
        f"{field} startups hiring India remote 2025",
        f"leading {field} companies careers jobs",
    ]
    sections = []
    for q in queries:
        results = _search(q)
        block = f"Query: {q}\n" + "\n".join(
            f"  - {r.get('title','')} | {r.get('url','')} | {r.get('snippet','')[:120]}"
            for r in results
        )
        sections.append(block)
    return "\n\n".join(sections)


def _parse_companies(text: str) -> List[Company]:
    """Extract a JSON array of {name, career_url} from arbitrary text."""
    # Strip markdown code fences if present
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

    print(f"[company_finder] searching for '{field}' companies in '{location}'...")
    search_results = _gather_search_results(field, location)

    llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)

    prompt = f"""You are a job-market researcher helping a {field} professional find companies hiring in {location} or Remote.

Below are web search results about top companies and employers in this space.
Use them to identify the 15 best companies to target — a mix of well-known names and fast-growing startups.
For each company you must also provide its careers/jobs page URL (infer it if not shown directly, e.g. company.com/careers).

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
    print(f"[company_finder] found {len(companies)} companies")
    for c in companies:
        print(f"  • {c['name']}  →  {c['career_url']}")

    return {"companies": companies}
