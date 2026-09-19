"""Shared CLI/UI runner with durable observations and explicit run outcomes."""

from __future__ import annotations
import uuid
from job_intel.core.graph import build_graph
from job_intel.core.llm import use_llm
from job_intel.core.models import Resume, Source
from job_intel.db import store


def run_pipeline(profile, config, *, resume_path=None, resume_data=None, companies=None, on_stage=None):
    if resume_data is not None:
        resume_data = Resume.model_validate(resume_data).model_dump()
    sources = [Source.model_validate(c).model_dump() for c in (companies or [])]
    if len(sources) > 15:
        raise ValueError("Use at most 15 sources per run")
    run_id = str(uuid.uuid4())
    result = {
        "run_id": run_id,
        "profile": profile.model_dump(),
        "resume_path": resume_path or "",
        "resume_data": resume_data or {},
        "companies": sources,
        "job_listings": [],
        "scored_listings": [],
        "ranked_listings": [],
        "outreach_drafts": [],
        "source_checks": [],
        "errors": [],
    }
    store.start_run(run_id, profile.model_dump(), resume_data)
    status = "failed"
    with use_llm(config):
        try:
            for update in build_graph().stream(result, stream_mode="updates"):
                for stage, values in update.items():
                    errors = values.get("errors", [])
                    result["errors"].extend(errors)
                    result.update({k: v for k, v in values.items() if k != "errors"})
                    if stage == "parse_resume" and result["resume_data"]:
                        store.save_parsed_resume(run_id, profile.model_dump(), result["resume_data"])
                    if stage == "scrape_careers":
                        store.save_job_listings(result["job_listings"], run_id=run_id)
                        store.save_source_checks(run_id, result["source_checks"])
                    if stage == "draft_outreach":
                        store.save_drafts(run_id, result["outreach_drafts"])
                    if on_stage:
                        on_stage(stage, values)
            checks = result["source_checks"]
            successful = any(c["status"] in ("ok", "partial") for c in checks)
            status = ("partial" if result["errors"] else "complete") if successful else "failed"
        except Exception as exc:
            result["errors"].append(f"Run interrupted ({type(exc).__name__}); saved observations retained")
        finally:
            store.finish_run(run_id, status, result["errors"])
    result["status"] = status
    result["changes"] = store.changes(run_id)
    result["usage"] = {
        "provider": config.provider,
        "model": config.model,
        "calls": config.calls,
        "input_tokens": config.input_tokens,
        "output_tokens": config.output_tokens,
    }
    result["new_matches"] = store.record_shortlist(profile.profile_id, result["ranked_listings"])
    return result
