from job_intel.core import graph
from job_intel.core.llm import RunLLM
from job_intel.core.pipeline import run_pipeline
from job_intel.core.models import Assessment
from job_intel.agents import career_scraper, job_scorer
from job_intel.db import store


def test_bad_resume_stops_before_discovery(monkeypatch, profile):
    monkeypatch.setattr(
        graph, "find_companies_node", lambda s: (_ for _ in ()).throw(AssertionError("Must not run"))
    )
    result = run_pipeline(profile, RunLLM("openai", "test", "model"), resume_path="/missing.pdf")
    assert result["status"] == "failed" and result["errors"]
    assert not result["ranked_listings"]


def test_full_pipeline_persists_then_reuses_scores(monkeypatch, profile, resume, job):
    calls = []
    monkeypatch.setattr(career_scraper.ats, "fetch", lambda company: [job])

    def score(*a):
        calls.append(1)
        return Assessment.model_validate(
            {
                "title_match": {"score": 3, "evidence": "Senior Data Engineer"},
                "skill_overlap": {"score": 3, "evidence": "Python and AWS"},
                "seniority_fit": {"score": 3, "evidence": "Senior engineer"},
                "reason": "Strong match",
            }
        )

    monkeypatch.setattr(job_scorer, "generate", score)
    args = dict(resume_data=resume, companies=[{"name": "Acme", "career_url": "https://jobs.lever.co/acme"}])
    first = run_pipeline(profile, RunLLM("openai", "test", "model"), **args)
    second = run_pipeline(profile, RunLLM("openai", "test", "model"), **args)
    assert first["status"] == second["status"] == "complete"
    assert len(first["new_matches"]) == 1 and second["new_matches"] == []
    assert len(calls) == 1 and len(store.history(profile.profile_id)) == 1
    store.set_status(profile.profile_id, job["id"], "applied")
    third = run_pipeline(profile, RunLLM("openai", "test", "model"), **args)
    assert not third["ranked_listings"] and len(calls) == 1


def test_source_failure_is_not_empty_success(monkeypatch, profile, resume, stored_job):
    def fail(company):
        raise RuntimeError("no connection")

    monkeypatch.setattr(career_scraper.ats, "fetch", fail)
    result = run_pipeline(
        profile,
        RunLLM("openai", "test", "model"),
        resume_data=resume,
        companies=[{"name": "Acme", "career_url": "https://jobs.lever.co/acme"}],
    )
    assert result["status"] == "failed" and result["source_checks"][0]["status"] == "failed"
    assert len(store.history(profile.profile_id)) == 1
