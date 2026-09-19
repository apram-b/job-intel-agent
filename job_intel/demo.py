"""Offline fictional sample; never scrapes or calls a model."""

from __future__ import annotations
import os
import uuid
from job_intel.core.models import SearchProfile
from job_intel.sources.ats import listing
from job_intel.db import store


def run_demo():
    # CLI-only demo deliberately selects its own persistent database.
    os.environ["JOB_INTEL_DB"] = "data/demo.db"
    profile = SearchProfile(profile_id="demo")
    run_id = str(uuid.uuid4())
    store.start_run(run_id, profile.model_dump())
    jobs = []
    for company, title, location, index in [
        ("Example Data Co", "Senior Data Engineer", "Gurugram, India", 1),
        ("Example ML Co", "MLOps Engineer", "Remote — India", 2),
    ]:
        job = listing(
            company,
            "fictional-demo",
            index,
            title,
            location,
            f"https://example.com/jobs/{index}",
            "Fictional example: own production Python and AWS pipelines, Airflow orchestration and MLflow model deployment. This is demonstration data and is not a real opening.",
            description_complete=True,
        )
        job.update(
            score=11 if index == 1 else 10,
            score_reason="Fictional demonstration score, not a live model assessment",
            assessment_status="demo",
            eligibility="demo",
        )
        jobs.append(job)
    store.save_job_listings(jobs, run_id=run_id)
    store.finish_run(run_id, "complete", [])
    changes = store.changes(run_id)
    return {
        "run_id": run_id,
        "status": "complete",
        "demo": True,
        "ranked_listings": jobs,
        "new_matches": [j for j in jobs if changes[j["id"]] in ("new", "changed")],
        "changes": changes,
        "errors": [],
        "source_checks": [],
        "outreach_drafts": [],
    }
