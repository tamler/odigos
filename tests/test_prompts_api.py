"""Tests for the prompts API endpoint."""
import pytest
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from odigos.api.prompts import router, _PROMPT_DIRS


@pytest.fixture
def app_with_prompts(tmp_path):
    agent_dir = tmp_path / "agent"
    prompts_dir = tmp_path / "prompts"
    agent_dir.mkdir()
    prompts_dir.mkdir()

    (agent_dir / "identity.md").write_text(
        "---\npriority: 10\nalways_include: true\n---\nYou are Odigos."
    )
    (prompts_dir / "summarizer.md").write_text("Summarize this conversation.")

    app = FastAPI()
    app.include_router(router)

    settings = MagicMock()
    settings.api_key = "test-key"
    app.state.settings = settings

    original_dirs = dict(_PROMPT_DIRS)
    _PROMPT_DIRS["agent"] = str(agent_dir)
    _PROMPT_DIRS["prompts"] = str(prompts_dir)

    yield TestClient(app)

    _PROMPT_DIRS.update(original_dirs)


def test_list_prompts(app_with_prompts):
    client = app_with_prompts
    resp = client.get("/api/prompts", headers={"Authorization": "Bearer test-key"})
    assert resp.status_code == 200
    data = resp.json()
    names = [p["name"] for p in data]
    assert "identity" in names
    assert "summarizer" in names


def test_read_prompt(app_with_prompts):
    client = app_with_prompts
    resp = client.get(
        "/api/prompts/agent/identity",
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 200
    assert "You are Odigos." in resp.json()["content"]


def test_update_prompt(app_with_prompts):
    client = app_with_prompts
    resp = client.put(
        "/api/prompts/prompts/summarizer",
        json={"content": "New summarizer prompt."},
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 200

    resp = client.get(
        "/api/prompts/prompts/summarizer",
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.json()["content"] == "New summarizer prompt."


def test_read_nonexistent_returns_404(app_with_prompts):
    client = app_with_prompts
    resp = client.get(
        "/api/prompts/agent/nonexistent",
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 404


def test_invalid_directory_returns_400(app_with_prompts):
    client = app_with_prompts
    resp = client.get(
        "/api/prompts/invalid/identity",
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 400
