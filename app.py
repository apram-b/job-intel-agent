"""Local-first Streamlit UI. Public mode requires verified OIDC sign-in."""

from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv
from job_intel.core import access
from job_intel.core.models import SearchProfile, Source
from job_intel.core.llm import settings
from job_intel.core.pipeline import run_pipeline
from job_intel.core.public import run_public
from job_intel.db import store
from job_intel.core.presentation import public_result

load_dotenv()
st.set_page_config(page_title="Job Intel", page_icon="🔎", layout="wide")


def render_theme():
    light = st.sidebar.toggle("Light mode", value=False, key="light_mode")
    bg, surface, text, muted, border, accent = (
        ("#F7F9FC", "#FFFFFF", "#17212D", "#526171", "#D4DDE7", "#176B58")
        if light
        else ("#0E1117", "#171E29", "#F0F4F8", "#B0BDCE", "#364152", "#65D6B4")
    )
    st.markdown(
        f"""<style>
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"],
    [data-testid="stSidebar"], [data-testid="stSidebarContent"] {{
        background: {bg}; color: {text}; color-scheme: {"light" if light else "dark"};
        --text-color: {text}; --background-color: {bg}; --secondary-background-color: {surface};
    }}
    .stApp h1, .stApp h2, .stApp h3, .stApp p, .stApp label,
    .stApp summary, .stApp [data-testid="stWidgetLabel"], .stApp [role="tab"] {{ color: {text}; }}
    .stApp [data-testid="stCaptionContainer"] p {{ color: {muted}; }}
    .stApp input, .stApp textarea, .stApp [data-baseweb="input"],
    .stApp [data-baseweb="base-input"], .stApp [data-baseweb="select"] > div,
    .stApp [data-testid="stFileUploaderDropzone"], [role="listbox"], [role="option"] {{
        background: {surface}; color: {text};
    }}
    .stApp button[kind="secondary"], .stApp a[kind="secondary"] {{
        background: {surface}; color: {text}; border-color: {border};
    }}
    .stApp [data-testid="stExpander"] details,
    .stApp [data-testid="stVerticalBlockBorderWrapper"] {{ border-color: {border}; }}
    .stApp [data-testid="stExpander"] summary {{ background: {surface}; color: {text}; }}
    .stApp a {{ color: {accent}; }}
    </style>""",
        unsafe_allow_html=True,
    )


