"""
database.py
Database abstraction layer supporting both SQLite (local) and Cloudflare D1 (production).

For local development, uses SQLite with file-based storage.
For Cloudflare Workers, uses D1 via the DB binding.
"""
import os
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, Any

# Environment detection
IS_CLOUDFLARE_WORKER = os.environ.get("CLOUDFLARE_WORKER") == "1"
IS_VERCEL = os.environ.get("VERCEL") == "1"

# =============================================================================
# Database Schema (SQLite version - D1 uses equivalent SQL)
# =============================================================================
SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS sent_emails (
    email TEXT PRIMARY KEY,
    hr_name TEXT,
    company TEXT,
    job_role TEXT,
    status TEXT,
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
    status TEXT DEFAULT 'draft',
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
    status TEXT DEFAULT 'pending',
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

# =============================================================================
# SQLite Backend (Local Development)
# =============================================================================
class SQLiteBackend:
    """SQLite database backend for local development."""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is not None:
            self.db_path = db_path
        else:
            if IS_VERCEL:
                data_dir = os.environ.get("TMPDIR", "/tmp")
            else:
                data_dir = os.environ.get("RESUMEMAILER_DATA_DIR", "")
                if not data_dir:
                    data_dir = str(Path(__file__).resolve().parent)
            self.db_path = Path(data_dir) / "resumemailer.db"

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.executescript(SQLITE_SCHEMA)
        self._conn.commit()
        self._migrate_add_user_id()

    def _migrate_add_user_id(self):
        """Add user_id columns and indexes if they don't exist."""
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

    def execute(self, query: str, params: tuple = ()) -> list:
        """Execute a query and return results as list of rows.

        For INSERT: returns [lastrowid] or [] if no rows affected
        For UPDATE/DELETE: returns number of affected rows
        For SELECT: returns list of rows
        """
        cur = self._conn.execute(query, params)
        query_upper = query.strip().upper()

        if query_upper.startswith("INSERT"):
            self._conn.commit()
            lastrowid = cur.lastrowid
            return [lastrowid] if lastrowid is not None else []
        elif query_upper.startswith(("UPDATE", "DELETE")):
            self._conn.commit()
            return cur.rowcount
        else:
            return cur.fetchall()

    def executemany(self, query: str, params_list: list):
        """Execute a query with multiple parameter sets."""
        self._conn.executemany(query, params_list)
        self._conn.commit()

    def close(self):
        self._conn.close()


# =============================================================================
# D1 Backend (Cloudflare Workers)
# =============================================================================
class D1Backend:
    """
    D1 database backend for Cloudflare Workers.

    D1 uses a different API - queries return results via a cursor-like interface.
    The binding provides exec() method that returns results.
    """

    def __init__(self, d1_binding):
        self._d1 = d1_binding

    def execute(self, query: str, params: tuple = ()) -> list:
        """
        Execute a query and return results as list of rows.
        D1.exec() returns a result set with rows accessible via iteration.
        """
        params_list = list(params) if params else []
        result = self._d1.exec(query, *params_list)

        rows = []
        for row in result:
            rows.append(row)

        return rows

    def executemany(self, query: str, params_list: list):
        """Execute a query with multiple parameter sets."""
        if self._is_d1:
            for params in params_list:
                params_tuple = tuple(params) if not isinstance(params, tuple) else params
                self._d1.exec(query, params_tuple)
        else:
            self._backend.executemany(query, params_list)

    def close(self):
        """D1 auto-closes, no-op for compatibility."""
        pass


# =============================================================================
# Database Factory
# =============================================================================
def create_database_backend(db_path: Optional[Path] = None, d1_binding=None) -> Any:
    """
    Factory function to create the appropriate database backend.

    Args:
        db_path: Path to the SQLite database file (only used for local development)
        d1_binding: D1 binding object (only used in Cloudflare Workers environment)

    Returns:
        SQLiteBackend for local development, D1Backend for Cloudflare Workers
    """
    if IS_CLOUDFLARE_WORKER and d1_binding is not None:
        return D1Backend(d1_binding)
    return SQLiteBackend(db_path)


# =============================================================================
# Database Interface (Unified API)
# =============================================================================
class Database:
    """
    Unified database interface that works with both SQLite and D1 backends.

    For Cloudflare Workers, pass the D1 binding:
        db = Database(d1_binding=context.modules.DB)
    """

    def __init__(self, db_path: Optional[Path] = None, d1_binding=None):
        self._backend = create_database_backend(db_path, d1_binding)
        self._is_d1 = isinstance(self._backend, D1Backend)

    def _ensure_user_id_filter(self, user_id: Optional[int], base_query: str, conditions: list, params: list) -> tuple[str, list]:
        """Helper to add user_id filter to queries."""
        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)
        query = base_query + " AND ".join(conditions) if conditions else base_query
        return query, params

    # -------------------------------------------------------------------------
    # Sent Emails (global, no user isolation)
    # -------------------------------------------------------------------------
    def is_already_sent(self, email: str) -> bool:
        rows = self._backend.execute(
            "SELECT status FROM sent_emails WHERE email = ? AND status = 'sent'",
            (email.lower(),)
        )
        return len(rows) > 0

    def record(self, email, hr_name, company, job_role, status, attempts, error=""):
        self._backend.execute(
            """
            INSERT INTO sent_emails (email, hr_name, company, job_role, status, attempts, error, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                status=excluded.status,
                attempts=excluded.attempts,
                error=excluded.error,
                timestamp=excluded.timestamp
            """,
            (email.lower(), hr_name, company, job_role, status, attempts, error,
             datetime.now().isoformat(timespec="seconds"))
        )

    def stats(self):
        rows = self._backend.execute(
            "SELECT status, COUNT(*) FROM sent_emails GROUP BY status"
        )
        result = {"sent": 0, "failed": 0}
        for row in rows:
            if len(row) >= 2:
                result[row[0]] = row[1]
        return result

    def all_records(self):
        rows = self._backend.execute(
            "SELECT email, hr_name, company, job_role, status, attempts, error, timestamp FROM sent_emails"
        )
        cols = ["email", "hr_name", "company", "job_role", "status", "attempts", "error", "timestamp"]
        return [dict(zip(cols, row)) for row in rows]

    def sent_emails_set(self) -> set[str]:
        rows = self._backend.execute("SELECT email FROM sent_emails WHERE status='sent'")
        return {row[0] for row in rows if row}

    # -------------------------------------------------------------------------
    # Templates
    # -------------------------------------------------------------------------
    def create_template(self, name: str, subject: str, body: str, signature: str, user_id: int) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        rows = self._backend.execute(
            "INSERT INTO templates (user_id, name, subject, body, signature, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, name, subject, body, signature, now, now)
        )
        if self._is_d1:
            result = self._backend.execute("SELECT last_insert_rowid()")
            return list(result[0])[0] if result else 0
        return rows[0] if rows else 0

    def list_templates(self, user_id: Optional[int] = None):
        if user_id is not None:
            rows = self._backend.execute(
                "SELECT id, user_id, name, subject, body, signature, created_at, updated_at FROM templates WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,)
            )
        else:
            rows = self._backend.execute(
                "SELECT id, user_id, name, subject, body, signature, created_at, updated_at FROM templates ORDER BY updated_at DESC"
            )
        cols = ["id", "user_id", "name", "subject", "body", "signature", "created_at", "updated_at"]
        return [dict(zip(cols, row)) for row in rows]

    def get_template(self, template_id: int, user_id: Optional[int] = None):
        if user_id is not None:
            rows = self._backend.execute(
                "SELECT id, user_id, name, subject, body, signature, created_at, updated_at FROM templates WHERE id = ? AND user_id = ?",
                (template_id, user_id)
            )
        else:
            rows = self._backend.execute(
                "SELECT id, user_id, name, subject, body, signature, created_at, updated_at FROM templates WHERE id = ?",
                (template_id,)
            )
        if not rows:
            return None
        cols = ["id", "user_id", "name", "subject", "body", "signature", "created_at", "updated_at"]
        return dict(zip(cols, rows[0]))

    def update_template(self, template_id: int, name: str, subject: str, body: str, signature: str, user_id: Optional[int] = None) -> bool:
        now = datetime.now().isoformat(timespec="seconds")
        if user_id is not None:
            rows = self._backend.execute(
                "UPDATE templates SET name=?, subject=?, body=?, signature=?, updated_at=? WHERE id=? AND user_id=?",
                (name, subject, body, signature, now, template_id, user_id)
            )
        else:
            rows = self._backend.execute(
                "UPDATE templates SET name=?, subject=?, body=?, signature=?, updated_at=? WHERE id=?",
                (name, subject, body, signature, now, template_id)
            )
        return rows > 0 if isinstance(rows, int) else len(rows) > 0

    def delete_template(self, template_id: int, user_id: Optional[int] = None) -> bool:
        if user_id is not None:
            rows = self._backend.execute("DELETE FROM templates WHERE id=? AND user_id=?", (template_id, user_id))
        else:
            rows = self._backend.execute("DELETE FROM templates WHERE id=?", (template_id,))
        return rows > 0 if isinstance(rows, int) else len(rows) > 0

    # -------------------------------------------------------------------------
    # Drafts
    # -------------------------------------------------------------------------
    def create_draft(self, name: str, subject: str, body: str, signature: str,
                      recipients: list[dict], attachments: list[str], settings: dict, user_id: int) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        rows = self._backend.execute(
            "INSERT INTO drafts (user_id, name, subject, body, signature, recipients_json, attachments_json, settings_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, name, subject, body, signature, json.dumps(recipients), json.dumps(attachments), json.dumps(settings), now, now)
        )
        if self._is_d1:
            result = self._backend.execute("SELECT last_insert_rowid()")
            return list(result[0])[0] if result else 0
        return rows[0] if rows else 0

    def list_drafts(self, user_id: Optional[int] = None):
        if user_id is not None:
            rows = self._backend.execute(
                "SELECT id, user_id, name, subject, body, signature, recipients_json, attachments_json, settings_json, created_at, updated_at FROM drafts WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,)
            )
        else:
            rows = self._backend.execute(
                "SELECT id, user_id, name, subject, body, signature, recipients_json, attachments_json, settings_json, created_at, updated_at FROM drafts ORDER BY updated_at DESC"
            )
        cols = ["id", "user_id", "name", "subject", "body", "signature", "recipients_json", "attachments_json", "settings_json", "created_at", "updated_at"]
        result = []
        for row in rows:
            d = dict(zip(cols, row))
            d["recipients"] = json.loads(d.pop("recipients_json", "[]") or "[]")
            d["attachments"] = json.loads(d.pop("attachments_json", "[]") or "[]")
            d["settings"] = json.loads(d.pop("settings_json", "{}") or "{}")
            result.append(d)
        return result

    def get_draft(self, draft_id: int, user_id: Optional[int] = None):
        if user_id is not None:
            rows = self._backend.execute(
                "SELECT id, user_id, name, subject, body, signature, recipients_json, attachments_json, settings_json, created_at, updated_at FROM drafts WHERE id = ? AND user_id = ?",
                (draft_id, user_id)
            )
        else:
            rows = self._backend.execute(
                "SELECT id, user_id, name, subject, body, signature, recipients_json, attachments_json, settings_json, created_at, updated_at FROM drafts WHERE id = ?",
                (draft_id,)
            )
        if not rows:
            return None
        cols = ["id", "user_id", "name", "subject", "body", "signature", "recipients_json", "attachments_json", "settings_json", "created_at", "updated_at"]
        d = dict(zip(cols, rows[0]))
        d["recipients"] = json.loads(d.pop("recipients_json", "[]") or "[]")
        d["attachments"] = json.loads(d.pop("attachments_json", "[]") or "[]")
        d["settings"] = json.loads(d.pop("settings_json", "{}") or "{}")
        return d

    def update_draft(self, draft_id: int, name: str, subject: str, body: str, signature: str,
                     recipients: list[dict], attachments: list[str], settings: dict, user_id: Optional[int] = None):
        now = datetime.now().isoformat(timespec="seconds")
        if user_id is not None:
            self._backend.execute(
                "UPDATE drafts SET name=?, subject=?, body=?, signature=?, recipients_json=?, attachments_json=?, settings_json=?, updated_at=? WHERE id=? AND user_id=?",
                (name, subject, body, signature, json.dumps(recipients), json.dumps(attachments), json.dumps(settings), now, draft_id, user_id)
            )
        else:
            self._backend.execute(
                "UPDATE drafts SET name=?, subject=?, body=?, signature=?, recipients_json=?, attachments_json=?, settings_json=?, updated_at=? WHERE id=?",
                (name, subject, body, signature, json.dumps(recipients), json.dumps(attachments), json.dumps(settings), now, draft_id)
            )

    def delete_draft(self, draft_id: int, user_id: Optional[int] = None) -> bool:
        if user_id is not None:
            rows = self._backend.execute("DELETE FROM drafts WHERE id=? AND user_id=?", (draft_id, user_id))
        else:
            rows = self._backend.execute("DELETE FROM drafts WHERE id=?", (draft_id,))
        return rows > 0 if isinstance(rows, int) else len(rows) > 0

    # -------------------------------------------------------------------------
    # Campaigns
    # -------------------------------------------------------------------------
    def create_campaign(self, subject: str, body: str, signature: str,
                        attachments: list[str], settings: dict, user_id: int) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        rows = self._backend.execute(
            "INSERT INTO campaigns (user_id, subject, body, signature, attachments_json, settings_json, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, subject, body, signature, json.dumps(attachments), json.dumps(settings), "draft", now, now)
        )
        if self._is_d1:
            result = self._backend.execute("SELECT last_insert_rowid()")
            return list(result[0])[0] if result else 0
        return rows[0] if rows else 0

    def list_campaigns(self, user_id: Optional[int] = None):
        if user_id is not None:
            rows = self._backend.execute(
                "SELECT id, user_id, subject, body, signature, attachments_json, settings_json, total_recipients, sent_count, failed_count, skipped_count, status, created_at, updated_at FROM campaigns WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,)
            )
        else:
            rows = self._backend.execute(
                "SELECT id, user_id, subject, body, signature, attachments_json, settings_json, total_recipients, sent_count, failed_count, skipped_count, status, created_at, updated_at FROM campaigns ORDER BY updated_at DESC"
            )
        cols = ["id", "user_id", "subject", "body", "signature", "attachments_json", "settings_json",
                "total_recipients", "sent_count", "failed_count", "skipped_count", "status", "created_at", "updated_at"]
        result = []
        for row in rows:
            d = dict(zip(cols, row))
            d["attachments"] = json.loads(d.pop("attachments_json", "[]") or "[]")
            d["settings"] = json.loads(d.pop("settings_json", "{}") or "{}")
            result.append(d)
        return result

    def get_campaign(self, campaign_id: int, user_id: Optional[int] = None):
        if user_id is not None:
            rows = self._backend.execute(
                "SELECT id, user_id, subject, body, signature, attachments_json, settings_json, total_recipients, sent_count, failed_count, skipped_count, status, created_at, updated_at FROM campaigns WHERE id = ? AND user_id = ?",
                (campaign_id, user_id)
            )
        else:
            rows = self._backend.execute(
                "SELECT id, user_id, subject, body, signature, attachments_json, settings_json, total_recipients, sent_count, failed_count, skipped_count, status, created_at, updated_at FROM campaigns WHERE id = ?",
                (campaign_id,)
            )
        if not rows:
            return None
        cols = ["id", "user_id", "subject", "body", "signature", "attachments_json", "settings_json",
                "total_recipients", "sent_count", "failed_count", "skipped_count", "status", "created_at", "updated_at"]
        d = dict(zip(cols, rows[0]))
        d["attachments"] = json.loads(d.pop("attachments_json", "[]") or "[]")
        d["settings"] = json.loads(d.pop("settings_json", "{}") or "{}")
        return d

    def update_campaign(self, campaign_id: int, user_id: Optional[int] = None, **kwargs):
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
            self._backend.execute(
                f"UPDATE campaigns SET {', '.join(sets)}, updated_at=? WHERE id=? AND user_id=?",
                values + [user_id]
            )
        else:
            self._backend.execute(
                f"UPDATE campaigns SET {', '.join(sets)}, updated_at=? WHERE id=?",
                values
            )

    def delete_campaign(self, campaign_id: int, user_id: Optional[int] = None) -> bool:
        if user_id is not None:
            self._backend.execute("DELETE FROM campaign_recipients WHERE campaign_id IN (SELECT id FROM campaigns WHERE campaign_id=? AND user_id=?)", (campaign_id, user_id))
            rows = self._backend.execute("DELETE FROM campaigns WHERE id=? AND user_id=?", (campaign_id, user_id))
        else:
            self._backend.execute("DELETE FROM campaign_recipients WHERE campaign_id=?", (campaign_id,))
            rows = self._backend.execute("DELETE FROM campaigns WHERE id=?", (campaign_id,))
        return rows > 0 if isinstance(rows, int) else len(rows) > 0

    # -------------------------------------------------------------------------
    # Campaign Recipients
    # -------------------------------------------------------------------------
    def add_campaign_recipients(self, campaign_id: int, recipients: list[dict]):
        now = datetime.now().isoformat(timespec="seconds")
        rows = []
        for r in recipients:
            rows.append((
                campaign_id, r.get("email", ""), r.get("hr_name", ""), r.get("company", ""),
                r.get("job_role", ""), r.get("location", ""), "pending", "", now,
            ))
        self._backend.executemany(
            "INSERT INTO campaign_recipients (campaign_id, email, hr_name, company, job_role, location, status, error, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows
        )

    def update_campaign_recipient(self, campaign_id: int, email: str, status: str, error: str = ""):
        self._backend.execute(
            "UPDATE campaign_recipients SET status=?, error=? WHERE campaign_id=? AND email=?",
            (status, error, campaign_id, email)
        )

    def get_campaign_recipients(self, campaign_id: int, status_filter: Optional[str] = None):
        query = "SELECT email, hr_name, company, job_role, location, status, error, timestamp FROM campaign_recipients WHERE campaign_id=?"
        params = [campaign_id]
        if status_filter:
            query += " AND status=?"
            params.append(status_filter)
        rows = self._backend.execute(query, params)
        cols = ["email", "hr_name", "company", "job_role", "location", "status", "error", "timestamp"]
        return [dict(zip(cols, row)) for row in rows]

    # -------------------------------------------------------------------------
    # Users
    # -------------------------------------------------------------------------
    def create_user(self, username: str, password_hash: str) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        rows = self._backend.execute(
            "INSERT INTO users (username, password_hash, created_at, updated_at, is_active) VALUES (?, ?, ?, ?, ?)",
            (username, password_hash, now, now, 1)
        )
        if self._is_d1:
            result = self._backend.execute("SELECT last_insert_rowid()")
            return list(result[0])[0] if result else 0
        return rows[0] if rows else 0

    def get_user_by_username(self, username: str):
        rows = self._backend.execute(
            "SELECT id, username, password_hash, created_at, updated_at, is_active, last_login_at FROM users WHERE username = ?",
            (username,)
        )
        if not rows:
            return None
        cols = ["id", "username", "password_hash", "created_at", "updated_at", "is_active", "last_login_at"]
        return dict(zip(cols, rows[0]))

    def get_user_by_id(self, user_id: int):
        rows = self._backend.execute(
            "SELECT id, username, password_hash, created_at, updated_at, is_active, last_login_at FROM users WHERE id = ?",
            (user_id,)
        )
        if not rows:
            return None
        cols = ["id", "username", "password_hash", "created_at", "updated_at", "is_active", "last_login_at"]
        return dict(zip(cols, rows[0]))

    def update_last_login(self, user_id: int):
        now = datetime.now().isoformat(timespec="seconds")
        self._backend.execute(
            "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
            (now, now, user_id)
        )

    def user_exists(self) -> bool:
        rows = self._backend.execute("SELECT 1 FROM users LIMIT 1")
        return len(rows) > 0

    def count_users(self) -> int:
        rows = self._backend.execute("SELECT COUNT(*) FROM users")
        return rows[0][0] if rows else 0

    def migrate_legacy_user(self, username: str, password_hash: str) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        rows = self._backend.execute(
            "INSERT INTO users (username, password_hash, created_at, updated_at, is_active) VALUES (?, ?, ?, ?, ?)",
            (username, password_hash, now, now, 1)
        )
        if self._is_d1:
            result = self._backend.execute("SELECT last_insert_rowid()")
            return list(result[0])[0] if result else 0
        return rows

    def close(self):
        self._backend.close()


# =============================================================================
# Legacy compatibility - allow Database() without arguments for local dev
# =============================================================================
_original_init = Database.__init__

def _compat_init(self, db_path=None, d1_binding=None):
    if d1_binding is not None:
        _original_init(self, db_path=db_path, d1_binding=d1_binding)
    elif IS_CLOUDFLARE_WORKER:
        raise RuntimeError(
            "Database requires d1_binding in Cloudflare Workers environment. "
            "Use: Database(d1_binding=context.modules.DB)"
        )
    else:
        _original_init(self, db_path=db_path)

Database.__init__ = _compat_init
