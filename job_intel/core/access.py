"""Durable public quotas keyed by a verified OIDC issuer + subject.

A credit is consumed at admission, before any paid call. Failed/abandoned runs do
not automatically refund; this prevents deliberate failure/retry credit reuse.
"""

from __future__ import annotations
import hashlib
import math
import os
import time
from job_intel.db.store import connection

FREE_RUNS = 3


class AccessDenied(ValueError):
    pass


def identity(claims: dict, issuer: str) -> str:
    if not issuer or claims.get("iss") != issuer or not claims.get("sub"):
        raise AccessDenied("A verified sign-in from the configured provider is required")
    if claims.get("email_verified") is not True:
        raise AccessDenied("Verify your email with the sign-in provider first")
    if not isinstance(claims["sub"], str):
        raise AccessDenied("Invalid sign-in subject")
    expires = claims.get("exp")
    if expires is not None and (
        not isinstance(expires, (float, int)) or not math.isfinite(expires) or expires <= time.time()
    ):
        raise AccessDenied("Your sign-in has expired. Sign out and sign in again")
    return hashlib.sha256((issuer + "\0" + claims["sub"]).encode()).hexdigest()


def _tables(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS admissions (
        request_id TEXT PRIMARY KEY, identity TEXT NOT NULL, sponsored INTEGER NOT NULL,
        admitted_at REAL NOT NULL, finished_at REAL, state TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS admissions_identity ON admissions(identity);
    """)


def remaining(user_id):
    with connection() as db:
        _tables(db)
        used = db.execute(
            "SELECT COUNT(*) FROM admissions WHERE identity=? AND sponsored=1", (user_id,)
        ).fetchone()[0]
        return max(0, FREE_RUNS - used)


def reserve(user_id, request_id, *, sponsored, timestamp=None):
    if not user_id or not request_id:
        raise AccessDenied("Missing authenticated identity or request ID")
    timestamp = time.time() if timestamp is None else timestamp
    with connection() as db:
        _tables(db)
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM admissions WHERE request_id=?", (request_id,)).fetchone():
            raise AccessDenied("This request has already been admitted; do not replay it")
        # Lease expiry unlocks interrupted runs without refunding their credits.
        db.execute(
            "UPDATE admissions SET state='abandoned',finished_at=? WHERE state='running' AND admitted_at<?",
            (timestamp, timestamp - 3600),
        )
        if db.execute("SELECT 1 FROM admissions WHERE identity=? AND state='running'", (user_id,)).fetchone():
            raise AccessDenied("A search is already running for your account")
        active = db.execute("SELECT COUNT(*) FROM admissions WHERE state='running'").fetchone()[0]
        if active >= int(os.getenv("JOB_INTEL_MAX_ACTIVE_RUNS", "3")):
            raise AccessDenied("The service is busy. Please try again shortly")
        if sponsored:
            used = db.execute(
                "SELECT COUNT(*) FROM admissions WHERE identity=? AND sponsored=1", (user_id,)
            ).fetchone()[0]
            if used >= FREE_RUNS:
                raise AccessDenied("Your three free runs are used. Enter your own API key to continue")
            used_today = db.execute(
                "SELECT COUNT(*) FROM admissions WHERE sponsored=1 AND admitted_at>=?", (timestamp - 86400,)
            ).fetchone()[0]
            if used_today >= int(os.getenv("JOB_INTEL_DAILY_FREE_RUNS", "20")):
                raise AccessDenied("The shared free-run budget is exhausted. Use your own key or try later")
        db.execute(
            "INSERT INTO admissions VALUES (?,?,?,?,NULL,'running')",
            (request_id, user_id, int(sponsored), timestamp),
        )


def release(request_id):
    with connection() as db:
        _tables(db)
        db.execute(
            "UPDATE admissions SET state='finished',finished_at=? WHERE request_id=? AND state='running'",
            (time.time(), request_id),
        )


def is_admin(user_id):
    """Only server-configured verified subject hashes receive public admin access."""
    allowed = {value.strip() for value in os.getenv("JOB_INTEL_ADMIN_IDS", "").split(",") if value.strip()}
    return bool(user_id and user_id in allowed)


def admin_overview(user_id):
    if not is_admin(user_id):
        raise AccessDenied("Administrator access required")
    with connection() as db:
        _tables(db)
        return {
            "runs": [
                dict(row)
                for row in db.execute(
                    "SELECT id,profile_id,started_at,finished_at,status,errors FROM runs ORDER BY started_at DESC LIMIT 100"
                )
            ],
            "sources": [
                dict(row)
                for row in db.execute(
                    "SELECT s.* FROM source_checks s JOIN runs r ON s.run_id=r.id ORDER BY r.started_at DESC LIMIT 200"
                )
            ],
            "usage": [
                dict(row)
                for row in db.execute(
                    "SELECT identity,COUNT(*) AS total_runs,SUM(sponsored) AS free_runs,SUM(state='running') AS active_runs FROM admissions GROUP BY identity"
                )
            ],
        }
