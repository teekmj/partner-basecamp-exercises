"""Tests for the new API endpoints (scenarios, search, evals, export, dev)."""

import json

import pytest

import storage
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    storage._reset_for_tests()
    with app.test_client() as c:
        yield c
    storage._reset_for_tests()


# ---------- scenarios ----------

def test_scenarios_list_empty(client):
    r = client.get("/api/scenarios")
    assert r.status_code == 200
    assert r.get_json() == {"scenarios": []}


def test_scenarios_save_with_questions(client):
    r = client.post("/api/scenarios", json={
        "name": "Acme Q1",
        "client": "Acme",
        "questions": [{"id": "Q1", "category": "technical", "text": "What is X?"}],
    })
    assert r.status_code == 200
    s = r.get_json()["scenario"]
    assert s["name"] == "Acme Q1"
    assert s["id"]


def test_scenarios_save_with_text_parses(client):
    """Save a scenario by passing raw text — it should be parsed into questions."""
    r = client.post("/api/scenarios", json={
        "name": "Custom",
        "text": "Q1. What is one?\n\nQ2. What is two?",
    })
    assert r.status_code == 200
    s = r.get_json()["scenario"]
    assert len(s["questions"]) == 2


def test_scenarios_save_requires_name(client):
    r = client.post("/api/scenarios", json={"text": "Q1. test"})
    assert r.status_code == 400


def test_scenarios_save_requires_questions_or_text(client):
    r = client.post("/api/scenarios", json={"name": "X"})
    assert r.status_code == 400


def test_scenarios_get_by_id(client):
    saved = storage.save_scenario({"name": "T", "questions": []})
    r = client.get(f"/api/scenarios/{saved['id']}")
    assert r.status_code == 200
    assert r.get_json()["scenario"]["name"] == "T"


def test_scenarios_get_unknown_returns_404(client):
    r = client.get("/api/scenarios/nonexistent")
    assert r.status_code == 404


def test_scenarios_delete(client):
    saved = storage.save_scenario({"name": "T", "questions": []})
    r = client.delete(f"/api/scenarios/{saved['id']}")
    assert r.status_code == 200
    assert client.get(f"/api/scenarios/{saved['id']}").status_code == 404


def test_scenarios_clone(client):
    src = storage.save_scenario({"name": "Original", "client": "Acme", "questions": []})
    r = client.post(f"/api/scenarios/{src['id']}/clone", json={})
    assert r.status_code == 200
    cloned = r.get_json()["scenario"]
    assert cloned["id"] != src["id"]
    assert "Original" in cloned["name"]


def test_scenarios_clone_with_explicit_name(client):
    src = storage.save_scenario({"name": "A", "questions": []})
    r = client.post(f"/api/scenarios/{src['id']}/clone", json={"name": "A Variant"})
    assert r.get_json()["scenario"]["name"] == "A Variant"


def test_scenarios_run_unknown_returns_404(client):
    r = client.post("/api/scenarios/nonexistent/run", json={"api_key": "x"})
    assert r.status_code == 404


# ---------- search ----------

def test_search_empty_query(client):
    r = client.post("/api/search", json={"query": ""})
    assert r.status_code == 400


def test_search_returns_kb_results(client):
    r = client.post("/api/search", json={"query": "encryption AES"})
    assert r.status_code == 200
    results = r.get_json()["results"]
    assert any(x["type"] == "kb" for x in results)


def test_search_with_type_filter(client):
    r = client.post("/api/search", json={"query": "encryption", "types": ["scenario"]})
    assert r.status_code == 200
    # No scenarios saved → no results
    assert r.get_json()["results"] == []


# ---------- evals ----------

def test_evals_suites_lists_four(client):
    r = client.get("/api/evals/suites")
    assert r.status_code == 200
    suites = r.get_json()["suites"]
    ids = [s["id"] for s in suites]
    assert set(ids) == {"smoke", "factual", "edge", "full"}


