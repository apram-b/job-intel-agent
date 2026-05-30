"""SQLite persistence layer using sqlite-utils."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

import sqlite_utils

from job_intel.core.state import JobListing, ResumeData

DB_PATH = Path(__file__).parent.parent.parent / "job_intel.db"


def _db() -> sqlite_utils.Database:
    return sqlite_utils.Database(DB_PATH)


def save_resume(data: ResumeData) -> None:
    """Upsert parsed resume data into the resumes table (keyed on name)."""
    db = _db()
    row = {
        "name": data["name"],
        "current_role": data["current_role"],
        "years_experience": float(data["years_experience"]),
        "skills": json.dumps(data["skills"]),
        "stack": json.dumps(data["stack"]),
        "inferred_field": data["inferred_field"],
        "seniority_level": data["seniority_level"],
    }
    db["resumes"].upsert(row, pk="name")


def save_job_listings(listings: List[JobListing]) -> None:
    """Upsert job listings into the job_listings table (keyed on id)."""
    if not listings:
        return
    db = _db()
    rows = [
        {
            "id": j["id"],
            "company": j["company"],
            "title": j["title"],
            "location": j["location"],
            "url": j["url"],
            "description": j["description"],
            "scraped_at": j["scraped_at"],
        }
        for j in listings
    ]
    db["job_listings"].upsert_all(rows, pk="id")
