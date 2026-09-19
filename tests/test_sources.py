import socket
import httpx
import pytest
from job_intel.sources import ats, web


def test_greenhouse_full_description(monkeypatch):
    def get(url):
        assert "content=true" in url
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 123,
                        "title": "Data Engineer",
                        "location": {"name": "India"},
                        "absolute_url": "https://example.com/jobs/123",
                        "content": "&lt;p&gt;Full description&lt;/p&gt;",
                    }
                ],
                "meta": {"total": 1},
            },
        )

    monkeypatch.setattr(web, "get", get)
    jobs = ats.fetch({"name": "Acme", "career_url": "https://job-boards.greenhouse.io/acme"})
    assert jobs[0]["description"] == "Full description" and jobs[0]["description_complete"]


def test_lever_paginates(monkeypatch):
    calls = []

    def get(url):
        calls.append(url)
        offset = 0 if "skip=0&" in url else 100
        length = 100 if offset == 0 else 1
        return httpx.Response(
            200,
            json=[
                {
                    "id": str(i + offset),
                    "text": "Data Engineer",
                    "categories": {"location": "India"},
                    "hostedUrl": f"https://example.com/jobs/{i + offset}",
                    "description": "Description",
                    "lists": [{"text": "Requirements", "content": "Python"}],
                    "additional": "More",
                }
                for i in range(length)
            ],
        )

    monkeypatch.setattr(web, "get", get)
    jobs = ats.fetch({"name": "Acme", "career_url": "https://jobs.lever.co/acme"})
    assert len(jobs) == 101 and len(calls) == 2
    assert "Requirements Python" in jobs[0]["description"]


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"])
def test_private_destinations_blocked(monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (ip, 443))])
    with pytest.raises(ValueError):
        web.validate_public_url("https://example.com/jobs")


def test_bad_schemes_and_tracking():
    for url in ("file:///etc/passwd", "http://user:password@example.com", "https://example.com:1234"):
        with pytest.raises(ValueError):
            web.canonical_url(url)
    assert (
        web.canonical_url("https://example.com/jobs?id=2&utm_source=x#top") == "https://example.com/jobs?id=2"
    )


def test_gzip_response_is_not_decoded_twice(monkeypatch):
    import gzip

    original_client = httpx.Client
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=gzip.compress(b'{"jobs":[]}'), headers={"content-encoding": "gzip"}
        )
    )
    monkeypatch.setattr(web, "validate_public_url", lambda url: url)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs))
    assert web.get("https://example.com/jobs").json() == {"jobs": []}


def test_redirect_destination_is_revalidated(monkeypatch):
    original_client = httpx.Client
    transport = httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
    )
    checked = []

    def validate(url):
        checked.append(url)
        if "127.0.0.1" in url:
            raise ValueError("Private destination")
        return url

    monkeypatch.setattr(web, "validate_public_url", validate)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs))
    with pytest.raises(ValueError, match="Private"):
        web.get("https://example.com/jobs")
    assert len(checked) == 2
