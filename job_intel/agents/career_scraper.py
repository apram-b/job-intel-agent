"""Agent: scrape career pages in parallel with Playwright, extract with Claude Haiku."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import List, Tuple
from urllib.parse import urljoin

import httpx
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from job_intel.core.llm import extract_json_array, get_llm, invoke_text
from job_intel.core.state import AgentState, Company, JobListing
from job_intel.db.store import save_job_listings

_log = logging.getLogger(__name__)
_console = Console()

_MAX_PAGE_CHARS = 20_000
_NAV_TIMEOUT_MS = 30_000
_NETWORKIDLE_TIMEOUT_MS = 8_000
_MAX_SCRAPERS = 5    # concurrent browser pages
_MAX_LLM = 3         # concurrent LLM extraction calls
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_HREF_RE = re.compile(r'href=["\']([^"\'#][^"\']*)["\']', re.IGNORECASE)


def _make_id(company: str, title: str, location: str) -> str:
    return hashlib.sha1(f"{company}|{title}|{location}".encode()).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_links(html: str, base_url: str) -> str:
    """Pull job-relevant <a href> links from raw HTML and return as a newline list."""
    hrefs = _HREF_RE.findall(html)
    job_links: List[str] = []
    seen: set[str] = set()
    for href in hrefs:
        href = href.strip()
        if not href or href.startswith("javascript"):
            continue
        full = urljoin(base_url, href)
        lower = href.lower()
        if any(
            kw in lower
            for kw in ("job", "career", "position", "role", "opening",
                       "vacancy", "apply", "requisition", "hiring")
        ):
            if full not in seen:
                seen.add(full)
                job_links.append(full)
    return "\n".join(job_links[:150])  # cap to keep prompt manageable


# ── httpx plain-HTTP fallback ──────────────────────────────────────────────────

def _httpx_fallback(url: str) -> Tuple[str, str]:
    """Try a plain HTTP GET for sites that block headless browsers.

    Returns (page_text, status_note). On success status_note is "" and
    page_text is populated; on failure page_text is "" and status_note
    explains what happened (for error reporting).
    """
    try:
        r = httpx.get(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=15,
            follow_redirects=True,
        )
        if r.status_code == 200:
            # Strip HTML tags to get readable text
            text = re.sub(r"<[^>]+>", " ", r.text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:_MAX_PAGE_CHARS], ""
        return "", f"httpx fallback: HTTP {r.status_code}"
    except Exception as exc:
        return "", f"httpx fallback: {str(exc)[:80]}"


# Playwright navigation errors where a plain-HTTP retry is worthwhile.
# DNS failures are excluded — httpx would fail identically.
_FALLBACK_NAV_ERRORS = ("ERR_HTTP2_PROTOCOL_ERROR", "ERR_CONNECTION_RESET", "ERR_SSL")


# ── Playwright scraping ────────────────────────────────────────────────────────

async def _fetch_page(
    url: str, browser, scrape_sem: asyncio.Semaphore
) -> Tuple[str, str, str | None]:
    """Return (page_text, page_links, error). Uses one browser context per URL."""
    async with scrape_sem:
        ctx = await browser.new_context(
            user_agent=_USER_AGENT,
            java_script_enabled=True,
        )
        page = await ctx.new_page()
        try:
            resp = await page.goto(
                url, timeout=_NAV_TIMEOUT_MS, wait_until="domcontentloaded"
            )

            # Handle hard blocks — try httpx fallback on 403
            if resp and resp.status in (401, 403, 404):
                if resp.status == 403:
                    fallback_text, note = await asyncio.to_thread(_httpx_fallback, url)
                    if fallback_text:
                        _log.debug("httpx fallback succeeded for %s", url)
                        return fallback_text, "", None
                    return "", "", f"HTTP 403 ({note})"
                return "", "", f"HTTP {resp.status}"

            # Wait for JS-rendered content to settle
            try:
                await page.wait_for_load_state("networkidle", timeout=_NETWORKIDLE_TIMEOUT_MS)
            except Exception:
                pass  # continue with whatever rendered so far

            # Multi-scroll to trigger lazy-loaded listings
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1_000)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(500)

            text = await page.inner_text("body")
            html = await page.content()
            links = _extract_links(html, url)

            return text[:_MAX_PAGE_CHARS], links, None

        except asyncio.TimeoutError:
            return "", "", "timeout"
        except Exception as exc:
            err = str(exc)
            # Chromium-specific network failures often succeed over plain HTTP/1.1
            if any(code in err for code in _FALLBACK_NAV_ERRORS):
                fallback_text, note = await asyncio.to_thread(_httpx_fallback, url)
                if fallback_text:
                    _log.debug("httpx fallback succeeded for %s after nav error", url)
                    return fallback_text, "", None
                return "", "", f"{err[:80]} ({note})"
            return "", "", err[:120]
        finally:
            await ctx.close()


# ── LLM extraction ─────────────────────────────────────────────────────────────

def _extract_jobs(
    company: str,
    career_url: str,
    page_text: str,
    page_links: str,
    inferred_field: str,
    skills: List[str],
    location: str,
) -> List[JobListing]:
    """Send page content to Claude Haiku; return filtered, typed JobListings."""
    if not page_text and not page_links:
        return []

    llm = get_llm()

    links_section = (
        f"\nEXTRACTED JOB-RELATED LINKS FROM PAGE:\n{page_links}"
        if page_links
        else "\nEXTRACTED JOB-RELATED LINKS: (none found)"
    )
    skills_str = ", ".join(skills[:8]) if skills else inferred_field

    prompt = f"""You are reviewing {company}'s careers page: {career_url}

