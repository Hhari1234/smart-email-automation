"""
server.py
FastAPI backend for ResumeMailer web application.
Wraps existing backend modules and exposes REST APIs.
"""
import os
import sys
import uuid
import json
import threading
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request, Response, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import auth
from auth import (
    require_auth,
    require_csrf,
    attempt_login,
    client_ip,
    build_auth_cookies,
    clear_auth_cookies,
    is_auth_disabled,
)

# Ensure project root is in path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from config import Settings, get_env
from database import Database
from excel_io import load_recipients, create_sample_recipients, append_log, export_failed, export_summary
from template_engine import render, extract_placeholders, text_to_html
from validators import is_valid_email, clean_email, validate_recipient_row
from mailer import EmailSender, SendError
from sender_worker import SendWorker
from recipient_parser import parse_recipients

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
logger = logging.getLogger("resumemailer")
if not logger.handlers:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

APP_ENV = os.environ.get("APP_ENV", "development").lower()
IS_PRODUCTION = APP_ENV == "production"

if is_auth_disabled() and IS_PRODUCTION:
    logger.warning(
        "Authentication is DISABLED (no APP_USERNAME/APP_PASSWORD_HASH/APP_SECRET_KEY set). "
        "Refusing to start in production."
    )
    raise SystemExit(
        "Refusing to start: APP_USERNAME, APP_PASSWORD_HASH and APP_SECRET_KEY must be set "
        "when APP_ENV=production."
    )

if is_auth_disabled():
    logger.warning(
        "Authentication is DISABLED. Set APP_USERNAME, APP_PASSWORD_HASH and APP_SECRET_KEY "
        "in your .env to require login."
    )

app = FastAPI(title="ResumeMailer API", version="1.0.0")

# CORS: the frontend is served from the same origin. Keep CORS minimal and
# never combine allow_origins=["*"] with allow_credentials=True.
_cors_origins_env = os.environ.get("CORS_ALLOW_ORIGINS", "").strip()
_cors_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )
else:
    # Same-origin deployment: do not enable CORS at all.
    pass


# ---------------------------------------------------------------------------
# Security headers + error handling middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    try:
        response = await call_next(request)
    except Exception as exc:
        # Log full traceback server-side, never leak to user.
        logger.exception("Unhandled error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Something went wrong. Please try again."},
        )

    path = request.url.path or ""
    # Don't add restrictive headers to the login page assets; keep HSTS only on HTML.
    is_html = path.endswith(".html") or path in ("/", "/login")

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if is_html:
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
            "font-src 'self' https://fonts.gstatic.com; "
            "script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self';",
        )

    if request.url.scheme == "https" or IS_PRODUCTION:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB

# Conservative allowlist of file types the app actually handles.
# Anything outside this list is rejected before anything is written to disk.
ALLOWED_UPLOAD_EXTENSIONS = {
    # Spreadsheets (recipients)
    ".xlsx", ".xls", ".csv",
    # Resume / common attachments
    ".pdf", ".docx", ".doc", ".txt", ".rtf", ".md",
    # Images that can be embedded inline
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
}

# Per-request upload kind ("recipients" | "attachment") controls the allowlist.
ALLOWED_KIND_EXTENSIONS = {
    "recipients": {".xlsx", ".xls", ".csv"},
    "attachment": ALLOWED_UPLOAD_EXTENSIONS,
}

def _runtime_dir(name: str) -> Path:
    base = os.environ.get("TMPDIR") or os.environ.get("TEMP") or os.environ.get("TMP")
    if not base or not Path(base).exists():
        base = str(Path.cwd())
    target = Path(base) / name
    target.mkdir(parents=True, exist_ok=True)
    return target

# Ensure data directory exists
data_dir = os.environ.get("RESUMEMAILER_DATA_DIR", "")
if data_dir:
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR = Path(data_dir) / "uploads"
    LOGS_DIR = Path(data_dir) / "logs"
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
else:
    UPLOADS_DIR = _runtime_dir("resumemailer_uploads")
    LOGS_DIR = _runtime_dir("resumemailer_logs")

