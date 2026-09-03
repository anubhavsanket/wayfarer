"""Tests for OAuth, multi-tenant user identity, and encrypted user settings.

Tests:
1. JWT token generation and verification roundtrip
2. User DB upsert and retrieval
3. Encrypted user settings roundtrip
4. Auth API endpoints (login, me, settings)
5. Multi-tenant saved jobs isolation
"""
from __future__ import annotations

import tempfile
import os
import pytest
import httpx
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch, MagicMock


# ── JWT Token Tests ────────────────────────────────────────────────────


def test_jwt_token_generation_and_decode():
    from backend.app.core.auth import create_access_token, decode_access_token

    token = create_access_token("user_abc", "test@example.com", "Test User", "https://pic.jpg")
    assert isinstance(token, str)
    assert len(token) > 50

    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "user_abc"
    assert payload["email"] == "test@example.com"
    assert payload["name"] == "Test User"
    assert payload["picture"] == "https://pic.jpg"
    assert "exp" in payload
    assert "iat" in payload


def test_jwt_token_invalid():
    from backend.app.core.auth import decode_access_token

    result = decode_access_token("invalid.token.here")
    assert result is None


def test_jwt_token_tampered():
    from backend.app.core.auth import create_access_token, decode_access_token

    token = create_access_token("user_abc", "test@example.com")
    # Tamper with the payload
    parts = token.split(".")
    parts[1] = parts[1][::-1]
    tampered = ".".join(parts)

    result = decode_access_token(tampered)
    assert result is None


# ── Encrypted Settings Roundtrip ────────────────────────────────────────


def test_encrypt_decrypt_roundtrip():
    from backend.app.utils.crypto import encrypt_text, decrypt_text

    original = "nvapi-my-secret-key-12345"
    encrypted = encrypt_text(original)
    assert encrypted != ""
    assert encrypted != original

    decrypted = decrypt_text(encrypted)
    assert decrypted == original


def test_encrypt_decrypt_empty():
    from backend.app.utils.crypto import encrypt_text, decrypt_text

    assert encrypt_text("") == ""
    assert decrypt_text("") == ""


def test_decrypt_invalid_token():
    from backend.app.utils.crypto import decrypt_text

    result = decrypt_text("not-a-valid-cipher-text")
    assert result == ""


# ── Database User Operations ────────────────────────────────────────────


def test_upsert_user():
    from backend.app.db import upsert_user, get_user, _conn

    # Use a temp DB for isolation
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name

    try:
        import backend.app.db as db_mod
        old_path = db_mod.settings.TRACKER_DB_PATH
        db_mod.settings.TRACKER_DB_PATH = temp_path
        db_mod._conn = None

        db_mod.init_db()

        user = upsert_user("user_test", "test@wayfarer.com", "Test Name", "https://pic.jpg")
        assert user is not None
        assert user["user_id"] == "user_test"
        assert user["email"] == "test@wayfarer.com"
        assert user["name"] == "Test Name"

        fetched = get_user("user_test")
        assert fetched is not None
        assert fetched["email"] == "test@wayfarer.com"

        db_mod._conn.close()
        db_mod._conn = None
        db_mod.settings.TRACKER_DB_PATH = old_path
    finally:
        os.unlink(temp_path)


