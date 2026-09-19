"""SQLite startup pragmas can race before the busy timeout applies to WAL changes."""

import sqlite3
import time


def enable_wal(connection):
    deadline = time.monotonic() + 30
    while True:
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or time.monotonic() >= deadline:
                raise
            time.sleep(0.05)
