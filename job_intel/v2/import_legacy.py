"""Idempotent copy from a v1 SQLite database. Original tables remain untouched."""

import json
import sqlite3
from pathlib import Path
from job_intel.core.models import fingerprint
from job_intel.v2 import schema as s
from job_intel.v2.models import CandidateProfile, SearchPreferences, JobListing


def import_legacy(repo, path):
    source = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "jobs" not in tables:
        source.close()
        return {"jobs": 0, "applications": 0, "profiles": 0}
    all_rows = {
        name: [dict(r) for r in source.execute('SELECT * FROM "' + name + '"')]
        for name in ["jobs", "runs", "observations", "applications", "scores", "profiles"]
        if name in tables
    }
    source.close()
    runs = {r["id"]: r for r in all_rows.get("runs", [])}
    company_ids = {}
    with repo.transaction() as c:
        for old in all_rows["jobs"]:
            raw = json.loads(old["payload"])
            origin = raw.get("source") or "legacy:unknown"
            cid = fingerprint(origin)
            company_ids[old["id"]] = cid
            repo.put(
                c,
                s.companies,
                dict(
                    id=cid,
                    source=origin,
                    enabled=False,
                    payload={
                        "id": cid,
                        "source": origin,
                        "name": raw.get("company", "Legacy company"),
                        "career_url": raw.get("url", ""),
                        "enabled": False,
                        "discovery_source": "legacy-import",
                        "tier": "secondary",
                    },
                ),
                ["id"],
                ignore=True,
            )
            job = JobListing(
                id=old["id"],
                company_id=cid,
                company=raw.get("company", "Legacy company"),
                source=origin,
                source_id=str(raw.get("source_id") or old["id"]),
                title=raw.get("title", "Unknown role"),
                location=raw.get("location") or "Not specified",
                url=raw.get("url", ""),
                description=raw.get("description", ""),
                description_complete=raw.get("description_complete", False),
            )
            payload = job.model_dump(mode="json")
            repo.put(
                c,
                s.jobs,
                dict(
                    id=job.id,
                    company_id=cid,
                    source=origin,
                    source_id=job.source_id,
                    payload=payload,
                    content_hash=fingerprint({k: v for k, v in payload.items() if k != "source_hash"}),
                    first_seen=old["first_seen"],
                    last_seen=old["last_seen"],
                    lifecycle="UNVERIFIED",
                    missing_count=0,
                ),
                ["id"],
                ignore=True,
            )
            if job.url:
                repo.put(c, s.aliases, dict(url=job.url, job_id=job.id), ["url"], ignore=True)
        for row in all_rows.get("observations", []):
            run = runs[row["run_id"]]
            scan_id = "legacy:" + fingerprint([run["id"], company_ids[row["job_id"]]])
            repo.put(
                c,
                s.scans,
                dict(
                    id=scan_id,
                    company_id=company_ids[row["job_id"]],
                    started_at=run["started_at"],
                    finished_at=run.get("finished_at"),
                    status="legacy",
                    count=0,
                    error="Legacy observations; source completeness unknown",
                ),
                ["id"],
                ignore=True,
            )
            repo.put(
                c,
                s.observations,
                dict(
                    scan_id=scan_id,
                    job_id=row["job_id"],
                    observed_at=run["started_at"],
                    change="updated" if row["change"] == "changed" else row["change"],
                    source_hash=row.get("content_hash", ""),
                    evidence={"legacy": True, "run_id": run["id"], "profile_id": run["profile_id"]},
                ),
                ["scan_id", "job_id"],
                ignore=True,
            )
        for row in all_rows.get("applications", []):
            repo.put(c, s.applications, row, ["profile_id", "job_id"], ignore=True)
        for row in all_rows.get("scores", []):
            original = json.loads(row["payload"])
            eid = "legacy:" + fingerprint([row["profile_id"], row["job_id"], row["cache_key"]])
            payload = {
                "id": eid,
                "job_id": row["job_id"],
                "profile_id": row["profile_id"],
                "status": "legacy",
                "fit": None,
                "confidence": 0,
                "strategy": None,
                "priority": None,
                "action": "review",
                "reasons": ["Legacy 0–12 assessment; v2 evaluation required"],
                "legacy_assessment": original,
            }
            repo.put(
                c,
                s.evaluations,
                dict(
                    id=eid,
                    job_id=row["job_id"],
                    profile_id=row["profile_id"],
                    cache_key="legacy:" + row["cache_key"],
                    evaluated_at=row["updated_at"],
                    payload=payload,
                ),
                ["id"],
                ignore=True,
            )
    count = 0
    for row in all_rows.get("profiles", []):
        if repo.profile(row["id"]):
            continue
        data = json.loads(row["payload"])
        if data.get("resume"):
            pref = data["profile"]
            pref.update(primary_roles=pref.get("target_roles", []), secondary_roles=[], stretch_roles=[])
            repo.save_profile(
                row["id"],
                CandidateProfile.model_validate(data["resume"]),
                SearchPreferences.model_validate(pref),
            )
            count += 1
    return {
        "jobs": len(all_rows["jobs"]),
        "applications": len(all_rows.get("applications", [])),
        "profiles": count,
    }
