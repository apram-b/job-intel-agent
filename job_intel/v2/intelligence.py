"""Evidence-backed independent fit, hiring confidence and career-value assessments."""

from __future__ import annotations
import json
import math
import os
import re
import uuid
from datetime import timedelta
from pydantic import Field
from job_intel.core.models import Model, fingerprint
from job_intel.core.matching import geography, contains
from job_intel.core.llm import generate, current, BudgetExceeded
from job_intel.sources import web
from job_intel.v2.models import ScoreEvaluation, version, utcnow
from job_intel.v2.storage import moment

EVALUATOR_VERSION = "v2-evidence-1"
CONFIDENCE_VERSION = "confidence-1"


class FitComponent(Model):
    rating: int = Field(ge=0, le=4)
    job_quote: str
    candidate_quote: str
    explanation: str


class StrategyComponent(Model):
    rating: int = Field(ge=0, le=4)
    job_quote: str
    explanation: str


class Analysis(Model):
    role: FitComponent
    technical: FitComponent
    seniority: FitComponent
    domain: FitComponent
    platform: StrategyComponent
    ownership: StrategyComponent
    leadership: StrategyComponent
    scope: StrategyComponent


def eligibility(job, candidate, prefs):
    title = job["title"].lower()
    for role in prefs.excluded_roles:
        if contains(title, role):
            return "excluded", [f"Excluded role: {role}"], 0
    if job.get("work_mode", "unknown") not in prefs.work_modes + ["unknown"]:
        return "excluded", ["Work mode is not allowed"], 0
    if job.get("work_mode", "unknown") == "unknown" and set(prefs.work_modes) != {
        "remote",
        "hybrid",
        "onsite",
    }:
        return "review", ["Work mode is not confirmed"], 0
    terms = {t for role in prefs.roles() for t in re.findall(r"[a-z]+", role.lower())} - {
        "senior",
        "lead",
        "principal",
        "engineer",
        "engineering",
        "of",
        "and",
    }
    if not any(contains(title, t) for t in terms):
        return "excluded", ["Title does not match a configured role family"], 0
    if not prefs.allow_stretch and any(
        contains(title, x) for x in ("staff", "principal", "director", "head")
    ):
        return "excluded", ["Seniority stretch is disabled"], 0
    explicit_level = next(
        (
            x
            for x in ("principal", "staff", "director", "head", "lead", "senior", "junior")
            if contains(title, x)
        ),
        None,
    )
    if (
        explicit_level
        and explicit_level not in prefs.seniority
        and not (prefs.allow_stretch and any(contains(title, r) for r in prefs.stretch_roles))
    ):
        return "excluded", [f"Seniority {explicit_level} is outside the configured levels"], 0
    min_years = re.search(r"(?:minimum|at least)\s+(\d+)\s*\+?\s*years", job.get("description", ""), re.I)
    if min_years and int(min_years[1]) > candidate.years_experience + 5:
        return (
            "excluded",
            ["Explicit minimum experience exceeds candidate experience by more than five years"],
            0,
        )
    geo, location_score, reason = geography(job, prefs)
    if geo == "ineligible":
        return "excluded", [reason], 0
    if geo == "review":
        return "review", [reason], 0
    missing = [x for x in prefs.must_have_skills if not contains(job.get("description", ""), x)]
    if missing:
        return "review", ["Missing required skill evidence: " + ", ".join(missing)], location_score
    if not job.get("description_complete") or len(job.get("description", "")) < 150:
        return "review", ["A complete job description is required"], location_score
    return "eligible", [reason], location_score


def confidence(row, observations, related_count=0, at=None):
    at = at or utcnow()
    valid = [o for o in observations if o["evidence"].get("direct_ats")]
    recently_seen = at - moment(row["last_seen"]) <= timedelta(hours=48)
    direct = bool(valid) and row["lifecycle"] in ("OPEN", "REPOSTED") and recently_seen
    link_current = bool(row["verified_at"]) and at - moment(row["verified_at"]) <= timedelta(hours=24)
    alive = row["apply_alive"] if link_current else None
    text = row["payload"]["description"].lower()
    specific = len(text) >= 400 and any(
        w in text for w in ("responsibil", "you will", "build", "design", "team")
    )
    first_age = (at - moment(row["first_seen"])).days
    points = {
        "direct_ats": 40 if direct else 0,
        "apply_link": 20 if alive else 0,
        "first_seen_recently": 10 if first_age <= 14 else 0,
        "repeated_observations": 10 if len(valid) >= 2 else 0,
        "specific_description": 10 if specific else 0,
        "related_openings": 10 if related_count else 0,
    }
    cautions = []
    if first_age > 90 and not any(o["change"] == "updated" for o in observations):
        points["long_unchanged"] = -5
        cautions.append("Long unchanged listing; age alone does not establish inactivity")
    if sum(o["change"] == "reposted" for o in observations) >= 2:
        points["repost_cycles"] = -15
        cautions.append("Repeated close/repost cycles")
    if any(x in text for x in ("evergreen", "future opportunities", "talent pool")):
        points["evergreen"] = -15
        cautions.append("Description may refer to ongoing talent collection")
    if alive is False:
        cautions.append("Apply URL returned a definitive unavailable response")
    return max(0, min(100, sum(points.values()))), {
        "version": CONFIDENCE_VERSION,
        "components": points,
        "direct_ats": direct,
        "apply_alive": alive,
        "verified_at": row["verified_at"],
        "last_seen": row["last_seen"],
        "first_seen": row["first_seen"],
        "unknown": ["apply_link"] if alive is None else [],
        "cautions": cautions,
    }


