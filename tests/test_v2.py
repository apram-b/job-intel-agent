from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
import uuid
import pytest
from sqlalchemy import select, func
from job_intel.v2.storage import Repository
from job_intel.v2.models import CandidateProfile, SearchPreferences, ScanResult, JobListing, load_preferences
from job_intel.v2.sources import company_from_url
from job_intel.v2 import schema as s
from job_intel.v2 import intelligence as intel

AT = datetime(2026, 9, 19, 2, 30, tzinfo=timezone.utc)


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("TEST_POSTGRES_URL") else []))
def repository(tmp_path, resume, request):
    cleanup = None
    if request.param == "postgresql":
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import make_url

        admin = create_engine(os.environ["TEST_POSTGRES_URL"])
        schema_name = "test_" + uuid.uuid4().hex
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema_name}"'))
        url = make_url(os.environ["TEST_POSTGRES_URL"]).update_query_dict(
            {"options": "-csearch_path=" + schema_name}
        )
        repo = Repository(url.render_as_string(hide_password=False))
        cleanup = (admin, schema_name)
    else:
        repo = Repository("sqlite:///" + str(tmp_path / "v2.db"))
    repo.migrate()
    repo.save_profile("personal", CandidateProfile(**resume), SearchPreferences())
    yield repo
    repo.engine.dispose()
    if cleanup:
        admin, schema_name = cleanup
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
        admin.dispose()


@pytest.fixture
def company(repository):
    c = company_from_url("Acme", "https://job-boards.greenhouse.io/acme")
    repository.save_company(c)
    return c


@pytest.fixture
def listing(company):
    return JobListing(
        id="job1",
        company_id=company.id,
        company=company.name,
        source=company.source,
        source_id="123",
        title="Senior Data Engineer",
        location="Gurugram, India",
        url="https://example.com/jobs/123",
        description="Build production Python and AWS pipelines. Design Airflow orchestration and MLflow platforms. "
        * 6,
        description_complete=True,
    )


def scan(repository, company, listings, identifier="s1", at=AT, status="complete"):
    repository.apply_scan(identifier, company, ScanResult(status=status, jobs=listings), at=at)


def test_migrations_and_identical_scan_identity(repository, company, listing):
    repository.migrate()
    scan(repository, company, [listing, listing])
    scan(repository, company, [listing], "s2", AT + timedelta(days=1))
    scan(repository, company, [listing], "s2", AT + timedelta(days=1))
    assert len(repository.jobs()) == 1
    assert len(repository.observations(listing.id)) == 2
    assert [o["change"] for o in repository.observations(listing.id)] == ["new", "unchanged"]


def test_failures_partial_and_grace_preserve_jobs(repository, company, listing):
    scan(repository, company, [listing])
    scan(repository, company, [], "f1", AT + timedelta(days=1), "failed")
    scan(repository, company, [], "p1", AT + timedelta(days=2), "partial")
    assert repository.jobs()[0]["lifecycle"] == "OPEN"
    assert repository.jobs()[0]["missing_count"] == 0
    for i in range(3):
        scan(repository, company, [], f"missing{i}", AT + timedelta(days=3 + i))
    assert (
        repository.jobs()[0]["lifecycle"] == "MISSING"
    )  # Three scans but only 48 hours since first missing.
    scan(repository, company, [], "close", AT + timedelta(days=6))
    assert repository.jobs()[0]["lifecycle"] == "CLOSED"
    scan(repository, company, [listing], "return", AT + timedelta(days=7))
    assert repository.jobs()[0]["lifecycle"] == "REPOSTED"
    assert repository.jobs()[0]["missing_count"] == 0


def test_updates_preserve_identity_and_old_alias(repository, company, listing):
    scan(repository, company, [listing])
    changed = listing.model_copy(
        update={
            "id": "different-id",
            "description": listing.description + " New requirements",
            "url": "https://example.com/new-url",
        }
    )
    scan(repository, company, [changed], "s2")
    assert repository.jobs()[0]["id"] == listing.id
    assert repository.observations(listing.id)[-1]["change"] == "updated"
    with repository.engine.connect() as c:
        assert c.execute(select(func.count()).select_from(s.aliases)).scalar() == 2


