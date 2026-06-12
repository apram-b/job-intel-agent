"""Streamlit front-end for the job-intel pipeline.

Usage:
    streamlit run app.py
"""
from __future__ import annotations

import tempfile
import time
import uuid
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from job_intel.core.graph import build_graph
from job_intel.db.store import clean_stale_listings

load_dotenv()

st.set_page_config(page_title="Job Intel Agent", page_icon="●", layout="wide")

# Pipeline nodes in execution order, with UI labels
_STAGES = [
    ("parse_resume", "Parsing resume"),
    ("find_companies", "Finding companies"),
    ("scrape_careers", "Scraping career pages"),
    ("score_jobs", "Scoring listings"),
    ("draft_outreach", "Drafting outreach"),
]


def _fmt_secs(seconds: float) -> str:
    if seconds >= 60:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    return f"{seconds:.1f}s"


def _run_pipeline(resume_path: str, location: str) -> dict:
    """Stream the graph node-by-node, updating a status widget per stage."""
    run_id = str(uuid.uuid4())
    graph = build_graph()

    state = {
        "resume_path": resume_path,
        "location": location,
        "run_id": run_id,
        "companies": [],
        "job_listings": [],
        "ranked_listings": [],
        "outreach_drafts": [],
        "errors": [],
    }

    result: dict = dict(state)
    stage_labels = dict(_STAGES)
    node_order = [name for name, _ in _STAGES]

    t_start = time.perf_counter()
    t_stage = t_start

    with st.status(f"{_STAGES[0][1]}…", expanded=True) as status:
        for update in graph.stream(state, stream_mode="updates"):
            for node_name, node_output in update.items():
                if node_output:
                    # errors accumulate; everything else overwrites
                    errs = node_output.get("errors")
                    if errs:
                        result["errors"] = result.get("errors", []) + errs
                    for k, v in node_output.items():
                        if k != "errors":
                            result[k] = v

                now = time.perf_counter()
                label = stage_labels.get(node_name, node_name)
                st.write(f"✓ {label} — {_fmt_secs(now - t_stage)}")
                t_stage = now

                # Show the next stage as running, with total elapsed time
                try:
                    next_label = _STAGES[node_order.index(node_name) + 1][1]
                    status.update(
                        label=f"{next_label}… ({_fmt_secs(now - t_start)} elapsed)"
                    )
                except (ValueError, IndexError):
                    pass

        total = time.perf_counter() - t_start
        status.update(
            label=f"Pipeline complete in {_fmt_secs(total)}",
            state="complete",
            expanded=True,
        )

    try:
        cleaned = clean_stale_listings(run_id)
        if cleaned:
            st.caption(f"Cleaned {cleaned} stale listing(s) from previous runs.")
    except Exception:
        pass

    return result


def _render_results(result: dict) -> None:
    resume = result.get("resume_data")
    if resume:
        st.subheader("Parsed Resume")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Name", resume["name"])
        c2.metric("Experience", f"{resume['years_experience']} yrs")
        c3.metric("Seniority", resume["seniority_level"])
        c4.metric("Field", resume["inferred_field"])
        st.markdown(f"**Current role:** {resume['current_role']}")
        st.markdown(f"**Skills:** {', '.join(resume['skills'])}")
        st.markdown(f"**Stack:** {', '.join(resume['stack'])}")
        st.divider()

    companies = result.get("companies", [])
    if companies:
        with st.expander(f"{len(companies)} Companies Targeted"):
            for c in companies:
                st.markdown(f"- [{c['name']}]({c['career_url']})")

    ranked = result.get("ranked_listings", [])
    listings = ranked if ranked else result.get("job_listings", [])
    if listings:
        st.subheader(f"{len(listings)} {'Top Ranked' if ranked else 'Relevant'} Job Listing(s)")
        for j in listings:
            score_badge = f" — {j['score']}/12" if "score" in j else ""
            with st.container(border=True):
                st.markdown(f"#### {j['title']}{score_badge}")
                st.markdown(f"**{j['company']}** · {j['location']}")
                st.link_button("View listing →", j["url"])
                if j.get("description"):
                    with st.expander("Description"):
                        st.write(j["description"])
                if j.get("score_reason"):
                    st.caption(j["score_reason"])
    else:
        st.markdown("*No relevant job listings found.*")

    drafts = result.get("outreach_drafts", [])
    if drafts:
        st.subheader(f"{len(drafts)} Outreach Draft(s)")
        for d in drafts:
            st.markdown(f"**{d['company']}** — {d['title']}")
            st.code(d["message"], language=None, wrap_lines=True)

    errors = result.get("errors", [])
    if errors:
        with st.expander(f"{len(errors)} error(s)"):
            for e in errors:
                st.text(f"- {e}")


def main() -> None:
    st.title("Job Intel Agent")
    st.caption(
        "Upload your resume, pick a location — the agents find companies, scrape "
        "career pages, rank the best-fit roles, and draft your outreach."
    )

    with st.sidebar:
        st.header("Inputs")
        uploaded = st.file_uploader("Resume (PDF)", type=["pdf"])
        location = st.text_input("Target location", placeholder='e.g. "Bangalore"')
        run = st.button("Find Jobs", type="primary", use_container_width=True,
                        disabled=not (uploaded and location.strip()))

    if run and uploaded and location.strip():
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(uploaded.getvalue())
            tmp_path = tmp.name
        try:
            result = _run_pipeline(tmp_path, location.strip())
            st.session_state["result"] = result
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    if "result" in st.session_state:
        _render_results(st.session_state["result"])
    elif not run:
        st.markdown("*Upload a resume PDF and enter a location in the sidebar to get started.*")


if __name__ == "__main__":
    main()
