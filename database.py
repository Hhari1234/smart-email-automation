"""
database.py
SQLite-backed storage that prevents duplicate sends and records full send history.
"""
import os
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional

if os.environ.get("VERCEL") == "1":
    DB_PATH = Path(os.environ.get("TMPDIR", "/tmp")) / "resumemailer.db"
else:
    data_dir = os.environ.get("RESUMEMAILER_DATA_DIR", "")
    if data_dir:
        DB_PATH = Path(data_dir) / "resumemailer.db"
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

CREATE TABLE IF NOT EXISTS templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    signature TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    signature TEXT NOT NULL,
    recipients_json TEXT NOT NULL,
    attachments_json TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    signature TEXT NOT NULL,
    attachments_json TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    total_recipients INTEGER DEFAULT 0,
    sent_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'draft',  -- draft | running | paused | completed | stopped | error
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS campaign_recipients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    hr_name TEXT,
    company TEXT,
    job_role TEXT,
    location TEXT,
    status TEXT DEFAULT 'pending',  -- pending | sent | failed | skipped
    error TEXT,
    timestamp TEXT,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    last_login_at TEXT NULL
);
"""


class Database:
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is not None:
            self.db_path = db_path
        else:
            if os.environ.get("VERCEL") == "1":
                data_dir = os.environ.get("TMPDIR", "/tmp")
            else:
                data_dir = os.environ.get("RESUMEMAILER_DATA_DIR", "")
                if data_dir:
                    pass
                else:
                    data_dir = str(Path(__file__).resolve().parent)

            self.db_path = Path(data_dir) / "resumemailer.db"

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._migrate_add_user_id()

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

    def sent_emails_set(self) -> set[str]:
        cur = self._conn.execute("SELECT email FROM sent_emails WHERE status='sent'")
        return {row[0] for row in cur.fetchall()}

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------
    def create_template(self, name: str, subject: str, body: str, signature: str, user_id: int) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        cur = self._conn.execute(
            "INSERT INTO templates (user_id, name, subject, body, signature, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, name, subject, body, signature, now, now),
        )
        self._conn.commit()
        return cur.lastrowid

    def list_templates(self, user_id: Optional[int] = None):
        if user_id is not None:
            cur = self._conn.execute(
                "SELECT id, user_id, name, subject, body, signature, created_at, updated_at FROM templates WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,)
            )
        else:
            cur = self._conn.execute(
                "SELECT id, user_id, name, subject, body, signature, created_at, updated_at FROM templates ORDER BY updated_at DESC"
            )
        cols = ["id", "user_id", "name", "subject", "body", "signature", "created_at", "updated_at"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_template(self, template_id: int, user_id: Optional[int] = None):
        if user_id is not None:
            cur = self._conn.execute(
                "SELECT id, user_id, name, subject, body, signature, created_at, updated_at FROM templates WHERE id = ? AND user_id = ?",
                (template_id, user_id),
            )
        else:
            cur = self._conn.execute(
                "SELECT id, user_id, name, subject, body, signature, created_at, updated_at FROM templates WHERE id = ?",
                (template_id,),
            )
        row = cur.fetchone()
        if not row:
            return None
        cols = ["id", "user_id", "name", "subject", "body", "signature", "created_at", "updated_at"]
        return dict(zip(cols, row))

    def update_template(self, template_id: int, name: str, subject: str, body: str, signature: str, user_id: Optional[int] = None) -> bool:
        now = datetime.now().isoformat(timespec="seconds")
        if user_id is not None:
            cursor = self._conn.execute(
                "UPDATE templates SET name=?, subject=?, body=?, signature=?, updated_at=? WHERE id=? AND user_id=?",
                (name, subject, body, signature, now, template_id, user_id),
            )
        else:
            cursor = self._conn.execute(
                "UPDATE templates SET name=?, subject=?, body=?, signature=?, updated_at=? WHERE id=?",
                (name, subject, body, signature, now, template_id),
            )
        self._conn.commit()
        return cursor.rowcount > 0

    def delete_template(self, template_id: int, user_id: Optional[int] = None) -> bool:
        if user_id is not None:
            cursor = self._conn.execute("DELETE FROM templates WHERE id=? AND user_id=?", (template_id, user_id))
        else:
            cursor = self._conn.execute("DELETE FROM templates WHERE id=?", (template_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Drafts
    # ------------------------------------------------------------------
    def create_draft(self, name: str, subject: str, body: str, signature: str,
                      recipients: list[dict], attachments: list[str], settings: dict, user_id: int) -> int:
        import json
        now = datetime.now().isoformat(timespec="seconds")
        cur = self._conn.execute(
            "INSERT INTO drafts (user_id, name, subject, body, signature, recipients_json, attachments_json, settings_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id, name, subject, body, signature,
                json.dumps(recipients), json.dumps(attachments), json.dumps(settings),
                now, now,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def list_drafts(self, user_id: Optional[int] = None):
        import json
        if user_id is not None:
            cur = self._conn.execute(
                "SELECT id, user_id, name, subject, body, signature, recipients_json, attachments_json, settings_json, created_at, updated_at FROM drafts WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,)
            )
        else:
            cur = self._conn.execute(
                "SELECT id, user_id, name, subject, body, signature, recipients_json, attachments_json, settings_json, created_at, updated_at FROM drafts ORDER BY updated_at DESC"
            )
        cols = ["id", "user_id", "name", "subject", "body", "signature", "recipients_json", "attachments_json", "settings_json", "created_at", "updated_at"]
        rows = []
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            d["recipients"] = json.loads(d.pop("recipients_json", "[]") or "[]")
            d["attachments"] = json.loads(d.pop("attachments_json", "[]") or "[]")
            d["settings"] = json.loads(d.pop("settings_json", "{}") or "{}")
            rows.append(d)
        return rows

    def get_draft(self, draft_id: int, user_id: Optional[int] = None):
        import json
        if user_id is not None:
            cur = self._conn.execute(
                "SELECT id, user_id, name, subject, body, signature, recipients_json, attachments_json, settings_json, created_at, updated_at FROM drafts WHERE id = ? AND user_id = ?",
                (draft_id, user_id),
            )
        else:
            cur = self._conn.execute(
                "SELECT id, user_id, name, subject, body, signature, recipients_json, attachments_json, settings_json, created_at, updated_at FROM drafts WHERE id = ?",
                (draft_id,),
            )
        row = cur.fetchone()
        if not row:
            return None
        cols = ["id", "user_id", "name", "subject", "body", "signature", "recipients_json", "attachments_json", "settings_json", "created_at", "updated_at"]
        d = dict(zip(cols, row))
        d["recipients"] = json.loads(d.pop("recipients_json", "[]") or "[]")
        d["attachments"] = json.loads(d.pop("attachments_json", "[]") or "[]")
        d["settings"] = json.loads(d.pop("settings_json", "{}") or "{}")
        return d

    def update_draft(self, draft_id: int, name: str, subject: str, body: str, signature: str,
                     recipients: list[dict], attachments: list[str], settings: dict, user_id: Optional[int] = None):
        import json
        now = datetime.now().isoformat(timespec="seconds")
        if user_id is not None:
            self._conn.execute(
                "UPDATE drafts SET name=?, subject=?, body=?, signature=?, recipients_json=?, attachments_json=?, settings_json=?, updated_at=? WHERE id=? AND user_id=?",
                (name, subject, body, signature, json.dumps(recipients), json.dumps(attachments), json.dumps(settings), now, draft_id, user_id),
            )
        else:
            self._conn.execute(
                "UPDATE drafts SET name=?, subject=?, body=?, signature=?, recipients_json=?, attachments_json=?, settings_json=?, updated_at=? WHERE id=?",
                (name, subject, body, signature, json.dumps(recipients), json.dumps(attachments), json.dumps(settings), now, draft_id),
            )
        self._conn.commit()

    def delete_draft(self, draft_id: int, user_id: Optional[int] = None) -> bool:
        if user_id is not None:
            cursor = self._conn.execute("DELETE FROM drafts WHERE id=? AND user_id=?", (draft_id, user_id))
        else:
            cursor = self._conn.execute("DELETE FROM drafts WHERE id=?", (draft_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Campaigns
    # ------------------------------------------------------------------
    def create_campaign(self, subject: str, body: str, signature: str,
                        attachments: list[str], settings: dict, user_id: int) -> int:
        import json
        now = datetime.now().isoformat(timespec="seconds")
        cur = self._conn.execute(
            "INSERT INTO campaigns (user_id, subject, body, signature, attachments_json, settings_json, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, subject, body, signature, json.dumps(attachments), json.dumps(settings), "draft", now, now),
        )
        self._conn.commit()
        return cur.lastrowid

    def list_campaigns(self, user_id: Optional[int] = None):
        import json
        if user_id is not None:
            cur = self._conn.execute(
                "SELECT id, user_id, subject, body, signature, attachments_json, settings_json, total_recipients, sent_count, failed_count, skipped_count, status, created_at, updated_at FROM campaigns WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,)
            )
        else:
            cur = self._conn.execute(
                "SELECT id, user_id, subject, body, signature, attachments_json, settings_json, total_recipients, sent_count, failed_count, skipped_count, status, created_at, updated_at FROM campaigns ORDER BY updated_at DESC"
            )
        cols = ["id", "user_id", "subject", "body", "signature", "attachments_json", "settings_json",
                "total_recipients", "sent_count", "failed_count", "skipped_count", "status", "created_at", "updated_at"]
        rows = []
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            d["attachments"] = json.loads(d.pop("attachments_json", "[]") or "[]")
            d["settings"] = json.loads(d.pop("settings_json", "{}") or "{}")
            rows.append(d)
        return rows

    def get_campaign(self, campaign_id: int, user_id: Optional[int] = None):
        import json
        if user_id is not None:
            cur = self._conn.execute(
                "SELECT id, user_id, subject, body, signature, attachments_json, settings_json, total_recipients, sent_count, failed_count, skipped_count, status, created_at, updated_at FROM campaigns WHERE id = ? AND user_id = ?",
                (campaign_id, user_id),
            )
        else:
            cur = self._conn.execute(
                "SELECT id, user_id, subject, body, signature, attachments_json, settings_json, total_recipients, sent_count, failed_count, skipped_count, status, created_at, updated_at FROM campaigns WHERE id = ?",
                (campaign_id,),
            )
        row = cur.fetchone()
        if not row:
            return None
        cols = ["id", "user_id", "subject", "body", "signature", "attachments_json", "settings_json",
                "total_recipients", "sent_count", "failed_count", "skipped_count", "status", "created_at", "updated_at"]
        d = dict(zip(cols, row))
        d["attachments"] = json.loads(d.pop("attachments_json", "[]") or "[]")
        d["settings"] = json.loads(d.pop("settings_json", "{}") or "{}")
        return d

    def update_campaign(self, campaign_id: int, user_id: Optional[int] = None, **kwargs):
        import json
        allowed = {"subject", "body", "signature", "attachments", "settings",
                   "total_recipients", "sent_count", "failed_count", "skipped_count", "status"}
        sets = []
        values = []
        for key, val in kwargs.items():
            if key not in allowed:
                continue
            if key in ("attachments", "settings"):
                val = json.dumps(val)
            sets.append(f"{key}=?")
            values.append(val)
        if not sets:
            return
        values.append(datetime.now().isoformat(timespec="seconds"))
        values.append(campaign_id)
        if user_id is not None:
            self._conn.execute(
                f"UPDATE campaigns SET {', '.join(sets)}, updated_at=? WHERE id=? AND user_id=?",
                values + [user_id],
            )
        else:
            self._conn.execute(
                f"UPDATE campaigns SET {', '.join(sets)}, updated_at=? WHERE id=?",
                values,
            )
        self._conn.commit()

    def delete_campaign(self, campaign_id: int, user_id: Optional[int] = None) -> bool:
        if user_id is not None:
            self._conn.execute("DELETE FROM campaign_recipients WHERE campaign_id IN (SELECT id FROM campaigns WHERE campaign_id=? AND user_id=?)", (campaign_id, user_id))
            cursor = self._conn.execute("DELETE FROM campaigns WHERE id=? AND user_id=?", (campaign_id, user_id))
        else:
            self._conn.execute("DELETE FROM campaign_recipients WHERE campaign_id=?", (campaign_id,))
            cursor = self._conn.execute("DELETE FROM campaigns WHERE id=?", (campaign_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    def add_campaign_recipients(self, campaign_id: int, recipients: list[dict]):
        import json
        now = datetime.now().isoformat(timespec="seconds")
        rows = []
        for r in recipients:
            rows.append((
                campaign_id, r.get("email", ""), r.get("hr_name", ""), r.get("company", ""),
                r.get("job_role", ""), r.get("location", ""), "pending", "", now,
            ))
        self._conn.executemany(
            "INSERT INTO campaign_recipients (campaign_id, email, hr_name, company, job_role, location, status, error, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()

    def update_campaign_recipient(self, campaign_id: int, email: str, status: str, error: str = ""):
        self._conn.execute(
            "UPDATE campaign_recipients SET status=?, error=? WHERE campaign_id=? AND email=?",
            (status, error, campaign_id, email),
        )
        self._conn.commit()

    def get_campaign_recipients(self, campaign_id: int, status_filter: Optional[str] = None):
        query = "SELECT email, hr_name, company, job_role, location, status, error, timestamp FROM campaign_recipients WHERE campaign_id=?"
        params = [campaign_id]
        if status_filter:
            query += " AND status=?"
            params.append(status_filter)
        cur = self._conn.execute(query, params)
        cols = ["email", "hr_name", "company", "job_role", "location", "status", "error", "timestamp"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def _migrate_add_user_id(self):
        try:
            cursor = self._conn.execute("PRAGMA table_info(templates)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'user_id' not in columns:
                self._conn.execute("ALTER TABLE templates ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")
                self._conn.commit()

            cursor = self._conn.execute("PRAGMA table_info(drafts)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'user_id' not in columns:
                self._conn.execute("ALTER TABLE drafts ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")
                self._conn.commit()

            cursor = self._conn.execute("PRAGMA table_info(campaigns)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'user_id' not in columns:
                self._conn.execute("ALTER TABLE campaigns ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")
                self._conn.commit()

            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_templates_user_id ON templates(user_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_drafts_user_id ON drafts(user_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_user_id ON campaigns(user_id)")
            self._conn.commit()
        except Exception:
            pass

    def close(self):
        self._conn.close()

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------
    def create_user(self, username: str, password_hash: str) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        cur = self._conn.execute(
            "INSERT INTO users (username, password_hash, created_at, updated_at, is_active) VALUES (?, ?, ?, ?, ?)",
            (username, password_hash, now, now, 1),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_user_by_username(self, username: str):
        cur = self._conn.execute(
            "SELECT id, username, password_hash, created_at, updated_at, is_active, last_login_at FROM users WHERE username = ?",
            (username,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = ["id", "username", "password_hash", "created_at", "updated_at", "is_active", "last_login_at"]
        return dict(zip(cols, row))

    def get_user_by_id(self, user_id: int):
        cur = self._conn.execute(
            "SELECT id, username, password_hash, created_at, updated_at, is_active, last_login_at FROM users WHERE id = ?",
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = ["id", "username", "password_hash", "created_at", "updated_at", "is_active", "last_login_at"]
        return dict(zip(cols, row))

    def update_last_login(self, user_id: int):
        now = datetime.now().isoformat(timespec="seconds")
        self._conn.execute(
            "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
            (now, now, user_id),
        )
        self._conn.commit()

    def user_exists(self) -> bool:
        cur = self._conn.execute("SELECT 1 FROM users LIMIT 1")
        return cur.fetchone() is not None

    def count_users(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM users")
        row = cur.fetchone()
        return row[0] if row else 0

    def migrate_legacy_user(self, username: str, password_hash: str) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        cur = self._conn.execute(
            "INSERT INTO users (username, password_hash, created_at, updated_at, is_active) VALUES (?, ?, ?, ?, ?)",
            (username, password_hash, now, now, 1),
        )
        self._conn.commit()
        return cur.lastrowid
