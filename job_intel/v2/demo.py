"""Public export is built ONLY from an explicitly fictional demo profile."""

from __future__ import annotations
import json
import os
from pathlib import Path
from job_intel.v2.models import CandidateProfile, SearchPreferences, version, utcnow


def seed_profile(repo):
    candidate = CandidateProfile(
        name="Fictional candidate",
        current_role="Senior Data Engineer",
        years_experience=6,
        skills=["Python", "SQL", "Airflow", "MLflow"],
        stack=["AWS", "SageMaker"],
        inferred_field="Data and ML platforms",
        seniority_level="senior",
        achievements=["Designed production data pipelines and owned ML infrastructure"],
        domains=["Data platforms"],
        fictional=True,
    )
    repo.save_profile("demo", candidate, SearchPreferences(profile_id="demo", max_jobs_to_score=2))


def snapshot(repo):
    stored = repo.profile("demo")
    if not stored or not stored[0].fictional:
        raise ValueError("Public export requires the separate fictional demo profile")
    candidate, prefs = stored
    jobs = []
    for row in repo.queue("demo"):
        evaluation = row["evaluation"]
        if (
            not evaluation
            or evaluation.get("status") != "scored"
            or evaluation.get("candidate_version") != version(candidate)
            or evaluation.get("preferences_version") != version(prefs)
            or row["lifecycle"] not in ("OPEN", "REPOSTED")
            or not row["company_enabled"]
        ):
            continue
        job = row["payload"]
        # Explicit output mapping: no arbitrary candidate, application, model or repository payloads.
        jobs.append(
            {
                "company": job["company"],
                "title": job["title"],
                "location": job["location"],
                "url": job.get("apply_url") or job["url"],
                "fit": evaluation["fit"],
                "confidence": evaluation["confidence"],
                "strategy": evaluation["strategy"],
                "priority": evaluation["priority"],
                "action": evaluation["action"],
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
                "seeded": False,
                "explanation": "Assessed against a fictional data/ML platform candidate. Confidence is a source-evidence heuristic, not a hiring guarantee.",
            }
        )
    return {
        "schema_version": 1,
        "demo": True,
        "updated_at": utcnow().isoformat(),
        "candidate": "Fictional data/ML platform candidate",
        "jobs": jobs[:20],
    }


def seed_snapshot():
    return {
        "schema_version": 1,
        "demo": True,
        "updated_at": None,
        "candidate": "Fictional data/ML platform candidate",
        "jobs": [
            {
                "company": "Example Data Co",
                "title": "Senior Data Engineer",
                "location": "Gurugram, India",
                "url": None,
                "fit": 88,
                "confidence": 80,
                "strategy": 82,
                "priority": 84.5,
                "action": "apply and consider outreach",
                "first_seen": None,
                "last_seen": None,
                "seeded": True,
                "explanation": "Illustrative example: strong Python/AWS alignment, production ownership and verified-source signals. This is not a real vacancy.",
            },
            {
                "company": "Example ML Co",
                "title": "ML Platform Engineer",
                "location": "Remote — India",
                "url": None,
                "fit": 81,
                "confidence": 45,
                "strategy": 92,
                "priority": 74.75,
                "action": "verify",
                "first_seen": None,
                "last_seen": None,
                "seeded": True,
                "explanation": "Illustrative example: attractive platform scope, but insufficient evidence of active hiring. Verify before applying. This is not a real vacancy.",
            },
        ],
    }


def export(repo, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    data = snapshot(repo)
    current = directory / "data.json"
    retained = False
    if not data["jobs"]:
        if current.exists():
            retained = True
        else:
            data = seed_snapshot()
    if not retained:
        temporary = directory / "data.json.tmp"
        temporary.write_text(json.dumps(data, ensure_ascii=False))
        os.replace(temporary, current)
    published = json.loads(current.read_text())
    (directory / "health.json").write_text(
        json.dumps(
            {
                "ready": True,
                "demo": True,
                "snapshot_updated_at": published["updated_at"],
                "seeded": all(j["seeded"] for j in published["jobs"]),
            }
        )
    )
    template = Path(__file__).with_name("public.html")
    (directory / "index.html").write_text(template.read_text())
    return {"retained_previous": retained, "path": str(directory.resolve())}
