"""Shared state definition for the job intelligence pipeline."""
from __future__ import annotations

import operator
from typing import Annotated, List, TypedDict


class ResumeData(TypedDict):
    """Structured data extracted from the candidate's resume."""

    name: str
    current_role: str
    years_experience: float
    skills: List[str]       # e.g. ["Python", "PyTorch", "Docker"]
    stack: List[str]        # e.g. ["AWS", "Kubernetes", "MLflow"]
    inferred_field: str     # e.g. "MLOps Engineering"
    seniority_level: str    # "junior" | "mid" | "senior" | "lead/principal"


class Company(TypedDict):
    """A company with a known career page URL."""

    name: str
    career_url: str


class JobListing(TypedDict):
    """A single job listing extracted from a career page."""

    id: str           # sha1(company|title|location)[:16]
    company: str
    title: str
    location: str
    url: str          # direct link to the listing (or career page if unavailable)
    description: str  # first 1000 chars of job description
    scraped_at: str   # ISO-8601 UTC timestamp


class RankedJobListing(TypedDict):
    """A job listing enriched with a relevance score."""

    id: str
    company: str
    title: str
    location: str
    url: str
    description: str
    scraped_at: str
    score: int          # 0–12 composite score
    score_reason: str   # human-readable explanation


class OutreachDraft(TypedDict):
    """A tailored cold outreach message for a specific job listing."""

    company: str
    title: str
    message: str        # ~150-word personalised outreach


class AgentState(TypedDict):
    """Shared state flowing through the LangGraph pipeline."""

    resume_path: str                                             # path to input PDF
    location: str                                               # e.g. "Bangalore"
    run_id: str                                                 # UUID per pipeline run (for stale-listing cleanup)
    resume_data: ResumeData                                     # populated by resume_parser
    companies: List[Company]                                    # populated by company_finder
    job_listings: List[JobListing]                              # populated by career_scraper
    ranked_listings: List[RankedJobListing]                     # populated by job_scorer
    outreach_drafts: List[OutreachDraft]                        # populated by outreach_drafter
    errors: Annotated[List[str], operator.add]                  # accumulated across nodes
