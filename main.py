"""Entry point for the job-intel pipeline.

Usage:
    python main.py --resume path/to/resume.pdf --location "Bangalore"
    python main.py --resume resume.pdf --location "Bangalore" --output results.json
"""
from __future__ import annotations

import argparse
import json
import logging
import uuid
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.rule import Rule

from job_intel.core.graph import build_graph
from job_intel.db.store import clean_stale_listings

# All agent modules use logging — set to WARNING so only real problems surface.
# Set to INFO or DEBUG here (or via LOG_LEVEL env var) for verbose output.
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

console = Console()


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Job Intel Agent")
    parser.add_argument("--resume", required=True, help="Path to resume PDF")
    parser.add_argument("--location", required=True, help='e.g. "Bangalore"')
    parser.add_argument(
        "--output",
        default=None,
        metavar="FILE",
        help="Optional path to save results as JSON (e.g. results.json)",
    )
    args = parser.parse_args()

    run_id = str(uuid.uuid4())
    graph = build_graph()

    console.print(Rule(f"[bold cyan]Job Intel[/bold cyan]  |  resume={args.resume!r}  location={args.location!r}"))
    console.print()

    result = graph.invoke(
        {
            "resume_path": args.resume,
            "location": args.location,
            "run_id": run_id,
            "companies": [],
            "job_listings": [],
            "ranked_listings": [],
            "outreach_drafts": [],
            "errors": [],
        }
    )

    # ── Parsed Resume ───────────────────────────────────────────────────────────
    resume_data = result.get("resume_data")
    if resume_data:
        console.print(Rule("[bold]Parsed Resume[/bold]"))
        console.print(f"  [bold]Name[/bold]            : {resume_data['name']}")
        console.print(f"  [bold]Current role[/bold]    : {resume_data['current_role']}")
        console.print(f"  [bold]Experience[/bold]      : {resume_data['years_experience']} year(s)")
        console.print(f"  [bold]Inferred field[/bold]  : {resume_data['inferred_field']}")
        console.print(f"  [bold]Seniority[/bold]       : {resume_data['seniority_level']}")
        console.print(f"  [bold]Skills[/bold]          : {', '.join(resume_data['skills'])}")
        console.print(f"  [bold]Stack[/bold]           : {', '.join(resume_data['stack'])}")
    else:
        console.print("[red]No resume data extracted.[/red]")

    # ── Companies Targeted ──────────────────────────────────────────────────────
    companies = result.get("companies", [])
    if companies:
        console.print()
        console.print(Rule(f"[bold]{len(companies)} Companies Targeted[/bold]"))
        for c in companies:
            console.print(f"  [cyan]•[/cyan] {c['name']}  [dim]→[/dim]  [link={c['career_url']}]{c['career_url']}[/link]")

    # ── Ranked Job Listings ─────────────────────────────────────────────────────
    ranked = result.get("ranked_listings", [])
    listings = result.get("job_listings", [])
    display_listings = ranked if ranked else listings

    if display_listings:
        console.print()
        label = "Top Ranked" if ranked else "Relevant"
        console.print(Rule(f"[bold]{len(display_listings)} {label} Job Listing(s)[/bold]"))
        for j in display_listings:
            score_str = f"  [bold green]Score: {j['score']}/12[/bold green]" if "score" in j else ""
            console.print()
            console.print(f"  [bold][{j['company']}][/bold]  {j['title']}{score_str}")
            console.print(f"  Location    : {j['location']}")
            console.print(f"  URL         : [link={j['url']}]{j['url']}[/link]")
            if j.get("description"):
                console.print(f"  Description : {j['description'][:160]}...")
            if "score_reason" in j and j["score_reason"]:
                console.print(f"  [dim]Why        : {j['score_reason']}[/dim]")
    else:
        console.print()
        console.print("  [yellow]No relevant job listings found.[/yellow]")

    # ── Outreach Drafts ─────────────────────────────────────────────────────────
    drafts = result.get("outreach_drafts", [])
    if drafts:
        console.print()
        console.print(Rule(f"[bold]{len(drafts)} Outreach Draft(s)[/bold]"))
        for d in drafts:
            console.print()
            console.print(f"  [bold cyan][{d['company']}][/bold cyan]  {d['title']}")
            console.print()
            for line in d["message"].splitlines():
                console.print(f"    {line}")
            console.print()
            console.print("  " + "─" * 60)

    # ── Errors ──────────────────────────────────────────────────────────────────
    errors = result.get("errors", [])
    if errors:
        console.print()
        console.print(Rule(f"[bold red]{len(errors)} Error(s)[/bold red]"))
        for e in errors:
            console.print(f"  [red]![/red] {e}")

    # ── Stale listing cleanup ───────────────────────────────────────────────────
    try:
        cleaned = clean_stale_listings(run_id)
        if cleaned:
            console.print(f"\n  [dim]Cleaned {cleaned} stale listing(s) from previous runs.[/dim]")
    except Exception:
        pass

    # ── Optional JSON output ────────────────────────────────────────────────────
    if args.output:
        output_data = {
            "run_id": run_id,
            "resume": resume_data,
            "companies": companies,
            "ranked_listings": ranked or listings,
            "outreach_drafts": drafts,
            "errors": errors,
        }
        out_path = Path(args.output)
        out_path.write_text(json.dumps(output_data, indent=2), encoding="utf-8")
        console.print(f"\n  [green]Results saved to[/green] {out_path.resolve()}")

    console.print()
    console.print(Rule())


if __name__ == "__main__":
    main()
