"""Agent: draft personalised cold outreach messages for the top-ranked job listings."""
from __future__ import annotations

import asyncio
import logging
from typing import List

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from job_intel.core.state import AgentState, OutreachDraft, RankedJobListing, ResumeData

_log = logging.getLogger(__name__)

_DRAFT_FOR_TOP_N = 3   # number of listings to draft outreach for


def _draft_message(
    listing: RankedJobListing,
    resume: ResumeData,
    llm: ChatAnthropic,
) -> str:
    """Ask Claude Sonnet to write a ~150-word cold outreach for a single listing."""
    skills_str = ", ".join(resume["skills"][:8])   # top skills only to keep prompt tight
    stack_str = ", ".join(resume["stack"][:6])

    prompt = f"""Write a concise (~150 words), professional cold outreach message from a job candidate to a hiring manager.

CANDIDATE:
- Name            : {resume["name"]}
- Current role    : {resume["current_role"]}
- Experience      : {resume["years_experience"]} year(s) in {resume["inferred_field"]}
- Key skills      : {skills_str}
- Stack           : {stack_str}

TARGET ROLE:
- Company     : {listing["company"]}
- Title       : {listing["title"]}
- Location    : {listing["location"]}
- Description : {listing["description"]}

TONE & FORMAT:
- Confident but not arrogant; specific rather than generic
- Mention 1-2 relevant skills that directly match the role
- Express genuine interest in the company
- End with a clear, low-pressure call to action (e.g. a short call or coffee chat)
- Do NOT use subject lines, greetings like "Dear Sir/Madam", or sign-offs — body text only
- Exactly 3 short paragraphs

Output only the message text, no extra commentary."""

    try:
        msg = llm.invoke([HumanMessage(content=prompt)])
        return (msg.content if isinstance(msg.content, str) else "").strip()
    except Exception as exc:
        _log.warning("Outreach draft failed for %s @ %s: %s", listing["title"], listing["company"], exc)
        return ""


async def _draft_all(
    listings: List[RankedJobListing],
    resume: ResumeData,
) -> List[OutreachDraft]:
    # Use Sonnet for higher-quality writing
    llm = ChatAnthropic(model="claude-sonnet-4-5", temperature=0.4)

    async def _draft_one(listing: RankedJobListing) -> OutreachDraft:
        message = await asyncio.to_thread(_draft_message, listing, resume, llm)
        return OutreachDraft(
            company=listing["company"],
            title=listing["title"],
            message=message,
        )

    drafts = await asyncio.gather(*[_draft_one(l) for l in listings])
    return [d for d in drafts if d["message"]]  # drop any that failed


def draft_outreach_node(state: AgentState) -> dict:
    """LangGraph node: generate cold outreach drafts for the top-ranked listings."""
    ranked: List[RankedJobListing] = state.get("ranked_listings", [])
    resume: ResumeData = state.get("resume_data", {})

    targets = ranked[:_DRAFT_FOR_TOP_N]
    if not targets:
        _log.info("No ranked listings to draft outreach for.")
        return {"outreach_drafts": []}

    _log.info("Drafting outreach for %d listing(s)...", len(targets))
    drafts = asyncio.run(_draft_all(targets, resume))
    _log.info("Drafted %d message(s)", len(drafts))

    return {"outreach_drafts": drafts}
