import asyncio
import httpx
import pytest
from types import SimpleNamespace
from pydantic import BaseModel
from job_intel.agents import company_finder, career_scraper
from job_intel.core.llm import RunLLM, use_llm, collection_budget, generate, BudgetExceeded


def test_search_engine_cannot_override_source_filter(monkeypatch, profile):
    results = [
        {"href": "https://in.linkedin.com/jobs/data-engineer", "title": "Jobs"},
        {"href": "https://www.naukri.com/data-jobs", "title": "Jobs"},
        {"href": "https://example.com/careers", "title": "Careers"},
        {"href": "https://job-boards.greenhouse.io/acme/jobs/123", "title": "Data Engineer at Acme"},
        {"href": "https://job-boards.greenhouse.io/acme/jobs/456", "title": "MLOps at Acme"},
        {"href": "https://jobs.lever.co/other/123", "title": "ML Engineer at Other"},
    ]
    monkeypatch.setattr(company_finder, "_search", lambda query: results)
    output = company_finder.find_companies_node({"profile": profile.model_dump()})
    assert len(output["companies"]) == 2
    assert {c["name"] for c in output["companies"]} == {"Acme", "Other"}


def test_no_supported_results_is_explicit(monkeypatch, profile):
    monkeypatch.setattr(
        company_finder, "_search", lambda query: [{"href": "https://wellfound.com/role/data-engineer"}]
    )
    output = company_finder.find_companies_node({"profile": profile.model_dump()})
    assert output["companies"] == []
    assert "No supported employer boards" in output["errors"][0]


def test_aggregators_do_not_fetch_or_call_models(monkeypatch):
    monkeypatch.setattr(career_scraper.ats, "fetch", lambda *a: pytest.fail("Must not fetch"))
    with use_llm(RunLLM("openai", "fake", "model")) as config:
        output = career_scraper.scrape_careers_node(
            {"companies": [{"name": "LinkedIn", "career_url": "https://in.linkedin.com/jobs/data-jobs"}]}
        )
    assert output["source_checks"][0]["status"] == "unsupported"
    assert config.calls == 0


def test_extraction_budget_preserves_scoring_capacity(monkeypatch):
    import openai

    class Result(BaseModel):
        value: str

    class Client:
        def __init__(self, **kwargs):
            self.responses = SimpleNamespace(
                parse=lambda **k: SimpleNamespace(output_parsed=Result(value="ok"), usage=None)
            )

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(openai, "OpenAI", Client)
    with use_llm(RunLLM("openai", "fake", "model", max_calls=4, max_collection_calls=1)) as config:

        async def collect():
            with collection_budget():
                return await asyncio.to_thread(generate, Result, "extract", {})

        asyncio.run(collect())
        with collection_budget(), pytest.raises(BudgetExceeded):
            generate(Result, "extract", {})
        assert generate(Result, "score", {}).value == "ok"
        assert config.calls == 2


@pytest.mark.parametrize(
    "error,status,detail",
    [
        (BudgetExceeded("limit"), "budget_exhausted", "reserved for scoring"),
        (
            httpx.HTTPStatusError(
                "blocked", request=httpx.Request("GET", "https://example.com"), response=httpx.Response(403)
            ),
            "blocked",
            "HTTP 403",
        ),
    ],
)
def test_source_failures_are_actionable(monkeypatch, error, status, detail):
    def fail(*a):
        raise error

    monkeypatch.setattr(career_scraper.ats, "fetch", fail)
    with use_llm(RunLLM("openai", "fake", "model")):
        result = career_scraper.scrape_careers_node(
            {"companies": [{"name": "Acme", "career_url": "https://jobs.lever.co/acme"}]}
        )
    check = result["source_checks"][0]
    assert check["status"] == status and detail in check["detail"]
