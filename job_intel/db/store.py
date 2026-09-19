"""Local, transactional job history. Missing observations never delete jobs.

New tables deliberately leave the original resumes/companies/job_listings tables
untouched; those remain available as an archive when opening an old database.
"""

from __future__ import annotations
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

STATUSES = ("new", "saved", "rejected", "applied", "interview", "offer", "closed")


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connection():
    path = Path(os.getenv("JOB_INTEL_DB", "data/job_intel.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, errors TEXT NOT NULL DEFAULT '[]', snapshot TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL, content_hash TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS observations (run_id TEXT NOT NULL REFERENCES runs(id), job_id TEXT NOT NULL REFERENCES jobs(id), change TEXT NOT NULL, content_hash TEXT NOT NULL, PRIMARY KEY(run_id,job_id));
        CREATE TABLE IF NOT EXISTS source_checks (run_id TEXT NOT NULL REFERENCES runs(id), source TEXT NOT NULL, status TEXT NOT NULL, count INTEGER NOT NULL, detail TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS scores (profile_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(id), cache_key TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(profile_id,job_id));
        CREATE TABLE IF NOT EXISTS applications (profile_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(id), status TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', applied_at TEXT, follow_up TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(profile_id,job_id));
        CREATE TABLE IF NOT EXISTS drafts (run_id TEXT NOT NULL REFERENCES runs(id), job_id TEXT NOT NULL REFERENCES jobs(id), message TEXT NOT NULL, PRIMARY KEY(run_id,job_id));
        CREATE TABLE IF NOT EXISTS shortlists (profile_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(id), signature TEXT NOT NULL, PRIMARY KEY(profile_id,job_id));
        CREATE INDEX IF NOT EXISTS idx_runs_profile ON runs(profile_id,started_at);
        """)
        db.execute("BEGIN IMMEDIATE")
        if "content_hash" not in {row[1] for row in db.execute("PRAGMA table_info(observations)")}:
            db.execute("ALTER TABLE observations ADD COLUMN content_hash TEXT NOT NULL DEFAULT ''")
        db.commit()
        with db:
            yield db
    finally:
        db.close()


def start_run(run_id, profile, resume=None):
    snapshot = json.dumps({"profile": profile, "resume": resume})
    with connection() as db:
        db.execute(
            "INSERT INTO profiles VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
            (profile["profile_id"], snapshot, now()),
        )
        db.execute(
            "INSERT INTO runs(id,profile_id,started_at,status,snapshot) VALUES (?,?,?,'running',?)",
            (run_id, profile["profile_id"], now(), snapshot),
        )


def finish_run(run_id, status, errors):
    with connection() as db:
        db.execute(
            "UPDATE runs SET finished_at=?,status=?,errors=? WHERE id=?",
            (now(), status, json.dumps(errors), run_id),
        )


def save_parsed_resume(run_id, profile, resume):
    snapshot = json.dumps({"profile": profile, "resume": resume})
    with connection() as db:
        db.execute("UPDATE runs SET snapshot=? WHERE id=?", (snapshot, run_id))
        db.execute(
            "UPDATE profiles SET payload=?,updated_at=? WHERE id=?", (snapshot, now(), profile["profile_id"])
        )


def save_job_listings(listings, *, run_id):
    from job_intel.core.models import fingerprint

    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        owner = db.execute("SELECT profile_id FROM runs WHERE id=?", (run_id,)).fetchone()
        if not owner:
            raise ValueError("Unknown run")
        for job in {j["id"]: j for j in listings}.values():
            stable = {k: v for k, v in job.items() if k not in ("scraped_at", "updated_at")}
            digest = fingerprint(stable)
            prior = db.execute(
                "SELECT o.content_hash FROM observations o JOIN runs r ON o.run_id=r.id WHERE o.job_id=? AND r.profile_id=? AND r.id!=? ORDER BY r.started_at DESC LIMIT 1",
                (job["id"], owner[0], run_id),
            ).fetchone()
            change = "new" if prior is None else "changed" if prior[0] != digest else "unchanged"
            timestamp = now()
            db.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,content_hash=excluded.content_hash,last_seen=excluded.last_seen",
                (job["id"], json.dumps(job), digest, timestamp, timestamp),
            )
            db.execute(
                "INSERT OR IGNORE INTO observations VALUES (?,?,?,?)", (run_id, job["id"], change, digest)
            )


def save_source_checks(run_id, checks):
    with connection() as db:
        db.executemany(
            "INSERT INTO source_checks VALUES (?,?,?,?,?)",
            [(run_id, c["source"], c["status"], c["count"], c.get("detail", "")) for c in checks],
        )


def cached_score(profile_id, job_id, cache_key):
    with connection() as db:
        row = db.execute(
            "SELECT payload FROM scores WHERE profile_id=? AND job_id=? AND cache_key=?",
            (profile_id, job_id, cache_key),
        ).fetchone()
        return json.loads(row[0]) if row else None


def save_score(profile_id, job, cache_key):
    with connection() as db:
        db.execute(
            "INSERT INTO scores VALUES (?,?,?,?,?) ON CONFLICT(profile_id,job_id) DO UPDATE SET cache_key=excluded.cache_key,payload=excluded.payload,updated_at=excluded.updated_at",
            (profile_id, job["id"], cache_key, json.dumps(job), now()),
        )


def save_drafts(run_id, drafts):
    with connection() as db:
        db.executemany(
            "INSERT OR REPLACE INTO drafts VALUES (?,?,?)",
            [(run_id, d["job_id"], d["message"]) for d in drafts],
        )


def set_status(profile_id, job_id, status, notes="", follow_up=None):
    if status not in STATUSES:
        raise ValueError("Unknown application status")
    if follow_up:
        from datetime import date

        date.fromisoformat(follow_up)
    with connection() as db:
        if not db.execute(
            "SELECT 1 FROM observations o JOIN runs r ON o.run_id=r.id WHERE o.job_id=? AND r.profile_id=?",
            (job_id, profile_id),
        ).fetchone():
            raise ValueError("Job is not part of this profile's history")
        db.execute(
            """INSERT INTO applications VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(profile_id,job_id) DO UPDATE SET status=excluded.status,notes=excluded.notes,
        applied_at=COALESCE(applications.applied_at,excluded.applied_at),follow_up=excluded.follow_up,updated_at=excluded.updated_at""",
            (profile_id, job_id, status, notes, now() if status == "applied" else None, follow_up, now()),
        )


def history(profile_id):
    with connection() as db:
        rows = db.execute(
            """SELECT j.*,s.payload AS score_payload,a.status,a.notes,a.applied_at,a.follow_up
        FROM jobs j LEFT JOIN scores s ON j.id=s.job_id AND s.profile_id=?
        LEFT JOIN applications a ON j.id=a.job_id AND a.profile_id=?
        WHERE EXISTS (SELECT 1 FROM observations o JOIN runs r ON o.run_id=r.id WHERE o.job_id=j.id AND r.profile_id=?)
        ORDER BY j.last_seen DESC""",
            (profile_id, profile_id, profile_id),
        ).fetchall()
        results = []
        for row in rows:
            item = json.loads(row["payload"])
            scored = json.loads(row["score_payload"]) if row["score_payload"] else {}
            item.update({k: v for k, v in scored.items() if k not in item})
            item.update({k: row[k] for k in ("first_seen", "last_seen", "notes", "applied_at", "follow_up")})
            item["status"] = row["status"] or "new"
            results.append(item)
        return results


def changes(run_id):
    with connection() as db:
        return dict(db.execute("SELECT job_id,change FROM observations WHERE run_id=?", (run_id,)).fetchall())


def record_shortlist(profile_id, jobs):
    """Include newly qualified jobs even if the posting itself was seen before."""
    from job_intel.core.models import fingerprint

    new_matches = []
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        for job in jobs:
            signature = fingerprint(
                {k: v for k, v in job.items() if k not in ("scraped_at", "updated_at", "cached")}
            )
            prior = db.execute(
                "SELECT signature FROM shortlists WHERE profile_id=? AND job_id=?", (profile_id, job["id"])
            ).fetchone()
            if not prior or prior[0] != signature:
                new_matches.append(job)
            db.execute(
                "INSERT INTO shortlists VALUES (?,?,?) ON CONFLICT(profile_id,job_id) DO UPDATE SET signature=excluded.signature",
                (profile_id, job["id"], signature),
            )
    return new_matches


def recent_runs(profile_id, limit=10):
    with connection() as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT id,started_at,finished_at,status,errors FROM runs WHERE profile_id=? ORDER BY started_at DESC LIMIT ?",
                (profile_id, limit),
            )
        ]
