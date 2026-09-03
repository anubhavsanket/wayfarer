"""Unit tests for the SQLite tracker layer and REST endpoints."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Use a temporary SQLite database for each test."""
    from backend.app import db
    from backend.app.config import settings

    db_file = str(tmp_path / "test_wayfarer.db")
    monkeypatch.setattr(settings, "TRACKER_DB_PATH", db_file)
    db.close_db()
    db.init_db()
    yield db_file
    db.close_db()


def test_db_save_job_and_re_save():
    from backend.app import db

    job_data = {
        "job_id": "job-101",
        "title": "Backend Engineer",
        "company": "TechCorp",
        "apply_url": "https://example.com/apply",
        "source": "remoteok",
        "location": "Remote",
        "match_score": 0.85,
    }

    # First save
    saved = db.save_job(job_data)
    assert saved["job_id"] == "job-101"
    assert saved["title"] == "Backend Engineer"
    assert "saved_at" in saved

    # Re-save with saved_at in dictionary (must not crash with TypeError)
    re_saved = db.save_job(saved)
    assert re_saved["job_id"] == "job-101"
    assert db.is_saved("job-101") is True

    # List saved
    all_saved = db.list_saved()
    assert len(all_saved) == 1
    assert all_saved[0]["job_id"] == "job-101"

    # Unsave
    assert db.unsave_job("job-101") is True
    assert db.is_saved("job-101") is False


def test_db_application_lifecycle():
    from backend.app import db

    app_data = {
        "job_id": "job-202",
        "title": "Frontend Engineer",
        "company": "DesignCo",
        "apply_url": None,
        "source": None,
        "location": None,
        "match_score": 0.9,
        "resume_id": None,
    }

    # Create application with NULL fields
    created = db.create_application(app_data)
    assert created["job_id"] == "job-202"
    assert created["status"] == "applied"

    # Update status and notes
    updated = db.update_application("job-202", status="interview", notes="Screening passed")
    assert updated["status"] == "interview"
    assert updated["notes"] == "Screening passed"

    # List applications
    apps = db.list_applications()
    assert len(apps) == 1
    assert apps[0]["status"] == "interview"

    # Delete application
    assert db.delete_application("job-202") is True
    assert db.get_application("job-202") is None


def test_tracker_api_endpoints():
    from backend.app.main import app

    client = TestClient(app)

    # 1. Save a job
    res = client.post(
        "/api/v1/tracker/saved",
        json={
            "job_id": "api-job-1",
            "title": "Fullstack Developer",
            "company": "Acme Inc",
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["job_id"] == "api-job-1"

    # 2. List saved jobs
    res = client.get("/api/v1/tracker/saved")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 1
    assert items[0]["job_id"] == "api-job-1"

    # 3. Create application
    res = client.post(
        "/api/v1/tracker/applications",
        json={
            "job_id": "api-job-1",
            "title": "Fullstack Developer",
            "company": "Acme Inc",
        },
    )
    assert res.status_code == 200
    app_data = res.json()
    assert app_data["status"] == "applied"

    # 4. Update application status
    res = client.patch(
        "/api/v1/tracker/applications/api-job-1",
        json={"status": "offer", "notes": "Got offer!"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "offer"

    # 5. List applications
    res = client.get("/api/v1/tracker/applications")
    assert res.status_code == 200
    assert len(res.json()) == 1

    # 6. Unsave & Delete application
    assert client.delete("/api/v1/tracker/saved/api-job-1").status_code == 200
    assert client.delete("/api/v1/tracker/applications/api-job-1").status_code == 200
