"""Discover supported employer boards, enforcing source policy in code."""

from __future__ import annotations
import re
from job_intel.core.models import SearchProfile
from job_intel.sources.ats import board
from job_intel.sources.web import canonical_url


def _search(query):
    from ddgs import DDGS

    with DDGS(timeout=15) as search:
        return list(search.text(query, max_results=8))


def find_companies_node(state):
    if state.get("companies"):
        return {"companies": state["companies"]}
    profile = SearchProfile.model_validate(state["profile"])
    companies, seen, errors = [], set(), []
    for role in profile.target_roles[:4]:
        for domain in ("job-boards.greenhouse.io", "jobs.lever.co"):
            try:
                results = _search(f'site:{domain} "{role}" India')
            except Exception:
                errors.append(f"Discovery search failed for {role} on {domain}")
                continue
            for result in results:
                try:
                    url = canonical_url(result.get("href", ""))
                    spec = board(url)
                except (ValueError, TypeError):
                    continue
                # Search engines can ignore site filters. Never rely on the query alone.
                if spec is None or spec in seen:
                    continue
                seen.add(spec)
                title = result.get("title", "")
                match = re.search(r"(?:Jobs at | at )(.+?)(?:\s+[|·]\s+|$)", title)
                name = match.group(1).strip() if match else spec[1]
                companies.append({"name": name, "career_url": url})
                if len(companies) == 15:
                    return {"companies": companies, "errors": errors}
    if not companies:
        errors.append(
            "No supported employer boards found. Add a Greenhouse or Lever career URL in Career sources; aggregator search pages are not supported."
        )
    return {"companies": companies, "errors": errors}
