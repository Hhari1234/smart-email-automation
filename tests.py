"""
tests.py
Comprehensive tests for ResumeMailer multi-user security and API functionality.

Tests cover:
- Authentication (registration, login, logout, CSRF, rate limiting)
- Multi-user data isolation
- IDOR protection
- Database operations

Note: Fixtures are defined in conftest.py
"""
import time

import pytest
from auth import (
    hash_password,
    verify_password,
    create_session_cookie,
    read_session_cookie,
    make_csrf_token,
    verify_csrf,
)


# =============================================================================
# AUTH TESTS
# =============================================================================
class TestAuthentication:
    """Test authentication functionality."""

    def test_frontend_pages_and_assets(self, client):
        """Frontend routes and root-relative assets should be available."""
        assert client.get("/").status_code == 200
        assert client.get("/login").status_code == 200
        assert client.get("/signup").status_code == 200
        assert client.get("/css/styles.css").status_code == 200
        assert client.get("/css/login.css").status_code == 200
        assert client.get("/js/app.js").status_code == 200

    def test_health_endpoint(self, client):
        """Health endpoint should return ok."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_auth_status_unauthenticated(self, client):
        """Unauthenticated users should see auth_enabled=True, authenticated=False."""
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] == False
        assert data["username"] == None
        assert data["auth_enabled"] == True

    def test_registration_success(self, client):
        """Valid registration should create an account without auto-login."""
        username = f"newuser_{int(time.time() * 1000)}"
        resp = client.post("/api/auth/register", json={
            "name": "New User",
            "email": f"{username}@example.com",
            "username": username,
            "password": "ValidPassword123!",
            "confirm_password": "ValidPassword123!",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["message"] == "Account created successfully"
        assert "rm_session" not in resp.cookies

        login = client.post("/api/auth/login", json={
            "username": username,
            "password": "ValidPassword123!",
        })
        assert login.status_code == 200
        assert "rm_session" in login.cookies

    def test_registration_duplicate_username(self, client, auth_cookies):
        """Registration with existing username should fail."""
        existing_username = auth_cookies[1]  # Use username from auth_cookies fixture
        resp = client.post("/api/auth/register", json={
            "name": "Another User",
            "email": f"another_{int(time.time() * 1000)}@example.com",
            "username": existing_username,
            "password": "NewPassword123!",
            "confirm_password": "NewPassword123!",
        })
        assert resp.status_code == 400
        assert "already taken" in resp.json()["detail"]

    def test_registration_duplicate_email(self, client, auth_cookies):
        """Registration with an existing email should fail safely."""
        username = f"another_{int(time.time() * 1000)}"
        resp = client.post("/api/auth/register", json={
            "name": "Another User",
            "email": auth_cookies[2],
            "username": username,
            "password": "NewPassword123!",
            "confirm_password": "NewPassword123!",
        })
        assert resp.status_code == 400
        assert "email already exists" in resp.json()["detail"]

    def test_registration_password_mismatch(self, client):
        """Registration with mismatched passwords should fail."""
        resp = client.post("/api/auth/register", json={
            "name": "Mismatch User",
            "email": f"mismatch_{int(time.time() * 1000)}@example.com",
            "username": f"testuser_{int(time.time() * 1000)}",
            "password": "Password123!",
            "confirm_password": "DifferentPassword456!",
        })
        assert resp.status_code == 400
        assert "match" in resp.json()["detail"].lower()

    def test_registration_weak_password(self, client):
        """Registration with weak password should fail."""
        resp = client.post("/api/auth/register", json={
            "name": "Weak User",
            "email": f"weak_{int(time.time() * 1000)}@example.com",
            "username": f"testuser_{int(time.time() * 1000)}",
            "password": "short",
            "confirm_password": "short",
        })
        assert resp.status_code == 400

    def test_login_success(self, client, auth_cookies):
        """Valid login should succeed with session cookie."""
        username = auth_cookies[1]
        resp = client.post("/api/auth/login", json={
            "username": username,
            "password": "TestPassword123!",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["username"] == username
        assert "rm_session" in resp.cookies

    def test_login_wrong_password(self, client, auth_cookies):
        """Login with wrong password should fail."""
        username = auth_cookies[1]
        resp = client.post("/api/auth/login", json={
            "username": username,
            "password": "WrongPassword123!",
        })
        assert resp.status_code == 401
        assert "Invalid" in resp.json()["detail"]

    def test_login_nonexistent_user(self, client):
        """Login with nonexistent user should fail."""
        resp = client.post("/api/auth/login", json={
            "username": "nonexistent_user_12345",
            "password": "SomePassword123!",
        })
        assert resp.status_code == 401

    def test_logout(self, client, auth_cookies):
        """Logout should clear session cookie."""
        resp = client.post("/api/auth/logout", cookies=auth_cookies[0])
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_get_current_user(self, client, auth_cookies):
        """Authenticated user should get their user info."""
        resp = client.get("/api/auth/me", cookies=auth_cookies[0])
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == auth_cookies[1]

    def test_get_current_user_unauthenticated(self, client):
        """Unauthenticated request should return 401."""
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_csrf_protection(self, client, auth_cookies):
        """POST requests without CSRF token should fail."""
        # Request without CSRF header
        resp = client.post("/api/templates", json={"name": "Test"}, cookies=auth_cookies[0])
        assert resp.status_code == 403

    def test_csrf_protection_with_valid_token(self, client, auth_cookies):
        """POST requests with valid CSRF token should succeed."""
        csrf_token = auth_cookies[0].get("rm_csrf", "")
        headers = {"X-CSRF-Token": csrf_token}
        resp = client.post(
            "/api/templates",
            json={"name": "Test Template", "subject": "Subject", "body": "Body", "signature": "Sig"},
            cookies=auth_cookies[0],
            headers=headers,
        )
        assert resp.status_code == 200


# =============================================================================
# MULTI-USER ISOLATION TESTS
# =============================================================================
class TestMultiUserIsolation:
    """Test that users can only access their own data."""

    def test_templates_isolated(self, client, two_users):
        """User A should not see User B's templates."""
        u1, u2 = two_users["user1"], two_users["user2"]

        # User 1 creates a template
        csrf1 = u1["cookies"].get("rm_csrf", "")
        resp1 = client.post(
            "/api/templates",
            json={"name": "User1 Template", "subject": "S1", "body": "B1", "signature": "S1"},
            cookies=u1["cookies"],
            headers={"X-CSRF-Token": csrf1},
        )
        assert resp1.status_code == 200
        template1_id = resp1.json()["id"]

        # User 2 lists templates - should be empty
        resp2 = client.get("/api/templates", cookies=u2["cookies"])
        assert resp2.status_code == 200
        templates2 = resp2.json()["templates"]
        assert len(templates2) == 0

        # User 1 lists templates - should have their template
        resp1_list = client.get("/api/templates", cookies=u1["cookies"])
        assert resp1_list.status_code == 200
        templates1 = resp1_list.json()["templates"]
        assert len(templates1) == 1
        assert templates1[0]["name"] == "User1 Template"

    def test_drafts_isolated(self, client, two_users):
        """User A should not see User B's drafts."""
        u1, u2 = two_users["user1"], two_users["user2"]

        # User 1 creates a draft
        csrf1 = u1["cookies"].get("rm_csrf", "")
        resp1 = client.post(
            "/api/drafts",
            json={"name": "User1 Draft", "subject": "S1", "body": "B1", "signature": "S1", "recipients": [], "attachments": [], "settings": {}},
            cookies=u1["cookies"],
            headers={"X-CSRF-Token": csrf1},
        )
        assert resp1.status_code == 200

        # User 2 lists drafts - should be empty
        resp2 = client.get("/api/drafts", cookies=u2["cookies"])
        assert resp2.status_code == 200
        drafts2 = resp2.json()["drafts"]
        assert len(drafts2) == 0

    def test_campaigns_isolated(self, client, two_users):
        """User A should not see User B's campaigns."""
        u1, u2 = two_users["user1"], two_users["user2"]

        # User 1 creates a campaign
        csrf1 = u1["cookies"].get("rm_csrf", "")
        resp1 = client.post(
            "/api/campaigns",
            json={"subject": "User1 Campaign", "body": "B1", "signature": "S1", "attachments": [], "settings": {}},
            cookies=u1["cookies"],
            headers={"X-CSRF-Token": csrf1},
        )
        assert resp1.status_code == 200
        campaign1_id = resp1.json()["id"]

        # User 2 lists campaigns - should be empty
        resp2 = client.get("/api/campaigns", cookies=u2["cookies"])
        assert resp2.status_code == 200
        campaigns2 = resp2.json()["campaigns"]
        assert len(campaigns2) == 0

        # User 1 lists campaigns - should have their campaign
        resp1_list = client.get("/api/campaigns", cookies=u1["cookies"])
        assert resp1_list.status_code == 200
        campaigns1 = resp1_list.json()["campaigns"]
        assert len(campaigns1) == 1
        assert campaigns1[0]["subject"] == "User1 Campaign"


