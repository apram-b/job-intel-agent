from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_local_app_loads(monkeypatch):
    monkeypatch.setenv("JOB_INTEL_MODE", "local")
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=15).run()
    assert not app.exception and not app.error
    assert app.title[0].value == "Job Intel"


def test_public_mode_fails_closed_without_issuer(monkeypatch):
    monkeypatch.setenv("JOB_INTEL_MODE", "public")
    monkeypatch.delenv("JOB_INTEL_OIDC_ISSUER", raising=False)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=15).run()
    assert not app.exception
    assert "not configured" in app.error[0].value
    assert not app.get("file_uploader")


def test_theme_toggle_preserves_session(monkeypatch):
    monkeypatch.setenv("JOB_INTEL_MODE", "local")
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()
    assert app.toggle(key="light_mode").value is False
    app.toggle(key="light_mode").set_value(True).run()
    assert not app.exception
    assert app.toggle(key="light_mode").value is True


def test_public_results_hide_diagnostics_and_show_review_links(monkeypatch):
    import streamlit as st
    from job_intel.core.access import identity

    class User(dict):
        is_logged_in = True

    claims = User(iss="issuer", sub="visitor", email_verified=True)
    monkeypatch.setattr(st, "user", claims)
    monkeypatch.setenv("JOB_INTEL_MODE", "public")
    monkeypatch.setenv("JOB_INTEL_OIDC_ISSUER", "issuer")
    monkeypatch.delenv("JOB_INTEL_ADMIN_IDS", raising=False)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py")
    app.session_state["identity"] = identity(claims, "issuer")
    app.session_state["result"] = {
        "ranked_listings": [],
        "new_matches": [],
        "status": "partial",
        "resume_data": {},
        "scored_listings": [
            {
                "id": "review1",
                "company": "Example",
                "title": "Engineer",
                "score_reason": "Review needed",
                "assessment_status": "needs_review",
                "url": "https://www.linkedin.com/jobs/view/123",
            }
        ],
        "source_checks": [],
        "errors": ["private diagnostic"],
        "usage": {},
        "outreach_drafts": [],
    }
    app.run()
    assert not app.exception
    assert "Source coverage and run details" not in [x.label for x in app.expander]
    assert len(app.get("link_button")) == 1
    assert "linkedin.com/jobs/view/123" in str(app.get("link_button")[0].proto)
