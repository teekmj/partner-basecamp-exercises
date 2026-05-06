"""Tests for durable eval archive (FR-408 / FR-409)."""

import pytest

import storage
from app import app


@pytest.fixture(autouse=True)
def clean_storage():
    storage._reset_for_tests()
    yield
    storage._reset_for_tests()


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_append_eval_writes_to_both_live_and_archive():
    storage.append_eval_run({"suite": "smoke", "passed": 4, "total": 4, "pass_rate": 100})
    assert len(storage.list_eval_runs()) == 1
    assert len(storage.list_eval_archive()) == 1


def test_clearing_live_log_does_not_touch_archive():
    """Storage doesn't expose a clear_eval_runs, but the archive must
    survive even if someone deletes the live log file."""
    storage.append_eval_run({"suite": "factual", "passed": 18, "total": 20, "pass_rate": 90})
    # Manually remove the live log
    storage.EVAL_RUNS_FILE.unlink()
    assert storage.list_eval_runs() == []
    assert len(storage.list_eval_archive()) == 1
    archived = storage.list_eval_archive()[0]
    assert archived["suite"] == "factual"


def test_archive_groups_by_day():
    """Multiple runs on the same day go into one archive file."""
    storage.append_eval_run({"suite": "smoke", "passed": 4, "total": 4, "pass_rate": 100})
    storage.append_eval_run({"suite": "smoke", "passed": 4, "total": 4, "pass_rate": 100})
    files = list(storage.EVAL_ARCHIVE_DIR.glob("*.jsonl"))
    assert len(files) == 1


def test_archive_endpoint_returns_runs(client):
    storage.append_eval_run({"suite": "edge", "passed": 3, "total": 3, "pass_rate": 100})
    r = client.get("/api/evals/archive")
    assert r.status_code == 200
    runs = r.get_json()["runs"]
    assert len(runs) == 1
    assert runs[0]["suite"] == "edge"


def test_archive_endpoint_respects_limit(client):
    for i in range(5):
        storage.append_eval_run({"suite": f"s{i}", "passed": 1, "total": 1, "pass_rate": 100})
    r = client.get("/api/evals/archive?limit=2")
    assert len(r.get_json()["runs"]) == 2