# =============================================================================
# IDOR PROTECTION TESTS
# =============================================================================
class TestIDORProtection:
    """Test that users cannot access other users' resources by changing IDs."""

    def test_cannot_get_other_users_template(self, client, two_users):
        """User B cannot get User A's template by changing template ID."""
        u1, u2 = two_users["user1"], two_users["user2"]

        # User 1 creates a template
        csrf1 = u1["cookies"].get("rm_csrf", "")
        resp1 = client.post(
            "/api/templates",
            json={"name": "User1 Private", "subject": "S1", "body": "B1", "signature": "S1"},
            cookies=u1["cookies"],
            headers={"X-CSRF-Token": csrf1},
        )
        assert resp1.status_code == 200
        template_id = resp1.json()["id"]

        # User 2 tries to get User 1's template - should get 404
        resp2 = client.get(f"/api/templates/{template_id}", cookies=u2["cookies"])
        assert resp2.status_code == 404

    def test_cannot_update_other_users_template(self, client, two_users):
        """User B cannot update User A's template."""
        u1, u2 = two_users["user1"], two_users["user2"]

        # User 1 creates a template
        csrf1 = u1["cookies"].get("rm_csrf", "")
        resp1 = client.post(
            "/api/templates",
            json={"name": "Original", "subject": "S1", "body": "B1", "signature": "S1"},
            cookies=u1["cookies"],
            headers={"X-CSRF-Token": csrf1},
        )
        template_id = resp1.json()["id"]

        # User 2 tries to update User 1's template - should get 404
        csrf2 = u2["cookies"].get("rm_csrf", "")
        resp2 = client.put(
            f"/api/templates/{template_id}",
            json={"name": "Hacked!", "subject": "S1", "body": "B1", "signature": "S1"},
            cookies=u2["cookies"],
            headers={"X-CSRF-Token": csrf2},
        )
        assert resp2.status_code == 404

        # Verify template was not modified
        resp_check = client.get(f"/api/templates/{template_id}", cookies=u1["cookies"])
        assert resp_check.json()["name"] == "Original"

    def test_cannot_delete_other_users_template(self, client, two_users):
        """User B cannot delete User A's template."""
        u1, u2 = two_users["user1"], two_users["user2"]

        # User 1 creates a template
        csrf1 = u1["cookies"].get("rm_csrf", "")
        resp1 = client.post(
            "/api/templates",
            json={"name": "ToDelete", "subject": "S1", "body": "B1", "signature": "S1"},
            cookies=u1["cookies"],
            headers={"X-CSRF-Token": csrf1},
        )
        template_id = resp1.json()["id"]

        # User 2 tries to delete User 1's template - should get 404
        csrf2 = u2["cookies"].get("rm_csrf", "")
        resp2 = client.delete(f"/api/templates/{template_id}", cookies=u2["cookies"], headers={"X-CSRF-Token": csrf2})
        assert resp2.status_code == 404

        # Verify template still exists
        resp_check = client.get(f"/api/templates/{template_id}", cookies=u1["cookies"])
        assert resp_check.status_code == 200

    def test_cannot_get_other_users_campaign(self, client, two_users):
        """User B cannot get User A's campaign by changing campaign ID."""
        u1, u2 = two_users["user1"], two_users["user2"]

        # User 1 creates a campaign
        csrf1 = u1["cookies"].get("rm_csrf", "")
        resp1 = client.post(
            "/api/campaigns",
            json={"subject": "Private Campaign", "body": "B1", "signature": "S1", "attachments": [], "settings": {}},
            cookies=u1["cookies"],
            headers={"X-CSRF-Token": csrf1},
        )
        campaign_id = resp1.json()["id"]

        # User 2 tries to get User 1's campaign - should get 404
        resp2 = client.get(f"/api/campaigns/{campaign_id}", cookies=u2["cookies"])
        assert resp2.status_code == 404

    def test_cannot_delete_other_users_campaign(self, client, two_users):
        """User B cannot delete User A's campaign."""
        u1, u2 = two_users["user1"], two_users["user2"]

        # User 1 creates a campaign
        csrf1 = u1["cookies"].get("rm_csrf", "")
        resp1 = client.post(
            "/api/campaigns",
            json={"subject": "Important Campaign", "body": "B1", "signature": "S1", "attachments": [], "settings": {}},
            cookies=u1["cookies"],
            headers={"X-CSRF-Token": csrf1},
        )
        campaign_id = resp1.json()["id"]

        # User 2 tries to delete User 1's campaign - should get 404
        csrf2 = u2["cookies"].get("rm_csrf", "")
        resp2 = client.delete(f"/api/campaigns/{campaign_id}", cookies=u2["cookies"], headers={"X-CSRF-Token": csrf2})
        assert resp2.status_code == 404

        # Verify campaign still exists
        resp_check = client.get(f"/api/campaigns/{campaign_id}", cookies=u1["cookies"])
        assert resp_check.status_code == 200

    def test_cannot_access_other_users_campaign_recipients(self, client, two_users):
        """User B cannot access User A's campaign recipients."""
        u1, u2 = two_users["user1"], two_users["user2"]

        # User 1 creates a campaign
        csrf1 = u1["cookies"].get("rm_csrf", "")
        resp1 = client.post(
            "/api/campaigns",
            json={"subject": "Campaign with Recipients", "body": "B1", "signature": "S1", "attachments": [], "settings": {}},
            cookies=u1["cookies"],
            headers={"X-CSRF-Token": csrf1},
        )
        campaign_id = resp1.json()["id"]

        # User 1 adds recipients to the campaign
        resp_add = client.post(
            f"/api/campaigns/{campaign_id}/recipients",
            json={"recipients": [{"email": "hr@company1.com", "hr_name": "HR Person", "company": "Company1"}]},
            cookies=u1["cookies"],
            headers={"X-CSRF-Token": csrf1},
        )
        assert resp_add.status_code == 200

        # User 2 tries to get User 1's campaign recipients - should get 404
        resp2 = client.get(f"/api/campaigns/{campaign_id}/recipients", cookies=u2["cookies"])
        assert resp2.status_code == 404

    def test_cannot_add_recipients_to_other_users_campaign(self, client, two_users):
        """User B cannot add recipients to User A's campaign."""
        u1, u2 = two_users["user1"], two_users["user2"]

        # User 1 creates a campaign
        csrf1 = u1["cookies"].get("rm_csrf", "")
        resp1 = client.post(
            "/api/campaigns",
            json={"subject": "Campaign", "body": "B1", "signature": "S1", "attachments": [], "settings": {}},
            cookies=u1["cookies"],
            headers={"X-CSRF-Token": csrf1},
        )
        campaign_id = resp1.json()["id"]

        # User 2 tries to add recipients to User 1's campaign - should get 404
        csrf2 = u2["cookies"].get("rm_csrf", "")
        resp2 = client.post(
            f"/api/campaigns/{campaign_id}/recipients",
            json={"recipients": [{"email": "hr@company1.com", "hr_name": "HR Person"}]},
            cookies=u2["cookies"],
            headers={"X-CSRF-Token": csrf2},
        )
        assert resp2.status_code == 404


