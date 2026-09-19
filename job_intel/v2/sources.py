"""ATS adapters with explicit completeness and bounded, polite retries."""

from __future__ import annotations
import time
import threading
from urllib.parse import urlsplit
from datetime import datetime, timezone
from typing import Protocol
import httpx
from job_intel.core.models import fingerprint
from job_intel.sources import ats, web
from job_intel.v2.models import Company, JobListing, ScanResult


class JobSource(Protocol):
    def discover_jobs(self, company: Company) -> ScanResult: ...


def company_from_url(name, url, *, enabled=True, discovery_source="manual"):
    spec = ats.board(url)
    if spec is None:
        raise ValueError("Use a verified Greenhouse or Lever board URL")
    provider, token, base = spec
    source = f"{provider}:{base}:{token}"
    host = (
        "https://job-boards.greenhouse.io"
        if provider == "greenhouse"
        else "https://jobs.eu.lever.co"
        if "eu.lever" in base
        else "https://jobs.lever.co"
    )
    return Company(
        id=fingerprint(source),
        name=name,
        career_url=f"{host}/{token}",
        source=source,
        enabled=enabled,
        discovery_source=discovery_source,
    )


def normalize(raw, company):
    posted = raw.get("posted_at")
    if isinstance(posted, (int, float)):
        posted = datetime.fromtimestamp(posted / 1000, timezone.utc)
    location = raw.get("location") or "Not specified"
    mode = next((x for x in ("remote", "hybrid", "onsite") if x in location.lower()), "unknown")
    return JobListing(
        id=raw["id"],
        company_id=company.id,
        company=company.name,
        source=raw["source"],
        source_id=raw["source_id"],
        title=raw["title"],
        location=location,
        url=web.canonical_url(raw["url"]),
        apply_url=web.canonical_url(raw.get("apply_url") or raw["url"]),
        description=raw.get("description", ""),
        description_complete=raw.get("description_complete", False),
        work_mode=mode,
        posted_at=posted,
        source_hash=fingerprint({k: v for k, v in raw.items() if k != "scraped_at"}),
    )


_rate_lock = threading.Lock()
_last_request = {}


def throttled_get(url):
    host = urlsplit(url).hostname
    with _rate_lock:
        delay = max(0, 0.5 - (time.monotonic() - _last_request.get(host, 0)))
        if delay:
            time.sleep(delay)
        _last_request[host] = time.monotonic()
    return web.get(url)


class ATSSource:
    def discover_jobs(self, company):
        for attempt in range(3):
            try:
                raw = ats.fetch({"name": company.name, "career_url": company.career_url}, get=throttled_get)
                if raw is None:
                    return ScanResult(status="failed", error="Unsupported ATS source")
                return ScanResult(status="complete", jobs=[normalize(r, company) for r in raw])
            except (httpx.TimeoutException, httpx.TransportError):
                error = "Source network error or timeout"
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                error = f"Source returned HTTP {code}"
                if code != 429 and code < 500:
                    break
            except (ValueError, KeyError, TypeError):
                return ScanResult(
                    status="failed", error="Invalid or incomplete source payload; previous states retained"
                )
            if attempt < 2:
                time.sleep(2**attempt)
        return ScanResult(status="failed", error=error)
