"""SQLite persistence layer using sqlite-utils."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List

import sqlite_utils

from job_intel.core.state import Company, JobListing, ResumeData

_log = logging.getLogger(__name__)

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
    _log.debug("Saved resume for %s", data["name"])


def save_companies(companies: List[Company]) -> None:
    """Upsert discovered companies into the companies table (keyed on name)."""
    if not companies:
        return
    db = _db()
    rows = [
        {"name": c["name"], "career_url": c["career_url"]}
        for c in companies
    ]
    db["companies"].upsert_all(rows, pk="name")
    _log.debug("Saved %d companies", len(rows))


def save_job_listings(listings: List[JobListing], *, run_id: str = "") -> None:
    """Upsert job listings into the job_listings table (keyed on id).

    Each row is stamped with ``run_id`` so stale listings from previous runs
    can be identified and cleaned up with :func:`clean_stale_listings`.
    """
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
            "run_id": run_id,
        }
        for j in listings
    ]
    db["job_listings"].upsert_all(rows, pk="id")
    _log.debug("Saved %d job listings (run_id=%s)", len(rows), run_id)


def clean_stale_listings(current_run_id: str) -> int:
    """Delete job listings that were not produced by the current run.

    Returns the number of rows deleted.
    """
    if not current_run_id:
        return 0
    db = _db()
    if "job_listings" not in db.table_names():
        return 0
    before = db["job_listings"].count
    db.execute(
        "DELETE FROM job_listings WHERE run_id != ? AND run_id != ''",
        [current_run_id],
    )
    after = db["job_listings"].count
    deleted = before - after
    if deleted:
        _log.info("Cleaned %d stale job listing(s) from previous runs", deleted)
    return deleted
