"""Read-only Greenhouse and Lever adapters, including complete descriptions."""

from __future__ import annotations
from urllib.parse import urlsplit, quote
from job_intel.core.models import fingerprint
from job_intel.db.store import now
from job_intel.sources import web


def board(url):
    parts = urlsplit(web.canonical_url(url))
    host, path = parts.hostname, [p for p in parts.path.split("/") if p]
    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io") and path:
        if host == "boards.eu.greenhouse.io":
            return None  # Do not guess regional API support.
        return "greenhouse", path[0], "https://boards-api.greenhouse.io"
    if host in ("jobs.lever.co", "jobs.eu.lever.co") and path:
        return (
            "lever",
            path[0],
            "https://api.eu.lever.co" if host == "jobs.eu.lever.co" else "https://api.lever.co",
        )
    return None


def listing(company, source, source_id, title, location, url, description, **extra):
    if not title or not source_id:
        raise ValueError("Job has no title or source ID")
    url = web.canonical_url(url)
    return {
        "id": fingerprint([source, str(source_id)]),
        "company": company,
        "source": source,
        "source_id": str(source_id),
        "title": title,
        "location": location or "Not specified",
        "url": url,
        "description": description,
        "scraped_at": now(),
        **extra,
    }


def fetch(company):
    spec = board(company["career_url"])
    if spec is None:
        return None
    provider, token, base = spec
    source = f"{provider}:{base}:{token}"
    token_url = quote(token, safe="")
    if provider == "greenhouse":
        payload = web.get(f"{base}/v1/boards/{token_url}/jobs?content=true").json()
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise ValueError("Invalid Greenhouse response")
        items = payload["jobs"]
        if payload.get("meta", {}).get("total", len(items)) != len(items):
            raise ValueError("Incomplete Greenhouse response")
        return [
            listing(
                company["name"],
                source,
                j["id"],
                j["title"],
                j.get("location", {}).get("name"),
                j["absolute_url"],
                web.text(j.get("content", "")),
                updated_at=j.get("updated_at"),
                description_complete=True,
            )
            for j in items
        ]
    results = []
    for page in range(20):
        items = web.get(f"{base}/v0/postings/{token_url}?mode=json&skip={page * 100}&limit=100").json()
        if not isinstance(items, list):
            raise ValueError("Invalid Lever response")
        for j in items:
            description = web.text(j.get("description", ""))
            for section in j.get("lists", []):
                description += "\n" + section.get("text", "") + " " + web.text(section.get("content", ""))
            description += "\n" + web.text(j.get("additional", ""))
            locations = j.get("categories", {}).get("allLocations") or [
                j.get("categories", {}).get("location", "Not specified")
            ]
            location = "; ".join(locations)
            workplace = j.get("workplaceType", "")
            if workplace:
                location += " (" + workplace + ")"
            results.append(
                listing(
                    company["name"],
                    source,
                    j["id"],
                    j["text"],
                    location,
                    j["hostedUrl"],
                    description,
                    description_complete=True,
                    posted_at=j.get("createdAt"),
                    salary=j.get("salaryRange"),
                )
            )
        if len(items) < 100:
            return results
    raise ValueError("Lever board exceeds pagination limit; incomplete result discarded")
