"""Deterministic eligibility checks precede model ranking."""

from __future__ import annotations
import re
from job_intel.core.models import SearchProfile

ALIASES = {
    "gurgaon": ["gurgaon", "gurugram"],
    "delhi ncr": ["delhi", "new delhi", "ncr", "noida", "gurgaon", "gurugram", "faridabad", "ghaziabad"],
    "bangalore": ["bangalore", "bengaluru"],
    "hyderabad": ["hyderabad"],
    "pune": ["pune"],
}
INDIA_CITIES = {x for group in ALIASES.values() for x in group} | {
    "mumbai",
    "chennai",
    "kolkata",
    "ahmedabad",
    "kochi",
}


def contains(text, phrase):
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"(?![a-z0-9])", text.lower()))


def aliases(city):
    city = city.lower()
    if city in ALIASES:
        return ALIASES[city]
    for values in ALIASES.values():
        if city in values:
            return values
    return [city]


def geography(job, profile: SearchProfile):
    location = job.get("location", "").lower()
    description = job.get("description", "").lower()
    restricted = re.search(
        r"(?:us|usa|united states|uk|united kingdom|europe|eu)[ -]only|(?:must|need to) (?:be |reside |live )?(?:based |located )?in (?:the )?(?:us|usa|united states|uk|united kingdom)",
        location + " " + description,
    )
    if restricted:
        return "ineligible", 0, "Posting explicitly restricts hiring outside India"
    preferred = any(contains(location, a) for city in profile.preferred_cities for a in aliases(city))
    secondary = any(contains(location, a) for city in profile.secondary_cities for a in aliases(city))
    india = contains(location, "india") or any(contains(location, c) for c in INDIA_CITIES)
    remote = contains(location, "remote")
    worldwide = any(contains(location, s) for s in ("worldwide", "anywhere", "global"))
    if remote:
        if not profile.allow_india_remote:
            return "ineligible", 0, "Remote work is disabled in your preferences"
        if india or worldwide:
            return "eligible", 2, "Remote location explicitly includes India or worldwide hiring"
        return "review", 0, "Remote hiring eligibility for India is not confirmed"
    if preferred:
        return "eligible", 3, "Preferred city or NCR alias matches"
    if secondary:
        return "eligible", 1, "Matches a secondary city"
    if not location or location in ("not specified", "hybrid", "india"):
        return "review", 0, "Exact work location needs confirmation"
    return "ineligible", 0, "Location does not match your configured cities"


def plausible_role(job, profile):
    title = job["title"].lower()
    if any(contains(title, t) for t in ("intern", "internship", "junior", "graduate", "trainee")):
        return False
    # Broad recall across the configured technical tracks; the LLM checks seniority.
    terms = {term for role in profile.target_roles for term in re.findall(r"[a-z]+", role.lower())} - {
        "senior",
        "lead",
        "principal",
        "engineer",
        "engineering",
        "of",
        "and",
    }
    return any(contains(title, t) for t in terms) or (
        "mlops" in terms and any(s in title for s in ("machine learning", "ml platform"))
    )