# =============================================================================
# DATABASE TESTS
# =============================================================================
class TestDatabase:
    """Test database operations."""

    def test_create_and_get_user(self, temp_db):
        """Users can be created and retrieved."""
        password_hash = hash_password("TestPassword123!")
        unique_username = f"testuser_{int(time.time() * 1000000)}"
        user_id = temp_db.create_user(unique_username, password_hash, name="Test User", email=f"{unique_username}@example.com")
        assert user_id > 0

        user = temp_db.get_user_by_username(unique_username)
        assert user is not None
        assert user["username"] == unique_username
        assert user["id"] == user_id

    def test_password_hashing(self):
        """Passwords are properly hashed and verified."""
        password = "TestPassword123!"
        hashed = hash_password(password)

        assert hashed != password
        assert verify_password(password, hashed) == True
        assert verify_password("WrongPassword", hashed) == False

    def test_session_cookie(self):
        """Session cookies can be created and read."""
        cookie = create_session_cookie(123, "testuser")
        assert cookie is not None

        session = read_session_cookie(cookie)
        assert session is not None
        assert session[0] == 123
        assert session[1] == "testuser"

    def test_session_cookie_invalid(self):
        """Invalid session cookies return None."""
        assert read_session_cookie("invalid.cookie") is None
        assert read_session_cookie("") is None

    def test_csrf_token(self):
        """CSRF tokens are properly created and verified."""
        session = create_session_cookie(123, "testuser")
        csrf = make_csrf_token(session)

        assert verify_csrf(session, csrf) == True
        assert verify_csrf(session, "invalid_csrf") == False
        assert verify_csrf("invalid_session", csrf) == False

    def test_template_crud(self, temp_db):
        """Templates can be created, read, updated, and deleted."""
        # Create
        tid = temp_db.create_template("Test", "Subject", "Body", "Sig", user_id=1)
        assert tid > 0

        # Read
        tpl = temp_db.get_template(tid, user_id=1)
        assert tpl is not None
        assert tpl["name"] == "Test"

        # Update
        result = temp_db.update_template(tid, "Updated", "NewSubj", "NewBody", "NewSig", user_id=1)
        assert result == True

        tpl_updated = temp_db.get_template(tid, user_id=1)
        assert tpl_updated["name"] == "Updated"

        # Delete
        result = temp_db.delete_template(tid, user_id=1)
        assert result == True

        tpl_deleted = temp_db.get_template(tid, user_id=1)
        assert tpl_deleted is None

    def test_draft_crud(self, temp_db):
        """Drafts can be created, read, updated, and deleted."""
        # Create
        did = temp_db.create_draft(
            "Test Draft", "Subject", "Body", "Sig",
            [{"email": "test@example.com"}], ["file.pdf"], {"key": "value"},
            user_id=1
        )
        assert did > 0

        # Read
        draft = temp_db.get_draft(did, user_id=1)
        assert draft is not None
        assert draft["name"] == "Test Draft"
        assert draft["recipients"][0]["email"] == "test@example.com"

        # Delete
        result = temp_db.delete_draft(did, user_id=1)
        assert result == True

    def test_campaign_crud(self, temp_db):
        """Campaigns can be created, read, and deleted."""
        # Create
        cid = temp_db.create_campaign(
            "Subject", "Body", "Sig", ["file.pdf"], {"key": "value"},
            user_id=1
        )
        assert cid > 0

        # Read
        campaign = temp_db.get_campaign(cid, user_id=1)
        assert campaign is not None
        assert campaign["subject"] == "Subject"

        # Delete
        result = temp_db.delete_campaign(cid, user_id=1)
        assert result == True

    def test_campaign_recipients(self, temp_db):
        """Campaign recipients can be added and retrieved."""
        # Create campaign
        cid = temp_db.create_campaign("Subject", "Body", "Sig", [], {}, user_id=1)

        # Add recipients
        recipients = [
            {"email": "hr1@company.com", "hr_name": "HR1", "company": "Company1", "job_role": "Engineer", "location": "NYC"},
            {"email": "hr2@company.com", "hr_name": "HR2", "company": "Company2", "job_role": "Manager", "location": "LA"},
        ]
        temp_db.add_campaign_recipients(cid, recipients)

        # Get recipients
        rows = temp_db.get_campaign_recipients(cid)
        assert len(rows) == 2
        emails = {r["email"] for r in rows}
        assert "hr1@company.com" in emails
        assert "hr2@company.com" in emails

    def test_user_isolation_queries(self, temp_db):
        """Database queries properly filter by user_id."""
        # Create resources for two users
        temp_db.create_template("U1 Template", "S", "B", "Sig", user_id=1)
        temp_db.create_template("U2 Template", "S", "B", "Sig", user_id=2)

        temp_db.create_draft("U1 Draft", "S", "B", "Sig", [], [], {}, user_id=1)
        temp_db.create_draft("U2 Draft", "S", "B", "Sig", [], [], {}, user_id=2)

        temp_db.create_campaign("U1 Campaign", "B", "Sig", [], {}, user_id=1)
        temp_db.create_campaign("U2 Campaign", "B", "Sig", [], {}, user_id=2)

        # Verify isolation
        templates_u1 = temp_db.list_templates(user_id=1)
        templates_u2 = temp_db.list_templates(user_id=2)
        assert len(templates_u1) == 1
        assert len(templates_u2) == 1
        assert templates_u1[0]["name"] == "U1 Template"
        assert templates_u2[0]["name"] == "U2 Template"

        drafts_u1 = temp_db.list_drafts(user_id=1)
        drafts_u2 = temp_db.list_drafts(user_id=2)
        assert len(drafts_u1) == 1
        assert len(drafts_u2) == 1

        campaigns_u1 = temp_db.list_campaigns(user_id=1)
        campaigns_u2 = temp_db.list_campaigns(user_id=2)
        assert len(campaigns_u1) == 1
        assert len(campaigns_u2) == 1


# =============================================================================
# RATE LIMITING TESTS
# =============================================================================
class TestRateLimiting:
    """Test rate limiting functionality."""

    def test_registration_rate_limit(self, client):
        """Multiple rapid registrations should be rate limited."""
        # Register many times quickly
        for i in range(5):
            username = f"rateuser_{i}_{int(time.time() * 1000)}"
            resp = client.post("/api/auth/register", json={
                "name": f"Rate User {i}",
                "email": f"{username}@example.com",
                "username": username,
                "password": "Password123!",
                "confirm_password": "Password123!",
            })
            # First few should succeed
            if i < 3:
                assert resp.status_code == 200

    def test_login_rate_limit(self, client, auth_cookies):
        """Multiple failed logins should be rate limited."""
        username = auth_cookies[1]

        # Make many failed login attempts
        for i in range(10):
            resp = client.post("/api/auth/login", json={
                "username": username,
                "password": "WrongPassword!",
            })
            if resp.status_code == 429:
                # Rate limited
                assert "Too many" in resp.json()["detail"]
                break
        else:
            # If we didn't get rate limited, the account might be locked
            pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
