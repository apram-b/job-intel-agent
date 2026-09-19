"""Bounded public HTTP reads. Validate destinations and every redirect."""

from __future__ import annotations
import ipaddress
import socket
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
import httpx
from bs4 import BeautifulSoup


def canonical_url(url):
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("Only public HTTP(S) URLs without credentials are supported")
    if parts.port not in (None, 80, 443):
        raise ValueError("Nonstandard destination port")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in ("gclid", "fbclid")
    ]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", urlencode(sorted(query)), "")
    )


def validate_public_url(url):
    url = canonical_url(url)
    host = urlsplit(url).hostname
    addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Private, local or reserved network destinations are blocked")
    return url


def get(url, *, max_bytes=5_000_000):
    with httpx.Client(
        timeout=25,
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": "JobIntel/0.2 (personal job research)"},
    ) as client:
        for _ in range(5):
            url = validate_public_url(url)
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("Source response exceeds download limit")
                    chunks.append(chunk)
                headers = dict(response.headers)
                headers.pop("content-encoding", None)
                headers.pop("content-length", None)
                return httpx.Response(
                    response.status_code,
                    content=b"".join(chunks),
                    headers=headers,
                    request=response.request,
                )
    raise ValueError("Too many source redirects")


def text(html):
    import html as html_module

    soup = BeautifulSoup(html_module.unescape(html), "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)