def test_repost_with_different_id_is_linked_not_merged(repository, company, listing):
    scan(repository, company, [listing])
    for i in range(5):
        scan(repository, company, [], f"m{i}", AT + timedelta(days=i + 1))
    other = listing.model_copy(update={"id": "new", "source_id": "new", "url": "https://example.com/new"})
    scan(repository, company, [other], "repost", AT + timedelta(days=6))
    assert len(repository.jobs()) == 2
    assert next(r for r in repository.jobs() if r["id"] == "new")["possible_repost_of"] == listing.id


def test_transaction_rolls_back_invalid_company(repository, company, listing):
    broken = listing.model_copy(update={"id": "broken", "company_id": "other"})
    with pytest.raises(ValueError):
        scan(repository, company, [listing, broken])
    assert repository.jobs() == []
    assert repository.recent_scans() == []


def test_concurrent_monthly_reservations_cannot_overspend(repository):
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda _: repository.reserve_budget(500_000, at=AT), range(20)))
    assert sum(x is not None for x in ids) == 6
    assert repository.reserve_budget(500_000, at=AT + timedelta(days=35))


def test_lease_expiry_and_owner_isolation(repository):
    assert repository.acquire("scan", "a", at=AT)
    assert not repository.acquire("scan", "b", at=AT)
    repository.release("scan", "b")
    assert not repository.acquire("scan", "b", at=AT)
    assert repository.acquire("scan", "b", at=AT + timedelta(hours=2))


def test_yaml_json_compatibility_and_weight_validation(tmp_path):
    f = tmp_path / "prefs.json"
    f.write_text(json.dumps({"target_roles": ["AI Engineer"]}))
    assert load_preferences(f).roles() == ["AI Engineer"]
    f = tmp_path / "prefs.yaml"
    f.write_text("allow_india_remote: false\n")
    assert not load_preferences(f).allow_india_remote
    with pytest.raises(ValueError):
        SearchPreferences(priority_weights={"fit": 1, "confidence": 1, "strategy": 1})


def test_eligibility_saves_rejections_without_model(repository, company, listing, monkeypatch):
    listing = listing.model_copy(update={"title": "Junior Data Engineer"})
    scan(repository, company, [listing])
    monkeypatch.setattr(intel, "analyze", lambda *a: pytest.fail("Excluded job must not spend tokens"))
    intel.evaluate_queue(repository, verify=False, at=AT)
    e = repository.queue()[0]["evaluation"]
    assert e["status"] == "excluded" and e["action"] == "skip"
    assert "junior" in e["reasons"][0]


def analysis():
    return intel.Analysis(
        **{
            **{
                key: {
                    "rating": 3,
                    "job_quote": "Python",
                    "candidate_quote": "Python",
                    "explanation": "Relevant evidence",
                }
                for key in ("role", "technical", "seniority", "domain")
            },
            **{
                key: {"rating": 3, "job_quote": "AWS", "explanation": "Career exposure"}
                for key in ("platform", "ownership", "leadership", "scope")
            },
        }
    )


def test_cached_fit_survives_budget_exhaustion_confidence_refreshes(
    repository, company, listing, monkeypatch
):
    from job_intel.core.llm import RunLLM

    scan(repository, company, [listing])
    repository.verify_link(listing.id, True, AT)
    monkeypatch.setattr(intel, "analyze", lambda *args: analysis())
    config = RunLLM("openai", "test", "gpt-5-mini-2025-08-07")
    intel.evaluate_queue(repository, config=config, verify=False, at=AT)
    first = repository.queue()[0]["evaluation"]
    assert first["status"] == "scored" and first["action"] == "apply and consider outreach"
    monkeypatch.setattr(intel, "analyze", lambda *args: pytest.fail("Cache hit must not call a model"))
    config.max_calls = 0
    intel.evaluate_queue(repository, config=config, verify=False, at=AT + timedelta(days=4))
    second = repository.queue()[0]["evaluation"]
    assert second["cache_hit"] and second["fit"] == first["fit"]
    assert second["confidence"] < first["confidence"] and second["action"] == "verify"


