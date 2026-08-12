"""
database.py
SQLite-backed storage that prevents duplicate sends and records full send history.
"""
import os
import sqlite3
from pathlib import Path
from datetime import datetime

if os.environ.get("VERCEL") == "1":
    DB_PATH = Path(os.environ.get("TMPDIR", "/tmp")) / "resumemailer.db"
else:
    DB_PATH = Path(__file__).resolve().parent / "resumemailer.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sent_emails (
    email TEXT PRIMARY KEY,
    hr_name TEXT,
    company TEXT,
    job_role TEXT,
    status TEXT,           -- 'sent' | 'failed'
    attempts INTEGER DEFAULT 0,
    error TEXT,
    timestamp TEXT
);
"""


class Database:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute(SCHEMA)
        self._conn.commit()

    def is_already_sent(self, email: str) -> bool:
        cur = self._conn.execute(
            "SELECT status FROM sent_emails WHERE email = ? AND status = 'sent'",
            (email.lower(),),
        )
        return cur.fetchone() is not None

    def record(self, email, hr_name, company, job_role, status, attempts, error=""):
        self._conn.execute(
            """
            INSERT INTO sent_emails (email, hr_name, company, job_role, status, attempts, error, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                status=excluded.status,
                attempts=excluded.attempts,
                error=excluded.error,
                timestamp=excluded.timestamp
            """,
            (
                email.lower(),
                hr_name,
                company,
                job_role,
                status,
                attempts,
                error,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self._conn.commit()

    def stats(self):
        cur = self._conn.execute(
            "SELECT status, COUNT(*) FROM sent_emails GROUP BY status"
        )
        result = {"sent": 0, "failed": 0}
        for status, count in cur.fetchall():
            result[status] = count
        return result

    def all_records(self):
        cur = self._conn.execute(
            "SELECT email, hr_name, company, job_role, status, attempts, error, timestamp FROM sent_emails"
        )
        cols = ["email", "hr_name", "company", "job_role", "status", "attempts", "error", "timestamp"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def close(self):
        self._conn.close()
