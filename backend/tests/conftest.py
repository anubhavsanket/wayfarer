"""Shared test fixtures — resets the resume index between tests to prevent
cross-test contamination from the persistent data/uploads/index.json."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# Ensure no API keys leak into tests
for _key in ("TAVILY_API_KEY", "BRAVE_API_KEY", "NVIDIA_NIM_API_KEY", "OPENROUTER_API_KEY"):
    os.environ.pop(_key, None)


@pytest.fixture(autouse=True)
def _reset_resume_index(tmp_path):
    """Reset the resume index before each test so tests are independent."""
    from backend.app.services import resume_store
    resume_store.UPLOADS_ROOT = tmp_path / "uploads"
    resume_store._INDEX_PATH = resume_store.UPLOADS_ROOT / "index.json"
    resume_store.UPLOADS_ROOT.mkdir(parents=True, exist_ok=True)
    yield
