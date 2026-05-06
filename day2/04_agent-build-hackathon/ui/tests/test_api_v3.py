"""Tests for the v3 API endpoints: /api/specialists, /api/scenarios/seed."""

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


def test_specialists_endpoint_returns_all(client):
    """4 drafting + 2 post-draft (reviewer + demoer) = 6 total."""
    r = client.get("/api/specialists")
    assert r.status_code == 200
    rows = r.get_json()["specialists"]
    assert len(rows) >= 4
    keys = {r["key"] for r in rows}
    drafting = {"architect", "pricing_lead", "compliance", "business_sme"}
    assert drafting <= keys
    # Post-draft specialists should also be present
    assert "reviewer" in keys
    assert "demoer" in keys


def test_specialists_have_labels_and_descriptions(client):
    rows = client.get("/api/specialists").get_json()["specialists"]
    for r in rows:
        assert r["label"]
        assert r["description"]
    # Drafting specialists have search_kb; post-draft don't
    by_key = {r["key"]: r for r in rows}
    for k in ["architect", "pricing_lead", "compliance", "business_sme"]:
        assert "search_kb" in by_key[k]["tools"]


def test_seed_endpoint_persists_50(client):
    r = client.post("/api/scenarios/seed", json={})
    assert r.status_code == 200
    d = r.get_json()
    assert d["saved"] == 50
    assert d["total"] == 50

    # Verify
    list_r = client.get("/api/scenarios")
    assert len(list_r.get_json()["scenarios"]) == 50


def test_seed_endpoint_is_idempotent(client):
    client.post("/api/scenarios/seed", json={})
    r2 = client.post("/api/scenarios/seed", json={})
    d = r2.get_json()
    assert d["saved"] == 0
    assert d["skipped"] == 50


def test_seed_endpoint_force_overwrites(client):
    client.post("/api/scenarios/seed", json={})
    r2 = client.post("/api/scenarios/seed", json={"force": True})
    assert r2.get_json()["saved"] == 50


def test_health_reports_specialist_count(client):
    """4 drafting + 2 post-draft = 6 specialists."""
    r = client.get("/api/health")
    assert r.get_json()["specialists"] >= 4


def test_health_reports_archive_count(client):
    storage.append_eval_run({"suite": "smoke", "passed": 4, "total": 4, "pass_rate": 100})
    d = client.get("/api/health").get_json()
    assert d["eval_archive"] >= 1
