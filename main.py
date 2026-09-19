"""CLI: reproducible searches, history and application tracking."""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from job_intel.core.models import load_profile
from job_intel.core.llm import settings
from job_intel.core.pipeline import run_pipeline
from job_intel.db import store


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Job Intel — verified matches and durable job history")
    parser.add_argument("--resume", help="Text-based PDF, at most 5 MB / 10 pages")
    parser.add_argument("--resume-json", help="Reviewed Resume schema JSON; skips PDF/model parsing")
    parser.add_argument("--profile", help="Search preferences JSON")
    parser.add_argument("--sources", help="JSON array of name/career_url entries")
    parser.add_argument("--location", help="Override primary city (legacy CLI compatibility)")
    parser.add_argument("--provider", choices=["openai", "anthropic"])
    parser.add_argument("--output", help="Save full run as JSON")
    parser.add_argument("--digest", help="Save new/changed qualified matches as Markdown")
    parser.add_argument("--db", help="SQLite path; default data/job_intel.db")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--status", choices=store.STATUSES)
    parser.add_argument("--job-id")
    parser.add_argument("--notes", default="")
    parser.add_argument("--follow-up", help="YYYY-MM-DD")
    parser.add_argument(
        "--demo", action="store_true", help="Offline fictional example in a separate database"
    )
    args = parser.parse_args()
    if args.db:
        os.environ["JOB_INTEL_DB"] = args.db
    profile = load_profile(args.profile)
    if args.location:
        profile.preferred_cities = [args.location]
    if args.demo:
        from job_intel.demo import run_demo

        result = run_demo()
    elif args.history:
        print(json.dumps(store.history(profile.profile_id), indent=2))
        return 0
    elif args.status:
        if not args.job_id:
            parser.error("--status requires --job-id")
        store.set_status(profile.profile_id, args.job_id, args.status, args.notes, args.follow_up)
        print("Application updated")
        return 0
    else:
        if not (args.resume or args.resume_json):
            parser.error("Provide --resume or --resume-json, or use --demo / --history")
        result = run_pipeline(
            profile,
            settings(args.provider),
            resume_path=args.resume,
            resume_data=json.loads(Path(args.resume_json).read_text()) if args.resume_json else None,
            companies=json.loads(Path(args.sources).read_text()) if args.sources else None,
            on_stage=lambda stage, values: print(
                stage + (": needs attention" if values.get("errors") else ": complete")
            ),
        )
    print(
        f"Run {result['status']}: {len(result['ranked_listings'])} qualified matches, {len(result['new_matches'])} new/changed"
    )
    for job in result["ranked_listings"]:
        print(f"  {job['score']}/12 | {job['company']} | {job['title']} | {job['location']}\n  {job['url']}")
    for error in result["errors"]:
        print("Attention: " + error)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.digest:
        lines = ["# Job Intel digest", f"Run status: {result['status']}", ""]
        for job in result["new_matches"]:
            lines.extend(
                [
                    f"- [{job['company']} — {job['title']}]({job['url']}) · {job['score']}/12",
                    f"  {job['score_reason']}",
                ]
            )
        if not result["new_matches"]:
            lines.append(
                "No new qualified matches. Check run status and source coverage before interpreting this as no openings."
            )
        Path(args.digest).parent.mkdir(parents=True, exist_ok=True)
        Path(args.digest).write_text("\n".join(lines), encoding="utf-8")
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
