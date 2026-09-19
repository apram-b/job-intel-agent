"""V2 relational schema, isolated from the preserved v1 tables."""

from sqlalchemy import (
    MetaData,
    Table,
    Column,
    String,
    Text,
    Integer,
    Boolean,
    JSON,
    ForeignKey,
    UniqueConstraint,
)

metadata = MetaData()
companies = Table(
    "v2_companies",
    metadata,
    Column("id", String, primary_key=True),
    Column("source", String, unique=True, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("enabled", Boolean, nullable=False),
    Column("last_success", String),
)
profiles = Table(
    "v2_profiles",
    metadata,
    Column("id", String, primary_key=True),
    Column("candidate_version", String, nullable=False),
    Column("preferences_version", String, nullable=False),
    Column("candidate", JSON, nullable=False),
    Column("preferences", JSON, nullable=False),
    Column("updated_at", String, nullable=False),
)
profile_versions = Table(
    "v2_profile_versions",
    metadata,
    Column("id", String, primary_key=True),
    Column("profile_id", String, nullable=False),
    Column("candidate", JSON, nullable=False),
    Column("preferences", JSON, nullable=False),
    Column("created_at", String, nullable=False),
)
scans = Table(
    "v2_scans",
    metadata,
    Column("id", String, primary_key=True),
    Column("company_id", String, ForeignKey("v2_companies.id"), nullable=False),
    Column("started_at", String, nullable=False),
    Column("finished_at", String),
    Column("status", String, nullable=False),
    Column("count", Integer, nullable=False, default=0),
    Column("error", Text),
)
jobs = Table(
    "v2_jobs",
    metadata,
    Column("id", String, primary_key=True),
    Column("company_id", String, ForeignKey("v2_companies.id"), nullable=False),
    Column("source", String, nullable=False),
    Column("source_id", String, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("content_hash", String, nullable=False),
    Column("first_seen", String, nullable=False),
    Column("last_seen", String, nullable=False),
    Column("lifecycle", String, nullable=False),
    Column("missing_count", Integer, nullable=False, default=0),
    Column("missing_since", String),
    Column("possible_repost_of", String),
    Column("verified_at", String),
    Column("apply_alive", Boolean),
    UniqueConstraint("company_id", "source", "source_id"),
)
observations = Table(
    "v2_observations",
    metadata,
    Column("scan_id", String, ForeignKey("v2_scans.id"), primary_key=True),
    Column("job_id", String, ForeignKey("v2_jobs.id"), primary_key=True),
    Column("observed_at", String, nullable=False),
    Column("change", String, nullable=False),
    Column("source_hash", String, nullable=False),
    Column("evidence", JSON, nullable=False),
)
aliases = Table(
    "v2_aliases",
    metadata,
    Column("url", String, primary_key=True),
    Column("job_id", String, ForeignKey("v2_jobs.id"), nullable=False),
)
evaluations = Table(
    "v2_evaluations",
    metadata,
    Column("id", String, primary_key=True),
    Column("job_id", String, ForeignKey("v2_jobs.id"), nullable=False, index=True),
    Column("profile_id", String, nullable=False),
    Column("cache_key", String, nullable=False, index=True),
    Column("evaluated_at", String, nullable=False),
    Column("payload", JSON, nullable=False),
)
applications = Table(
    "v2_applications",
    metadata,
    Column("profile_id", String, primary_key=True),
    Column("job_id", String, ForeignKey("v2_jobs.id"), primary_key=True),
    Column("status", String, nullable=False),
    Column("notes", Text, nullable=False),
    Column("applied_at", String),
    Column("follow_up", String),
    Column("updated_at", String, nullable=False),
)
leases = Table(
    "v2_leases",
    metadata,
    Column("name", String, primary_key=True),
    Column("owner", String, nullable=False),
    Column("expires_at", String, nullable=False),
)
budgets = Table(
    "v2_budgets",
    metadata,
    Column("month", String, primary_key=True),
    Column("reserved_microusd", Integer, nullable=False, default=0),
)
reservations = Table(
    "v2_reservations",
    metadata,
    Column("id", String, primary_key=True),
    Column("month", String, ForeignKey("v2_budgets.month"), nullable=False),
    Column("amount_microusd", Integer, nullable=False),
    Column("created_at", String, nullable=False),
)