# ---------------------------------------------------------------------------
# Global state (thread-safe for simple reads; writes happen mainly from
# the send worker callbacks which we control)
# ---------------------------------------------------------------------------
class AppState:
    def __init__(self):
        self.settings = Settings()
        self.recipients: list[dict] = []
        self.worker: Optional[SendWorker] = None
        self.worker_status = "idle"  # idle | running | paused
        self.progress = {"sent": 0, "failed": 0, "skipped": 0, "total": 0}
        self.logs: list[str] = []
        self.last_error: Optional[str] = None
        self._lock = threading.Lock()

        # Repeat-send state
        self.repeat_worker: Optional[RepeatSendWorker] = None
        self.repeat_status = "idle"  # idle | running | stopped | completed | error
        self.repeat_progress = {"current": 0, "sent": 0, "failed": 0, "total": 0}
        self.repeat_logs: list[str] = []

        # Campaign state
        self.campaign_worker: Optional[SendWorker] = None
        self.campaign_status = "idle"  # idle | running | paused
        self.campaign_progress = {"sent": 0, "failed": 0, "skipped": 0, "total": 0}
        self.campaign_logs: list[str] = []
        self.active_campaign_id: Optional[int] = None

    def add_log(self, message: str):
        with self._lock:
            self.logs.append(message)
            if len(self.logs) > 2000:
                self.logs = self.logs[-1000:]

    def add_repeat_log(self, message: str):
        with self._lock:
            self.repeat_logs.append(message)
            if len(self.repeat_logs) > 2000:
                self.repeat_logs = self.repeat_logs[-1000:]

    def add_campaign_log(self, message: str):
        with self._lock:
            self.campaign_logs.append(message)
            if len(self.campaign_logs) > 2000:
                self.campaign_logs = self.campaign_logs[-1000:]

    def clear_logs(self):
        with self._lock:
            self.logs = []
            self.repeat_logs = []
            self.campaign_logs = []

state = AppState()
db = Database()


