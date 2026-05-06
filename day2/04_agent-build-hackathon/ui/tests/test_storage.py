"""Tests for storage layer (scenarios + eval runs + request log)."""

import pytest

import storage


@pytest.fixture(autouse=True)
def clean_storage():
    storage._reset_for_tests()
    yield
    storage._reset_for_tests()


def test_save_creates_scenario_with_id():
    s = storage.save_scenario({"name": "Acme Q1", "client": "Acme", "questions": []})
    assert s["id"]
    assert s["name"] == "Acme Q1"
    assert s["created_at"]
    assert s["updated_at"]


def test_list_scenarios_returns_metadata():
    storage.save_scenario({"name": "S1", "client": "Acme", "questions": [{"id": "Q1", "text": "?", "category": "technical"}]})
    storage.save_scenario({"name": "S2", "client": "Bcorp", "questions": [{"id": "Q1", "text": "?", "category": "technical"}, {"id": "Q2", "text": "?", "category": "pricing"}]})
    rows = storage.list_scenarios()
    assert len(rows) == 2
    by_name = {r["name"]: r for r in rows}
    assert by_name["S2"]["question_count"] == 2
    assert by_name["S1"]["client"] == "Acme"
    assert all("id" in r for r in rows)


def test_get_scenario_returns_full_record():
    s = storage.save_scenario({"name": "Test", "client": "X", "questions": [], "description": "demo"})
    full = storage.get_scenario(s["id"])
    assert full["description"] == "demo"


def test_attach_result_persists():
    s = storage.save_scenario({"name": "T", "questions": []})
    fake = {"answers": [{"question_id": "Q1", "answer": "x"}], "review": {"consistency_score": "high"}}
    storage.attach_result(s["id"], fake)
    full = storage.get_scenario(s["id"])
    assert full["result"]["review"]["consistency_score"] == "high"
    assert full["last_run_at"]


def test_attach_result_unknown_id_returns_none():
    assert storage.attach_result("nonexistent", {}) is None


def test_delete_scenario_removes():
    s = storage.save_scenario({"name": "T", "questions": []})
    assert storage.delete_scenario(s["id"]) is True
    assert storage.get_scenario(s["id"]) is None


def test_delete_unknown_returns_false():
    assert storage.delete_scenario("zzz") is False


def test_clone_scenario_makes_copy_with_new_id():
    src = storage.save_scenario({"name": "Original", "client": "Acme", "questions": [{"id": "Q1", "text": "?", "category": "technical"}]})
    src_id = src["id"]
    storage.attach_result(src_id, {"answers": [{"question_id": "Q1", "answer": "x"}], "review": {}})

    cloned = storage.clone_scenario(src_id)
    assert cloned["id"] != src_id
    assert cloned["name"].startswith("Original")  # has "(copy)" suffix
    assert cloned["client"] == "Acme"
    # Result must NOT carry over
    assert cloned.get("result") is None


def test_clone_with_explicit_name():
    src = storage.save_scenario({"name": "A", "questions": []})
    cloned = storage.clone_scenario(src["id"], new_name="A Variant")
    assert cloned["name"] == "A Variant"


def test_clone_unknown_returns_none():
    assert storage.clone_scenario("nonexistent") is None


def test_eval_runs_append_and_list():
    storage.append_eval_run({"suite": "smoke", "passed": 4, "total": 4, "pass_rate": 100})
    storage.append_eval_run({"suite": "factual", "passed": 18, "total": 20, "pass_rate": 90})
    runs = storage.list_eval_runs()
    assert len(runs) == 2
    suites = [r["suite"] for r in runs]
    assert "smoke" in suites and "factual" in suites


def test_request_log_append_and_list():
    storage.append_request_log({"path": "/api/run", "method": "POST", "status": 200, "elapsed_ms": 75})
    storage.append_request_log({"path": "/api/health", "method": "GET", "status": 200, "elapsed_ms": 2})
    log = storage.list_request_log()
    assert len(log) == 2


def test_request_log_clear():
    storage.append_request_log({"path": "/x", "method": "GET", "status": 200, "elapsed_ms": 1})
    assert len(storage.list_request_log()) == 1
    storage.clear_request_log()
    assert storage.list_request_log() == []