def test_preferences_invalidate_cache(repository, company, listing, monkeypatch):
    from job_intel.core.llm import RunLLM

    scan(repository, company, [listing])
    monkeypatch.setattr(intel, "analyze", lambda *args: analysis())
    intel.evaluate_queue(repository, config=RunLLM("openai", "test", "model"), verify=False, at=AT)
    candidate, prefs = repository.profile()
    repository.save_profile("personal", candidate, prefs.model_copy(update={"must_have_skills": ["Rust"]}))
    intel.evaluate_queue(repository, verify=False, at=AT + timedelta(seconds=1))
    e = repository.queue()[0]["evaluation"]
    assert e["status"] == "review" and "Rust" in e["reasons"][0]


def test_invalid_candidate_evidence_fails(repository, company, listing, monkeypatch):
    from job_intel.core.llm import RunLLM, use_llm

    monkeypatch.setattr(intel, "_reserve", lambda *args: None)
    bad = analysis()
    bad.role.candidate_quote = "Invented achievement"
    monkeypatch.setattr(intel, "generate", lambda *args: bad)
    with use_llm(RunLLM("openai", "test", "model")), pytest.raises(ValueError, match="candidate evidence"):
        intel.analyze(repository, listing.model_dump(), *repository.profile())


def test_budget_requires_explicit_matching_model_prices(repository, monkeypatch):
    from job_intel.core.llm import RunLLM, use_llm, BudgetExceeded

    monkeypatch.delenv("JOB_INTEL_OPENAI_INPUT_USD_PER_MILLION", raising=False)
    with use_llm(RunLLM("openai", "test", "model")), pytest.raises(BudgetExceeded):
        intel._reserve(repository, {}, intel.Analysis)


def test_unknown_link_is_not_false(repository, company, listing):
    scan(repository, company, [listing])
    row = repository.jobs()[0]
    _, evidence = intel.confidence(row, repository.observations(listing.id), at=AT)
    assert evidence["apply_alive"] is None and "apply_link" in evidence["unknown"]


def test_export_rejects_personal_and_retains_snapshot(repository, tmp_path):
    from job_intel.v2.demo import export, seed_profile

    with pytest.raises(ValueError):
        export(repository, tmp_path / "public")
    seed_profile(repository)
    export(repository, tmp_path / "public")
    path = tmp_path / "public/data.json"
    before = path.read_text()
    assert export(repository, tmp_path / "public")["retained_previous"]
    assert path.read_text() == before and "not a real vacancy" in before


def test_legacy_import_preserves_history_and_notes(repository, stored_job, tmp_path, monkeypatch):
    import os
    from job_intel.db import store
    from job_intel.v2.import_legacy import import_legacy

    store.set_status("personal", stored_job["id"], "applied", "Private note", "2026-10-01")
    store.save_score("personal", {**stored_job, "score": 10}, "legacy-score")
    path = os.environ["JOB_INTEL_DB"]
    import_legacy(repository, path)
    import_legacy(repository, path)
    rows = repository.queue()
    assert len(rows) == 1 and rows[0]["id"] == stored_job["id"]
    assert rows[0]["application"]["notes"] == "Private note"
    assert rows[0]["application"]["status"] == "applied"
    assert rows[0]["evaluation"]["status"] == "legacy"
    assert rows[0]["evaluation"]["fit"] is None
    assert len(repository.observations(stored_job["id"])) == 1
    assert store.history("personal")[0]["notes"] == "Private note"


def test_scan_retry_same_identifier_is_idempotent(repository, company, listing):
    from job_intel.v2.workflow import scan_watchlist

    class Source:
        def discover_jobs(self, company):
            return ScanResult(status="complete", jobs=[listing])

    scan_watchlist(repository, source=Source(), scan_prefix="retry")
    scan_watchlist(repository, source=Source(), scan_prefix="retry")
    assert len(repository.observations(listing.id)) == 1