# ---------------------------------------------------------------------------
# Repeat send worker (single recipient, multiple sequential sends)
# ---------------------------------------------------------------------------
class RepeatSendWorker(threading.Thread):
    def __init__(self, settings, to_email, subject_template, body_template,
                 signature_html, count, delay_seconds, attachments,
                 on_progress, on_log, on_done):
        super().__init__(daemon=True)
        self.settings = settings
        self.to_email = clean_email(to_email)
        self.subject_template = subject_template
        self.body_template = body_template
        self.signature_html = signature_html
        self.count = int(count)
        self.delay_seconds = float(delay_seconds)
        self.attachments = attachments or []
        self.on_progress = on_progress
        self.on_log = on_log
        self.on_done = on_done

        self._stop_flag = threading.Event()
        self.sent = 0
        self.failed = 0
        self.completed = False

    def stop(self):
        self._stop_flag.set()

    def _sleep_with_checks(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            if self._stop_flag.is_set():
                return
            time.sleep(min(0.5, max(0, end - time.time())))

    def run(self):
        try:
            sender = EmailSender(self.settings)
        except SendError as e:
            self.on_log(f"FATAL: Could not initialize email backend: {e}")
            self.on_done({"sent": 0, "failed": self.count, "status": "error", "error": str(e)})
            return

        self.on_log(f"Using backend: {sender.backend_name}")
        context_static = {
            "your_name": self.settings.get("sender_name", ""),
            "your_email": self.settings.get("sender_email", ""),
            "your_phone": self.settings.get("sender_phone", ""),
            "your_linkedin": self.settings.get("sender_linkedin", ""),
        }

        for i in range(1, self.count + 1):
            if self._stop_flag.is_set():
                self.on_log("Stopped by user.")
                break

            self.on_log(f"Sending email {i} of {self.count}...")
            context = dict(context_static)
            context.update({
                "hr_name": "",
                "company": "",
                "job_role": "",
                "location": "",
            })
            subject = render(self.subject_template, context)
            body_html = text_to_html(render(self.body_template, context))
            sig_html = render(self.signature_html, context)
            full_html = f"{body_html}{sig_html}"

            try:
                sender.send(self.to_email, subject, full_html, self.attachments)
                self.sent += 1
                self.on_log(f"Email {i} sent successfully")
            except SendError as e:
                self.failed += 1
                self.on_log(f"Email {i} failed: {e}")

            self.on_progress(i, self.sent, self.failed, self.count)

            if i < self.count and not self._stop_flag.is_set():
                if self.delay_seconds > 0:
                    self.on_log(f"Waiting {self.delay_seconds} seconds...")
                    self._sleep_with_checks(self.delay_seconds)

        self.completed = not self._stop_flag.is_set()
        status = "completed" if self.completed else "stopped"
        self.on_log(
            f"Email batch completed: sent={self.sent} failed={self.failed} total={self.count}"
        )
        self.on_done({
            "sent": self.sent,
            "failed": self.failed,
            "total": self.count,
            "status": status,
        })


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class SettingsModel(BaseModel):
    sender_name: str = ""
    sender_email: str = ""
    sender_phone: str = ""
    sender_linkedin: str = ""
    use_gmail_api: bool = True
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    delay_min_seconds: float = 5
    delay_max_seconds: float = 15
    max_retries: int = 3
    resume_path: str = ""
    extra_attachments: list[str] = []
    template_path: str = str(BASE_DIR / "sample_data" / "email_template.txt")
    subject: str = "Application for {{job_role}} at {{company}}"
    signature: str = (
        "<br><br>Best regards,<br>"
        "<b>{{your_name}}</b><br>{{your_phone}} | {{your_email}}<br>"
        "{{your_linkedin}}"
    )
    recipients_path: str = ""
    last_column_map: dict = {}

class PreviewRequest(BaseModel):
    subject: str
    body: str
    signature: str
    context: dict

class SendTestRequest(BaseModel):
    subject: str
    body: str
    signature: str
    to_email: str
    context: dict
    attachments: list[str] = []

class StartSendRequest(BaseModel):
    subject: str
    body: str
    signature: str
    attachments: list[str] = []

class RepeatSendRequest(BaseModel):
    to_email: str
    subject: str
    body: str
    signature: str
    count: int = 1
    delay_seconds: float = 5
    attachments: list[str] = []

class ParseRecipientsRequest(BaseModel):
    raw_text: str

class MergeRecipientsRequest(BaseModel):
    new_recipients: list[dict]

class CampaignCreateRequest(BaseModel):
    name: str = ""
    subject: str
    body: str
    signature: str
    attachments: list[str] = []
    settings: dict = {}

class DraftCreateRequest(BaseModel):
    name: str = ""
    subject: str
    body: str
    signature: str
    recipients: list[dict] = []
    attachments: list[str] = []
    settings: dict = {}

class TemplateCreateRequest(BaseModel):
    name: str
    subject: str
    body: str
    signature: str

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _save_upload(upload: UploadFile, kind: str = "attachment") -> str:
    raw_name = upload.filename or "file"
    ext = Path(raw_name).suffix.lower()

    allowed = ALLOWED_KIND_EXTENSIONS.get(kind, ALLOWED_UPLOAD_EXTENSIONS)
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' is not allowed for {kind} upload.",
        )

    # Generated server-side filename: never trust the client-provided stem.
    safe_ext = ext or ".bin"
    name = f"upload_{uuid.uuid4().hex}{safe_ext}"
    dest = UPLOADS_DIR / name

    # Defense-in-depth: ensure the resolved path is still inside UPLOADS_DIR.
    try:
        dest_resolved = dest.resolve()
        if UPLOADS_DIR.resolve() not in dest_resolved.parents and dest_resolved != dest.resolve():
            raise HTTPException(status_code=400, detail="Invalid upload path")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid upload path")

    written = 0
    chunk_size = 1024 * 1024
    try:
        with open(dest, "wb") as f:
            while True:
                chunk = upload.file.read(chunk_size)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    f.close()
                    try:
                        dest.unlink()
                    except OSError:
                        pass
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds maximum size of {MAX_UPLOAD_BYTES // (1024*1024)} MB",
                    )
                f.write(chunk)
    except HTTPException:
        # Clean up any partial file.
        try:
            if dest.exists():
                dest.unlink()
        except OSError:
            pass
        raise
    except Exception:
        try:
            if dest.exists():
                dest.unlink()
        except OSError:
            pass
        raise HTTPException(status_code=500, detail="Upload failed")
    return str(dest)

