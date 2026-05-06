"""Lightweight JSON-file storage for scenarios + eval runs + request log.

Designed to be replaceable by a real database later. Each store is
file-backed so server restarts preserve state.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

SCENARIOS_FILE = DATA_DIR / "scenarios.json"
EVAL_RUNS_FILE = DATA_DIR / "eval_runs.jsonl"
REQUEST_LOG_FILE = DATA_DIR / "request_log.jsonl"

# Eval archive: append-only, committed to repo. Survives clear/reset
# of the live eval_runs.jsonl. Provides historical audit trail.
EVAL_ARCHIVE_DIR = DATA_DIR / "evals_archive"
EVAL_ARCHIVE_DIR.mkdir(exist_ok=True)

_lock = threading.Lock()


# ============================================================
# Scenarios
# ============================================================

def _load_scenarios() -> dict:
    if not SCENARIOS_FILE.exists():
        return {}
    try:
        return json.loads(SCENARIOS_FILE.read_text())
    except json.JSONDecodeError:
        return {}


def _save_scenarios(data: dict) -> None:
    SCENARIOS_FILE.write_text(json.dumps(data, indent=2))


def list_scenarios() -> list[dict]:
    """Return all saved scenarios with brief metadata."""
    with _lock:
        scenarios = _load_scenarios()
    return [
        {
            "id": sid,
            "name": s.get("name", ""),
            "client": s.get("client", ""),
            "description": s.get("description", ""),
            "question_count": len(s.get("questions", [])),
            "has_result": bool(s.get("result")),
            "created_at": s.get("created_at"),
            "last_run_at": s.get("last_run_at"),
        }
        for sid, s in scenarios.items()
    ]


def get_scenario(sid: str) -> dict | None:
    with _lock:
        return _load_scenarios().get(sid)


def save_scenario(scenario: dict) -> dict:
    """Create or update a scenario."""
    with _lock:
        scenarios = _load_scenarios()
        sid = scenario.get("id") or str(uuid.uuid4())[:8]
        scenarios[sid] = {
            **scenarios.get(sid, {}),
            **scenario,
            "id": sid,
            "created_at": scenarios.get(sid, {}).get("created_at") or time.time(),
            "updated_at": time.time(),
        }
        _save_scenarios(scenarios)
        return scenarios[sid]


def attach_result(sid: str, result: dict) -> dict | None:
    """Store the latest pipeline result on a scenario."""
    with _lock:
        scenarios = _load_scenarios()
        if sid not in scenarios:
            return None
        scenarios[sid]["result"] = result
        scenarios[sid]["last_run_at"] = time.time()
        _save_scenarios(scenarios)
        return scenarios[sid]


def delete_scenario(sid: str) -> bool:
    with _lock:
        scenarios = _load_scenarios()
        if sid not in scenarios:
            return False
        del scenarios[sid]
        _save_scenarios(scenarios)
        return True


def clone_scenario(sid: str, new_name: str | None = None) -> dict | None:
    """Duplicate a scenario (keeps client + questions, drops result)."""
    src = get_scenario(sid)
    if not src:
        return None
    cloned = {
        **src,
        "id": None,  # force new ID
        "name": new_name or f"{src.get('name', 'Scenario')} (copy)",
        "result": None,
        "last_run_at": None,
    }
    cloned.pop("created_at", None)
    cloned.pop("updated_at", None)
    return save_scenario(cloned)


# ============================================================
# Eval runs
# ============================================================

def append_eval_run(run: dict) -> None:
    """Append a single eval run record to BOTH the live log and the archive.

    Live log is mutable (can be cleared); archive is append-only and
    intended to be committed alongside the code as a durable history.
    """
    run.setdefault("timestamp", time.time())
    with _lock:
        # Live log
        with open(EVAL_RUNS_FILE, "a") as f:
            f.write(json.dumps(run) + "\n")
        # Archive: one file per day so commits stay reviewable
        day = time.strftime("%Y-%m-%d", time.gmtime(run["timestamp"]))
        with open(EVAL_ARCHIVE_DIR / f"{day}.jsonl", "a") as f:
            f.write(json.dumps(run) + "\n")


def list_eval_runs(limit: int = 50) -> list[dict]:
    if not EVAL_RUNS_FILE.exists():
        return []
    with _lock:
        lines = EVAL_RUNS_FILE.read_text().splitlines()
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def list_eval_archive(limit: int = 200) -> list[dict]:
    """Read all archived eval runs (across all daily files), most recent last."""
    if not EVAL_ARCHIVE_DIR.exists():
        return []
    rows: list[dict] = []
    with _lock:
        for path in sorted(EVAL_ARCHIVE_DIR.glob("*.jsonl")):
            try:
                for line in path.read_text().splitlines():
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            except OSError:
                continue
    return rows[-limit:]


# ============================================================
# Request log
# ============================================================

def append_request_log(entry: dict) -> None:
    entry.setdefault("timestamp", time.time())
    with _lock:
        with open(REQUEST_LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")


def list_request_log(limit: int = 100) -> list[dict]:
    if not REQUEST_LOG_FILE.exists():
        return []
    with _lock:
        lines = REQUEST_LOG_FILE.read_text().splitlines()
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def clear_request_log() -> None:
    with _lock:
        if REQUEST_LOG_FILE.exists():
            REQUEST_LOG_FILE.unlink()


# ============================================================
# Test helpers (used in pytest only)
# ============================================================

def _reset_for_tests():
    """Wipe storage. Tests call this to avoid cross-pollution.

    Also wipes the archive — tests don't need durable history.
    """
    with _lock:
        for f in [SCENARIOS_FILE, EVAL_RUNS_FILE, REQUEST_LOG_FILE]:
            if f.exists():
                f.unlink()
        if EVAL_ARCHIVE_DIR.exists():
            for child in EVAL_ARCHIVE_DIR.glob("*.jsonl"):
                child.unlink()
