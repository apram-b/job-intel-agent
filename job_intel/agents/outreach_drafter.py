"""Draft only for qualified jobs. No sending capability is present."""

from pydantic import Field
from job_intel.core.models import Model, SearchProfile
from job_intel.core.llm import generate


class Message(Model):
    message: str = Field(min_length=1, max_length=2500)


def draft_outreach_node(state):
    profile = SearchProfile.model_validate(state["profile"])
    drafts, errors = [], []
    for job in state.get("ranked_listings", [])[: profile.draft_top_n]:
        if (
            job.get("assessment_status") != "scored"
            or job.get("eligibility") != "eligible"
            or job["score"] < profile.min_score
        ):
            continue
        try:
            message = generate(
                Message,
                "Draft a concise outreach body of 100–150 words in three paragraphs. Mention only achievements present in the candidate profile. Reference specific role requirements; do not invent company news, performance metrics or personal connections. End with a low-pressure call to action. This is a draft for user review.",
                {
                    "candidate": state["resume_data"],
                    "job": {
                        "title": job["title"],
                        "company": job["company"],
                        "description": job["description"][:10000],
                    },
                },
            )
            drafts.append(
                {
                    "job_id": job["id"],
                    "company": job["company"],
                    "title": job["title"],
                    "message": message.message,
                }
            )
        except Exception:
            errors.append("Outreach draft failed for " + job["company"])
    return {"outreach_drafts": drafts, "errors": errors}
