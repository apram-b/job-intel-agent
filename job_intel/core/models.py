"""Validated user settings and model responses. Unknown facts stay unknown."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SearchProfile(Model):
    profile_id: str = "personal"
    target_roles: list[str] = Field(
        default_factory=lambda: [
            "Senior Data Engineer",
            "MLOps Engineer",
            "ML Platform Engineer",
            "ML Infrastructure Engineer",
        ]
    )
    preferred_cities: list[str] = Field(default_factory=lambda: ["Gurgaon", "Delhi NCR"])
    secondary_cities: list[str] = Field(default_factory=lambda: ["Bangalore", "Hyderabad", "Pune"])
    allow_india_remote: bool = True
    allow_stretch: bool = True
    must_have_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(
        default_factory=lambda: ["Python", "AWS", "MLflow", "Airflow", "SageMaker"]
    )
    min_score: int = Field(default=8, ge=0, le=12)
    max_jobs_to_score: int = Field(default=40, ge=1, le=200)
    top_n: int = Field(default=10, ge=1, le=50)
    draft_top_n: int = Field(default=0, ge=0, le=5)

    @field_validator("profile_id")
    @classmethod
    def nonempty_id(cls, v):
        if not v or len(v) > 100:
            raise ValueError("profile_id must contain 1–100 characters")
        return v

    @field_validator("target_roles")
    @classmethod
    def nonempty_roles(cls, v):
        if not v or any(not x.strip() for x in v):
            raise ValueError("Provide at least one nonempty target role")
        return v


class Resume(Model):
    name: str = Field(min_length=1)
    current_role: str = Field(min_length=1)
    years_experience: float = Field(ge=0, le=70)
    skills: list[str]
    stack: list[str]
    inferred_field: str = Field(min_length=1)
    seniority_level: Literal["junior", "mid", "senior", "lead", "principal", "unknown"] = "unknown"
    achievements: list[str] = Field(default_factory=list)


class Dimension(Model):
    score: int = Field(strict=True, ge=0, le=3)
    evidence: str = Field(min_length=1, max_length=1500)


class Assessment(Model):
    title_match: Dimension
    skill_overlap: Dimension
    seniority_fit: Dimension
    required_skills_missing: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=1500)


class Source(Model):
    name: str = Field(min_length=1)
    career_url: str = Field(min_length=1)


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_profile(path: str | None = None) -> SearchProfile:
    return SearchProfile.model_validate_json(Path(path).read_text()) if path else SearchProfile()
