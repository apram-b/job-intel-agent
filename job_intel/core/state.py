"""Shared graph state; boundary models validate external inputs."""

from __future__ import annotations
import operator
from typing import Annotated, TypedDict

ResumeData = dict
Company = dict
JobListing = dict
RankedJobListing = dict
OutreachDraft = dict


class AgentState(TypedDict, total=False):
    resume_path: str
    location: str
    profile: dict
    resume_data: dict
    run_id: str
    companies: list[dict]
    job_listings: list[dict]
    scored_listings: list[dict]
    ranked_listings: list[dict]
    outreach_drafts: list[dict]
    source_checks: list[dict]
    errors: Annotated[list[str], operator.add]
