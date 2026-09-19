"""Prefer structured boards; generic fallback opens observed posting links."""

from __future__ import annotations
import asyncio
import httpx
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from pydantic import Field
from job_intel.core.models import Model
from job_intel.core.llm import generate, current, collection_budget, BudgetExceeded
from job_intel.sources import ats, web
from job_intel.sources.policy import is_aggregator


class ExtractedJob(Model):
    title: str = Field(min_length=1)
    location: str


class PostingLinks(Model):
    urls: list[str] = Field(max_length=12)


def _generic(company):
    page = web.get(company["career_url"])
    soup = BeautifulSoup(page.text, "html.parser")
    observed = {}
    for anchor in soup.select("a[href]"):
        try:
            url = web.canonical_url(urljoin(str(page.url), anchor["href"]))
        except ValueError:
            continue
        label = anchor.get_text(" ", strip=True)
        if any(
            word in (label + " " + url).lower()
            for word in ("engineer", "job", "career", "platform", "data", "mlops")
        ):
            observed[url] = label[:150]
    if not observed:
        raise ValueError("No posting links in static HTML; this site needs a dedicated adapter")
    selection = generate(
        PostingLinks,
        "Select direct individual technical job-posting URLs from the observed links. Do not return search pages, articles or guessed URLs.",
        {"links": dict(list(observed.items())[:100])},
    )
    jobs, failures = [], 0
    for url in dict.fromkeys(selection.urls):
        if url not in observed:
            failures += 1
            continue
        try:
            response = web.get(url)
            desc = web.text(response.text)
            if len(desc) < 150:
                raise ValueError("Posting text too short")
            extracted = generate(
                ExtractedJob,
                "Extract the exact title and hiring location of this individual job posting. Preserve remote restrictions. Use Not specified for absent location. Do not infer from company offices.",
                {"posting_text": desc[:12000]},
            )
            jobs.append(
                ats.listing(
                    company["name"],
                    "web:" + company["career_url"],
                    web.canonical_url(str(response.url)),
                    extracted.title,
                    extracted.location,
                    str(response.url),
                    desc,
                    description_complete=False,
                )
            )
        except BudgetExceeded:
            return (
                jobs,
                "Generic extraction allowance reached; remaining model calls reserved for scoring. Coverage is partial.",
            )
        except Exception:
            failures += 1
    return (
        jobs,
        (
            f"Generic static-page coverage is partial; {failures} posting(s) failed. Configure an ATS source for reliable coverage."
            if jobs or failures
            else "No individual posting links selected from this page; coverage could not be established."
        ),
    )


async def _all(companies):
    sem = asyncio.Semaphore(3)

    async def one(company):
        async with sem:
            try:
                if is_aggregator(company["career_url"]):
                    return [], {
                        "source": company["career_url"],
                        "status": "unsupported",
                        "count": 0,
                        "detail": "Aggregator search pages are unsupported. Use the employer's Greenhouse/Lever board or direct career page. No model calls spent on this source.",
                    }
                jobs = await asyncio.to_thread(ats.fetch, company)
                detail, status = "", "ok"
                if jobs is None:
                    if not current().allow_generic_sources:
                        raise ValueError("Public searches require a Greenhouse or Lever board URL")
                    if current().collection_calls >= current().max_collection_calls:
                        raise BudgetExceeded("Generic extraction allowance reached")
                    jobs, detail = await asyncio.to_thread(_generic, company)
                    status = "partial"
                return jobs, {
                    "source": company["career_url"],
                    "status": status,
                    "count": len(jobs),
                    "detail": detail,
                }
            except Exception as exc:
                if isinstance(exc, BudgetExceeded):
                    status, detail = (
                        "budget_exhausted",
                        "Generic extraction allowance reached; remaining model calls reserved for scoring.",
                    )
                elif isinstance(exc, httpx.HTTPStatusError):
                    code = exc.response.status_code
                    status = "blocked" if code in (401, 403, 429) else "failed"
                    detail = f"Source returned HTTP {code}. It may require login, rate-limit access, or block automated requests. No access restriction was bypassed."
                elif isinstance(exc, httpx.TimeoutException):
                    status, detail = "failed", "Source request timed out. Retry later or use its ATS board."
                elif isinstance(exc, RuntimeError):
                    status, detail = (
                        "failed",
                        "Model extraction failed; check model access, key validity or provider limits. This is not proof the source has no jobs.",
                    )
                elif isinstance(exc, ValueError):
                    status, detail = (
                        "unsupported",
                        "Source has no usable static posting data, exceeds a safety bound, or uses an unsupported URL. Use its Greenhouse/Lever board.",
                    )
                else:
                    status, detail = (
                        "failed",
                        f"Source processing failed ({type(exc).__name__}); previous observations preserved.",
                    )
                return [], {
                    "source": company["career_url"],
                    "status": status,
                    "count": 0,
                    "detail": detail,
                }

    return await asyncio.gather(*(one(c) for c in companies[:15]))


def scrape_careers_node(state):
    with collection_budget():
        results = asyncio.run(_all(state.get("companies", [])))
    jobs = {j["id"]: j for batch, _ in results for j in batch}
    checks = [check for _, check in results]
    return {
        "job_listings": list(jobs.values()),
        "source_checks": checks,
        "errors": [c["source"] + ": " + c["detail"] for c in checks if c["status"] != "ok"],
    }
