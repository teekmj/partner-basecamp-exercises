"""Tests for the Flask HTTP API."""

import json

import pytest

from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["kb_entries"] >= 1


def test_sample_returns_5_questions(client):
    r = client.get("/api/sample")
    assert r.status_code == 200
    data = r.get_json()
    assert "questions" in data and "raw_text" in data
    assert len(data["questions"]) == 5
    assert all(set(q.keys()) >= {"id", "category", "text"} for q in data["questions"])


def test_kb_endpoint(client):
    r = client.get("/api/kb")
    assert r.status_code == 200
    data = r.get_json()
    assert "entries" in data
    assert len(data["entries"]) >= 1
    e = data["entries"][0]
    assert {"id", "source", "tags", "preview"} <= set(e.keys())


def test_parse_endpoint_with_text(client):
    r = client.post("/api/parse", json={"text": "Q1. Detection latency?\n\nQ2. Pricing?"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["count"] == 2
    assert len(data["questions"]) == 2


def test_parse_endpoint_empty(client):
    r = client.post("/api/parse", json={"text": ""})
    assert r.status_code == 200
    assert r.get_json()["count"] == 0


def test_retrieve_endpoint_basic(client):
    r = client.post("/api/retrieve", json={"query": "threat detection"})
    assert r.status_code == 200
    data = r.get_json()
    assert "results" in data
    assert isinstance(data["results"], list)


def test_retrieve_endpoint_missing_query(client):
    r = client.post("/api/retrieve", json={})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_run_endpoint_requires_text(client):
    r = client.post("/api/run", json={"text": "", "api_key": "k"})
    assert r.status_code == 400


def test_run_endpoint_requires_key(client, monkeypatch):
    # Force no default key
    monkeypatch.setattr("app.DEFAULT_API_KEY", "")
    r = client.post("/api/run", json={"text": "Q?"})
    assert r.status_code == 400


def test_index_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Helios RFP Agent" in r.data


def test_static_files_served(client):
    r = client.get("/static/styles.css")
    assert r.status_code == 200
    r = client.get("/static/app.js")
    assert r.status_code == 200


def test_index_has_architecture_mode(client):
    """Architecture mode is now a top-level nav tab."""
    r = client.get("/")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert 'data-mode="arch"' in body
    assert "Pipeline stages" in body
    assert "SSE event protocol" in body


def test_index_has_demo_button(client):
    """Demo mode button is present."""
    r = client.get("/")
    body = r.data.decode("utf-8")
    assert 'id="btn-demo"' in body
    assert "Demo mode" in body


def test_arch_mode_describes_all_5_stages(client):
    """The architecture mode content lists all 5 pipeline stages."""
    r = client.get("/")
    body = r.data.decode("utf-8")
    for stage_name in ["Parse", "Retrieve", "Draft", "Review", "Export"]:
        assert stage_name in body, f"Missing stage: {stage_name}"


def test_app_js_has_demo_function(client):
    """Demo mode function is wired in app.js (now uses activateOutputTab)."""
    r = client.get("/static/app.js")
    body = r.data.decode("utf-8")
    assert "runDemo" in body
    assert "showToast" in body
    assert "activateOutputTab" in body
    assert "switchMode" in body
