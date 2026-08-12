"""
server.py
FastAPI backend for ResumeMailer web application.
Wraps existing backend modules and exposes REST APIs.
"""
import os
import sys
import uuid
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(title="ResumeMailer API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
def _runtime_dir(name: str) -> Path:
    base = Path(os.environ.get("TMPDIR", "/tmp"))
    target = base / name
    target.mkdir(parents=True, exist_ok=True)
    return target

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

    def add_log(self, message: str):
        with self._lock:
            self.logs.append(message)
            if len(self.logs) > 2000:
                self.logs = self.logs[-1000:]

    def clear_logs(self):
        with self._lock:
            self.logs = []

state = AppState()
db = Database()

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _save_upload(upload: UploadFile) -> str:
    ext = Path(upload.filename or "file").suffix
    name = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOADS_DIR / name
    with open(dest, "wb") as f:
        f.write(upload.file.read())
    return str(dest)

def _recipients_to_dicts(df) -> list[dict]:
    from excel_io import _normalize_columns
    df = _normalize_columns(df)
    return df[["hr_name", "company", "email", "job_role", "location"]].to_dict("records")

# ---------------------------------------------------------------------------
# Routes: State & Health
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

@app.get("/api/state")
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
@app.get("/api/settings")
async def get_settings():
    return state.settings.data

@app.post("/api/settings")
async def update_settings(payload: dict):
    with state._lock:
        for k, v in payload.items():
            if k in state.settings.data:
                state.settings.set(k, v)
    return {"status": "saved", "settings": state.settings.data}

# ---------------------------------------------------------------------------
# Routes: Files
# ---------------------------------------------------------------------------
@app.post("/api/files/upload")
async def upload_file(file: UploadFile = File(...)):
    path = _save_upload(file)
    return {"path": path, "name": Path(path).name}

@app.get("/api/files/sample")
async def download_sample():
    out = UPLOADS_DIR / "recipients_sample.xlsx"
    if not out.exists():
        create_sample_recipients(out)
    return FileResponse(out, filename="recipients_sample.xlsx")

# ---------------------------------------------------------------------------
# Routes: Recipients
# ---------------------------------------------------------------------------
@app.post("/api/recipients/import")
async def import_recipients(file: UploadFile = File(...)):
    path = _save_upload(file)
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
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/recipients")
async def get_recipients():
    with state._lock:
        return {
            "count": len(state.recipients),
            "valid": sum(1 for r in state.recipients if is_valid_email(r.get("email", ""))),
            "recipients": state.recipients,
        }

# ---------------------------------------------------------------------------
# Routes: Template
# ---------------------------------------------------------------------------
@app.post("/api/template/preview")
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

@app.post("/api/email/test")
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
# Routes: Send
# ---------------------------------------------------------------------------
@app.post("/api/send/start")
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

@app.post("/api/send/pause")
async def pause_send():
    with state._lock:
        if state.worker and state.worker_status == "running":
            state.worker.pause()
            state.worker_status = "paused"
            return {"status": "paused"}
    raise HTTPException(status_code=400, detail="Nothing to pause")

@app.post("/api/send/resume")
async def resume_send():
    with state._lock:
        if state.worker and state.worker_status == "paused":
            state.worker.resume()
            state.worker_status = "running"
            return {"status": "resumed"}
    raise HTTPException(status_code=400, detail="Nothing to resume")

@app.post("/api/send/stop")
async def stop_send():
    with state._lock:
        if state.worker:
            state.worker.stop()
            state.worker_status = "idle"
            return {"status": "stopped"}
    raise HTTPException(status_code=400, detail="Nothing to stop")

@app.get("/api/send/status")
async def send_status():
    with state._lock:
        return {
            "worker_status": state.worker_status,
            "progress": state.progress,
            "logs": state.logs[-100:],
        }

@app.get("/api/send/history")
async def send_history():
    records = db.all_records()
    return {"records": records, "stats": db.stats()}

# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------
FRONTEND_DIR = BASE_DIR / "frontend"

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
    uvicorn.run(app, host="127.0.0.1", port=8000)