def test_evals_runs_empty(client):
    r = client.get("/api/evals/runs")
    assert r.get_json() == {"runs": []}


def test_evals_run_unknown_suite(client):
    r = client.post("/api/evals/run", json={"suite": "fake_suite", "api_key": "x"})
    assert r.status_code == 400


def test_evals_run_requires_api_key(client, monkeypatch):
    monkeypatch.setattr("app.DEFAULT_API_KEY", "")
    r = client.post("/api/evals/run", json={"suite": "smoke"})
    assert r.status_code == 400


# ---------- export ----------

def test_export_html_with_inline_final(client):
    final = {
        "rfp_name": "T", "total_questions": 1,
        "answers": [{"question_id": "Q1", "category": "technical", "answer": "x",
                     "sources": ["S"], "confidence": "high", "flags": []}],
        "review": {"consistency_score": "high", "issues": [], "recommendations": []},
        "metadata": {"model": "m", "knowledge_base_entries": 1, "generated_at": "2026"}
    }
    r = client.post("/api/export/html", json={"final": final})
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("text/html")
    assert b"<!DOCTYPE html>" in r.data
    assert b"Q1" in r.data


def test_export_html_with_scenario_id(client):
    s = storage.save_scenario({"name": "S", "client": "X", "questions": []})
    storage.attach_result(s["id"], {
        "rfp_name": "S", "total_questions": 1,
        "answers": [{"question_id": "Q1", "category": "technical", "answer": "x",
                     "sources": ["S"], "confidence": "high", "flags": []}],
        "review": {"consistency_score": "high", "issues": [], "recommendations": []},
        "metadata": {"model": "m", "knowledge_base_entries": 1, "generated_at": "2026"}
    })
    r = client.post("/api/export/html", json={"scenario_id": s["id"]})
    assert r.status_code == 200
    assert b"<!DOCTYPE html>" in r.data


def test_export_html_missing_returns_400(client):
    r = client.post("/api/export/html", json={})
    assert r.status_code == 400


# ---------- dev mode ----------

def test_dev_prompts_returns_system_and_review(client):
    r = client.get("/api/dev/prompts")
    assert r.status_code == 200
    d = r.get_json()
    assert "system_prompt" in d
    assert "review_prompt_template" in d
    assert "kb_full" in d
    assert isinstance(d["kb_full"], list)
    assert "search_kb" in d["system_prompt"]


def test_dev_log_returns_recent_entries(client):
    # Trigger some endpoints
    client.get("/api/health")
    client.get("/api/sample")
    client.post("/api/parse", json={"text": "Q1. test"})

    r = client.get("/api/dev/log")
    assert r.status_code == 200
    entries = r.get_json()["entries"]
    paths = [e["path"] for e in entries]
    assert "/api/health" in paths
    assert "/api/sample" in paths


def test_dev_log_clear(client):
    client.get("/api/health")
    client.post("/api/dev/log/clear")
    r = client.get("/api/dev/log")
    # After clear, only the clear request itself might be logged (or nothing)
    entries = r.get_json()["entries"]
    # Should be empty or very minimal
    assert len(entries) <= 2


# ---------- HTML structure (mode tabs) ----------

def test_html_has_all_six_modes(client):
    r = client.get("/")
    body = r.data.decode("utf-8")
    for mode in ["run", "scenarios", "search", "evals", "arch", "dev"]:
        assert f'data-mode="{mode}"' in body, f"Missing mode: {mode}"


def test_html_has_top_nav(client):
    body = client.get("/").data.decode("utf-8")
    assert 'class="topnav"' in body
    assert "Scenarios" in body
    assert "Search" in body
    assert "Evals" in body
    assert "Dev" in body


def test_app_js_has_mode_handlers(client):
    body = client.get("/static/app.js").data.decode("utf-8")
    assert "switchMode" in body
    assert "loadScenarios" in body
    assert "runSearch" in body
    assert "runEvalSuite" in body
    assert "loadDevPrompts" in body