def recheck_link(repo, row, at=None):
    import httpx

    at = at or utcnow()
    if row["verified_at"] and at - moment(row["verified_at"]) < timedelta(hours=24):
        return
    try:
        response = web.get(row["payload"].get("apply_url") or row["payload"]["url"])
        # A generic HTTP 200 is only link reachability, never proof that hiring is active.
        alive = True if response.status_code == 200 else None
    except httpx.HTTPStatusError as exc:
        alive = False if exc.response.status_code in (404, 410) else None
    except (httpx.HTTPError, ValueError, OSError):
        alive = None
    repo.verify_link(row["id"], alive, at)
    row.update(apply_alive=alive, verified_at=at.isoformat())


def _reserve(repo, payload, schema):
    config = current()
    # Rates must be explicitly configured and reviewed before paid v2 work.
    prefix = "JOB_INTEL_" + config.provider.upper()
    input_rate = os.getenv(prefix + "_INPUT_USD_PER_MILLION")
    output_rate = os.getenv(prefix + "_OUTPUT_USD_PER_MILLION")
    priced_model = os.getenv(prefix + "_PRICED_MODEL")
    if not input_rate or not output_rate or priced_model != config.model:
        raise BudgetExceeded("Configure current rates for this exact model before paid evaluation")
    rates = [float(input_rate), float(output_rate)]
    if not all(math.isfinite(x) and x > 0 for x in rates):
        raise BudgetExceeded("Model rates must be positive finite numbers")
    # Same input byte ceiling as the provider adapter; byte count exceeds token count.
    amount = math.ceil(62_000 * rates[0] + 4096 * rates[1])
    limit = min(3_000_000, int(float(os.getenv("JOB_INTEL_MONTHLY_MODEL_USD", "3")) * 1_000_000))
    if not repo.reserve_budget(amount, limit_microusd=limit):
        raise BudgetExceeded("Monthly model budget exhausted")


def analyze(repo, job, candidate, prefs):
    instruction = (
        "Rate each fit and career-value component 0–4 (0 absent, 1 weak, 2 moderate, 3 strong, 4 exceptional). "
        "Use only evidence in the supplied data. Each nonzero fit component requires a short exact quote from "
        "both the job title/description and candidate. Each nonzero strategy component requires an exact job quote. "
        "Empty quotes are allowed only for zero ratings. Explain uncertainty. Do not infer compensation. "
        "Role fit uses target roles; platform means ML/AI platform exposure; scope means concrete business scope."
    )
    payload = {
        "candidate": candidate.model_dump(),
        "preferences": prefs.model_dump(),
        "job": {"title": job["title"], "description": job["description"][:14000]},
    }
    config = current()
    if config.calls >= config.max_calls:
        raise BudgetExceeded("Run model allowance exhausted")
    _reserve(repo, payload, Analysis)
    analysis = generate(Analysis, instruction, payload)
    source = (job["title"] + " " + job["description"][:14000]).casefold()
    candidate_text = json.dumps(candidate.model_dump(), ensure_ascii=False).casefold()
    for name, component in analysis:
        if component.rating:
            if not component.job_quote.strip() or component.job_quote.casefold() not in source:
                raise ValueError(f"Unsupported posting evidence in {name}")
            if isinstance(component, FitComponent) and (
                not component.candidate_quote.strip()
                or component.candidate_quote.casefold() not in candidate_text
            ):
                raise ValueError(f"Unsupported candidate evidence in {name}")
    return analysis


