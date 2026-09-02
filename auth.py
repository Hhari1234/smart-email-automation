"""
auth.py
Lightweight single-user authentication for ResumeMailer.

Features:
- Bcrypt password hashing
- Signed, server-side session cookies (itsdangerous)
- CSRF token bound to the session
- In-memory per-IP and per-username rate limiting for login attempts
- Session fixation protection (new session id on login)
- Reasonable session expiration

Configuration is via environment variables (.env file is fine):
    APP_USERNAME       -- the login username
    APP_PASSWORD_HASH  -- bcrypt hash of the password
    APP_SECRET_KEY     -- long random string used to sign session cookies
    APP_ENV            -- "development" or "production"
    APP_SESSION_HOURS  -- optional, default 12
"""
import hmac
import os
import time
import threading
from hashlib import sha256
from typing import Optional

import bcrypt
from fastapi import Request, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def _env(key: str, default: str = "") -> str:
    val = os.environ.get(key)
    return val if val is not None else default


def _is_configured() -> bool:
    return bool(
        _env("APP_USERNAME")
        and _env("APP_PASSWORD_HASH")
        and _env("APP_SECRET_KEY")
    )


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
def hash_password(plaintext: str) -> str:
    """Hash a plaintext password with bcrypt and return a utf-8 string."""
    if not plaintext:
        raise ValueError("password must not be empty")
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    """Constant-time-ish bcrypt verification."""
    if not plaintext or not hashed:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Session cookie signing
# ---------------------------------------------------------------------------
def _secret() -> str:
    secret = _env("APP_SECRET_KEY")
    if not secret:
        # In development, derive a process-local secret so the app still runs.
        # In production this should always be set via env.
        if _env("APP_ENV", "development") == "production":
            raise RuntimeError(
                "APP_SECRET_KEY is not set. Refusing to start in production."
            )
        secret = "dev-only-insecure-secret-change-me"
    return secret


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(), salt="resumemailer-session")


SESSION_COOKIE = "rm_session"
CSRF_COOKIE = "rm_csrf"
SESSION_HEADER = "X-Session-Id"

SESSION_MAX_AGE_SECONDS = int(_env("APP_SESSION_HOURS", "12")) * 3600


def _make_session_payload(username: str) -> str:
    # Random nonce included so every login produces a fresh session id,
    # defeating session fixation.
    nonce = sha256(os.urandom(32)).hexdigest()[:24]
    issued = int(time.time())
    return f"{username}|{nonce}|{issued}"


def create_session_cookie(username: str) -> str:
    payload = _make_session_payload(username)
    return _serializer().dumps(payload)


def read_session_cookie(token: str) -> Optional[str]:
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    parts = data.split("|")
    if len(parts) < 3:
        return None
    return parts[0] or None


# ---------------------------------------------------------------------------
# CSRF protection
# ---------------------------------------------------------------------------
def make_csrf_token(session_token: str) -> str:
    """Derive a stable CSRF token from the session token using HMAC."""
    mac = hmac.new(_secret().encode("utf-8"), session_token.encode("utf-8"), sha256)
    return mac.hexdigest()[:32]


def verify_csrf(session_token: str, csrf_token: str) -> bool:
    if not session_token or not csrf_token:
        return False
    expected = make_csrf_token(session_token)
    return hmac.compare_digest(expected, csrf_token)


