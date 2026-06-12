"""Agent: score and rank job listings by relevance to the candidate's profile."""
from __future__ import annotations

import asyncio
import logging
from typing import List, Tuple

from langchain_anthropic import ChatAnthropic

from job_intel.core.llm import extract_json_object, get_llm, invoke_text
from job_intel.core.state import AgentState, JobListing, RankedJobListing, ResumeData

_log = logging.getLogger(__name__)

_MAX_LLM = 3   # concurrent scoring calls
_TOP_N = 5     # how many top listings to surface


def _score_listing(
    listing: JobListing,
    resume: ResumeData,
    llm: ChatAnthropic,
) -> Tuple[int, str]:
    """Ask Claude to score a single listing against the candidate profile.

    Returns (score, score_reason) where score is 0–12.
    """
    skills_str = ", ".join(resume["skills"])
    stack_str = ", ".join(resume["stack"])

    prompt = f"""You are a career advisor scoring a job listing for a candidate.

CANDIDATE PROFILE:
- Current role    : {resume["current_role"]}
- Inferred field  : {resume["inferred_field"]}
- Seniority level : {resume["seniority_level"]}
- Skills          : {skills_str}
- Stack           : {stack_str}
- Target location : (see listing)

JOB LISTING:
- Company     : {listing["company"]}
- Title       : {listing["title"]}
- Location    : {listing["location"]}
- Description : {listing["description"]}

Score this listing on four dimensions (0–3 each, total 0–12):

1. title_match   : How closely does the job title align with the candidate's current role / inferred field?
                   3=direct match, 2=very related, 1=somewhat related, 0=unrelated
2. skill_overlap : How many of the candidate's skills appear in the description?
                   3=strong overlap (5+), 2=moderate (2-4), 1=minor (1), 0=none
3. location_fit  : Location suitability.
                   3=exact city match, 2=Remote/Hybrid/Anywhere, 1=other India city, 0=no match
4. seniority_fit : Does the required seniority match?
                   3=exact match, 2=one level off, 1=two levels off, 0=completely mismatched

Output ONLY a JSON object — no prose:
{{
  "title_match": <0-3>,
  "skill_overlap": <0-3>,
  "location_fit": <0-3>,
  "seniority_fit": <0-3>,
  "reason": "<one concise sentence explaining the total score>"
}}"""

    try:
        data = extract_json_object(invoke_text(llm, prompt))
        if data is None:
            return 0, "Could not parse score"
        score = (
            int(data.get("title_match", 0))
            + int(data.get("skill_overlap", 0))
            + int(data.get("location_fit", 0))
            + int(data.get("seniority_fit", 0))
        )
        score = max(0, min(12, score))
        reason = str(data.get("reason", "")).strip()
        return score, reason
    except Exception as exc:
        _log.debug("Scoring failed for %s @ %s: %s", listing["title"], listing["company"], exc)
        return 0, f"Scoring error: {exc}"


async def _score_all(
    listings: List[JobListing],
    resume: ResumeData,
) -> List[RankedJobListing]:
    llm = get_llm()
    sem = asyncio.Semaphore(_MAX_LLM)

    async def _score_one(listing: JobListing) -> RankedJobListing:
        async with sem:
            score, reason = await asyncio.to_thread(_score_listing, listing, resume, llm)
        return RankedJobListing(**listing, score=score, score_reason=reason)

    ranked = await asyncio.gather(*[_score_one(l) for l in listings])
    return sorted(ranked, key=lambda r: r["score"], reverse=True)


def score_jobs_node(state: AgentState) -> dict:
    """LangGraph node: score every job listing and return a ranked shortlist."""
    listings: List[JobListing] = state.get("job_listings", [])
    resume: ResumeData = state.get("resume_data", {})

    if not listings:
        _log.info("No listings to score.")
        return {"ranked_listings": []}

    _log.info("Scoring %d listing(s)...", len(listings))
    ranked = asyncio.run(_score_all(listings, resume))
    top = ranked[:_TOP_N]
    _log.info("Top score: %d/12  (%s @ %s)", top[0]["score"], top[0]["title"], top[0]["company"])

    return {"ranked_listings": top}