def _evaluate_queue(repo, profile_id="personal", *, config=None, verify=True, at=None):
    from contextlib import nullcontext
    from job_intel.core.llm import use_llm

    stored = repo.profile(profile_id)
    if not stored:
        return {"evaluated": 0, "pending": 0, "error": "No reviewed candidate profile configured"}
    candidate, prefs = stored
    company_map = {x.id: x for x in repo.companies()}
    rows = repo.queue(profile_id)
    cv, pv = version(candidate), version(prefs)
    from job_intel.core.llm import DEFAULT_MODELS

    provider = os.getenv("JOB_INTEL_PROVIDER", "openai")
    configured_model = os.getenv(
        "JOB_INTEL_" + provider.upper() + "_MODEL", DEFAULT_MODELS.get(provider, "unknown")
    )
    model = config.provider + ":" + config.model if config else provider + ":" + configured_model
    pending, count, failed = 0, 0, 0
    with use_llm(config) if config else nullcontext():
        for row in rows:
            at_job = at or utcnow()
            job = row["payload"]
            state, reasons, location_score = eligibility(job, candidate, prefs)
            if not row["company_enabled"]:
                state, reasons = "review", ["Company is disabled; enable it after checking its source"]
            if row["lifecycle"] in ("CLOSED", "MISSING", "UNVERIFIED"):
                state, reasons = "review", ["Listing availability requires a fresh complete source scan"]
            app = row.get("application")
            suppressed = app and app["status"] in ("rejected", "applied", "interview", "offer", "closed")
            if verify and state == "eligible" and not suppressed:
                recheck_link(repo, row, at_job)
            observations = repo.observations(row["id"])
            related = sum(
                r["id"] != row["id"]
                and r["company_id"] == row["company_id"]
                and r["lifecycle"] in ("OPEN", "REPOSTED")
                for r in rows
            )
            conf, conf_evidence = confidence(row, observations, related, at_job)
            company = company_map[row["company_id"]]
            key = fingerprint([row["content_hash"], cv, pv, EVALUATOR_VERSION, model, company.tier])
            result = ScoreEvaluation(
                id=str(uuid.uuid4()),
                job_id=row["id"],
                profile_id=profile_id,
                candidate_version=cv,
                preferences_version=pv,
                evaluator_version=EVALUATOR_VERSION,
                cache_key=key,
                evaluated_at=at_job,
                eligibility=state,
                status="excluded" if state == "excluded" else "review",
                action="skip" if state == "excluded" else "verify",
                confidence=conf,
                reasons=reasons,
                evidence={"confidence": conf_evidence, "job_content_hash": row["content_hash"]},
            )
            cached = repo.cached_evaluation(profile_id, row["id"], key) if state == "eligible" else None
            if cached:
                result.fit, result.strategy = cached["fit"], cached["strategy"]
                result.evidence.update({k: v for k, v in cached["evidence"].items() if k != "confidence"})
                result.status, result.cache_hit = "scored", True
            elif state == "eligible" and not suppressed:
                if config is None or count >= prefs.max_jobs_to_score:
                    result.status = "pending"
                    result.reasons.append("Waiting for model configuration or evaluation budget")
                else:
                    try:
                        analysis = analyze(repo, job, candidate, prefs)
                        count += 1
                        fit_points = sum(
                            getattr(analysis, k).rating / 4 * w
                            for k, w in {"role": 20, "technical": 25, "seniority": 15, "domain": 10}.items()
                        )
                        fit_points += location_score / 3 * 10
                        result.fit = round(fit_points / 80 * 100, 2)
                        strategy = {
                            k: getattr(analysis, k).rating / 4 * 100
                            for k in ("platform", "ownership", "leadership", "scope")
                        }
                        strategy["company"] = {"primary": 100, "secondary": 60, "explore": 20}[company.tier]
                        result.strategy = round(
                            sum(strategy[k] * w for k, w in prefs.strategic_weights.items()), 2
                        )
                        result.evidence.update(
                            components=analysis.model_dump(),
                            location_points=location_score / 3 * 10,
                            company_tier=company.tier,
                        )
                        result.status = "scored"
                    except BudgetExceeded as exc:
                        result.status = "pending"
                        result.reasons.append(str(exc))
                    except (RuntimeError, ValueError):
                        result.status = "failed"
                        result.reasons.append(
                            "Model evaluation failed evidence validation or provider request; retry is safe"
                        )
            if result.status == "scored":
                result.priority = round(
                    result.fit * prefs.priority_weights["fit"]
                    + conf * prefs.priority_weights["confidence"]
                    + result.strategy * prefs.priority_weights["strategy"],
                    2,
                )
                if conf_evidence["apply_alive"] is not True or conf < prefs.apply_confidence:
                    result.action = "verify"
                elif result.fit >= prefs.apply_fit:
                    result.action = "apply and consider outreach"
                else:
                    result.action = "review"
            if suppressed:
                result.action = "tracked"
                result.reasons.append("Already tracked: " + app["status"])
            pending += result.status == "pending"
            failed += result.status == "failed"
            repo.save_evaluation(result)
    return {"evaluated": len(rows), "pending": pending, "failed": failed}


def evaluate_queue(repo, profile_id="personal", *, config=None, verify=True, at=None):
    owner = str(uuid.uuid4())
    if not repo.acquire("evaluation:" + profile_id, owner, minutes=60):
        return {"status": "busy", "evaluated": 0, "pending": 0}
    try:
        return _evaluate_queue(repo, profile_id, config=config, verify=verify, at=at)
    finally:
        repo.release("evaluation:" + profile_id, owner)