def main():
    public = os.getenv("JOB_INTEL_MODE", "local") == "public"
    if not public and st.get_option("server.address") not in ("localhost", "127.0.0.1", "::1"):
        st.error(
            "Local mode requires a loopback server address. Configure public mode and sign-in before exposing this app."
        )
        st.stop()
    render_theme()
    st.title("Job Intel")
    st.caption("Find relevant roles. Keep the evidence. Track your next move.")
    if not public:
        workspace = st.sidebar.radio("Workspace", ["Daily queue", "Legacy search"], index=0)
        if workspace == "Daily queue":
            from job_intel.v2.ui import render

            render()
            return
    claims, user_id = {}, "personal"
    if public:
        issuer = os.getenv("JOB_INTEL_OIDC_ISSUER", "")
        if not issuer:
            st.error("Public sign-in is not configured. Contact the owner.")
            st.stop()
        if not st.user.is_logged_in:
            st.info("Sign in for three free searches. After that, continue with your own API key.")
            if st.button("Sign in"):
                st.login()
            st.stop()
        claims = dict(st.user)
        try:
            user_id = access.identity(claims, issuer)
        except access.AccessDenied as exc:
            st.error(str(exc))
            if st.button("Sign out"):
                st.logout()
            st.stop()
        if st.session_state.get("identity") != user_id:
            for session_key in list(st.session_state):
                if session_key != "light_mode":
                    del st.session_state[session_key]
            st.session_state["identity"] = user_id
        if st.sidebar.button("Sign out"):
            st.session_state.clear()
            st.logout()
        st.sidebar.caption(f"{access.remaining(user_id)} of 3 free runs remaining")
    diagnostics = not public or access.is_admin(user_id)
    if public and diagnostics:
        if st.sidebar.toggle("Admin view", value=False):
            st.subheader("Administration")
            overview = access.admin_overview(user_id)
            for title, rows in overview.items():
                with st.expander(title.capitalize(), expanded=title == "runs"):
                    st.dataframe(rows, use_container_width=True)
    if st.session_state.pop("clear_key", False):
        st.session_state.pop("own_key", None)
    search_tab, history_tab = st.tabs(["Find jobs", "Saved history"])
    with search_tab:
        with st.expander("Search preferences", expanded=True):
            roles = st.text_input("Target roles", value=", ".join(SearchProfile().target_roles))
            left, right = st.columns(2)
            cities = left.text_input("Preferred cities", value="Gurgaon, Delhi NCR")
            secondary = right.text_input(
                "Other cities you would consider", value="Bangalore, Hyderabad, Pune"
            )
            remote = left.checkbox("Include remote roles eligible in India", value=True)
            stretch = right.checkbox("Include reasonable seniority stretch roles", value=True)
            must = left.text_input("Must-have skills", help="Missing evidence sends a job to manual review")
            minimum = right.slider("Minimum fit score", 0, 12, 8)
            drafts = left.checkbox("Prepare outreach drafts for the best two matches", value=False)
        with st.expander("Career sources (optional)"):
            st.caption(
                "One employer and career URL per line, separated by |. Greenhouse and Lever boards provide the most reliable coverage. Leave blank to discover sources."
            )
            source_text = st.text_area("Sources", placeholder="Employer | https://jobs.lever.co/board-name")
        upload = st.file_uploader(
            "Your resume", type=["pdf"], help="Text-based PDF, maximum 5 MB and 10 pages"
        )
        funding, provider, key = "own", os.getenv("JOB_INTEL_PROVIDER", "openai"), None
        if public:
            options = (
                ["Use a free run", "Use my own API key"]
                if access.remaining(user_id) > 0
                else ["Use my own API key"]
            )
            choice = st.radio("How to run this search", options)
            funding = "sponsored" if choice == "Use a free run" else "own"
        if not public or funding == "own":
            provider = st.selectbox("Model provider", ["openai", "anthropic"])
            key = st.text_input(
                "Your API key" if public else "API key (optional if configured locally)",
                type="password",
                key="own_key",
            )
            st.caption(
                "Your key is held only in server session memory and used for this provider. It is not saved to the job database. Clear it with the button below."
            )
            if st.button("Clear API key"):
                st.session_state["clear_key"] = True
                st.rerun()
        consent = st.checkbox(
            "I understand my resume and selected job text are sent to the selected model provider, and my job history is stored by this app."
        )
        if public:
            st.caption(
                "A free run is consumed when a valid search starts, including failed or interrupted searches. Refreshing does not refund it. Shared daily limits may apply."
            )
        start = st.button("Find matching jobs", type="primary", disabled=not upload or not consent)
        if start:

            def split(value):
                return [x.strip() for x in value.split(",") if x.strip()]

            try:
                profile = SearchProfile(
                    profile_id=user_id,
                    target_roles=split(roles),
                    preferred_cities=split(cities),
                    secondary_cities=split(secondary),
                    allow_india_remote=remote,
                    allow_stretch=stretch,
                    must_have_skills=split(must),
                    min_score=minimum,
                    draft_top_n=2 if drafts else 0,
                )
                sources = []
                for line in source_text.splitlines():
                    if line.strip():
                        name, url = line.split("|", 1)
                        sources.append(Source(name=name, career_url=url).model_dump())
                if len(sources) > 15:
                    raise ValueError("Use at most 15 career sources")
                if upload.size > 5_000_000:
                    raise ValueError("Resume must be smaller than 5 MB")
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as file:
                    file.write(upload.getvalue())
                    path = file.name
                try:
                    st.session_state.pop("result", None)
                    with st.status("Searching…", expanded=True) as progress:

                        def stage(name, values):
                            label = name.replace("_", " ").capitalize()
                            st.write(
                                label + (" — needs attention" if values.get("errors") else " — finished")
                            )

                        if public:
                            result = run_public(
                                claims,
                                profile,
                                resume_path=path,
                                funding=funding,
                                own_key=key,
                                own_provider=provider,
                                companies=sources,
                                on_stage=stage,
                            )
                        else:
                            result = run_pipeline(
                                profile,
                                settings(provider, key or None),
                                resume_path=path,
                                companies=sources,
                                on_stage=stage,
                            )
                        progress.update(
                            label="Search " + result["status"],
                            state="complete" if result["status"] == "complete" else "error",
                        )
                    st.session_state["result"] = result
                    st.session_state["clear_key"] = True
                finally:
                    Path(path).unlink(missing_ok=True)
                st.rerun()
            except (ValueError, access.AccessDenied) as exc:
                st.error(str(exc))
            except Exception:
                st.error("Search could not start. Check the local configuration or contact the owner.")
        result = st.session_state.get("result")
        if result:
            st.subheader(f"{len(result['ranked_listings'])} qualified matches")
            st.caption(f"{len(result['new_matches'])} new or changed · Run {result['status']}")
            with st.expander("Parsed resume — review for accuracy"):
                st.json(result["resume_data"])
            for job in result["ranked_listings"]:
                with st.container(border=True):
                    st.subheader(job["title"])
                    st.write(f"{job['company']} · {job['location']} · {job['score']}/12")
                    st.write(job["score_reason"])
                    st.link_button("View job / Apply ↗", job["url"])
                    with st.expander("Fit evidence"):
                        st.json(job.get("dimensions", {}))
            review = [j for j in result.get("scored_listings", []) if j.get("assessment_status") != "scored"]
            with st.expander(f"Needs review or excluded ({len(review)})"):
                for job in review:
                    st.write(f"{job['company']} — {job['title']}: {job['score_reason']}")
                    if job.get("url"):
                        st.link_button("View job / Apply ↗", job["url"], key="review_" + job["id"])
            if diagnostics:
                with st.expander("Source coverage and run details"):
                    st.json(result["source_checks"])
                    for error in result["errors"]:
                        st.warning(error)
                    st.json(result["usage"])
            elif result["status"] != "complete":
                st.info("This search is incomplete. You can review the available jobs or try again later.")
            for draft in result["outreach_drafts"]:
                st.text_area(
                    f"Draft: {draft['company']} — {draft['title']}",
                    draft["message"],
                    height=160,
                    key="draft_" + draft["job_id"],
                )
            st.download_button(
                "Download results",
                json.dumps(result if diagnostics else public_result(result), indent=2),
                "job-intel-results.json",
                "application/json",
            )
    with history_tab:
        items = store.history(user_id)
        if not items:
            st.info("Your job history will appear here after the first search.")
        for job in items:
            with st.expander(f"{job['company']} — {job['title']} · {job['status']}"):
                st.write(job["location"])
                st.link_button("View job / Apply ↗", job["url"], key="link_" + job["id"])
                st.caption(
                    f"First seen {job['first_seen'][:10]} · Last seen {job['last_seen'][:10]}. Absence from later searches does not mean closed."
                )
                with st.form("track_" + job["id"]):
                    status = st.selectbox("Status", store.STATUSES, index=store.STATUSES.index(job["status"]))
                    notes = st.text_area("Notes", value=job.get("notes") or "")
                    follow = st.text_input("Follow-up date (YYYY-MM-DD)", value=job.get("follow_up") or "")
                    if st.form_submit_button("Save"):
                        try:
                            store.set_status(user_id, job["id"], status, notes, follow or None)
                            st.rerun()
                        except ValueError:
                            st.error("Use a valid follow-up date in YYYY-MM-DD format")
        with st.expander("Recent searches"):
            runs = store.recent_runs(user_id)
            st.json(
                runs if diagnostics else [{k: v for k, v in run.items() if k != "errors"} for run in runs]
            )


if __name__ == "__main__":
    main()