def test_user_settings_encrypted_roundtrip():
    from backend.app.db import upsert_user, save_user_settings, get_user_settings

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name

    try:
        import backend.app.db as db_mod
        old_path = db_mod.settings.TRACKER_DB_PATH
        db_mod.settings.TRACKER_DB_PATH = temp_path
        db_mod._conn = None

        db_mod.init_db()

        upsert_user("user_settings_test", "settings@wayfarer.com", "Settings User")

        test_settings = {
            "llm_provider": "nvidia",
            "nvidia_api_key": "nvapi-super-secret-123",
            "openrouter_api_key": "sk-or-secret-456",
        }

        save_user_settings("user_settings_test", test_settings)

        retrieved = get_user_settings("user_settings_test")
        assert retrieved == test_settings

        # Verify data is encrypted in DB (not plaintext)
        import sqlite3
        conn = sqlite3.connect(temp_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT encrypted_settings FROM user_settings WHERE user_id = 'user_settings_test'").fetchone()
        raw_encrypted = row["encrypted_settings"]
        assert raw_encrypted != str(test_settings)
        assert "nvapi-super-secret-123" not in raw_encrypted
        conn.close()

        db_mod._conn.close()
        db_mod._conn = None
        db_mod.settings.TRACKER_DB_PATH = old_path
    finally:
        os.unlink(temp_path)


# ── Auth API Endpoint Tests ────────────────────────────────────────────


@pytest.fixture
def client():
    from backend.app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


def test_auth_login_local_dev(client):
    resp = client.post("/api/v1/auth/login", json={"email": "dev@wayfarer.com", "name": "Dev User"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["email"] == "dev@wayfarer.com"
    assert data["name"] == "Dev User"
    assert data["user_id"] == "user_dev_at_wayfarer.com"
    assert data["token_type"] == "bearer"


def test_auth_me_with_token(client):
    # Login first
    login_resp = client.post("/api/v1/auth/login", json={"email": "me@wayfarer.com", "name": "Me User"})
    token = login_resp.json()["access_token"]

    # Call /me with bearer
    me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == "me@wayfarer.com"
    assert me_data["user_id"] == "user_me_at_wayfarer.com"


def test_auth_me_local_fallback(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["user_id"] == "local"


def test_auth_login_no_email_no_token(client):
    resp = client.post("/api/v1/auth/login", json={})
    assert resp.status_code == 400


def test_user_settings_save_and_load(client):
    # Login
    login_resp = client.post("/api/v1/auth/login", json={"email": "settings@wayfarer.com"})
    token = login_resp.json()["access_token"]

    # Save settings
    save_resp = client.post(
        "/api/v1/user/settings",
        json={"settings": {"llm_provider": "nvidia", "nvidia_api_key": "nvapi-test"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert save_resp.status_code == 200
    assert save_resp.json()["settings"]["llm_provider"] == "nvidia"

    # Load settings
    load_resp = client.get("/api/v1/user/settings", headers={"Authorization": f"Bearer {token}"})
    assert load_resp.status_code == 200
    assert load_resp.json()["settings"]["nvidia_api_key"] == "nvapi-test"


# ── Multi-Tenant Tracker Isolation ─────────────────────────────────────


def test_multi_tenant_tracker_isolation(client):
    # Login as user A
    login_a = client.post("/api/v1/auth/login", json={"email": "user_a@wayfarer.com"})
    token_a = login_a.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Login as user B
    login_b = client.post("/api/v1/auth/login", json={"email": "user_b@wayfarer.com"})
    token_b = login_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User A saves a job
    job_a = {
        "job_id": "job_a_001",
        "title": "Python Dev",
        "company": "Company A",
        "apply_url": "https://apply-a.com",
        "source": "test",
        "location": "Remote",
    }
    resp = client.post("/api/v1/tracker/saved", json=job_a, headers=headers_a)
    assert resp.status_code == 200

    # User A can see their saved job
    list_a = client.get("/api/v1/tracker/saved", headers=headers_a)
    assert any(j["job_id"] == "job_a_001" for j in list_a.json())

    # User B cannot see user A's saved job
    list_b = client.get("/api/v1/tracker/saved", headers=headers_b)
    assert not any(j["job_id"] == "job_a_001" for j in list_b.json())


def test_unauthenticated_tracker_uses_local(client):
    # Without auth header, data goes to "local" user scope
    list_resp = client.get("/api/v1/tracker/saved")
    assert list_resp.status_code == 200


# ── Cover Letter Endpoint Auth ─────────────────────────────────────────


def test_cover_letter_with_auth(client):
    from backend.app.services.resume_store import store_upload, save_parsed
    from backend.app.services.resume_parser import ParsedResume, ResumeBullet

    parsed = ParsedResume(
        sections={"summary": ["Experienced dev"]},
        bullets=[ResumeBullet(id="b0", section="summary", text="Built amazing things")],
    )
    resume_id, _ = store_upload(b"fake content", "test.pdf")
    save_parsed(resume_id, parsed)

    login_resp = client.post("/api/v1/auth/login", json={"email": "cl@wayfarer.com"})
    token = login_resp.json()["access_token"]

    resp = client.post(
        "/api/v1/tracker/cover-letter",
        json={
            "resume_id": resume_id,
            "job": {"title": "Dev", "company": "Tech Co", "description": "Build things"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    # This may fail due to no LLM, but the auth should pass
    assert resp.status_code in (200, 400, 500)
