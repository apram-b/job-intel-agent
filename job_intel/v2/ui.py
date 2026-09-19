"""Owner-only local Streamlit queue backed by the shared repository."""

import streamlit as st
from sqlalchemy import inspect
from job_intel.v2.storage import Repository
from job_intel.v2.models import SearchPreferences, CandidateProfile


def render():
    repo = Repository()
    if not inspect(repo.engine).has_table("v2_jobs"):
        st.info(
            "Your daily queue is ready to set up. Run the v2 migration and import your existing history; legacy searches remain available below."
        )
        return
    queue, watchlist, preferences, operations = st.tabs(
        ["Daily queue", "Companies", "Profile & preferences", "Scan health"]
    )
    with queue:
        st.subheader("Your opportunity queue")
        st.caption("Fit, hiring evidence and career value are separate. Applications remain your decision.")
        left, right = st.columns(2)
        search = left.text_input("Search company, role or location", key="v2_query")
        action = right.selectbox(
            "Next action", ["All", "apply and consider outreach", "verify", "review", "skip", "tracked"]
        )
        include_inactive = st.checkbox("Include closed or disabled sources", value=False)
        rows = repo.queue()
        if rows and not any(r["company_enabled"] for r in rows):
            st.info(
                "Saved history is preserved. Add or enable verified ATS companies to start the daily queue; use the checkbox above to inspect old sources."
            )
        if not rows:
            st.info("Add verified company boards, then run a watchlist scan.")
        for row in rows:
            job, evaluation = row["payload"], row["evaluation"]
            evaluation = evaluation or {
                "status": "pending",
                "action": "review",
                "fit": None,
                "confidence": None,
                "strategy": None,
                "priority": None,
                "reasons": ["Awaiting evaluation"],
            }
            if not include_inactive and (row["lifecycle"] == "CLOSED" or not row["company_enabled"]):
                continue
            if search.casefold() not in f"{job['company']} {job['title']} {job['location']}".casefold():
                continue
            if action != "All" and evaluation["action"] != action:
                continue
            with st.container(border=True):
                st.subheader(job["title"])
                st.write(f"{job['company']} · {job['location']}")
                cols = st.columns(4)
                for col, label, key in zip(
                    cols,
                    ["Fit", "Hiring confidence", "Career value", "Priority"],
                    ["fit", "confidence", "strategy", "priority"],
                ):
                    val = evaluation.get(key)
                    col.metric(label, "Pending" if val is None else f"{val:.0f}/100")
                st.write("Next action: **" + evaluation["action"] + "**")
                st.caption(
                    f"{row['lifecycle']} · Last seen {row['last_seen'][:16]} UTC · Evaluation {evaluation['status']}"
                )
                if st.button("Recheck availability", key="v2_verify_" + job["id"]):
                    from job_intel.v2.intelligence import recheck_link, evaluate_queue

                    with st.spinner("Checking current source evidence…"):
                        recheck_link(repo, row)
                        evaluate_queue(repo, verify=False)
                    st.rerun()
                st.link_button(
                    "View job / Apply", job.get("apply_url") or job["url"], key="v2_link_" + job["id"]
                )
                with st.expander("Why this recommendation"):
                    for reason in evaluation.get("reasons", []):
                        st.write(reason)
                    st.json(evaluation.get("evidence", {}))
                    if row["possible_repost_of"]:
                        st.info(
                            "Possible repost of another listing; review before treating it as a new opportunity."
                        )
                with st.expander("Observations and application notes"):
                    st.dataframe(repo.observations(job["id"]), hide_index=True)
                    from job_intel.db.store import STATUSES

                    old = row.get("application") or {}
                    with st.form("v2_track_" + job["id"]):
                        status = st.selectbox(
                            "Application status", STATUSES, index=STATUSES.index(old.get("status", "new"))
                        )
                        notes = st.text_area("Private notes", old.get("notes", ""))
                        follow = st.text_input("Follow-up date (YYYY-MM-DD)", old.get("follow_up") or "")
                        if st.form_submit_button("Save tracking"):
                            try:
                                repo.set_application("personal", job["id"], status, notes, follow)
                                st.rerun()
                            except ValueError as exc:
                                st.error(str(exc))
    with watchlist:
        st.subheader("Company watchlist")
        st.caption(
            "Discovery suggestions stay disabled until you enable them. Only complete ATS scans can close missing listings."
        )
        with st.form("add_company"):
            name = st.text_input("Company name")
            url = st.text_input("Greenhouse or Lever board URL")
            if st.form_submit_button("Add verified board"):
                from job_intel.v2.sources import company_from_url

                try:
                    repo.save_company(company_from_url(name, url))
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        for company in repo.companies():
            enabled = st.checkbox(company.name, value=company.enabled, key="enabled_" + company.id)
            if enabled != company.enabled:
                repo.enable_company(company.id, enabled)
                st.rerun()
            st.caption(f"{company.career_url} · {company.discovery_source}")
            tier = st.selectbox(
                "Company preference",
                ["primary", "secondary", "explore"],
                index=["primary", "secondary", "explore"].index(company.tier),
                key="tier_" + company.id,
            )
            if tier != company.tier:
                repo.save_company(company.model_copy(update={"tier": tier}))
                st.rerun()
    with preferences:
        import yaml

        stored = repo.profile()
        candidate, prefs = stored if stored else (None, SearchPreferences())
        base = candidate.model_dump() if candidate else {}

        def split(value):
            return [part.strip() for part in value.split(",") if part.strip()]

        st.caption(
            "Review your experience, then choose the roles you want next. These settings stay private."
        )
        with st.form("v2_settings"):
            st.subheader("Your experience")
            left, right = st.columns(2)
            name = left.text_input("Name", base.get("name", ""))
            current_role = right.text_input("Current role", base.get("current_role", ""))
            years = left.number_input(
                "Years of experience", 0.0, 70.0, float(base.get("years_experience", 0)), step=0.5
            )
            levels = ["junior", "mid", "senior", "lead", "principal", "unknown"]
            seniority = right.selectbox(
                "Current seniority", levels, index=levels.index(base.get("seniority_level", "unknown"))
            )
            skills = st.text_input(
                "Skills", ", ".join(base.get("skills", [])), help="Separate skills with commas"
            )
            stack = st.text_input("Tools and platforms", ", ".join(base.get("stack", [])))
            field = st.text_input("Professional field", base.get("inferred_field", ""))
            domains = st.text_input("Domain experience", ", ".join(base.get("domains", [])))
            achievements = st.text_area(
                "Achievements — one per line", "\n".join(base.get("achievements", []))
            )
            st.subheader("Your next role")
            primary = st.text_input(
                "Primary role families", ", ".join(prefs.primary_roles or prefs.target_roles)
            )
            secondary = st.text_input("Secondary role families", ", ".join(prefs.secondary_roles))
            stretch = st.text_input("Stretch role families", ", ".join(prefs.stretch_roles))
            left, right = st.columns(2)
            preferred = left.text_input("Preferred cities", ", ".join(prefs.preferred_cities))
            other = right.text_input("Other acceptable cities", ", ".join(prefs.secondary_cities))
            remote = left.checkbox("Include India-eligible remote roles", prefs.allow_india_remote)
            allow_stretch = right.checkbox("Include configured stretch roles", prefs.allow_stretch)
            work_modes = st.multiselect(
                "Work arrangements", ["remote", "hybrid", "onsite"], default=prefs.work_modes
            )
            target_levels = st.multiselect(
                "Target seniority",
                ["junior", "mid", "senior", "lead", "staff", "principal", "director", "head"],
                default=prefs.seniority,
            )
            required = st.text_input("Required skill evidence", ", ".join(prefs.must_have_skills))
            excluded = st.text_input("Exclude titles containing", ", ".join(prefs.excluded_roles))
            with st.expander("Ranking and lifecycle settings"):
                st.caption(
                    "Weights total 1. These advanced settings are also available in your YAML configuration."
                )
                advanced_keys = [
                    "priority_weights",
                    "strategic_weights",
                    "close_after_scans",
                    "close_after_hours",
                    "apply_fit",
                    "apply_confidence",
                    "max_jobs_to_score",
                ]
                advanced = st.text_area(
                    "Advanced settings",
                    yaml.safe_dump({k: prefs.model_dump()[k] for k in advanced_keys}, sort_keys=False),
                    height=260,
                )
            if st.form_submit_button("Save profile and preferences"):
                try:
                    new_candidate = CandidateProfile.model_validate(
                        {
                            **base,
                            "name": name,
                            "current_role": current_role,
                            "years_experience": years,
                            "seniority_level": seniority,
                            "skills": split(skills),
                            "stack": split(stack),
                            "inferred_field": field,
                            "domains": split(domains),
                            "achievements": [x.strip() for x in achievements.splitlines() if x.strip()],
                            "fictional": False,
                        }
                    )
                    rules = yaml.safe_load(advanced)
                    if not isinstance(rules, dict) or set(rules) - set(advanced_keys):
                        raise ValueError("Use only the displayed advanced setting names")
                    new_preferences = SearchPreferences.model_validate(
                        {
                            **prefs.model_dump(),
                            **rules,
                            "profile_id": "personal",
                            "target_roles": [],
                            "primary_roles": split(primary),
                            "secondary_roles": split(secondary),
                            "stretch_roles": split(stretch),
                            "preferred_cities": split(preferred),
                            "secondary_cities": split(other),
                            "allow_india_remote": remote,
                            "allow_stretch": allow_stretch,
                            "work_modes": work_modes,
                            "seniority": target_levels,
                            "must_have_skills": split(required),
                            "excluded_roles": split(excluded),
                        }
                    )
                    repo.save_profile("personal", new_candidate, new_preferences)
                    st.success("Saved. Your queue will flag older assessments until the next evaluation.")
                except (ValueError, yaml.YAMLError) as exc:
                    st.error(str(exc))
    with operations:
        st.dataframe(repo.recent_scans(), hide_index=True)
        st.caption(
            "Scheduled scans run at 08:00 IST. Source failures preserve prior listings. Model budget exhaustion leaves jobs pending."
        )