@pytest.mark.parametrize("provider", ["greenhouse", "lever"])
def test_fixture_connectors_preserve_apply_urls_and_provenance(provider, monkeypatch):
    import httpx
    from pathlib import Path
    from job_intel.v2 import sources

    payload = json.loads((Path(__file__).parent / "fixtures" / f"{provider}-v2.json").read_text())
    monkeypatch.setattr(sources, "throttled_get", lambda url: httpx.Response(200, json=payload))
    url = (
        "https://job-boards.greenhouse.io/acme" if provider == "greenhouse" else "https://jobs.lever.co/acme"
    )
    company = sources.company_from_url("Acme", url)
    result = sources.ATSSource().discover_jobs(company)
    assert result.status == "complete" and len(result.jobs) == 1
    assert result.jobs[0].source == company.source and result.jobs[0].source_hash
    assert result.jobs[0].description_complete
    if provider == "lever":
        assert result.jobs[0].apply_url.endswith("/apply")


def test_incomplete_feed_cannot_reconcile_missing(repository, company, listing, monkeypatch):
    import httpx
    from job_intel.v2 import sources

    scan(repository, company, [listing])
    monkeypatch.setattr(
        sources, "throttled_get", lambda url: httpx.Response(200, json={"jobs": [], "meta": {"total": 1}})
    )
    result = sources.ATSSource().discover_jobs(company)
    assert result.status == "failed"
    repository.apply_scan("broken", company, result)
    assert repository.jobs()[0]["lifecycle"] == "OPEN"


def test_public_snapshot_cannot_export_personal_scores_or_notes(repository, company, listing, monkeypatch):
    from job_intel.core.llm import RunLLM
    from job_intel.v2.demo import seed_profile, snapshot

    scan(repository, company, [listing])
    repository.set_application("personal", listing.id, "saved", "PRIVATE-CONTACT-SECRET")
    monkeypatch.setattr(intel, "analyze", lambda *args: analysis())
    intel.evaluate_queue(repository, config=RunLLM("openai", "test", "model"), verify=False, at=AT)
    seed_profile(repository)
    assert snapshot(repository)["jobs"] == []  # A personal assessment is never a demo assessment.
    intel.evaluate_queue(repository, "demo", config=RunLLM("openai", "test", "model"), verify=False, at=AT)
    result = snapshot(repository)
    assert len(result["jobs"]) == 1
    assert "PRIVATE-CONTACT-SECRET" not in json.dumps(result)
    assert "candidate_quote" not in json.dumps(result)
    assert "application" not in result["jobs"][0]


def test_queue_flags_changed_preferences_before_rescoring(repository, company, listing, monkeypatch):
    from job_intel.core.llm import RunLLM

    scan(repository, company, [listing])
    monkeypatch.setattr(intel, "analyze", lambda *args: analysis())
    intel.evaluate_queue(repository, config=RunLLM("openai", "test", "model"), verify=False, at=AT)
    candidate, prefs = repository.profile()
    repository.save_profile("personal", candidate, prefs.model_copy(update={"must_have_skills": ["Rust"]}))
    row = repository.queue()[0]
    assert row["evaluation"]["status"] == "pending"
    assert row["evaluation"]["priority"] is None


def test_pilot_gate_does_not_fabricate_time_or_human_labels(repository):
    from job_intel.v2.validation import pilot_report

    result = pilot_report(repository, at=AT)
    assert not result["ready_for_public_release"]
    assert result["reviewed_postings"] == 0


def test_role_family_edit_replaces_default_tracks():
    prefs = SearchPreferences(primary_roles=["AI Engineer"], secondary_roles=[], stretch_roles=[])
    assert prefs.roles() == ["AI Engineer"]
    assert SearchPreferences.model_validate(prefs.model_dump()).roles() == ["AI Engineer"]


def test_migrated_dashboard_shows_queue_and_private_controls(repository, company, listing, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    scan(repository, company, [listing])
    monkeypatch.setenv("JOB_INTEL_DATABASE_URL", repository.engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv("JOB_INTEL_MODE", "local")
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=15).run()
    assert not app.exception and not app.error
    assert "Senior Data Engineer" in [x.value for x in app.subheader]
    assert "Daily queue" in [x.label for x in app.tabs]
    assert any(x.label == "Skills" for x in app.text_input)

    role_field = next(x for x in app.text_input if x.label == "Primary role families")
    role_field.set_value("AI Engineer")
    next(x for x in app.button if x.label == "Save profile and preferences").click().run()
    assert not app.exception and not app.error
    assert repository.profile()[1].primary_roles == ["AI Engineer"]
