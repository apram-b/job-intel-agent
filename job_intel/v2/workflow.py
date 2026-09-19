"""Restartable scheduled work independent of Streamlit and résumé parsing."""

import uuid
from job_intel.v2.sources import ATSSource, company_from_url
from job_intel.v2.models import ScanResult, SearchPreferences
from job_intel.v2.intelligence import evaluate_queue


def scan_watchlist(repo, *, profile_id="personal", source=None, scan_prefix=None):
    source = source or ATSSource()
    owner = str(uuid.uuid4())
    if not repo.acquire("watchlist-scan", owner, minutes=60):
        return {"status": "busy", "scans": []}
    stored = repo.profile(profile_id)
    prefs = stored[1] if stored else SearchPreferences()
    results = []
    try:
        for company in repo.companies(enabled_only=True):
            scan_id = f"{scan_prefix}:{company.id}" if scan_prefix else str(uuid.uuid4())
            repo.begin_scan(scan_id, company.id)
            try:
                result = source.discover_jobs(company)
            except Exception as exc:
                result = ScanResult(
                    status="failed", error=f"Source failed ({type(exc).__name__}); history preserved"
                )
            repo.apply_scan(scan_id, company, result, prefs)
            results.append({"company": company.name, "status": result.status, "count": len(result.jobs)})
    finally:
        repo.release("watchlist-scan", owner)
    status = (
        "complete"
        if results and all(r["status"] == "complete" for r in results)
        else "partial"
        if any(r["status"] != "failed" for r in results)
        else "failed"
    )
    return {"status": status, "scans": results}


def discover(repo, profile_id="personal"):
    from job_intel.agents.company_finder import find_companies_node
    from job_intel.core.models import SearchProfile

    stored = repo.profile(profile_id)
    prefs = stored[1] if stored else SearchPreferences()
    old_fields = {k: v for k, v in prefs.model_dump().items() if k in SearchProfile.model_fields}
    old_fields["target_roles"] = prefs.roles()
    result = find_companies_node({"profile": old_fields})
    existing = {c.id for c in repo.companies()}
    added = 0
    for data in result["companies"]:
        company = company_from_url(
            data["name"], data["career_url"], enabled=False, discovery_source="weekly-discovery"
        )
        if company.id not in existing:
            repo.save_company(company)
            existing.add(company.id)
            added += 1
    return {"added_for_review": added, "errors": result.get("errors", [])}


def worker(repo, *, config=None):
    owner = str(uuid.uuid4())
    if not repo.acquire("daily-worker", owner, minutes=60):
        return {"status": "busy"}
    try:
        collected = scan_watchlist(repo)
        result = evaluate_queue(repo, config=config)
        return {"collection": collected, "intelligence": result}
    finally:
        repo.release("daily-worker", owner)
