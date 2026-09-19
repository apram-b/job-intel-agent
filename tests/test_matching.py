import pytest
from job_intel.core.matching import geography
from job_intel.core.models import Assessment
from job_intel.core.llm import RunLLM, use_llm
from job_intel.agents import job_scorer


@pytest.mark.parametrize(
    "location,status,score",
    [
        ("Gurugram, India", "eligible", 3),
        ("Noida, India (Hybrid)", "eligible", 3),
        ("Bengaluru, India", "eligible", 1),
        ("Remote — India", "eligible", 2),
        ("Remote — US only", "ineligible", 0),
        ("Remote", "review", 0),
        ("Not specified", "review", 0),
        ("London, UK", "ineligible", 0),
    ],
)
def test_geography(location, status, score, job, profile):
    actual = geography({**job, "location": location}, profile)
    assert actual[:2] == (status, score)


def assessment():
    return Assessment.model_validate(
        {
            "title_match": {"score": 3, "evidence": "Senior Data Engineer"},
            "skill_overlap": {"score": 3, "evidence": "Python and AWS"},
            "seniority_fit": {"score": 3, "evidence": "Senior engineer"},
            "reason": "Direct role and stack evidence",
        }
    )


def test_invalid_dimension_is_rejected():
    data = assessment().model_dump()
    data["title_match"]["score"] = 99
    with pytest.raises(ValueError):
        Assessment.model_validate(data)


def test_cached_scoring_avoids_model_calls(stored_job, profile, resume, monkeypatch):
    calls = []
    monkeypatch.setattr(job_scorer, "generate", lambda *a: calls.append(1) or assessment())
    with use_llm(RunLLM("openai", "test", "test-model")):
        first = job_scorer._score(stored_job, resume, profile)
        second = job_scorer._score(stored_job, resume, profile)
    assert first["score"] == 12 and second["cached"] and len(calls) == 1


def test_unsupported_evidence_is_failure(stored_job, profile, resume, monkeypatch):
    data = assessment().model_dump()
    data["title_match"]["evidence"] = "invented job title"
    monkeypatch.setattr(job_scorer, "generate", lambda *a: Assessment.model_validate(data))
    with use_llm(RunLLM("openai", "test", "test-model")):
        result = job_scorer._score(stored_job, resume, profile)
    assert result["score"] is None and result["assessment_status"] == "scoring_failed"


def test_unknown_remote_never_calls_model(stored_job, profile, resume, monkeypatch):
    monkeypatch.setattr(job_scorer, "generate", lambda *a: pytest.fail("No model call expected"))
    with use_llm(RunLLM("openai", "test", "test-model")):
        result = job_scorer._score({**stored_job, "location": "Remote"}, resume, profile)
    assert result["eligibility"] == "review" and result["score"] is None
