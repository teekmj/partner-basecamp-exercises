"""Eval framework runnable from the UI.

Suites:
  - smoke    : 1 question, structural checks only (fast)
  - factual  : 5 sample questions, check expected data points
  - edge     : 3 deliberately problematic questions
  - full     : 5 sample questions, check facts + consistency review

Each suite returns a list of assertions: {test, passed, detail}.
"""

from __future__ import annotations

import re
import time
from typing import Iterable

import anthropic

from agent_core import draft_answer, review_answers


# ============================================================
# Reusable assertion primitives
# ============================================================

def _normalize(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*/\s*", " per ", text)
    text = re.sub(r"\s*per\s+", " per ", text)
    return text


def assert_contains_any(text: str, options: list[str]) -> bool:
    norm = _normalize(text)
    return any(_normalize(o) in norm for o in options)


# ============================================================
# Suite definitions
# ============================================================

SAMPLE_RFP = [
    {"id": "Q1", "category": "technical", "text": "Describe your platform's approach to real-time threat detection. What data sources are ingested, and what is the average detection-to-alert latency?"},
    {"id": "Q2", "category": "compliance", "text": "List all compliance certifications your organization currently holds (SOC 2, ISO 27001, FedRAMP, etc.) and the date of most recent audit for each."},
    {"id": "Q3", "category": "pricing", "text": "Provide per-seat pricing for 500, 1,000, and 5,000 endpoints. Are volume discounts available? Is there a minimum contract term?"},
    {"id": "Q4", "category": "company-info", "text": "How many customers do you currently serve in the financial services vertical? Provide 2–3 reference accounts."},
    {"id": "Q5", "category": "technical", "text": "How does your platform handle data residency requirements for customers operating in the EU? Describe encryption at rest and in transit."},
]


EXPECTED_FACTS = {
    "Q1": [["2.3 second", "2.3s"], ["18 second", "18s"]],
    "Q2": [["december 2024"]],
    "Q3": [["$18"], ["12 month"]],
    "Q4": [["47 customer"]],
    "Q5": [["aes-256-gcm"], ["tls 1.3"]],
}


EDGE_CASES = [
    {
        "qid": "E_OOS",
        "category": "technical",
        "text": "What is the airspeed velocity of an unladen swallow?",
        "validate": lambda a: a.get("confidence") in ("low", "medium") and len(a.get("flags", [])) > 0,
        "description": "Out-of-scope question handled with low confidence + flags",
    },
    {
        "qid": "E_AMBIG",
        "category": "company-info",
        "text": "Tell us about your stuff.",
        "validate": lambda a: bool(a.get("answer")) and a.get("confidence") in ("low", "medium"),
        "description": "Ambiguous question handled gracefully",
    },
    {
        "qid": "E_TYPOS",
        "category": "pricing",
        "text": "Wat iz ur pricng for 500 endpointes?",
        "validate": lambda a: "$18" in (a.get("answer") or "") and a.get("confidence") in ("high", "medium"),
        "description": "Typo'd question still resolves to correct pricing",
    },
]


# ============================================================
# Suite runners
# ============================================================

def _record(results: list[dict], test: str, passed: bool, detail: str = "", qid: str = "") -> None:
    results.append({"test": test, "passed": passed, "detail": detail, "qid": qid})


def run_smoke(client: anthropic.Anthropic, on_progress=None) -> dict:
    """Quick: 1 question, structural-only checks."""
    results: list[dict] = []
    t0 = time.time()
    if on_progress:
        on_progress({"type": "step", "message": "Drafting Q1 (smoke)…"})
    ans = draft_answer(client, "Q1", SAMPLE_RFP[0]["text"], "technical")

    _record(results, "structure_question_id", ans.get("question_id") == "Q1", qid="Q1")
    _record(results, "structure_has_answer", bool(ans.get("answer")), qid="Q1")
    _record(results, "structure_has_sources", isinstance(ans.get("sources"), list) and len(ans["sources"]) >= 1, qid="Q1")
    _record(results, "structure_valid_confidence", ans.get("confidence") in {"high", "medium", "low"}, qid="Q1")

    return _summarize("smoke", results, time.time() - t0)


def run_factual(client: anthropic.Anthropic, on_progress=None) -> dict:
    """Run all 5 questions, assert expected facts present in answers."""
    results: list[dict] = []
    t0 = time.time()
    answers_by_id: dict[str, dict] = {}

    for q in SAMPLE_RFP:
        if on_progress:
            on_progress({"type": "step", "message": f"Drafting {q['id']}…"})
        ans = draft_answer(client, q["id"], q["text"], q["category"])
        answers_by_id[q["id"]] = ans

        # Structural
        _record(results, "valid_confidence", ans.get("confidence") in {"high", "medium", "low"}, qid=q["id"])
        _record(results, "has_sources", isinstance(ans.get("sources"), list) and len(ans["sources"]) >= 1, qid=q["id"])

        # Factual
        text = ans.get("answer", "")
        for group in EXPECTED_FACTS.get(q["id"], []):
            label = f"fact_{group[0][:30].replace(' ', '_')}"
            passed = assert_contains_any(text, group)
            _record(results, label, passed, detail=f"options={group}", qid=q["id"])

    return _summarize("factual", results, time.time() - t0)


def run_edge_cases(client: anthropic.Anthropic, on_progress=None) -> dict:
    """Run 3 deliberately problematic questions; check graceful handling."""
    results: list[dict] = []
    t0 = time.time()

    for ec in EDGE_CASES:
        if on_progress:
            on_progress({"type": "step", "message": f"Edge case: {ec['qid']}…"})
        ans = draft_answer(client, ec["qid"], ec["text"], ec["category"])
        passed = ec["validate"](ans)
        _record(
            results,
            ec["qid"].lower(),
            passed,
            detail=f"confidence={ans.get('confidence')} flags={len(ans.get('flags', []))}",
            qid=ec["qid"],
        )

    return _summarize("edge", results, time.time() - t0)


def run_full(client: anthropic.Anthropic, on_progress=None) -> dict:
    """Full suite: factual + consistency review check."""
    results: list[dict] = []
    t0 = time.time()
    answers: list[dict] = []

    for q in SAMPLE_RFP:
        if on_progress:
            on_progress({"type": "step", "message": f"Drafting {q['id']}…"})
        ans = draft_answer(client, q["id"], q["text"], q["category"])
        answers.append(ans)

        _record(results, "valid_confidence", ans.get("confidence") in {"high", "medium", "low"}, qid=q["id"])
        _record(results, "has_sources", isinstance(ans.get("sources"), list) and len(ans["sources"]) >= 1, qid=q["id"])
        text = ans.get("answer", "")
        for group in EXPECTED_FACTS.get(q["id"], []):
            label = f"fact_{group[0][:30].replace(' ', '_')}"
            _record(results, label, assert_contains_any(text, group), detail=f"options={group}", qid=q["id"])

    # Review
    if on_progress:
        on_progress({"type": "step", "message": "Running consistency review…"})
    review = review_answers(client, answers)
    _record(results, "review_parseable", "parse_error" not in review, qid="review")
    _record(results, "consistency_high", review.get("consistency_score") == "high", detail=f"score={review.get('consistency_score')}", qid="review")

    return _summarize("full", results, time.time() - t0)


def _summarize(suite: str, results: list[dict], elapsed: float) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    return {
        "suite": suite,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total * 100, 1) if total else 0,
        "elapsed_s": round(elapsed, 1),
        "assertions": results,
    }


SUITES = {
    "smoke": run_smoke,
    "factual": run_factual,
    "edge": run_edge_cases,
    "full": run_full,
}
