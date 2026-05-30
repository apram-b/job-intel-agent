"""Agent 1b: scrape career pages in parallel with Playwright, extract with Claude Haiku."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import List, Tuple

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from job_intel.core.state import AgentState, Company, JobListing
from job_intel.db.store import save_job_listings

_JSON_ARRAY_RE = re.compile(r"\[.*?\]", re.DOTALL)
_MAX_PAGE_CHARS = 12_000
_NAV_TIMEOUT_MS = 30_000
_MAX_SCRAPERS = 5   # concurrent browser pages
_MAX_LLM = 3        # concurrent LLM extraction calls


def _make_id(company: str, title: str, location: str) -> str:
    return hashlib.sha1(f"{company}|{title}|{location}".encode()).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Playwright scraping ────────────────────────────────────────────────────────

async def _fetch_page(url: str, browser, scrape_sem: asyncio.Semaphore) -> Tuple[str, str | None]:
    """Return (page_text, error). Uses one browser context per URL."""
    async with scrape_sem:
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            java_script_enabled=True,
        )
        page = await ctx.new_page()
        try:
            resp = await page.goto(
                url, timeout=_NAV_TIMEOUT_MS, wait_until="domcontentloaded"
            )
            # Abort early on hard blocks
            if resp and resp.status in (401, 403, 404):
                return "", f"HTTP {resp.status}"

            # Give JS-heavy pages time to render dynamic content
            await page.wait_for_timeout(2_500)

            # Scroll once to trigger lazy-loaded listings
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1_000)

            text = await page.inner_text("body")
            return text[:_MAX_PAGE_CHARS], None

        except asyncio.TimeoutError:
            return "", "timeout"
        except Exception as exc:
            short = str(exc)[:120]
            return "", short
        finally:
            await ctx.close()


# ── LLM extraction ─────────────────────────────────────────────────────────────

def _extract_jobs(
    company: str,
    career_url: str,
    page_text: str,
    inferred_field: str,
    location: str,
) -> List[JobListing]:
    """Send page text to Claude Haiku; return filtered, typed JobListings."""
    if not page_text:
        return []

    llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)

    prompt = f"""You are reviewing {company}'s careers page: {career_url}

The candidate is a {inferred_field} professional seeking roles in {location} or Remote.

Extract job listings relevant to: MLOps, ML Engineering, Data Engineering, AI/ML Platform,
LLMOps, Data Science, or closely related technical roles.

Include a listing ONLY if BOTH conditions are met:
1. Role is relevant to the candidate's field (see above)
2. Location mentions "{location}", "India", "Remote", "Anywhere", "Hybrid", or is unspecified

For each matching listing output a JSON object:
  "title"       : job title (string)
  "location"    : location as shown on the page, or "Not specified" (string)
  "url"         : direct link to the posting; fall back to "{career_url}" if none visible (string)
  "description" : first 200 chars of the job summary or description; "" if not available (string)

Output ONLY a valid JSON array. If nothing matches, output [].

PAGE TEXT:
{page_text}"""

    try:
        msg = llm.invoke([HumanMessage(content=prompt)])
        raw = msg.content if isinstance(msg.content, str) else ""
        match = _JSON_ARRAY_RE.search(raw)
        if not match:
            return []
        items = json.loads(match.group())
    except Exception:
        return []

    now = _now_iso()
    listings: List[JobListing] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        loc = str(item.get("location") or "Not specified").strip()
        url = str(item.get("url") or career_url).strip()
        desc = str(item.get("description") or "").strip()[:200]
        listings.append(
            JobListing(
                id=_make_id(company, title, loc),
                company=company,
                title=title,
                location=loc,
                url=url,
                description=desc,
                scraped_at=now,
            )
        )
    return listings


# ── Per-company coroutine ──────────────────────────────────────────────────────

async def _process_company(
    company: Company,
    browser,
    scrape_sem: asyncio.Semaphore,
    llm_sem: asyncio.Semaphore,
    inferred_field: str,
    location: str,
) -> Tuple[List[JobListing], List[str]]:
    name = company["name"]
    url = company["career_url"]

    page_text, error = await _fetch_page(url, browser, scrape_sem)

    if error:
        label = "timeout" if "timeout" in error.lower() else f"error ({error})"
        print(f"  [scraper] {name}: {label}")
        return [], [f"career_scraper [{name}]: {error}"]

    async with llm_sem:
        listings = await asyncio.to_thread(
            _extract_jobs, name, url, page_text, inferred_field, location
        )

    status = f"{len(listings)} match(es)" if listings else "no relevant listings"
    print(f"  [scraper] {name}: {status}")
    return listings, []


# ── Async orchestrator ─────────────────────────────────────────────────────────

async def _scrape_all(
    companies: List[Company],
    inferred_field: str,
    location: str,
) -> Tuple[List[JobListing], List[str]]:
    from playwright.async_api import async_playwright

    scrape_sem = asyncio.Semaphore(_MAX_SCRAPERS)
    llm_sem = asyncio.Semaphore(_MAX_LLM)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        tasks = [
            _process_company(c, browser, scrape_sem, llm_sem, inferred_field, location)
            for c in companies
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        await browser.close()

    all_listings: List[JobListing] = []
    all_errors: List[str] = []
    for i, res in enumerate(raw_results):
        if isinstance(res, Exception):
            all_errors.append(f"career_scraper [{companies[i]['name']}]: {res}")
        else:
            listings, errors = res
            all_listings.extend(listings)
            all_errors.extend(errors)

    return all_listings, all_errors


# ── LangGraph node ─────────────────────────────────────────────────────────────

def scrape_careers_node(state: AgentState) -> dict:
    """LangGraph node: scrape all career pages in parallel, return relevant listings."""
    companies: List[Company] = state.get("companies", [])
    resume_data = state.get("resume_data", {})
    inferred_field = resume_data.get("inferred_field", "Machine Learning")
    location = state.get("location", "India")

    if not companies:
        return {"job_listings": [], "errors": ["career_scraper: no companies in state"]}

    print(f"\n[career_scraper] scraping {len(companies)} companies in parallel...")

    listings, errors = asyncio.run(
        _scrape_all(companies, inferred_field, location)
    )

    print(f"[career_scraper] done — {len(listings)} relevant listing(s) total\n")

    if listings:
        try:
            save_job_listings(listings)
        except Exception as exc:
            errors.append(f"career_scraper: DB save failed: {exc}")

    return {"job_listings": listings, "errors": errors}