The candidate is a {inferred_field} professional seeking roles in {location} or Remote.
Their key skills: {skills_str}

Extract ANY job listing plausibly related to the candidate's field or skills — including
adjacent titles (e.g. platform, infrastructure, backend-with-ML, analytics roles).
When in doubt, INCLUDE the listing — a later scoring stage filters precisely.

Include a listing ONLY if:
- Location mentions "{location}", "India", "Remote", "Anywhere", "Hybrid", or is unspecified

For each matching listing output a JSON object with these exact keys:
  "title"       : job title as written on the page (string)
  "location"    : location exactly as shown, or "Not specified" if truly absent (string)
  "url"         : use the most specific direct link to this posting from the LINKS section below;
                  only fall back to "{career_url}" if no better URL exists (string)
  "description" : first 1000 chars of the job summary or requirements; "" if unavailable (string)

Output ONLY a valid JSON array. If nothing matches, output [].
{links_section}

PAGE TEXT:
{page_text}"""

    try:
        items = extract_json_array(invoke_text(llm, prompt)) or []
    except Exception as exc:
        _log.debug("LLM extraction failed for %s: %s", company, exc)
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
        desc = str(item.get("description") or "").strip()[:1000]
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
    skills: List[str],
    location: str,
    progress: Progress,
    overall_task,
) -> Tuple[List[JobListing], List[str]]:
    name = company["name"]
    url = company["career_url"]

    page_text, page_links, error = await _fetch_page(url, browser, scrape_sem)

    if error:
        label = "timeout" if "timeout" in error.lower() else f"error ({error})"
        progress.console.print(f"  [red]✗[/red] [dim]{name}[/dim]: {label}")
        progress.advance(overall_task)
        return [], [f"career_scraper [{name}]: {error}"]

    async with llm_sem:
        listings = await asyncio.to_thread(
            _extract_jobs, name, url, page_text, page_links, inferred_field, skills, location
        )

    if listings:
        progress.console.print(
            f"  [green]✓[/green] [bold]{name}[/bold]: {len(listings)} listing(s)"
        )
    else:
        progress.console.print(f"  [yellow]–[/yellow] [dim]{name}[/dim]: no relevant listings")

    progress.advance(overall_task)
    return listings, []


# ── Async orchestrator ─────────────────────────────────────────────────────────

async def _scrape_all(
    companies: List[Company],
    inferred_field: str,
    skills: List[str],
    location: str,
) -> Tuple[List[JobListing], List[str]]:
    from playwright.async_api import async_playwright

    scrape_sem = asyncio.Semaphore(_MAX_SCRAPERS)
    llm_sem = asyncio.Semaphore(_MAX_LLM)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=_console,
        transient=False,
    ) as progress:
        overall_task = progress.add_task(
            f"[cyan]Scraping {len(companies)} career pages...", total=len(companies)
        )

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            tasks = [
                _process_company(
                    c, browser, scrape_sem, llm_sem,
                    inferred_field, skills, location, progress, overall_task
                )
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
    skills = resume_data.get("skills", [])
    location = state.get("location", "India")
    run_id = state.get("run_id", "")

    if not companies:
        return {"job_listings": [], "errors": ["career_scraper: no companies in state"]}

    listings, errors = asyncio.run(
        _scrape_all(companies, inferred_field, skills, location)
    )

    if listings:
        try:
            save_job_listings(listings, run_id=run_id)
        except Exception as exc:
            errors.append(f"career_scraper: DB save failed: {exc}")

    return {"job_listings": listings, "errors": errors}