def _recipients_to_dicts(df) -> list[dict]:
    from excel_io import _normalize_columns
    df = _normalize_columns(df)
    return df[["hr_name", "company", "email", "job_role", "location"]].to_dict("records")

def _merge_recipients(existing: list[dict], new_ones: list[dict]) -> tuple[list[dict], int, int]:
    """
    Merge new recipients into existing list.
    Returns (merged_list, new_count, duplicate_count)
    """
    existing_lower = {r.get("email", "").lower(): r for r in existing if r.get("email")}
    merged = list(existing)
    new_count = 0
    dup_count = 0
    for r in new_ones:
        email = r.get("email", "").lower()
        if not email:
            continue
        if email in existing_lower:
            dup_count += 1
            continue
        merged.append(r)
        existing_lower[email] = r
        new_count += 1
    return merged, new_count, dup_count

# ---------------------------------------------------------------------------
# Routes: State & Health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health_root():
    return {"status": "ok"}

@app.get("/api/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

@app.get("/api/auth/status")
async def auth_status(request: Request):
    user = auth.get_session_user(request)
    return {
        "authenticated": bool(user),
        "username": user,
        "auth_enabled": not is_auth_disabled(),
    }


# ---------------------------------------------------------------------------
# Routes: Auth (login / logout)
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str


def _set_cookie(response: Response, name: str, value: str, **kwargs):
    response.set_cookie(key=name, value=value, **kwargs)


@app.post("/api/auth/login")
async def login(payload: LoginRequest, request: Request):
    ip = client_ip(request)
    if is_auth_disabled():
        return {"status": "ok", "auth_disabled": True}

    success, message = attempt_login(payload.username, payload.password, ip)
    if not success:
        # 401 for invalid credentials, 429 for rate-limited.
        status_code = 429 if "Too many" in message else 401
        raise HTTPException(status_code=status_code, detail=message)

    cookies = build_auth_cookies(payload.username)
    response = JSONResponse({"status": "ok", "username": payload.username})
    for name, cfg in cookies.items():
        _set_cookie(response, name, cfg["value"], **{
            k: v for k, v in cfg.items() if k != "value"
        })
    return response


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    cookies = clear_auth_cookies()
    for name, cfg in cookies.items():
        _set_cookie(response, name, cfg["value"], **{
            k: v for k, v in cfg.items() if k != "value"
        })
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Authorization helpers for protected endpoints
# ---------------------------------------------------------------------------
def _auth_and_csrf_dep(request: Request, _user: str = Depends(require_auth)) -> None:
    """For state-changing routes: require auth, then verify CSRF."""
    require_csrf(request)


def _read_dep(_user: str = Depends(require_auth)) -> str:
    """For read-only routes: require auth only."""
    return _user

@app.get("/api/state", dependencies=[Depends(_read_dep)])
async def get_state():
    with state._lock:
        return {
            "worker_status": state.worker_status,
            "progress": state.progress,
            "logs": state.logs[-200:],
            "last_error": state.last_error,
            "settings": state.settings.data,
            "recipients_count": len(state.recipients),
            "valid_emails": sum(1 for r in state.recipients if is_valid_email(r.get("email", ""))),
        }

# ---------------------------------------------------------------------------
# Routes: Settings
# ---------------------------------------------------------------------------
@app.get("/api/settings", dependencies=[Depends(_read_dep)])
async def get_settings():
    return state.settings.data

@app.post("/api/settings", dependencies=[Depends(_auth_and_csrf_dep)])
async def update_settings(payload: dict):
    with state._lock:
        for k, v in payload.items():
            if k in state.settings.data:
                state.settings.set(k, v)
    return {"status": "saved", "settings": state.settings.data}

# ---------------------------------------------------------------------------
# Routes: Files
# ---------------------------------------------------------------------------
@app.post("/api/files/upload", dependencies=[Depends(_auth_and_csrf_dep)])
async def upload_file(file: UploadFile = File(...)):
    path = _save_upload(file, kind="attachment")
    return {"path": path, "name": Path(path).name}

@app.get("/api/files/sample", dependencies=[Depends(_read_dep)])
async def download_sample():
    out = UPLOADS_DIR / "recipients_sample.xlsx"
    if not out.exists():
        create_sample_recipients(out)
    return FileResponse(out, filename="recipients_sample.xlsx")

# ---------------------------------------------------------------------------
# Routes: Recipients
# ---------------------------------------------------------------------------
@app.post("/api/recipients/import", dependencies=[Depends(_auth_and_csrf_dep)])
async def import_recipients(file: UploadFile = File(...)):
    path = _save_upload(file, kind="recipients")
    try:
        import pandas as pd
        if file.filename and file.filename.lower().endswith(".csv"):
            df = pd.read_csv(path, dtype=str).fillna("")
        else:
            df = pd.read_excel(path, dtype=str).fillna("")
        rows = _recipients_to_dicts(df)
        valid = sum(1 for r in rows if is_valid_email(r.get("email", "")))
        with state._lock:
            state.recipients = rows
        return {"imported": len(rows), "valid_emails": valid, "recipients": rows[:100]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/recipients/parse", dependencies=[Depends(_auth_and_csrf_dep)])
async def parse_pasted_recipients(payload: ParseRecipientsRequest):
    result = parse_recipients(payload.raw_text)
    return {
        "valid": len(result["valid"]),
        "invalid": len(result["invalid"]),
        "duplicates": len(result["duplicates"]),
        "valid_recipients": result["valid"],
        "invalid_entries": result["invalid"],
        "duplicate_emails": result["duplicates"],
    }

@app.post("/api/recipients/merge", dependencies=[Depends(_auth_and_csrf_dep)])
async def merge_recipients(payload: MergeRecipientsRequest):
    with state._lock:
        merged, new_count, dup_count = _merge_recipients(state.recipients, payload.new_recipients)
        state.recipients = merged
        valid = sum(1 for r in merged if is_valid_email(r.get("email", "")))
    return {
        "total": len(merged),
        "valid": valid,
        "new_added": new_count,
        "duplicates_removed": dup_count,
        "recipients": merged[:100],
    }

@app.get("/api/recipients", dependencies=[Depends(_read_dep)])
async def get_recipients():
    with state._lock:
        sent_emails = set(db.sent_emails_set())
        valid = 0
        invalid = 0
        duplicates = 0
        previously_sent = 0
        ready = 0
        seen: set[str] = set()
        for r in state.recipients:
            email = (r.get("email") or "").lower().strip()
            if not is_valid_email(email):
                invalid += 1
                continue
            valid += 1
            if email in seen:
                duplicates += 1
                continue
            seen.add(email)
            if email in sent_emails:
                previously_sent += 1
            else:
                ready += 1
        return {
            "count": len(state.recipients),
            "valid": valid,
            "invalid": invalid,
            "duplicates": duplicates,
            "previously_sent": previously_sent,
            "ready": ready,
            "recipients": state.recipients,
        }

# ---------------------------------------------------------------------------
# Routes: Template
# ---------------------------------------------------------------------------
@app.get("/api/templates", dependencies=[Depends(_read_dep)])
async def list_templates():
    return {"templates": db.list_templates()}

@app.post("/api/templates", dependencies=[Depends(_auth_and_csrf_dep)])
async def create_template(payload: TemplateCreateRequest):
    tid = db.create_template(payload.name, payload.subject, payload.body, payload.signature)
    return {"id": tid, "status": "saved"}

@app.get("/api/templates/{template_id}", dependencies=[Depends(_read_dep)])
async def get_template(template_id: int):
    tpl = db.get_template(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return tpl

@app.put("/api/templates/{template_id}", dependencies=[Depends(_auth_and_csrf_dep)])
async def update_template(template_id: int, payload: TemplateCreateRequest):
    db.update_template(template_id, payload.name, payload.subject, payload.body, payload.signature)
    return {"status": "updated"}

@app.delete("/api/templates/{template_id}", dependencies=[Depends(_auth_and_csrf_dep)])
async def delete_template(template_id: int):
    db.delete_template(template_id)
    return {"status": "deleted"}

@app.post("/api/template/preview", dependencies=[Depends(_auth_and_csrf_dep)])
async def preview_email(payload: PreviewRequest):
    subject = render(payload.subject, payload.context)
    body = render(payload.body, payload.context)
    sig = render(payload.signature, payload.context)
    return {
        "subject": subject,
        "body": body,
        "signature": sig,
        "full_html": text_to_html(body) + sig,
    }

# ---------------------------------------------------------------------------
# Routes: Drafts
# ---------------------------------------------------------------------------
@app.get("/api/drafts", dependencies=[Depends(_read_dep)])
async def list_drafts():
    return {"drafts": db.list_drafts()}

@app.post("/api/drafts", dependencies=[Depends(_auth_and_csrf_dep)])
async def create_draft(payload: DraftCreateRequest):
    did = db.create_draft(
        payload.name, payload.subject, payload.body, payload.signature,
        payload.recipients, payload.attachments, payload.settings,
    )
    return {"id": did, "status": "saved"}

@app.get("/api/drafts/{draft_id}", dependencies=[Depends(_read_dep)])
async def get_draft(draft_id: int):
    d = db.get_draft(draft_id)
    if not d:
        raise HTTPException(status_code=404, detail="Draft not found")
    return d

@app.put("/api/drafts/{draft_id}", dependencies=[Depends(_auth_and_csrf_dep)])
async def update_draft(draft_id: int, payload: DraftCreateRequest):
    db.update_draft(
        draft_id, payload.name, payload.subject, payload.body, payload.signature,
        payload.recipients, payload.attachments, payload.settings,
    )
    return {"status": "updated"}

@app.delete("/api/drafts/{draft_id}", dependencies=[Depends(_auth_and_csrf_dep)])
async def delete_draft(draft_id: int):
    db.delete_draft(draft_id)
    return {"status": "deleted"}

# ---------------------------------------------------------------------------
# Routes: Campaigns
# ---------------------------------------------------------------------------
@app.get("/api/campaigns", dependencies=[Depends(_read_dep)])
async def list_campaigns():
    return {"campaigns": db.list_campaigns()}

@app.post("/api/campaigns", dependencies=[Depends(_auth_and_csrf_dep)])
async def create_campaign(payload: CampaignCreateRequest):
    cid = db.create_campaign(
        payload.subject, payload.body, payload.signature, payload.attachments, payload.settings,
    )
    return {"id": cid, "status": "created"}

@app.get("/api/campaigns/{campaign_id}", dependencies=[Depends(_read_dep)])
async def get_campaign(campaign_id: int):
    c = db.get_campaign(campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return c

@app.delete("/api/campaigns/{campaign_id}", dependencies=[Depends(_auth_and_csrf_dep)])
async def delete_campaign(campaign_id: int):
    db.delete_campaign(campaign_id)
    return {"status": "deleted"}

@app.get("/api/campaigns/{campaign_id}/recipients", dependencies=[Depends(_read_dep)])
async def get_campaign_recipients(campaign_id: int, status: Optional[str] = Query(None)):
    rows = db.get_campaign_recipients(campaign_id, status_filter=status)
    return {"recipients": rows}

@app.post("/api/campaigns/{campaign_id}/recipients", dependencies=[Depends(_auth_and_csrf_dep)])
async def add_campaign_recipients(campaign_id: int, payload: dict):
    recipients = payload.get("recipients", [])
    db.add_campaign_recipients(campaign_id, recipients)
    c = db.get_campaign(campaign_id)
    if c:
        db.update_campaign(campaign_id, total_recipients=len(c.get("settings", {}).get("recipients", [])) + len(recipients))
    return {"status": "added", "count": len(recipients)}

# ---------------------------------------------------------------------------
# Routes: Email Test
# ---------------------------------------------------------------------------
@app.post("/api/email/test", dependencies=[Depends(_auth_and_csrf_dep)])
async def send_test_email(payload: SendTestRequest):
    try:
        s = state.settings
        sender = EmailSender(s.data)
        subject = "[TEST] " + render(payload.subject, payload.context)
        html_body = text_to_html(render(payload.body, payload.context)) + render(payload.signature, payload.context)
        sender.send(payload.to_email, subject, html_body, payload.attachments)
        return {"status": "sent", "backend": sender.backend_name}
    except SendError as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# Routes: Repeat Send
# ---------------------------------------------------------------------------
@app.post("/api/repeat-send/start", dependencies=[Depends(_auth_and_csrf_dep)])
async def start_repeat_send(payload: RepeatSendRequest):
    with state._lock:
        if state.repeat_status == "running":
            raise HTTPException(status_code=400, detail="A repeat send is already in progress")
        if not is_valid_email(payload.to_email):
            raise HTTPException(status_code=400, detail="Invalid recipient email address")
        count = max(1, min(20, int(payload.count or 1)))
        delay = max(1, min(60, float(payload.delay_seconds or 5)))
        state.repeat_status = "running"
        state.repeat_progress = {"current": 0, "sent": 0, "failed": 0, "total": count}
        state.repeat_logs = []

    def _on_progress(current, sent, failed, total):
        with state._lock:
            state.repeat_progress = {"current": current, "sent": sent, "failed": failed, "total": total}

    def _on_log(message):
        state.add_repeat_log(message)

    def _on_done(result):
        with state._lock:
            state.repeat_status = result.get("status", "completed")
            state.repeat_progress = {
                "current": result.get("total", state.repeat_progress["total"]),
                "sent": result.get("sent", 0),
                "failed": result.get("failed", 0),
                "total": result.get("total", state.repeat_progress["total"]),
            }
        state.add_repeat_log(
            f"Done. Sent={result.get('sent',0)} Failed={result.get('failed',0)} Total={result.get('total',0)}"
        )

    # Build attachments list (resume + extra)
    attachments = list(payload.attachments or [])
    resume = state.settings.get("resume_path", "")
    if resume and Path(resume).exists() and resume not in attachments:
        attachments.insert(0, resume)
    extra = state.settings.get("extra_attachments", []) or []
    for p in extra:
        if p and p not in attachments and Path(p).exists():
            attachments.append(p)

    worker = RepeatSendWorker(
        settings=state.settings.data,
        to_email=payload.to_email,
        subject_template=payload.subject,
        body_template=payload.body,
        signature_html=payload.signature,
        count=count,
        delay_seconds=delay,
        attachments=attachments,
        on_progress=_on_progress,
        on_log=_on_log,
        on_done=_on_done,
    )

    with state._lock:
        state.repeat_worker = worker

    worker.start()
    return {"status": "started", "total": count, "delay": delay}


@app.post("/api/repeat-send/stop", dependencies=[Depends(_auth_and_csrf_dep)])
async def stop_repeat_send():
    with state._lock:
        if state.repeat_worker and state.repeat_status == "running":
            state.repeat_worker.stop()
            state.repeat_status = "stopped"
            return {"status": "stopped"}
    raise HTTPException(status_code=400, detail="Nothing to stop")


@app.get("/api/repeat-send/status", dependencies=[Depends(_read_dep)])
async def repeat_send_status():
    with state._lock:
        return {
            "repeat_status": state.repeat_status,
            "progress": state.repeat_progress,
            "logs": state.repeat_logs[-100:],
        }


# ---------------------------------------------------------------------------
# Routes: Send
# ---------------------------------------------------------------------------
@app.post("/api/send/start", dependencies=[Depends(_auth_and_csrf_dep)])
async def start_send(payload: StartSendRequest):
    with state._lock:
        if state.worker_status == "running":
            raise HTTPException(status_code=400, detail="A send is already in progress")
        if not state.recipients:
            raise HTTPException(status_code=400, detail="No recipients loaded")
        state.worker_status = "running"
        state.progress = {"sent": 0, "failed": 0, "skipped": 0, "total": len(state.recipients)}
        state.clear_logs()
        state.last_error = None

    def _on_progress(sent, failed, skipped, total):
        with state._lock:
            state.progress = {"sent": sent, "failed": failed, "skipped": skipped, "total": total}

    def _on_log(message):
        state.add_log(message)

    def _on_done(stats):
        with state._lock:
            state.worker_status = "idle"
            state.progress = {
                "sent": stats.get("sent", 0),
                "failed": stats.get("failed", 0),
                "skipped": stats.get("skipped", 0),
                "total": len(state.recipients),
            }
        state.add_log(f"Done. Sent={stats.get('sent',0)} Failed={stats.get('failed',0)} Skipped={stats.get('skipped',0)}")

    # Build attachments list (resume + extra)
    attachments = list(payload.attachments or [])
    resume = state.settings.get("resume_path", "")
    resume = state.settings.get("resume_path", "")
    if resume and Path(resume).exists():
        attachments.insert(0, resume)
    extra = state.settings.get("extra_attachments", []) or []
    for p in extra:
        if p and p not in attachments and Path(p).exists():
            attachments.append(p)

    worker = SendWorker(
        settings=state.settings.data,
        recipients=state.recipients,
        template_text=payload.body,
        subject_template=payload.subject,
        signature_html=payload.signature,
        attachments=attachments,
        on_progress=_on_progress,
        on_log=_on_log,
        on_done=_on_done,
    )

    with state._lock:
        state.worker = worker

    worker.start()
    return {"status": "started", "total": len(state.recipients)}

@app.post("/api/send/pause", dependencies=[Depends(_auth_and_csrf_dep)])
async def pause_send():
    with state._lock:
        if state.worker and state.worker_status == "running":
            state.worker.pause()
            state.worker_status = "paused"
            return {"status": "paused"}
    raise HTTPException(status_code=400, detail="Nothing to pause")

@app.post("/api/send/resume", dependencies=[Depends(_auth_and_csrf_dep)])
async def resume_send():
    with state._lock:
        if state.worker and state.worker_status == "paused":
            state.worker.resume()
            state.worker_status = "running"
            return {"status": "resumed"}
    raise HTTPException(status_code=400, detail="Nothing to resume")

@app.post("/api/send/stop", dependencies=[Depends(_auth_and_csrf_dep)])
async def stop_send():
    with state._lock:
        if state.worker:
            state.worker.stop()
            state.worker_status = "idle"
            return {"status": "stopped"}
    raise HTTPException(status_code=400, detail="Nothing to stop")

@app.get("/api/send/status", dependencies=[Depends(_read_dep)])
async def send_status():
    with state._lock:
        return {
            "worker_status": state.worker_status,
            "progress": state.progress,
            "logs": state.logs[-100:],
        }

@app.get("/api/send/history", dependencies=[Depends(_read_dep)])
async def send_history():
    records = db.all_records()
    return {"records": records, "stats": db.stats()}

# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------
FRONTEND_DIR = BASE_DIR / "frontend"

@app.get("/login")
async def serve_login():
    return FileResponse(FRONTEND_DIR / "login.html")

@app.get("/")
async def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")

@app.get("/static/{file_path:path}")
async def serve_static(file_path: str):
    p = FRONTEND_DIR / file_path
    if not p.exists():
        raise HTTPException(status_code=404)
    return FileResponse(p)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    # Only enable reload in development.
    reload = APP_ENV != "production"
    uvicorn.run("server:app", host=host, port=port, reload=reload)
