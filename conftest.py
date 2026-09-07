"""
conftest.py
Pytest configuration and shared fixtures for ResumeMailer tests.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

# Set test environment BEFORE any imports
os.environ["APP_ENV"] = "test"
os.environ["APP_SECRET_KEY"] = "test-secret-key-for-testing-only"
os.environ["CLOUDFLARE_WORKER"] = "0"

# Add project root to path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import pytest

# Import after environment is set
import server
import database as db_module
import auth

# Reset auth module state
auth._legacy_migrated = False


@pytest.fixture(scope="function")
def temp_db():
    """Create a temporary database for each test."""
    with tempfile.NamedTemporaryFile(suffix=f".db_{int(time.time() * 1000000)}", delete=False) as f:
        db_path = Path(f.name)

    # Create database with this path
    db = db_module.Database(db_path=db_path)

    yield db

    # Cleanup
    try:
        db.close()
        db_path.unlink()
    except:
        pass


@pytest.fixture(scope="function")
def client(temp_db):
    """Create a test client with temporary database."""
    # Reset auth state for this test
    auth._legacy_migrated = True

    # Use the temp_db as the server's db
    original_db = getattr(server, 'db', None)
    server.db = temp_db

    from fastapi.testclient import TestClient

    with TestClient(server.app) as c:
        yield c

    server.db = original_db


@pytest.fixture(scope="function")
def auth_cookies(client):
    """Register and login a user, return auth cookies."""
    username = f"testuser_{int(time.time() * 1000000)}"
    password = "TestPassword123!"
    confirm = password

    # Register
    resp = client.post("/api/auth/register", json={
        "username": username,
        "password": password,
        "confirm_password": confirm,
    })
    assert resp.status_code == 200, f"Registration failed: {resp.json()}"

    # Get session cookie
    cookies = resp.cookies
    return {
        "rm_session": cookies.get("rm_session", ""),
        "rm_csrf": cookies.get("rm_csrf", ""),
    }, username


@pytest.fixture(scope="function")
def two_users(client):
    """Create two separate users and return their auth cookies."""
    # Create first user
    user1_name = f"user1_{int(time.time() * 1000000)}"
    resp1 = client.post("/api/auth/register", json={
        "username": user1_name,
        "password": "Password123!",
        "confirm_password": "Password123!",
    })
    assert resp1.status_code == 200
    cookies1 = resp1.cookies

    # Create second user
    user2_name = f"user2_{int(time.time() * 1000000)}"
    resp2 = client.post("/api/auth/register", json={
        "username": user2_name,
        "password": "Password456!",
        "confirm_password": "Password456!",
    })
    assert resp2.status_code == 200
    cookies2 = resp2.cookies

    return {
        "user1": {"cookies": cookies1, "username": user1_name},
        "user2": {"cookies": cookies2, "username": user2_name},
    }


@pytest.fixture(scope="function", autouse=True)
def reset_rate_limiter():
    """Reset rate limiters before each test to avoid rate limit issues."""
    auth._rate_limiter._failures_by_ip.clear()
    auth._rate_limiter._failures_by_user.clear()
    auth._registration_limiter._registrations_by_ip.clear()
    yield
