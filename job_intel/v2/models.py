"""Versioned contracts. Missing evidence is represented explicitly."""

from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from pydantic import Field, model_validator, field_validator
from job_intel.core.models import Model, Resume, SearchProfile, fingerprint


def utcnow():
    return datetime.now(timezone.utc)


def version(model):
    return fingerprint(model.model_dump(mode="json", exclude={"profile_id"}))


class CandidateProfile(Resume):
    schema_version: int = 2
    resume_version: str = "reviewed-1"
    domains: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    fictional: bool = False


class SearchPreferences(SearchProfile):
    schema_version: int = 2
    target_roles: list[str] = Field(default_factory=list)
    primary_roles: list[str] = Field(default_factory=lambda: ["Senior Data Engineer", "MLOps Engineer"])
    secondary_roles: list[str] = Field(
        default_factory=lambda: ["ML Platform Engineer", "ML Infrastructure Engineer"]
    )
    stretch_roles: list[str] = Field(
        default_factory=lambda: ["Lead Data Engineer", "Lead ML Platform Engineer"]
    )
    excluded_roles: list[str] = Field(
        default_factory=lambda: ["intern", "internship", "junior", "graduate", "trainee"]
    )
    seniority: list[str] = Field(default_factory=lambda: ["senior", "lead"])
    work_modes: list[Literal["remote", "hybrid", "onsite"]] = Field(
        default_factory=lambda: ["remote", "hybrid", "onsite"]
    )
    strategic_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "platform": 0.30,
            "ownership": 0.25,
            "leadership": 0.15,
            "scope": 0.15,
            "company": 0.15,
        }
    )
    priority_weights: dict[str, float] = Field(
        default_factory=lambda: {"fit": 0.5, "confidence": 0.25, "strategy": 0.25}
    )
    close_after_scans: int = Field(default=3, ge=2)
    close_after_hours: int = Field(default=72, ge=24)
    apply_fit: float = Field(default=70, ge=0, le=100)
    apply_confidence: float = Field(default=60, ge=0, le=100)

    @field_validator("target_roles")
    @classmethod
    def nonempty_roles(cls, value):
        if any(not item.strip() for item in value):
            raise ValueError("Role names cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_weights(self):
        if not self.roles():
            raise ValueError("Configure at least one role family")
        for weights, keys in [
            (self.priority_weights, {"fit", "confidence", "strategy"}),
            (self.strategic_weights, {"platform", "ownership", "leadership", "scope", "company"}),
        ]:
            if (
                set(weights) != keys
                or any(not 0 <= x <= 1 for x in weights.values())
                or abs(sum(weights.values()) - 1) > 0.00001
            ):
                raise ValueError("Weights must contain the documented components and total 1")
        return self

    def roles(self):
        return list(
            dict.fromkeys(
                self.target_roles
                + self.primary_roles
                + self.secondary_roles
                + (self.stretch_roles if self.allow_stretch else [])
            )
        )


def load_preferences(path=None):
    import yaml

    if not path:
        return SearchPreferences()
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError("Preferences must be an object")
    # A v1 JSON target_roles setting is authoritative, not supplemented by new defaults.
    if "target_roles" in data and "primary_roles" not in data:
        data.update(primary_roles=data["target_roles"], secondary_roles=[], stretch_roles=[])
    return SearchPreferences.model_validate(data)


class Company(Model):
    id: str
    name: str = Field(min_length=1)
    career_url: str
    source: str
    tier: Literal["primary", "secondary", "explore"] = "secondary"
    enabled: bool = True
    discovery_source: str = "manual"


class JobListing(Model):
    id: str
    company_id: str
    company: str
    source: str
    source_id: str
    title: str
    location: str = "Not specified"
    url: str
    apply_url: str | None = None
    description: str = ""
    description_complete: bool = False
    work_mode: Literal["remote", "hybrid", "onsite", "unknown"] = "unknown"
    posted_at: datetime | None = None
    source_hash: str = ""


class ScanResult(Model):
    status: Literal["complete", "partial", "failed"]
    jobs: list[JobListing] = Field(default_factory=list)
    error: str | None = None


class Observation(Model):
    scan_id: str
    job_id: str
    observed_at: datetime
    change: Literal["new", "updated", "unchanged", "missing", "closed", "reposted"]
    source_hash: str
    evidence: dict = Field(default_factory=dict)


class ScoreEvaluation(Model):
    id: str
    job_id: str
    profile_id: str
    candidate_version: str
    preferences_version: str
    evaluator_version: str
    cache_key: str
    evaluated_at: datetime
    eligibility: Literal["eligible", "review", "excluded"]
    status: Literal["scored", "pending", "review", "excluded", "failed", "legacy"]
    fit: float | None = Field(default=None, ge=0, le=100)
    confidence: float = Field(default=0, ge=0, le=100)
    strategy: float | None = Field(default=None, ge=0, le=100)
    priority: float | None = Field(default=None, ge=0, le=100)
    action: str
    reasons: list[str] = Field(default_factory=list)
    evidence: dict = Field(default_factory=dict)
    cache_hit: bool = False