# ---------------------------------------------------------------------------
# In-memory rate limiting (login brute-force protection)
# ---------------------------------------------------------------------------
class _RateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._failures_by_ip: dict[str, list[float]] = {}
        self._failures_by_user: dict[str, list[float]] = {}

    def _prune(self, store: dict, window: float):
        cutoff = time.time() - window
        for k in list(store.keys()):
            store[k] = [t for t in store[k] if t >= cutoff]
            if not store[k]:
                store.pop(k, None)

    def record_failure(self, key_ip: str, key_user: str):
        with self._lock:
            now = time.time()
            self._failures_by_ip.setdefault(key_ip, []).append(now)
            self._failures_by_user.setdefault(key_user.lower(), []).append(now)
            self._prune(self._failures_by_ip, 600)
            self._prune(self._failures_by_user, 900)

    def clear(self, key_ip: str, key_user: str):
        with self._lock:
            self._failures_by_ip.pop(key_ip, None)
            self._failures_by_user.pop(key_user.lower(), None)

    def is_limited(self, key_ip: str, key_user: str) -> tuple[bool, str]:
        """Return (limited, reason). 5 failures / 10 min per IP, 8 / 15 min per user."""
        with self._lock:
            self._prune(self._failures_by_ip, 600)
            self._prune(self._failures_by_user, 900)
            ip_count = len(self._failures_by_ip.get(key_ip, []))
            user_count = len(self._failures_by_user.get(key_user.lower(), []))
        if ip_count >= 5:
            return True, "Too many failed login attempts from this IP. Try again in a few minutes."
        if user_count >= 8:
            return True, "Too many failed login attempts for this account. Try again in a few minutes."
        return False, ""


_limiter = _RateLimiter()


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------
def _is_auth_disabled() -> bool:
    """Auth is disabled when no credentials are configured at all.

    This preserves the existing local workflow for users who don't want auth.
    A clear warning is logged at startup in that case.
    """
    return not _is_configured()


def get_session_user(request: Request) -> Optional[str]:
    if _is_auth_disabled():
        return "anonymous"
    token = request.cookies.get(SESSION_COOKIE)
    return read_session_cookie(token)


def require_auth(request: Request) -> str:
    user = get_session_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


def require_csrf(request: Request) -> None:
    if _is_auth_disabled():
        return
    session_token = request.cookies.get(SESSION_COOKIE, "")
    header_token = request.headers.get("X-CSRF-Token", "")
    if not verify_csrf(session_token, header_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token missing or invalid",
        )


def is_auth_disabled() -> bool:
    return _is_auth_disabled()


# ---------------------------------------------------------------------------
# Login / logout helpers
# ---------------------------------------------------------------------------
def attempt_login(username: str, password: str, ip: str) -> tuple[bool, str]:
    """Returns (success, message). Enforces rate limiting."""
    if _is_auth_disabled():
        return True, "auth-disabled"

    expected_user = _env("APP_USERNAME")
    expected_hash = _env("APP_PASSWORD_HASH")

    limited, reason = _limiter.is_limited(ip, username or "")
    if limited:
        return False, reason

    if not username or not password:
        _limiter.record_failure(ip, username or "")
        return False, "Username and password are required"

    if not hmac.compare_digest(username.encode("utf-8"), expected_user.encode("utf-8")):
        _limiter.record_failure(ip, username)
        return False, "Invalid username or password"

    if not verify_password(password, expected_hash):
        _limiter.record_failure(ip, username)
        return False, "Invalid username or password"

    _limiter.clear(ip, username)
    return True, "ok"


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def build_auth_cookies(username: str) -> dict[str, str]:
    """Return cookies to set on a successful login response."""
    session_value = create_session_cookie(username)
    csrf_value = make_csrf_token(session_value)
    secure = _env("APP_ENV", "development") == "production"
    common = {
        "path": "/",
        "httponly": True,
        "samesite": "lax",
        "secure": secure,
    }
    return {
        SESSION_COOKIE: {"value": session_value, **common},
        CSRF_COOKIE: {
            "value": csrf_value,
            "path": "/",
            "httponly": False,  # JS needs to read this for the header
            "samesite": "lax",
            "secure": secure,
        },
    }


def clear_auth_cookies() -> dict[str, str]:
    secure = _env("APP_ENV", "development") == "production"
    common = {
        "path": "/",
        "expires": "Thu, 01 Jan 1970 00:00:00 GMT",
        "samesite": "lax",
        "secure": secure,
    }
    return {
        SESSION_COOKIE: {"value": "", "httponly": True, **common},
        CSRF_COOKIE: {"value": "", "httponly": False, **common},
    }
