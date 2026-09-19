"""Aggregator listings are not employer-owned career sources."""

from urllib.parse import urlsplit

AGGREGATORS = (
    "naukri.com",
    "cutshort.io",
    "wellfound.com",
    "linkedin.com",
    "hirist.tech",
    "indeed.com",
    "internshala.com",
    "glassdoor.com",
    "glassdoor.co.in",
    "apna.co",
    "foundit.in",
    "monster.com",
    "ziprecruiter.com",
)


def is_aggregator(url):
    host = (urlsplit(url).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in AGGREGATORS)
