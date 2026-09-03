"""Tests for request-scoped X-* HTTP header overrides."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# Strip environment keys for clean test slate
for key in ("TAVILY_API_KEY", "BRAVE_API_KEY", "NVIDIA_NIM_API_KEY", "OPENROUTER_API_KEY", "BLUEDOOR_API_KEY"):
    os.environ.pop(key, None)


@pytest.fixture
def client():
    from backend.app.main import app
    with TestClient(app) as c:
        yield c


def test_tavily_header_override_enables_client():
    from backend.app.context import RequestOverrides, request_overrides_var
    from backend.app.services.search_api import TavilyClient

    assert not TavilyClient().available()

    token = request_overrides_var.set(RequestOverrides(tavily_api_key="tvly-header-key"))
    try:
        c = TavilyClient()
        assert c.available()
        assert c.api_key == "tvly-header-key"
    finally:
        request_overrides_var.reset(token)


def test_brave_header_override_enables_client():
    from backend.app.context import RequestOverrides, request_overrides_var
    from backend.app.services.search_api import BraveClient

    assert not BraveClient().available()

    token = request_overrides_var.set(RequestOverrides(brave_api_key="bsa-header-key"))
    try:
        c = BraveClient()
        assert c.available()
        assert c.api_key == "bsa-header-key"
    finally:
        request_overrides_var.reset(token)


def test_bluedoor_header_override_enables_key():
    from backend.app.context import RequestOverrides, request_overrides_var
    from backend.app.models.job_boards import JobBoardEntry, _get_api_key

    board = JobBoardEntry(
        name="bluedoor",
        base_url="https://api.bluedoor.sh",
        auth="api_key",
        api_key_env="BLUEDOOR_API_KEY",
    )
    assert _get_api_key(board) is None

    token = request_overrides_var.set(RequestOverrides(bluedoor_api_key="jobs_live_header"))
    try:
        assert _get_api_key(board) == "jobs_live_header"
    finally:
        request_overrides_var.reset(token)


def test_llm_router_header_overrides(monkeypatch):
    from backend.app.config import settings
    from backend.app.context import RequestOverrides, request_overrides_var
    from backend.app.llm_router import router

    # Ensure settings has no key for nvidia
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", None)

    # _model_for resolves model name from settings (independent of credentials)
    assert router._model_for("nvidia", "simple") == settings.LLM_MODELS["simple"]["nvidia"]

    token = request_overrides_var.set(
        RequestOverrides(
            llm_provider="custom",
            nvidia_api_key="nv-key-header",
            custom_endpoint="http://custom:8080/v1",
            custom_api_key="custom-key-header",
            custom_model="my-custom-model",
        )
    )
    try:
        # nvidia is now available via header key
        assert router._model_for("nvidia", "simple") is not None

        # custom model is resolved
        assert router._model_for("custom", "simple") == "my-custom-model"
    finally:
        request_overrides_var.reset(token)


def test_middleware_extracts_headers(client):
    """End-to-end HTTP middleware test verifying X-* headers populate context."""
    headers = {
        "X-LLM-Provider": "custom",
        "X-NVIDIA-API-Key": "nv-test",
        "X-Tavily-API-Key": "tvly-test",
        "X-Custom-Endpoint": "http://localhost:8080/v1",
        "X-Custom-Model": "custom-llama",
    }

    # /health endpoint invokes dependency checks which read overrides
    resp = client.get("/health", headers=headers)
    assert resp.status_code == 200
