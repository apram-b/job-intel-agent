import pytest
from job_intel.db import store
from job_intel.core.models import fingerprint


def test_empty_failed_run_preserves_history(stored_job, profile):
    store.start_run("empty", profile.model_dump())
    store.save_job_listings([], run_id="empty")
    store.finish_run("empty", "failed", ["source failed"])
    assert len(store.history(profile.profile_id)) == 1


def test_observations_and_application_survive_changes(stored_job, profile):
    store.set_status(profile.profile_id, stored_job["id"], "applied", "Sent application", "2026-10-01")
    store.start_run("run2", profile.model_dump())
    store.save_job_listings([stored_job], run_id="run2")
    assert store.changes("run2")[stored_job["id"]] == "unchanged"
    store.start_run("run3", profile.model_dump())
    store.save_job_listings([{**stored_job, "description": "Changed requirements"}], run_id="run3")
    item = store.history(profile.profile_id)[0]
    assert store.changes("run3")[stored_job["id"]] == "changed"
    assert item["status"] == "applied" and item["follow_up"] == "2026-10-01"
    assert item["first_seen"] <= item["last_seen"]


def test_profiles_isolated(stored_job, profile):
    assert store.history("other") == []
    with pytest.raises(ValueError):
        store.set_status("other", stored_job["id"], "rejected")


def test_requisitions_do_not_collide(job):
    from job_intel.sources.ats import listing

    other = listing(
        job["company"],
        job["source"],
        "456",
        job["title"],
        job["location"],
        "https://example.com/jobs/456",
        job["description"],
    )
    assert job["id"] != other["id"]


def test_cache_is_profile_and_content_specific(stored_job, profile):
    key = fingerprint(stored_job)
    store.save_score(profile.profile_id, {**stored_job, "score": 9}, key)
    assert store.cached_score(profile.profile_id, stored_job["id"], key)["score"] == 9
    assert store.cached_score("other", stored_job["id"], key) is None
    assert store.cached_score(profile.profile_id, stored_job["id"], "changed") is None


def test_legacy_tables_are_not_removed(tmp_path):
    with store.connection() as db:
        db.execute("CREATE TABLE job_listings (id TEXT)")
        db.execute("INSERT INTO job_listings VALUES ('old')")
    with store.connection() as db:
        assert db.execute("SELECT id FROM job_listings").fetchone()[0] == "old"


def test_first_seen_is_new_for_each_profile(stored_job, profile):
    store.start_run("other-run", {**profile.model_dump(), "profile_id": "other"})
    store.save_job_listings([stored_job], run_id="other-run")
    assert store.changes("other-run")[stored_job["id"]] == "new"
    assert len(store.history("other")) == 1


def test_previously_seen_job_can_be_newly_qualified(stored_job, profile):
    assert store.record_shortlist(profile.profile_id, []) == []
    scored = {**stored_job, "score": 9, "cached": False}
    assert len(store.record_shortlist(profile.profile_id, [scored])) == 1
    assert store.record_shortlist(profile.profile_id, [{**scored, "cached": True}]) == []
    assert len(store.record_shortlist(profile.profile_id, [{**scored, "score": 10}])) == 1
