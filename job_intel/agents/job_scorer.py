"""Evidence-backed scores with eligibility gates and profile/content caching."""

from __future__ import annotations
import asyncio
from job_intel.core.models import SearchProfile, Assessment, fingerprint
from job_intel.core.llm import generate, model_identity, current
from job_intel.core.matching import geography, plausible_role, contains
from job_intel.db.store import cached_score, save_score, history

SCORER_VERSION = "evidence-v1"


def _score(job, resume, profile):
    stable = {k: v for k, v in job.items() if k not in ("scraped_at", "updated_at")}
    cache_key = fingerprint([stable, resume, profile.model_dump(), model_identity(), SCORER_VERSION])
    cached = cached_score(profile.profile_id, job["id"], cache_key)
    if cached:
        return {**cached, **job, "cached": True}
    eligibility, location_score, location_reason = geography(job, profile)
    result = {
        **job,
        "score": None,
        "assessment_status": "needs_review",
        "eligibility": eligibility,
        "score_reason": location_reason,
        "cached": False,
    }
    if eligibility == "ineligible" or not plausible_role(job, profile):
        result.update(assessment_status="ineligible", eligibility="ineligible")
    elif eligibility == "review" or len(job.get("description", "")) < 150:
        result["score_reason"] += "; full description and location evidence are required"
    else:
        try:
            assessment = generate(
                Assessment,
                "Assess relevance for the TARGET roles, not just the candidate's current title. Each dimension is 0–3: title (direct=3, adjacent=2, weak=1, unrelated=0), skills (strong=3, moderate=2, minor=1, absent=0), seniority (matched responsibility=3, acceptable stretch=2, large gap=1, incompatible=0). For each nonzero dimension, evidence must be a short EXACT quote from the job title or description. For zero scores explain absent evidence. Do not manufacture matches. Respect allow_stretch. Report missing requirements and uncertainty. Location is assessed separately by code.",
                {
                    "candidate": resume,
                    "preferences": profile.model_dump(),
                    "job": {"title": job["title"], "description": job["description"][:14000]},
                },
            )
            evidence_source = (job["title"] + " " + job["description"]).casefold()
            for dimension in (assessment.title_match, assessment.skill_overlap, assessment.seniority_fit):
                if dimension.score and dimension.evidence.casefold() not in evidence_source:
                    raise ValueError("Score evidence is not present in the posting")
            missing = [skill for skill in profile.must_have_skills if not contains(job["description"], skill)]
            dimensions = assessment.model_dump()
            dimensions["location_fit"] = {"score": location_score, "evidence": location_reason}
            result.update(
                score=location_score
                + assessment.title_match.score
                + assessment.skill_overlap.score
                + assessment.seniority_fit.score,
                dimensions=dimensions,
                score_reason=assessment.reason,
                assessment_status="scored",
                uncertainties=assessment.uncertainties,
                missing_must_haves=missing,
            )
            if missing or not job.get("description_complete", False):
                result.update(assessment_status="needs_review", eligibility="review")
                result["score_reason"] += "; verify incomplete source or missing must-have skills"
        except Exception:
            result.update(
                assessment_status="scoring_failed",
                score_reason="Could not obtain a validated, evidence-backed score",
            )
    if result["assessment_status"] != "scoring_failed":
        save_score(profile.profile_id, result, cache_key)
    return result


async def _score_all(jobs, resume, profile):
    sem = asyncio.Semaphore(3)

    async def one(job):
        async with sem:
            return await asyncio.to_thread(_score, job, resume, profile)

    return await asyncio.gather(*(one(j) for j in jobs))


def score_jobs_node(state):
    profile = SearchProfile.model_validate(state["profile"])
    statuses = {j["id"]: j["status"] for j in history(profile.profile_id)}
    jobs = [
        j
        for j in state.get("job_listings", [])
        if statuses.get(j["id"], "new") not in ("rejected", "applied", "interview", "offer", "closed")
        and plausible_role(j, profile)
    ]
    jobs.sort(key=lambda j: (geography(j, profile)[0] != "eligible", -geography(j, profile)[1], j["id"]))
    config = current()
    available = max(0, config.max_calls - config.calls - profile.draft_top_n)
    selected = jobs[: min(profile.max_jobs_to_score, available)]
    scored = asyncio.run(_score_all(selected, state["resume_data"], profile))
    ranked = sorted(
        [
            j
            for j in scored
            if j["assessment_status"] == "scored"
            and j["eligibility"] == "eligible"
            and j["score"] >= profile.min_score
        ],
        key=lambda j: (-j["score"], j["id"]),
    )[: profile.top_n]
    errors = [
        f"Scoring failed for {j['company']}: {j['title']}"
        for j in scored
        if j["assessment_status"] == "scoring_failed"
    ]
    if len(jobs) > len(selected):
        errors.append(f"Scoring budget reached: {len(jobs) - len(selected)} plausible jobs remain unscored")
    return {"scored_listings": scored, "ranked_listings": ranked, "errors": errors}
