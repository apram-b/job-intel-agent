"""V2 operational commands; legacy main.py commands remain compatible."""

import argparse
import json
from pathlib import Path
from dotenv import load_dotenv
from job_intel.v2.storage import Repository, moment
from job_intel.v2.models import CandidateProfile, load_preferences, utcnow


def main(argv=None):
    load_dotenv()
    p = argparse.ArgumentParser(description="Job Intel v2 daily queue")
    p.add_argument("--database-url", help="SQLAlchemy connection URL; prefer environment for credentials")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    old = sub.add_parser("import-legacy")
    old.add_argument("path")
    conf = sub.add_parser("configure")
    conf.add_argument("--candidate", required=True)
    conf.add_argument("--preferences", required=True)
    watch = sub.add_parser("watchlist")
    watch.add_argument("--import-sources")
    watch.add_argument("--enable")
    watch.add_argument("--disable")
    sub.add_parser("discover")
    scan = sub.add_parser("scan")
    scan.add_argument("--scan-id")
    for name in ("evaluate", "worker"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--profile", default="personal")
        cmd.add_argument("--offline", action="store_true")
    sub.add_parser("queue")
    demo = sub.add_parser("export-demo")
    demo.add_argument("--output", default="data/public-demo")
    demo.add_argument("--seed-profile", action="store_true")
    sub.add_parser("health")
    review = sub.add_parser("review-packet")
    review.add_argument("--output", default="data/relevance-review.json")
    pilot = sub.add_parser("pilot-report")
    pilot.add_argument("--labels")
    args = p.parse_args(argv)
    repo = Repository(args.database_url)
    if args.command == "migrate":
        repo.migrate()
        print("V2 schema is current. Legacy tables were retained.")
        return 0
    # Other commands intentionally require explicit migrations; avoid schema changes on every request.
    if args.command == "import-legacy":
        from job_intel.v2.import_legacy import import_legacy

        result = import_legacy(repo, args.path)
    elif args.command == "configure":
        candidate = CandidateProfile.model_validate_json(Path(args.candidate).read_text())
        prefs = load_preferences(args.preferences)
        repo.save_profile(prefs.profile_id, candidate, prefs)
        result = {"configured": prefs.profile_id}
    elif args.command == "watchlist":
        from job_intel.v2.sources import company_from_url

        if args.import_sources:
            sources = json.loads(Path(args.import_sources).read_text())
            for item in sources:
                repo.save_company(company_from_url(item["name"], item["career_url"]))
        if args.enable:
            repo.enable_company(args.enable, True)
        if args.disable:
            repo.enable_company(args.disable, False)
        result = [c.model_dump() for c in repo.companies()]
    elif args.command == "discover":
        from job_intel.v2.workflow import discover

        result = discover(repo)
    elif args.command == "scan":
        from job_intel.v2.workflow import scan_watchlist

        result = scan_watchlist(repo, scan_prefix=args.scan_id)
    elif args.command in ("evaluate", "worker"):
        from job_intel.core.llm import settings
        from job_intel.v2.intelligence import evaluate_queue
        from job_intel.v2.workflow import worker

        config = None
        if not args.offline:
            try:
                config = settings()
            except ValueError:
                pass  # Collection is useful even when paid evaluation is unavailable.
        result = (
            worker(repo, config=config)
            if args.command == "worker"
            else evaluate_queue(repo, args.profile, config=config, verify=not args.offline)
        )
    elif args.command == "export-demo":
        from job_intel.v2.demo import seed_profile, export

        if args.seed_profile:
            seed_profile(repo)
        result = export(repo, args.output)
    elif args.command == "queue":
        result = repo.queue()
    elif args.command == "review-packet":
        from job_intel.v2.validation import review_packet

        result = review_packet(repo, args.output)
    elif args.command == "pilot-report":
        from job_intel.v2.validation import pilot_report

        result = pilot_report(repo, args.labels)
        print(json.dumps(result, indent=2))
        return 0 if result["ready_for_public_release"] else 1
    else:
        scans = repo.recent_scans()
        enabled = repo.companies(enabled_only=True)
        complete = [s for s in scans if s["status"] == "complete"]
        latest = max((s["finished_at"] for s in complete), default=None)
        healthy = bool(enabled) and all(
            any(
                s["company_id"] == c.id
                and s["status"] == "complete"
                and (utcnow() - moment(s["finished_at"])).total_seconds() < 48 * 3600
                for s in scans
            )
            for c in enabled
        )
        result = {
            "database": "ok",
            "fresh": healthy,
            "last_successful_scan": latest,
            "enabled_companies": len(enabled),
        }
        print(json.dumps(result))
        return 0 if healthy else 1
    print(json.dumps(result, indent=2, default=str))
    if isinstance(result, dict) and (
        result.get("status") == "failed"
        or result.get("failed", 0) > 0
        or result.get("intelligence", {}).get("failed", 0) > 0
        or result.get("collection", {}).get("status") == "failed"
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
