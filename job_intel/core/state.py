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
    seniority_level: str    # "junior" | "mid" | "senior"


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
    description: str  # first 200 chars of job description
    scraped_at: str   # ISO-8601 UTC timestamp


class AgentState(TypedDict):
    """Shared state flowing through the LangGraph pipeline."""

    resume_path: str                                        # path to input PDF
    location: str                                           # e.g. "London"
    resume_data: ResumeData                                 # populated by resume_parser
    companies: List[Company]                                # populated by company_finder
    job_listings: List[JobListing]                          # populated by career_scraper
    errors: Annotated[List[str], operator.add]              # accumulated across nodes
