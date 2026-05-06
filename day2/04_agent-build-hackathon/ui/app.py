"""Flask backend for the interactive RFP agent platform.

Routes overview:
  GET  /                        → SPA (static index.html)
  GET  /api/health              → liveness + counts
  GET  /api/sample              → sample 5-question RFP
  GET  /api/kb                  → KB entries (preview only)
  POST /api/parse               → parse a raw questionnaire (no LLM)
  POST /api/retrieve            → search KB (no LLM)
  POST /api/run                 → SSE stream that runs the full pipeline
  POST /api/search              → search across KB + scenarios + answers
  GET  /api/scenarios           → list saved scenarios
  POST /api/scenarios           → save / update a scenario
  GET  /api/scenarios/<id>      → get one scenario
  DEL  /api/scenarios/<id>      → delete one scenario
  POST /api/scenarios/<id>/clone → clone a scenario (variant)
  POST /api/scenarios/<id>/run  → run a saved scenario through the pipeline (SSE)
  GET  /api/evals/suites        → list available eval suites
  POST /api/evals/run           → run an eval suite (SSE)
  GET  /api/evals/runs          → list past eval runs
  POST /api/export/html         → render a final RFP as HTML (download)
  GET  /api/dev/prompts         → return SYSTEM_PROMPT + REVIEW_PROMPT_TMPL
  GET  /api/dev/log             → return recent request log entries
  POST /api/dev/log/clear       → clear the request log
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from pathlib import Path

import anthropic
from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

import storage
import search_engine
import evals as evals_module
import exporter as exporter_module
from agent_core import (
    KNOWLEDGE_BASE,
    REVIEW_PROMPT_TMPL,
    SYSTEM_PROMPT,
    parse_questionnaire,
    retrieve,
    run_pipeline,
    run_pipeline_parallel,
)
from specialists import list_specialists, SPECIALISTS, SPECIALIST_LABELS
import seed_scenarios

ROOT = Path(__file__).parent
STATIC = ROOT / "static"

app = Flask(__name__, static_folder=str(STATIC), static_url_path="/static")
CORS(app)

DEFAULT_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


SAMPLE_RFP = [
    {"id": "Q1", "category": "technical", "text": "Describe your platform's approach to real-time threat detection. What data sources are ingested, and what is the average detection-to-alert latency?"},
    {"id": "Q2", "category": "compliance", "text": "List all compliance certifications your organization currently holds (SOC 2, ISO 27001, FedRAMP, etc.) and the date of most recent audit for each."},
    {"id": "Q3", "category": "pricing", "text": "Provide per-seat pricing for 500, 1,000, and 5,000 endpoints. Are volume discounts available? Is there a minimum contract term?"},
    {"id": "Q4", "category": "company-info", "text": "How many customers do you currently serve in the financial services vertical? Provide 2–3 reference accounts."},
    {"id": "Q5", "category": "technical", "text": "How does your platform handle data residency requirements for customers operating in the EU? Describe encryption at rest and in transit."},
]


# ---------- request logging middleware ----------

@app.before_request
def _log_request():
    if request.path.startswith("/static/") or request.path.startswith("/api/dev/log"):
        return
    request._t0 = time.time()


@app.after_request
def _log_response(response):
    t0 = getattr(request, "_t0", None)
    if t0 is not None and request.path.startswith("/api/"):
        storage.append_request_log({
            "path": request.path,
            "method": request.method,
            "status": response.status_code,
            "elapsed_ms": int((time.time() - t0) * 1000),
        })
    return response


# ---------- static / health ----------

@app.route("/")
def root():
    return send_from_directory(STATIC, "index.html")


@app.route("/api/health")
def health():
    return jsonify({
        "ok": True,
        "kb_entries": len(KNOWLEDGE_BASE),
        "default_key_set": bool(DEFAULT_API_KEY),
        "scenarios": len(storage.list_scenarios()),
        "eval_runs": len(storage.list_eval_runs()),
        "eval_archive": len(storage.list_eval_archive()),
        "specialists": len(SPECIALISTS),
    })


@app.route("/api/specialists")
def api_specialists():
    """List the four specialist sub-agents."""
    return jsonify({"specialists": list_specialists()})


@app.route("/api/scenarios/seed", methods=["POST"])
def api_seed_scenarios():
    """Idempotently seed 50 sample scenarios."""
    body = request.get_json(silent=True) or {}
    force = bool(body.get("force"))
    result = seed_scenarios.seed(force=force)
    return jsonify(result)


@app.route("/api/evals/archive")
def api_eval_archive():
    """Read the durable, append-only eval archive."""
    limit = int(request.args.get("limit", 200))
    return jsonify({"runs": storage.list_eval_archive(limit=limit)})


@app.route("/api/sample")
def sample():
    return jsonify({
        "questions": SAMPLE_RFP,
        "raw_text": "\n\n".join(f"{q['id']}. {q['text']}" for q in SAMPLE_RFP),
    })


@app.route("/api/kb")
def kb():
    return jsonify({
        "entries": [
            {"id": k, "source": v["source"], "tags": v["tags"], "preview": v["content"][:200], "content": v["content"]}
            for k, v in KNOWLEDGE_BASE.items()
        ]
    })


# ---------- parse / retrieve (cheap utilities) ----------

@app.route("/api/parse", methods=["POST"])
def api_parse():
    body = request.get_json(silent=True) or {}
    raw = body.get("text", "")
    questions = parse_questionnaire(raw)
    return jsonify({"questions": questions, "count": len(questions)})


@app.route("/api/retrieve", methods=["POST"])
def api_retrieve():
    body = request.get_json(silent=True) or {}
    q = body.get("query", "")
    category = body.get("category")
    if not q:
        return jsonify({"error": "query required"}), 400
    return jsonify({"results": retrieve(q, category)})


# ---------- search (across KB + scenarios + answers) ----------

@app.route("/api/search", methods=["POST"])
def api_search():
    body = request.get_json(silent=True) or {}
    query = body.get("query", "")
    types = body.get("types")  # list or None
    limit = int(body.get("limit", 20))
    if not query.strip():
        return jsonify({"error": "query required"}), 400
    return jsonify({"results": search_engine.search(query, types=types, limit=limit)})


# ---------- run pipeline (SSE) ----------

@app.route("/api/run", methods=["POST"])
def api_run():
    body = request.get_json(silent=True) or {}
    raw = body.get("text", "").strip()
    api_key = body.get("api_key") or DEFAULT_API_KEY
    if not raw:
        return jsonify({"error": "text required"}), 400
    if not api_key:
        return jsonify({"error": "api_key required (or set ANTHROPIC_API_KEY)"}), 400

    rfp_name = body.get("rfp_name") or "Interactive RFP Run"
    parallel = body.get("parallel", True)
    return Response(
        _stream_pipeline(raw, api_key, rfp_name, scenario_id=None, parallel=parallel),
        mimetype="text/event-stream",
    )


# ---------- scenarios ----------

@app.route("/api/scenarios", methods=["GET"])
def api_list_scenarios():
    return jsonify({"scenarios": storage.list_scenarios()})


@app.route("/api/scenarios", methods=["POST"])
def api_save_scenario():
    body = request.get_json(silent=True) or {}
    if not body.get("name"):
        return jsonify({"error": "name required"}), 400
    if not isinstance(body.get("questions"), list):
        # Allow saving from raw text — parse it
        if body.get("text"):
            body["questions"] = parse_questionnaire(body["text"])
        else:
            return jsonify({"error": "questions[] or text required"}), 400
    saved = storage.save_scenario(body)
    return jsonify({"scenario": saved})


@app.route("/api/scenarios/<sid>", methods=["GET"])
def api_get_scenario(sid):
    s = storage.get_scenario(sid)
    if not s:
        return jsonify({"error": "not found"}), 404
    return jsonify({"scenario": s})


@app.route("/api/scenarios/<sid>", methods=["DELETE"])
def api_delete_scenario(sid):
    if not storage.delete_scenario(sid):
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/scenarios/<sid>/clone", methods=["POST"])
def api_clone_scenario(sid):
    body = request.get_json(silent=True) or {}
    cloned = storage.clone_scenario(sid, new_name=body.get("name"))
    if not cloned:
        return jsonify({"error": "not found"}), 404
    return jsonify({"scenario": cloned})


@app.route("/api/scenarios/<sid>/run", methods=["POST"])
def api_run_scenario(sid):
    s = storage.get_scenario(sid)
    if not s:
        return jsonify({"error": "not found"}), 404
    body = request.get_json(silent=True) or {}
    api_key = body.get("api_key") or DEFAULT_API_KEY
    if not api_key:
        return jsonify({"error": "api_key required"}), 400
    raw = "\n\n".join(f"{q.get('id', f'Q{i+1}')}. {q.get('text', '')}" for i, q in enumerate(s.get("questions", [])))
    rfp_name = s.get("name", "Scenario")
    parallel = body.get("parallel", True)
    return Response(
        _stream_pipeline(raw, api_key, rfp_name, scenario_id=sid, parallel=parallel, scenario=s),
        mimetype="text/event-stream",
    )


# ---------- evals ----------

@app.route("/api/evals/suites")
def api_eval_suites():
    return jsonify({
        "suites": [
            {"id": "smoke", "name": "Smoke", "description": "1 question, structural checks (~25s)"},
            {"id": "factual", "name": "Factual", "description": "5 questions, expected data points (~80s)"},
            {"id": "edge", "name": "Edge cases", "description": "3 problematic questions (~60s)"},
            {"id": "full", "name": "Full", "description": "5 questions + consistency review (~90s)"},
        ]
    })


@app.route("/api/evals/runs")
def api_eval_runs():
    return jsonify({"runs": storage.list_eval_runs(limit=50)})


@app.route("/api/evals/run", methods=["POST"])
def api_run_eval():
    body = request.get_json(silent=True) or {}
    suite = body.get("suite", "smoke")
    api_key = body.get("api_key") or DEFAULT_API_KEY
    if suite not in evals_module.SUITES:
        return jsonify({"error": f"unknown suite '{suite}'"}), 400
    if not api_key:
        return jsonify({"error": "api_key required"}), 400
    return Response(_stream_evals(suite, api_key), mimetype="text/event-stream")


# ---------- export ----------

@app.route("/api/export/html", methods=["POST"])
def api_export_html():
    body = request.get_json(silent=True) or {}
    final = body.get("final")
    scenario = body.get("scenario")
    if not isinstance(final, dict) or "answers" not in final:
        # Try loading from a scenario id
        sid = body.get("scenario_id")
        if sid:
            s = storage.get_scenario(sid)
            if s and s.get("result"):
                final = s["result"]
                scenario = s
        if not isinstance(final, dict) or "answers" not in final:
            return jsonify({"error": "final result with 'answers' required"}), 400
    html_doc = exporter_module.render_html(final, scenario=scenario)
    return Response(
        html_doc,
        mimetype="text/html",
        headers={"Content-Disposition": "attachment; filename=rfp-response.html"},
    )


# ---------- dev mode ----------

@app.route("/api/dev/prompts")
def api_dev_prompts():
    return jsonify({
        "system_prompt": SYSTEM_PROMPT,
        "review_prompt_template": REVIEW_PROMPT_TMPL,
        "kb_full": [
            {"id": k, **v} for k, v in KNOWLEDGE_BASE.items()
        ],
    })


@app.route("/api/dev/log")
def api_dev_log():
    limit = int(request.args.get("limit", 100))
    return jsonify({"entries": storage.list_request_log(limit=limit)})


@app.route("/api/dev/log/clear", methods=["POST"])
def api_dev_log_clear():
    storage.clear_request_log()
    return jsonify({"ok": True})


# ============================================================
# Streaming helpers
# ============================================================

def _stream_pipeline(raw: str, api_key: str, rfp_name: str, scenario_id: str | None,
                     parallel: bool = True, scenario: dict | None = None):
    q: queue.Queue = queue.Queue()
    sentinel = object()

    def producer():
        try:
            if parallel:
                final = run_pipeline_parallel(
                    raw, api_key,
                    on_event=lambda evt: q.put(evt),
                    rfp_name=rfp_name,
                    scenario=scenario,
                    parallelism=4,
                )
            else:
                final = run_pipeline(raw, api_key, on_event=lambda evt: q.put(evt), rfp_name=rfp_name)
            if scenario_id:
                storage.attach_result(scenario_id, final)
                q.put({"type": "scenario_updated", "scenario_id": scenario_id})
        except Exception as e:
            q.put({"type": "error", "error": str(e)[:500]})
        finally:
            q.put(sentinel)

    t = threading.Thread(target=producer, daemon=True)
    t.start()

    yield f"data: {json.dumps({'type': 'pipeline_start', 'rfp_name': rfp_name, 'scenario_id': scenario_id, 'parallel': parallel})}\n\n"
    while True:
        evt = q.get()
        if evt is sentinel:
            break
        yield f"data: {json.dumps(evt)}\n\n"


def _stream_evals(suite: str, api_key: str):
    q: queue.Queue = queue.Queue()
    sentinel = object()

    def producer():
        try:
            client = anthropic.Anthropic(api_key=api_key)
            runner = evals_module.SUITES[suite]
            result = runner(client, on_progress=lambda evt: q.put(evt))
            storage.append_eval_run(result)
            q.put({"type": "eval_complete", "result": result})
        except Exception as e:
            q.put({"type": "error", "error": str(e)[:500]})
        finally:
            q.put(sentinel)

    t = threading.Thread(target=producer, daemon=True)
    t.start()

    yield f"data: {json.dumps({'type': 'eval_start', 'suite': suite})}\n\n"
    while True:
        evt = q.get()
        if evt is sentinel:
            break
        yield f"data: {json.dumps(evt)}\n\n"


def _autoseed_if_empty() -> None:
    """If the scenario store is empty, seed it with 50 samples."""
    if not storage.list_scenarios():
        result = seed_scenarios.seed()
        print(f"📂 Seeded {result['saved']} sample scenarios.")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5005"))
    print(f"\n🛡️  Helios RFP Agent Platform on http://localhost:{port}")
    if not DEFAULT_API_KEY:
        print("⚠️  ANTHROPIC_API_KEY not set in env — users must paste a key in the UI.")
    _autoseed_if_empty()
    print()
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
