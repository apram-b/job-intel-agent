"""Server-side trial admission; no credentials enter persistent pipeline state."""

from __future__ import annotations
import os
import uuid
from job_intel.core import access
from job_intel.core.llm import settings
from job_intel.core.models import SearchProfile, Source
from job_intel.sources.ats import board
from job_intel.core.pipeline import run_pipeline
from job_intel.agents.resume_parser import extract_pdf_text


def run_public(
    claims, profile, *, resume_path, funding, own_key=None, own_provider=None, companies=None, on_stage=None
):
    user_id = access.identity(claims, os.getenv("JOB_INTEL_OIDC_ISSUER", ""))
    if funding not in ("sponsored", "own"):
        raise access.AccessDenied("Choose free runs or your own key")
    if funding == "own" and not (own_key and own_key.strip()):
        raise access.AccessDenied("Enter your own API key; the owner's key will not be used")
    # Configuration errors and malformed uploads are caught before consuming credit.
    config = settings(own_provider, own_key) if funding == "own" else settings()
    sources = [Source.model_validate(c).model_dump() for c in (companies or [])]
    if len(sources) > 15 or any(board(c["career_url"]) is None for c in sources):
        raise ValueError("Public searches support up to 15 Greenhouse or Lever board URLs")
    extract_pdf_text(resume_path)
    values = profile.model_dump()
    values.update(
        profile_id=user_id,
        max_jobs_to_score=min(profile.max_jobs_to_score, 20),
        draft_top_n=min(profile.draft_top_n, 2),
    )
    profile = SearchProfile.model_validate(values)
    config.max_calls = 30
    config.allow_generic_sources = False
    request_id = str(uuid.uuid4())
    access.reserve(user_id, request_id, sponsored=funding == "sponsored")
    try:
        return run_pipeline(profile, config, resume_path=resume_path, companies=sources, on_stage=on_stage)
    finally:
        access.release(request_id)
