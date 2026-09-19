"""Transactional repositories for SQLite and PostgreSQL."""

from __future__ import annotations
from job_intel.db.sqlite import enable_wal
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from sqlalchemy import create_engine, select, update, delete, event
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from job_intel.core.models import fingerprint
from job_intel.v2 import schema as s
from job_intel.v2.models import Company, CandidateProfile, SearchPreferences, version, utcnow


def stamp(dt=None):
    return (dt or utcnow()).astimezone(timezone.utc).isoformat()


def moment(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def database_url():
    return os.getenv("JOB_INTEL_DATABASE_URL") or "sqlite:///" + str(
        Path(os.getenv("JOB_INTEL_DB", "data/job_intel.db")).resolve()
    )


class Repository:
    def __init__(self, url=None):
        url = url or database_url()
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        if url.startswith("sqlite:///") and not url.endswith(":memory:"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            url, pool_pre_ping=True, connect_args={"timeout": 30} if url.startswith("sqlite:") else {}
        )
        if self.engine.dialect.name == "sqlite":

            @event.listens_for(self.engine, "connect")
            def configure(db, _):
                db.execute("PRAGMA foreign_keys=ON")
                enable_wal(db)

    def migrate(self):
        from alembic import command
        from alembic.config import Config

        root = Path(__file__).resolve().parents[2]
        cfg = Config(str(root / "alembic.ini"))
        with self.engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")

    @contextmanager
    def transaction(self):
        with self.engine.connect() as conn:
            if conn.dialect.name == "sqlite":
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                conn.begin()
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def put(self, conn, table, values, keys, *, ignore=False):
        insert = sqlite_insert if conn.dialect.name == "sqlite" else pg_insert
        query = insert(table).values(**values)
        if ignore:
            query = query.on_conflict_do_nothing(index_elements=keys)
        else:
            query = query.on_conflict_do_update(
                index_elements=keys, set_={k: v for k, v in values.items() if k not in keys}
            )
        conn.execute(query)

    def save_company(self, company):
        data = company.model_dump(mode="json")
        with self.transaction() as c:
            self.put(
                c,
                s.companies,
                dict(id=company.id, source=company.source, payload=data, enabled=company.enabled),
                ["id"],
            )

    def companies(self, enabled_only=False):
        query = select(s.companies).order_by(s.companies.c.id)
        if enabled_only:
            query = query.where(s.companies.c.enabled.is_(True))
        with self.engine.connect() as c:
            return [Company.model_validate({**r.payload, "enabled": r.enabled}) for r in c.execute(query)]

    def enable_company(self, company_id, enabled):
        with self.transaction() as c:
            c.execute(update(s.companies).where(s.companies.c.id == company_id).values(enabled=enabled))

    def save_profile(self, profile_id, candidate, preferences):
        candidate = CandidateProfile.model_validate(candidate) if isinstance(candidate, dict) else candidate
        preferences = (
            SearchPreferences.model_validate(preferences) if isinstance(preferences, dict) else preferences
        )
        cv, pv = version(candidate), version(preferences)
        candidate_data, preference_data = (
            candidate.model_dump(mode="json"),
            preferences.model_dump(mode="json"),
        )
        with self.transaction() as c:
            self.put(
                c,
                s.profiles,
                dict(
                    id=profile_id,
                    candidate_version=cv,
                    preferences_version=pv,
                    candidate=candidate_data,
                    preferences=preference_data,
                    updated_at=stamp(),
                ),
                ["id"],
            )
            self.put(
                c,
                s.profile_versions,
                dict(
                    id=fingerprint([profile_id, cv, pv]),
                    profile_id=profile_id,
                    candidate=candidate_data,
                    preferences=preference_data,
                    created_at=stamp(),
                ),
                ["id"],
                ignore=True,
            )

    def profile(self, profile_id="personal"):
        with self.engine.connect() as c:
            row = c.execute(select(s.profiles).where(s.profiles.c.id == profile_id)).mappings().first()
            if not row:
                return None
            return CandidateProfile.model_validate(row["candidate"]), SearchPreferences.model_validate(
                row["preferences"]
            )

    def acquire(self, name, owner, at=None, minutes=60):
        at = at or utcnow()
        with self.transaction() as c:
            self.put(
                c,
                s.leases,
                dict(name=name, owner=owner, expires_at=stamp(at + timedelta(minutes=minutes))),
                ["name"],
                ignore=True,
            )
            row = (
                c.execute(select(s.leases).where(s.leases.c.name == name).with_for_update()).mappings().one()
            )
            if row["owner"] == owner:
                return True
            if moment(row["expires_at"]) <= at:
                c.execute(
                    update(s.leases)
                    .where(s.leases.c.name == name)
                    .values(owner=owner, expires_at=stamp(at + timedelta(minutes=minutes)))
                )
                return True
            return False

    def release(self, name, owner):
        with self.transaction() as c:
            c.execute(delete(s.leases).where(s.leases.c.name == name, s.leases.c.owner == owner))

    def begin_scan(self, scan_id, company_id, at=None):
        with self.transaction() as c:
            self.put(
                c,
                s.scans,
                dict(id=scan_id, company_id=company_id, started_at=stamp(at), status="running", count=0),
                ["id"],
                ignore=True,
            )

    def apply_scan(self, scan_id, company, result, preferences=None, at=None):
        prefs = preferences or SearchPreferences()
        at = at or utcnow()
        timestamp = stamp(at)
        with self.transaction() as c:
            c.execute(select(s.companies).where(s.companies.c.id == company.id).with_for_update()).one()
            existing = c.execute(select(s.scans).where(s.scans.c.id == scan_id)).mappings().first()
            if existing and existing["company_id"] != company.id:
                raise ValueError("Scan ID belongs to a different company")
            if existing and existing["status"] != "running":
                return False
            self.put(
                c,
                s.scans,
                dict(
                    id=scan_id,
                    company_id=company.id,
                    started_at=existing["started_at"] if existing else timestamp,
                    finished_at=timestamp,
                    status=result.status,
                    count=len(result.jobs),
                    error=result.error,
                ),
                ["id"],
            )
            if result.status == "failed":
                return True
            seen = set()
            for listing in result.jobs:
                if listing.company_id != company.id or listing.source != company.source:
                    raise ValueError("Listing belongs to a different company/source")
                # Source identity is authoritative even if a caller supplies a different internal ID.
                identity = (
                    c.execute(
                        select(s.jobs).where(
                            s.jobs.c.company_id == company.id,
                            s.jobs.c.source == listing.source,
                            s.jobs.c.source_id == listing.source_id,
                        )
                    )
                    .mappings()
                    .first()
                )
                job = listing.model_copy(update={"id": identity["id"]}) if identity else listing
                if job.id in seen:
                    continue
                seen.add(job.id)
                old = identity or c.execute(select(s.jobs).where(s.jobs.c.id == job.id)).mappings().first()
                if old and old["company_id"] != company.id:
                    raise ValueError("Job ID collision across companies")
                payload = job.model_dump(mode="json")
                digest = fingerprint({k: v for k, v in payload.items() if k != "source_hash"})
                change = (
                    "new"
                    if not old
                    else "reposted"
                    if old["lifecycle"] == "CLOSED"
                    else "updated"
                    if old["content_hash"] != digest
                    else "unchanged"
                )
                possible = old["possible_repost_of"] if old else None
                if not old:
                    closed = c.execute(
                        select(s.jobs).where(
                            s.jobs.c.company_id == company.id, s.jobs.c.lifecycle == "CLOSED"
                        )
                    ).mappings()
                    for prior in closed:
                        if (
                            prior["payload"]["title"].casefold(),
                            prior["payload"]["location"].casefold(),
                        ) == (job.title.casefold(), job.location.casefold()):
                            possible = prior["id"]
                            break
                self.put(
                    c,
                    s.jobs,
                    dict(
                        id=job.id,
                        company_id=company.id,
                        source=job.source,
                        source_id=job.source_id,
                        payload=payload,
                        content_hash=digest,
                        first_seen=old["first_seen"] if old else timestamp,
                        last_seen=timestamp,
                        lifecycle="REPOSTED" if change == "reposted" else "OPEN",
                        missing_count=0,
                        missing_since=None,
                        possible_repost_of=possible,
                        verified_at=old["verified_at"] if old else None,
                        apply_alive=old["apply_alive"] if old else None,
                    ),
                    ["id"],
                )
                for url in {job.url, job.apply_url} - {None}:
                    self.put(c, s.aliases, dict(url=url, job_id=job.id), ["url"], ignore=True)
                self.put(
                    c,
                    s.observations,
                    dict(
                        scan_id=scan_id,
                        job_id=job.id,
                        observed_at=timestamp,
                        change=change,
                        source_hash=job.source_hash or digest,
                        evidence={"direct_ats": True, "collection_status": result.status},
                    ),
                    ["scan_id", "job_id"],
                    ignore=True,
                )
            if result.status == "complete":
                query = select(s.jobs).where(
                    s.jobs.c.company_id == company.id, s.jobs.c.lifecycle != "CLOSED"
                )
                if seen:
                    query = query.where(s.jobs.c.id.not_in(seen))
                for old in c.execute(query).mappings().all():
                    missing_since = old["missing_since"] or timestamp
                    count = old["missing_count"] + 1
                    closed = count >= prefs.close_after_scans and at - moment(missing_since) >= timedelta(
                        hours=prefs.close_after_hours
                    )
                    state = "CLOSED" if closed else "MISSING"
                    c.execute(
                        update(s.jobs)
                        .where(s.jobs.c.id == old["id"])
                        .values(lifecycle=state, missing_count=count, missing_since=missing_since)
                    )
                    self.put(
                        c,
                        s.observations,
                        dict(
                            scan_id=scan_id,
                            job_id=old["id"],
                            observed_at=timestamp,
                            change="closed" if closed else "missing",
                            source_hash=old["content_hash"],
                            evidence={"complete_source_scan": True},
                        ),
                        ["scan_id", "job_id"],
                        ignore=True,
                    )
                c.execute(
                    update(s.companies).where(s.companies.c.id == company.id).values(last_success=timestamp)
                )
            return True

    def jobs(self):
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(select(s.jobs).order_by(s.jobs.c.id)).mappings()]

    def observations(self, job_id):
        with self.engine.connect() as c:
            return [
                dict(r)
                for r in c.execute(
                    select(s.observations)
                    .where(s.observations.c.job_id == job_id)
                    .order_by(s.observations.c.observed_at)
                ).mappings()
            ]

    def verify_link(self, job_id, alive, at=None):
        with self.transaction() as c:
            c.execute(
                update(s.jobs).where(s.jobs.c.id == job_id).values(apply_alive=alive, verified_at=stamp(at))
            )

    def save_evaluation(self, evaluation):
        data = evaluation.model_dump(mode="json")
        with self.transaction() as c:
            self.put(
                c,
                s.evaluations,
                dict(
                    id=evaluation.id,
                    job_id=evaluation.job_id,
                    profile_id=evaluation.profile_id,
                    cache_key=evaluation.cache_key,
                    evaluated_at=data["evaluated_at"],
                    payload=data,
                ),
                ["id"],
                ignore=True,
            )

    def cached_evaluation(self, profile_id, job_id, key):
        with self.engine.connect() as c:
            rows = c.execute(
                select(s.evaluations.c.payload)
                .where(
                    s.evaluations.c.profile_id == profile_id,
                    s.evaluations.c.job_id == job_id,
                    s.evaluations.c.cache_key == key,
                )
                .order_by(s.evaluations.c.evaluated_at.desc())
            ).scalars()
            return next((r for r in rows if r["status"] == "scored"), None)

    def queue(self, profile_id="personal"):
        with self.engine.connect() as c:
            evaluations = c.execute(
                select(s.evaluations)
                .where(s.evaluations.c.profile_id == profile_id)
                .order_by(s.evaluations.c.evaluated_at.desc())
            ).mappings()
            latest = {}
            for row in evaluations:
                latest.setdefault(row["job_id"], row["payload"])
            apps = {
                r["job_id"]: dict(r)
                for r in c.execute(
                    select(s.applications).where(s.applications.c.profile_id == profile_id)
                ).mappings()
            }
            companies = {r.id: r.enabled for r in c.execute(select(s.companies.c.id, s.companies.c.enabled))}
        result = [
            {
                **r,
                "evaluation": latest.get(r["id"]),
                "application": apps.get(r["id"]),
                "company_enabled": companies.get(r["company_id"], False),
            }
            for r in self.jobs()
        ]
        profile = self.profile(profile_id)
        for item in result:
            evaluation = item["evaluation"]
            if not evaluation or evaluation.get("status") == "legacy":
                continue
            stale = profile and (
                evaluation.get("candidate_version") != version(profile[0])
                or evaluation.get("preferences_version") != version(profile[1])
            )
            content_stale = evaluation.get("evidence", {}).get("job_content_hash") != item["content_hash"]
            if stale or content_stale:
                item["evaluation"] = {
                    **evaluation,
                    "status": "pending",
                    "action": "verify",
                    "priority": None,
                    "reasons": ["Candidate, preferences or posting changed; a new evaluation is required"],
                }
            if item["evaluation"]["action"] == "apply and consider outreach" and (
                not item["verified_at"] or utcnow() - moment(item["verified_at"]) > timedelta(hours=24)
            ):
                item["evaluation"] = {
                    **item["evaluation"],
                    "action": "verify",
                    "reasons": item["evaluation"].get("reasons", [])
                    + ["Link verification is older than 24 hours; recheck before applying"],
                }
            if item["application"] and item["application"]["status"] in (
                "applied",
                "interview",
                "offer",
                "rejected",
                "closed",
            ):
                item["evaluation"] = {**item["evaluation"], "action": "tracked"}
        return sorted(
            result, key=lambda r: (-(r["evaluation"].get("priority") or 0) if r["evaluation"] else 0, r["id"])
        )

    def set_application(self, profile_id, job_id, status, notes="", follow_up=None):
        from datetime import date
        from job_intel.db.store import STATUSES

        if status not in STATUSES:
            raise ValueError("Unknown application status")
        if follow_up:
            date.fromisoformat(follow_up)
        with self.transaction() as c:
            old = (
                c.execute(
                    select(s.applications).where(
                        s.applications.c.profile_id == profile_id, s.applications.c.job_id == job_id
                    )
                )
                .mappings()
                .first()
            )
            self.put(
                c,
                s.applications,
                dict(
                    profile_id=profile_id,
                    job_id=job_id,
                    status=status,
                    notes=notes,
                    applied_at=old["applied_at"]
                    if old and old["applied_at"]
                    else stamp()
                    if status == "applied"
                    else None,
                    follow_up=follow_up or None,
                    updated_at=stamp(),
                ),
                ["profile_id", "job_id"],
            )

    def reserve_budget(self, amount_microusd, *, limit_microusd=3_000_000, at=None):
        if amount_microusd <= 0 or limit_microusd < 0:
            raise ValueError("Invalid budget reservation")
        at = at or utcnow()
        month = at.strftime("%Y-%m")
        with self.transaction() as c:
            self.put(c, s.budgets, dict(month=month, reserved_microusd=0), ["month"], ignore=True)
            result = c.execute(
                update(s.budgets)
                .where(
                    s.budgets.c.month == month,
                    s.budgets.c.reserved_microusd + amount_microusd <= limit_microusd,
                )
                .values(reserved_microusd=s.budgets.c.reserved_microusd + amount_microusd)
            )
            if not result.rowcount:
                return None
            rid = str(uuid.uuid4())
            c.execute(
                s.reservations.insert().values(
                    id=rid, month=month, amount_microusd=amount_microusd, created_at=stamp(at)
                )
            )
            return rid

    def recent_scans(self, limit=100):
        with self.engine.connect() as c:
            return [
                dict(r)
                for r in c.execute(
                    select(s.scans).order_by(s.scans.c.started_at.desc()).limit(limit)
                ).mappings()
            ]
