"""Entry point for the job-intel pipeline.

Usage:
    python main.py --resume path/to/resume.pdf --location "London"
"""
from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv

from job_intel.core.graph import build_graph


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Job Intel Agent")
    parser.add_argument("--resume", required=True, help="Path to resume PDF")
    parser.add_argument("--location", required=True, help='e.g. "London"')
    args = parser.parse_args()

    graph = build_graph()

    print(f"\n=== Job Intel  |  resume={args.resume!r}  location={args.location!r} ===\n")

    result = graph.invoke(
        {
            "resume_path": args.resume,
            "location": args.location,
            "companies": [],
            "job_listings": [],
            "errors": [],
        }
    )

    resume_data = result.get("resume_data")
    errors = result.get("errors", [])

    if resume_data:
        print("=== Parsed Resume ===")
        print(f"  Name            : {resume_data['name']}")
        print(f"  Current role    : {resume_data['current_role']}")
        print(f"  Experience      : {resume_data['years_experience']} year(s)")
        print(f"  Inferred field  : {resume_data['inferred_field']}")
        print(f"  Seniority       : {resume_data['seniority_level']}")
        print(f"  Skills          : {', '.join(resume_data['skills'])}")
        print(f"  Stack           : {', '.join(resume_data['stack'])}")
    else:
        print("No resume data extracted.")

    companies = result.get("companies", [])
    if companies:
        print(f"\n=== {len(companies)} Companies Targeted ===")
        for c in companies:
            print(f"  • {c['name']}")

    listings = result.get("job_listings", [])
    if listings:
        print(f"\n=== {len(listings)} Relevant Job Listing(s) ===")
        for j in listings:
            print(f"\n  [{j['company']}]  {j['title']}")
            print(f"  Location    : {j['location']}")
            print(f"  URL         : {j['url']}")
            if j["description"]:
                print(f"  Description : {j['description'][:120]}...")
    else:
        print("\n  No relevant job listings found.")

    if errors:
        print(f"\n=== {len(errors)} error(s) ===")
        for e in errors:
            print(f"  ! {e}")


if __name__ == "__main__":
    main()
