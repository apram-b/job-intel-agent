from concurrent.futures import ThreadPoolExecutor
import pytest
from job_intel.core import access


def test_three_lifetime_runs_survive_reconnects_and_restarts():
    for i in range(3):
        access.reserve("alice", str(i), sponsored=True)
        access.release(str(i))
    assert access.remaining("alice") == 0
    with pytest.raises(access.AccessDenied):
        access.reserve("alice", "fourth", sponsored=True)
    access.reserve("alice", "own", sponsored=False)
    access.release("own")
    assert access.remaining("alice") == 0


def test_parallel_admission_cannot_exceed_three(monkeypatch):
    monkeypatch.setenv("JOB_INTEL_MAX_ACTIVE_RUNS", "100")

    def attempt(i):
        try:
            access.reserve("alice", str(i), sponsored=True)
            access.release(str(i))
            return True
        except access.AccessDenied:
            return False

    with ThreadPoolExecutor(max_workers=12) as pool:
        assert sum(pool.map(attempt, range(30))) <= 3
    assert access.remaining("alice") >= 0


def test_replay_and_concurrent_tabs_rejected():
    access.reserve("alice", "same", sponsored=True)
    with pytest.raises(access.AccessDenied):
        access.reserve("alice", "same", sponsored=True)
    with pytest.raises(access.AccessDenied):
        access.reserve("alice", "new-tab", sponsored=True)
    access.release("same")
    with pytest.raises(access.AccessDenied):
        access.reserve("alice", "same", sponsored=True)


def test_abandoned_run_is_not_refunded():
    access.reserve("alice", "old", sponsored=True, timestamp=1)
    access.reserve("alice", "new", sponsored=True, timestamp=4000)
    assert access.remaining("alice") == 1


def test_shared_daily_budget(monkeypatch):
    monkeypatch.setenv("JOB_INTEL_DAILY_FREE_RUNS", "1")
    access.reserve("alice", "a", sponsored=True)
    access.release("a")
    with pytest.raises(access.AccessDenied):
        access.reserve("bob", "b", sponsored=True)
    access.reserve("bob", "own", sponsored=False)


def test_verified_identity_is_not_email_or_browser_based():
    issuer = "https://accounts.google.com"
    a = access.identity(
        {"iss": issuer, "sub": "123", "email_verified": True, "email": "old@example.com"}, issuer
    )
    b = access.identity(
        {"iss": issuer, "sub": "123", "email_verified": True, "email": "new@example.com"}, issuer
    )
    assert a == b
    for claims in (
        {},
        {"iss": "evil", "sub": "123", "email_verified": True},
        {"iss": issuer, "sub": "123", "email_verified": False},
    ):
        with pytest.raises(access.AccessDenied):
            access.identity(claims, issuer)


def test_missing_personal_key_never_falls_back(monkeypatch, profile):
    from job_intel.core.public import run_public

    monkeypatch.setenv("JOB_INTEL_OIDC_ISSUER", "issuer")
    monkeypatch.setenv("OPENAI_API_KEY", "owner-secret")
    with pytest.raises(access.AccessDenied, match="owner's key"):
        run_public(
            {"iss": "issuer", "sub": "alice", "email_verified": True},
            profile,
            resume_path="unused",
            funding="own",
            own_key="",
        )


def test_public_runner_uses_own_key_after_free_quota(monkeypatch, profile):
    from job_intel.core import public

    issuer = "https://accounts.google.com"
    claims = {"iss": issuer, "sub": "alice", "email_verified": True}
    monkeypatch.setenv("JOB_INTEL_OIDC_ISSUER", issuer)
    monkeypatch.setenv("OPENAI_API_KEY", "owner-secret")
    user = access.identity(claims, issuer)
    for i in range(3):
        access.reserve(user, str(i), sponsored=True)
        access.release(str(i))
    seen = []
    monkeypatch.setattr(public, "extract_pdf_text", lambda path: "valid")

    def run(profile, config, **kwargs):
        seen.append((profile.profile_id, config.api_key, config.max_calls, config.allow_generic_sources))
        return {"status": "complete"}

    monkeypatch.setattr(public, "run_pipeline", run)
    public.run_public(
        claims, profile, resume_path="fake", funding="own", own_key="personal-secret", own_provider="openai"
    )
    assert seen == [(user, "personal-secret", 30, False)]
    assert access.remaining(user) == 0


def test_public_failures_consume_credit_without_saving_key(monkeypatch, profile):
    from job_intel.core import public
    from job_intel.db import store

    issuer = "issuer"
    monkeypatch.setenv("JOB_INTEL_OIDC_ISSUER", issuer)
    monkeypatch.setenv("OPENAI_API_KEY", "owner-secret")
    claims = {"iss": issuer, "sub": "alice", "email_verified": True}
    user = access.identity(claims, issuer)
    monkeypatch.setattr(public, "extract_pdf_text", lambda path: "valid")

    def fail(*args, **kwargs):
        raise RuntimeError("failed")

    monkeypatch.setattr(public, "run_pipeline", fail)
    with pytest.raises(RuntimeError):
        public.run_public(claims, profile, resume_path="fake", funding="sponsored")
    assert access.remaining(user) == 2
    with store.connection() as db:
        assert "owner-secret" not in "\n".join(db.iterdump())
        assert db.execute("SELECT state FROM admissions").fetchone()[0] == "finished"


def test_invalid_upload_does_not_consume_credit(monkeypatch, profile):
    from job_intel.core.public import run_public

    monkeypatch.setenv("JOB_INTEL_OIDC_ISSUER", "issuer")
    monkeypatch.setenv("OPENAI_API_KEY", "owner-secret")
    claims = {"iss": "issuer", "sub": "alice", "email_verified": True}
    with pytest.raises(ValueError):
        run_public(claims, profile, resume_path="missing.pdf", funding="sponsored")
    assert access.remaining(access.identity(claims, "issuer")) == 3


def test_expired_signed_identity_requires_new_login():
    with pytest.raises(access.AccessDenied, match="expired"):
        access.identity({"iss": "issuer", "sub": "alice", "email_verified": True, "exp": 1}, "issuer")


def test_admin_access_is_explicit_and_server_checked(monkeypatch):
    monkeypatch.setenv("JOB_INTEL_ADMIN_IDS", "owner-id")
    assert access.is_admin("owner-id")
    assert not access.is_admin("visitor-id")
    with pytest.raises(access.AccessDenied):
        access.admin_overview("visitor-id")
    assert set(access.admin_overview("owner-id")) == {"runs", "sources", "usage"}
