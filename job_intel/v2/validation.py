"""Human relevance review and evidence-based pilot release gate."""

import json
from datetime import timedelta
from pathlib import Path
from job_intel.v2.models import utcnow
from job_intel.v2.storage import moment


def review_packet(repo, path):
    rows = [r for r in repo.queue() if r["lifecycle"] in ("OPEN", "REPOSTED") and r["company_enabled"]]
    packet = {
        "instructions": "Review each posting against your actual candidate profile. Set worth_review and hard_exclusion to true or false; do not fill labels using model predictions.",
        "created_at": utcnow().isoformat(),
        "labels": [
            {
                "job_id": r["id"],
                "title": r["payload"]["title"],
                "company": r["payload"]["company"],
                "url": r["payload"]["url"],
                "worth_review": None,
                "hard_exclusion": None,
            }
            for r in rows[:50]
        ],
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(packet, indent=2))
    return {"postings_to_label": len(packet["labels"]), "required": 50}


def pilot_report(repo, labels_path=None, at=None):
    at = at or utcnow()
    enabled = repo.companies(enabled_only=True)
    scans = repo.recent_scans(limit=10000)
    days = {(at.date() - timedelta(days=i)).isoformat() for i in range(7)}
    missing = {}
    for company in enabled:
        completed = {
            moment(s["finished_at"]).date().isoformat()
            for s in scans
            if s["company_id"] == company.id and s["status"] == "complete" and s["finished_at"]
        }
        absent = sorted(days - completed)
        if absent:
            missing[company.name] = absent
    queue = repo.queue()
    eligible = [
        r
        for r in queue
        if r["company_enabled"]
        and r["lifecycle"] in ("OPEN", "REPOSTED")
        and r["evaluation"]
        and r["evaluation"].get("status") == "scored"
        and r["evaluation"].get("eligibility") == "eligible"
        and r["evaluation"].get("action") != "tracked"
    ]
    top = eligible[:10]
    labels = json.loads(Path(labels_path).read_text()).get("labels", []) if labels_path else []
    real_ids = {r["id"] for r in queue if r["company_enabled"] and r["lifecycle"] in ("OPEN", "REPOSTED")}
    reviewed = {
        r["job_id"]: r
        for r in labels
        if r.get("job_id") in real_ids
        and isinstance(r.get("worth_review"), bool)
        and isinstance(r.get("hard_exclusion"), bool)
    }
    top_reviewed = [reviewed[r["id"]] for r in top if r["id"] in reviewed]
    worth = sum(r["worth_review"] for r in top_reviewed)
    violation = any(r["hard_exclusion"] for r in top_reviewed)
    ready = (
        bool(enabled)
        and not missing
        and len(reviewed) >= 50
        and len(top_reviewed) == 10
        and worth >= 8
        and not violation
    )
    return {
        "ready_for_public_release": ready,
        "complete_scan_days_required": 7,
        "missing_scan_days": missing,
        "enabled_companies": len(enabled),
        "reviewed_postings": len(reviewed),
        "required_reviews": 50,
        "top_ten_reviewed": len(top_reviewed),
        "top_ten_worth_review": worth,
        "hard_exclusion_in_top_ten": violation,
        "remaining_operational_checks": [
            "Verify cold HTTPS visit, backup restore, redeploy and subscription/billing configuration before publishing."
        ],
    }
