"""
auth.py
Multi-user authentication for ResumeMailer.

Features:
- Bcrypt password hashing
- Signed, server-side session cookies (itsdangerous)
- CSRF token bound to the session
- In-memory per-IP and per-username rate limiting for login attempts
- Registration rate limiting
- Session fixation protection (new session id on login)
- Reasonable session expiration
- SQLite-backed user storage with migration path for legacy env-based auth

Configuration is via environment variables (.env file is fine):
    APP_SECRET_KEY     -- long random string used to sign session cookies
    APP_ENV            -- "development" or "production"
    APP_SESSION_HOURS  -- optional, default 12
"""
import hmac
import os
import re
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


def _is_production() -> bool:
    return _env("APP_ENV", "development") == "production"


def _secret() -> str:
    secret = _env("APP_SECRET_KEY")
    if not secret:
        if _is_production():
            raise RuntimeError(
                "APP_SECRET_KEY is not set. Refusing to start in production."
            )
        secret = "dev-only-insecure-secret-change-me"
    return secret


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
# Database integration
# ---------------------------------------------------------------------------
_legacy_migrated = False
_legacy_migration_lock = threading.Lock()


def _get_db():
    from database import Database
    return Database()


def _migrate_legacy_user():
    global _legacy_migrated
    if _legacy_migrated:
        return

    with _legacy_migration_lock:
        if _legacy_migrated:
            return

        db = _get_db()
        if db.user_exists():
            _legacy_migrated = True
            return

        username = _env("APP_USERNAME")
        password_hash = _env("APP_PASSWORD_HASH")

        if username and password_hash:
            db.migrate_legacy_user(username, password_hash)
            _legacy_migrated = True


def _ensure_db_initialized():
    try:
        _migrate_legacy_user()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Session cookie signing
# ---------------------------------------------------------------------------
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(), salt="resumemailer-session")


SESSION_COOKIE = "rm_session"
CSRF_COOKIE = "rm_csrf"
SESSION_HEADER = "X-Session-Id"

SESSION_MAX_AGE_SECONDS = int(_env("APP_SESSION_HOURS", "12")) * 3600


def _make_session_payload(user_id: int, username: str) -> str:
    nonce = sha256(os.urandom(32)).hexdigest()[:24]
    issued = int(time.time())
    return f"{user_id}|{username}|{nonce}|{issued}"


def create_session_cookie(user_id: int, username: str) -> str:
    payload = _make_session_payload(user_id, username)
    return _serializer().dumps(payload)


def read_session_cookie(token: str) -> Optional[tuple[int, str]]:
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    parts = data.split("|")
    if len(parts) < 4:
        return None
    try:
        user_id = int(parts[0])
        username = parts[1]
        return (user_id, username) if username else None
    except (ValueError, IndexError):
        return None


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


# Registration rate limiter: 5 registrations per IP per hour
class _RegistrationRateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._registrations_by_ip: dict[str, list[float]] = {}

    def _prune(self, window: float):
        cutoff = time.time() - window
        for k in list(self._registrations_by_ip.keys()):
            self._registrations_by_ip[k] = [t for t in self._registrations_by_ip[k] if t >= cutoff]
            if not self._registrations_by_ip[k]:
                self._registrations_by_ip.pop(k, None)

    def record_registration(self, key_ip: str):
        with self._lock:
            now = time.time()
            self._registrations_by_ip.setdefault(key_ip, []).append(now)
            self._prune(3600)

    def is_limited(self, key_ip: str) -> tuple[bool, str]:
        with self._lock:
            self._prune(3600)
            count = len(self._registrations_by_ip.get(key_ip, []))
        if count >= 5:
            return True, "Too many account creation attempts from this IP. Try again in an hour."
        return False, ""


_rate_limiter = _RateLimiter()
_registration_limiter = _RegistrationRateLimiter()


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------
def _is_auth_disabled() -> bool:
    return False


def get_session_user(request: Request) -> Optional[tuple[int, str]]:
    token = request.cookies.get(SESSION_COOKIE)
    return read_session_cookie(token)


def require_auth(request: Request) -> tuple[int, str]:
    session = get_session_user(request)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return session


def require_csrf(request: Request) -> None:
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
def attempt_login(username: str, password: str, ip: str, db=None) -> tuple[bool, str, Optional[tuple[int, str]]]:
    """Returns (success, message, session_data). Enforces rate limiting."""
    _ensure_db_initialized()

    limited, reason = _rate_limiter.is_limited(ip, username or "")
    if limited:
        return False, reason, None

    if not username or not password:
        _rate_limiter.record_failure(ip, username or "")
        return False, "Username and password are required", None

    if db is None:
        db = _get_db()
    user = db.get_user_by_username(username)

    if not user:
        _rate_limiter.record_failure(ip, username)
        return False, "Invalid username or password", None

    if not user.get("is_active", 1):
        _rate_limiter.record_failure(ip, username)
        return False, "Invalid username or password", None

    if not verify_password(password, user["password_hash"]):
        _rate_limiter.record_failure(ip, username)
        return False, "Invalid username or password", None

    _rate_limiter.clear(ip, username)
    db.update_last_login(user["id"])
    return True, "ok", (user["id"], user["username"])


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def build_auth_cookies(user_id: int, username: str) -> dict[str, str]:
    """Return cookies to set on a successful login response."""
    session_value = create_session_cookie(user_id, username)
    csrf_value = make_csrf_token(session_value)
    secure = _is_production()
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
            "httponly": False,
            "samesite": "lax",
            "secure": secure,
        },
    }


def clear_auth_cookies() -> dict[str, str]:
    secure = _is_production()
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


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------
USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_-]{3,50}$")


def validate_username(username: str) -> tuple[bool, str]:
    if not username:
        return False, "Please enter a username."
    username = username.strip()
    if len(username) < 3 or len(username) > 50:
        return False, "Username must be 3–50 characters and may contain letters, numbers, _ or -."
    if not USERNAME_REGEX.match(username):
        return False, "Username must be 3–50 characters and may contain letters, numbers, _ or -."
    return True, ""


def validate_password(password: str) -> tuple[bool, str]:
    if not password:
        return False, "Please enter a password."
    if len(password) < 8:
        return False, "Password must be at least 8 characters."
    if len(password) > 128:
        return False, "Password must be at most 128 characters."
    return True, ""


def attempt_register(username: str, password: str, confirm_password: str, ip: str, db=None) -> tuple[bool, str, Optional[tuple[int, str]]]:
    """Returns (success, message, session_data). Enforces registration rate limiting."""
    _ensure_db_initialized()

    limited, reason = _registration_limiter.is_limited(ip)
    if limited:
        return False, reason, None

    valid, msg = validate_username(username)
    if not valid:
        return False, msg, None

    valid, msg = validate_password(password)
    if not valid:
        return False, msg, None

    if password != confirm_password:
        return False, "Passwords do not match.", None

    _registration_limiter.record_registration(ip)

    if db is None:
        db = _get_db()

    existing = db.get_user_by_username(username.strip())
    if existing:
        return False, "That username is already in use.", None

    password_hash = hash_password(password)
    user_id = db.create_user(username.strip(), password_hash)

    return True, "ok", (user_id, username.strip())
