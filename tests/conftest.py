import pytest
from job_intel.core.models import SearchProfile
from job_intel.sources.ats import listing
from job_intel.db import store


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_INTEL_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("JOB_INTEL_DAILY_FREE_RUNS", "20")
    monkeypatch.setenv("JOB_INTEL_MAX_ACTIVE_RUNS", "3")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def profile():
    return SearchProfile()


@pytest.fixture
def resume():
    return {
        "name": "Sample Candidate",
        "current_role": "Data Engineer",
        "years_experience": 5.0,
        "skills": ["Python", "Airflow"],
        "stack": ["AWS", "MLflow"],
        "inferred_field": "Data Engineering",
        "seniority_level": "senior",
        "achievements": [],
    }


@pytest.fixture
def job():
    return listing(
        "Acme",
        "greenhouse:acme",
        "123",
        "Senior Data Engineer",
        "Gurugram, India",
        "https://example.com/jobs/123",
        "Own production Python and AWS data pipelines. Build Airflow orchestration and operate reliable MLflow infrastructure. Senior engineer with responsibility for design, delivery and production support.",
        description_complete=True,
    )


@pytest.fixture
def stored_job(job, profile):
    store.start_run("run1", profile.model_dump())
    store.save_job_listings([job], run_id="run1")
    return job
