"""
Cloudflare Python Worker for Smart Email Automation.

This module serves the FastAPI application on Cloudflare Workers with:
- D1 database for persistence
- Cloudflare Static Assets for frontend files

Environment:
- CLOUDFLARE_WORKER=1: Running in Cloudflare Workers
- APP_SECRET_KEY: Session signing key (set via wrangler secret)
"""
import json
import os
from datetime import datetime
from typing import Optional

os.environ["CLOUDFLARE_WORKER"] = "1"
os.environ["APP_ENV"] = "production"

from workers import WorkerEntrypoint, Response
import asgi
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from auth import (
    require_auth,
    require_csrf,
    attempt_login,
    attempt_register,
    client_ip,
    build_auth_cookies,
    clear_auth_cookies,
    get_session_user,
)
from database import Database

_db: Optional[Database] = None

def get_db(env) -> Database:
    global _db
    if _db is None:
        d1_binding = env.DB
        _db = Database(d1_binding=d1_binding)
    return _db


def create_app() -> FastAPI:
    app = FastAPI(title="Smart Email Automation API", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )

    class LoginRequest(BaseModel):
        username: str
        password: str

    class RegisterRequest(BaseModel):
        username: str
        password: str
        confirm_password: str

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/health")
    async def api_health():
        return {"status": "ok", "time": datetime.now().isoformat()}

    @app.get("/api/auth/status")
    async def auth_status(request: Request):
        session = get_session_user(request)
        if session:
            return {
                "authenticated": True,
                "username": session[1],
                "user_id": session[0],
                "auth_enabled": True,
            }
        return {
            "authenticated": False,
            "username": None,
            "user_id": None,
            "auth_enabled": True,
        }

    @app.post("/api/auth/login")
    async def login(payload: LoginRequest, request: Request):
        ip = client_ip(request)
        env = request.scope["env"]
        db = get_db(env)
        success, message, session_data = attempt_login(
            payload.username, payload.password, ip, db
        )
        if not success:
            status_code = 429 if "Too many" in message else 401
            raise HTTPException(status_code=status_code, detail=message)

        user_id, username = session_data
        cookies = build_auth_cookies(user_id, username)
        response = JSONResponse({"status": "ok", "username": username})
        for name, cfg in cookies.items():
            response.set_cookie(
                key=name,
                value=cfg["value"],
                path=cfg.get("path", "/"),
                httponly=cfg.get("httponly", True),
                samesite=cfg.get("samesite", "lax"),
                secure=cfg.get("secure", True),
            )
        return response

    @app.post("/api/auth/register")
    async def register(payload: RegisterRequest, request: Request):
        ip = client_ip(request)
        env = request.scope["env"]
        db = get_db(env)
        success, message, session_data = attempt_register(
            payload.username, payload.password, payload.confirm_password, ip, db
        )
        if not success:
            status_code = 429 if "Too many" in message else 400
            raise HTTPException(status_code=status_code, detail=message)

        user_id, username = session_data
        cookies = build_auth_cookies(user_id, username)
        response = JSONResponse({"status": "ok", "username": username})
        for name, cfg in cookies.items():
            response.set_cookie(
                key=name,
                value=cfg["value"],
                path=cfg.get("path", "/"),
                httponly=cfg.get("httponly", True),
                samesite=cfg.get("samesite", "lax"),
                secure=cfg.get("secure", True),
            )
        return response

    @app.post("/api/auth/logout")
    async def logout(request: Request):
        cookies = clear_auth_cookies()
        response = JSONResponse({"status": "ok"})
        for name, cfg in cookies.items():
            response.set_cookie(
                key=name,
                value=cfg["value"],
                path=cfg.get("path", "/"),
                expires=cfg.get("expires", "Thu, 01 Jan 1970 00:00:00 GMT"),
                httponly=cfg.get("httponly", True),
                samesite=cfg.get("samesite", "lax"),
                secure=cfg.get("secure", True),
            )
        return response

    @app.get("/api/auth/me")
    async def get_current_user(request: Request):
        session = get_session_user(request)
        if not session:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": session[0], "username": session[1]}

    @app.get("/api/templates")
    async def list_templates(request: Request):
        session = require_auth(request)
        env = request.scope["env"]
        db = get_db(env)
        return {"templates": db.list_templates(session[0])}

    @app.post("/api/templates")
    async def create_template(request: Request):
        require_csrf(request)
        session = require_auth(request)
        env = request.scope["env"]
        db = get_db(env)
        data = await request.json()
        tid = db.create_template(
            data.get("name", ""),
            data.get("subject", ""),
            data.get("body", ""),
            data.get("signature", ""),
            session[0]
        )
        return {"id": tid, "status": "saved"}

    @app.get("/api/templates/{template_id}")
    async def get_template(template_id: int, request: Request):
        session = require_auth(request)
        env = request.scope["env"]
        db = get_db(env)
        tpl = db.get_template(template_id, session[0])
        if not tpl:
            raise HTTPException(status_code=404, detail="Template not found")
        return tpl

    @app.put("/api/templates/{template_id}")
    async def update_template(template_id: int, request: Request):
        require_csrf(request)
        session = require_auth(request)
        env = request.scope["env"]
        db = get_db(env)
        data = await request.json()
        if not db.update_template(template_id, data.get("name", ""), data.get("subject", ""),
                                   data.get("body", ""), data.get("signature", ""), session[0]):
            raise HTTPException(status_code=404, detail="Template not found")
        return {"status": "updated"}

    @app.delete("/api/templates/{template_id}")
    async def delete_template(template_id: int, request: Request):
        require_csrf(request)
        session = require_auth(request)
        env = request.scope["env"]
        db = get_db(env)
        if not db.delete_template(template_id, session[0]):
            raise HTTPException(status_code=404, detail="Template not found")
        return {"status": "deleted"}

    @app.get("/api/drafts")
    async def list_drafts(request: Request):
        session = require_auth(request)
        env = request.scope["env"]
        db = get_db(env)
        return {"drafts": db.list_drafts(session[0])}

    @app.post("/api/drafts")
    async def create_draft(request: Request):
        require_csrf(request)
        session = require_auth(request)
        env = request.scope["env"]
        db = get_db(env)
        data = await request.json()
        did = db.create_draft(
            data.get("name", ""),
            data.get("subject", ""),
            data.get("body", ""),
            data.get("signature", ""),
            data.get("recipients", []),
            data.get("attachments", []),
            data.get("settings", {}),
            session[0]
        )
        return {"id": did, "status": "saved"}

    @app.get("/api/drafts/{draft_id}")
    async def get_draft(draft_id: int, request: Request):
        session = require_auth(request)
        env = request.scope["env"]
        db = get_db(env)
        d = db.get_draft(draft_id, session[0])
        if not d:
            raise HTTPException(status_code=404, detail="Draft not found")
        return d

    @app.put("/api/drafts/{draft_id}")
    async def update_draft(draft_id: int, request: Request):
        require_csrf(request)
        session = require_auth(request)
        env = request.scope["env"]
        db = get_db(env)
        data = await request.json()
        if not db.update_draft(
            draft_id, data.get("name", ""), data.get("subject", ""),
            data.get("body", ""), data.get("signature", ""),
            data.get("recipients", []), data.get("attachments", []),
            data.get("settings", {}), session[0]
        ):
            raise HTTPException(status_code=404, detail="Draft not found")
        return {"status": "updated"}

    @app.delete("/api/drafts/{draft_id}")
    async def delete_draft(draft_id: int, request: Request):
        require_csrf(request)
        session = require_auth(request)
        env = request.scope["env"]
        db = get_db(env)
        if not db.delete_draft(draft_id, session[0]):
            raise HTTPException(status_code=404, detail="Draft not found")
        return {"status": "deleted"}

    @app.get("/api/campaigns")
    async def list_campaigns(request: Request):
        session = require_auth(request)
        env = request.scope["env"]
        db = get_db(env)
        return {"campaigns": db.list_campaigns(session[0])}

    @app.post("/api/campaigns")
    async def create_campaign(request: Request):
        require_csrf(request)
        session = require_auth(request)
        env = request.scope["env"]
        db = get_db(env)
        data = await request.json()
        cid = db.create_campaign(
            data.get("subject", ""),
            data.get("body", ""),
            data.get("signature", ""),
            data.get("attachments", []),
            data.get("settings", {}),
            session[0]
        )
        return {"id": cid, "status": "created"}

    @app.get("/api/campaigns/{campaign_id}")
    async def get_campaign(campaign_id: int, request: Request):
        session = require_auth(request)
        env = request.scope["env"]
        db = get_db(env)
        c = db.get_campaign(campaign_id, session[0])
        if not c:
            raise HTTPException(status_code=404, detail="Campaign not found")
        return c

    @app.delete("/api/campaigns/{campaign_id}")
    async def delete_campaign(campaign_id: int, request: Request):
        require_csrf(request)
        session = require_auth(request)
        env = request.scope["env"]
        db = get_db(env)
        if not db.delete_campaign(campaign_id, session[0]):
            raise HTTPException(status_code=404, detail="Campaign not found")
        return {"status": "deleted"}

    @app.get("/api/campaigns/{campaign_id}/recipients")
    async def get_campaign_recipients(campaign_id: int, request: Request, status: str = None):
        session = require_auth(request)
        env = request.scope["env"]
        db = get_db(env)
        c = db.get_campaign(campaign_id, session[0])
        if not c:
            raise HTTPException(status_code=404, detail="Campaign not found")
        rows = db.get_campaign_recipients(campaign_id, status_filter=status)
        return {"recipients": rows}

    @app.post("/api/campaigns/{campaign_id}/recipients")
    async def add_campaign_recipients(campaign_id: int, request: Request):
        require_csrf(request)
        session = require_auth(request)
        env = request.scope["env"]
        db = get_db(env)
        c = db.get_campaign(campaign_id, session[0])
        if not c:
            raise HTTPException(status_code=404, detail="Campaign not found")
        data = await request.json()
        recipients = data.get("recipients", [])
        db.add_campaign_recipients(campaign_id, recipients)
        return {"status": "added", "count": len(recipients)}

    @app.get("/api/state")
    async def get_state(request: Request):
        require_auth(request)
        return {
            "worker_status": "idle",
            "progress": {"sent": 0, "failed": 0, "skipped": 0, "total": 0},
            "logs": [],
            "last_error": None,
            "settings": {},
            "recipients_count": 0,
            "valid_emails": 0,
        }

    @app.get("/{path:path}")
    async def serve_frontend(path: str, request: Request):
        env = request.scope["env"]
        if path == "" or path == "/":
            path = "index.html"
        elif path == "login":
            path = "login.html"
        asset_url = f"https://assets.local/{path}"
        resp = await env.ASSETS.fetch(asset_url)
        body = await resp.bytes()
        headers = dict(resp.headers)
        return Response(
            content=body,
            status_code=resp.status,
            headers=headers
        )

    return app


app = create_app()


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        return await asgi.fetch(app, request, self.env)
