"""Tests for Reviewer + Demoer specialists and the parallel pipeline."""

import json
from unittest.mock import patch

import pytest

from agent_core import (
    review_quality,
    generate_demo_script,
    run_pipeline_parallel,
)


# ---------- Reviewer ----------

def test_reviewer_parses_clean_json(mock_anthropic_client, make_text_response):
    payload = {
        "scores": {"accuracy": 9, "completeness": 8, "cite_quality": 9, "tone_consistency": 9},
        "overall": 8.75,
        "verdict": "ship",
        "summary": "Strong response.",
        "top_issues": [],
        "strengths": ["Clear pricing tier explanation"],
    }
    mock_anthropic_client.messages.create.return_value = make_text_response(json.dumps(payload))
    result = review_quality(mock_anthropic_client, [{"question_id": "Q1"}])
    assert result["verdict"] == "ship"
    assert result["scores"]["accuracy"] == 9


def test_reviewer_computes_overall_when_missing(mock_anthropic_client, make_text_response):
    payload = {
        "scores": {"accuracy": 8, "completeness": 8, "cite_quality": 8, "tone_consistency": 8},
        "verdict": "ship",
        "summary": "ok",
        "top_issues": [],
        "strengths": [],
    }
    mock_anthropic_client.messages.create.return_value = make_text_response(json.dumps(payload))
    result = review_quality(mock_anthropic_client, [{"question_id": "Q1"}])
    assert result["overall"] == 8.0


def test_reviewer_handles_malformed_response(mock_anthropic_client, make_text_response):
    mock_anthropic_client.messages.create.return_value = make_text_response("Not JSON.")
    result = review_quality(mock_anthropic_client, [])
    assert result["verdict"] == "unknown"
    assert "parse_error" in result


# ---------- Demoer ----------

def test_demoer_returns_presenter_script(mock_anthropic_client, make_text_response):
    payload = {
        "elevator_pitch": "Helios Sentinel detects threats in under 3 seconds.",
        "top_talking_points": ["Sub-3s detection", "FedRAMP authorized", "47 fin-svcs customers"],
        "key_differentiators": ["Built-in correlation engine", "EU residency on day one"],
        "likely_followups": [
            {"question": "How does your SIEM compare to Splunk?", "answer_hint": "We bundle correlation; SIEM is a paid add-on."},
        ],
        "call_to_action": "Schedule a 90-minute technical deep-dive.",
    }
    mock_anthropic_client.messages.create.return_value = make_text_response(json.dumps(payload))
    result = generate_demo_script(mock_anthropic_client, [{"question_id": "Q1"}])
    assert "elevator_pitch" in result
    assert len(result["top_talking_points"]) == 3


def test_demoer_uses_scenario_context(mock_anthropic_client, make_text_response):
    payload = {
        "elevator_pitch": "x", "top_talking_points": [],
        "key_differentiators": [], "likely_followups": [],
        "call_to_action": "x",
    }
    mock_anthropic_client.messages.create.return_value = make_text_response(json.dumps(payload))

    generate_demo_script(
        mock_anthropic_client,
        [{"question_id": "Q1"}],
        scenario={"client": "Acme Bank", "description": "Tier-1 retail bank"},
    )
    # Verify the prompt sent to the LLM included the scenario blurb
    args, kwargs = mock_anthropic_client.messages.create.call_args
    user_msg = kwargs["messages"][0]["content"]
    assert "Acme Bank" in user_msg
    assert "Tier-1 retail bank" in user_msg


def test_demoer_handles_malformed(mock_anthropic_client, make_text_response):
    mock_anthropic_client.messages.create.return_value = make_text_response("not json")
    result = generate_demo_script(mock_anthropic_client, [])
    assert result["elevator_pitch"] == ""
    assert "parse_error" in result


# ---------- Parallel pipeline ----------

def test_parallel_pipeline_runs_all_stages(mock_anthropic_client, make_text_response):
    """Run pipeline_parallel end-to-end with mocks; verify all 6 stages fire."""
    answer_template = {
        "answer": "Mocked", "sources": ["Mock Source"],
        "confidence": "high", "flags": [],
    }
    review_payload = {"issues": [], "consistency_score": "high", "recommendations": []}
    qa_payload = {
        "scores": {"accuracy": 9, "completeness": 9, "cite_quality": 9, "tone_consistency": 9},
        "overall": 9, "verdict": "ship", "summary": "ok",
        "top_issues": [], "strengths": [],
    }
    demo_payload = {
        "elevator_pitch": "x", "top_talking_points": ["a", "b", "c"],
        "key_differentiators": ["x"], "likely_followups": [],
        "call_to_action": "y",
    }

    # Order is fragile under parallelism — use side_effect as a queue
    # but make it order-tolerant by always returning the right shape based on input.
    responses = []
    # 2 questions × 1 LLM call each (no tool use) = 2 draft responses
    for qid in ["Q1", "Q2"]:
        responses.append(make_text_response(json.dumps({**answer_template, "question_id": qid, "category": "technical"})))
    # Then review + qa + demo
    responses.extend([
        make_text_response(json.dumps(review_payload)),
        make_text_response(json.dumps(qa_payload)),
        make_text_response(json.dumps(demo_payload)),
    ])
    mock_anthropic_client.messages.create.side_effect = responses

    with patch("agent_core.anthropic.Anthropic", return_value=mock_anthropic_client):
        events = []
        result = run_pipeline_parallel(
            "Question one?\n\nQuestion two?",
            api_key="fake-key",
            on_event=lambda e: events.append(e),
            parallelism=1,  # Sequential for deterministic mock order
        )

    types = [e["type"] for e in events]
    # Every stage_start
    expected_stages = {"parse", "retrieve_draft", "review", "qa_review", "demo", "export"}
    started = {e["stage"] for e in events if e["type"] == "stage_start"}
    assert expected_stages <= started, f"Missing: {expected_stages - started}"

    # Final result includes qa_review and demo_script
    assert "qa_review" in result
    assert "demo_script" in result
    assert result["qa_review"]["verdict"] == "ship"


def test_parallel_pipeline_can_skip_qa_and_demo(mock_anthropic_client, make_text_response):
    """include_qa=False and include_demo=False should skip those stages."""
    responses = [
        make_text_response(json.dumps({"question_id": "Q1", "category": "technical",
                                       "answer": "x", "sources": ["s"], "confidence": "high", "flags": []})),
        make_text_response(json.dumps({"issues": [], "consistency_score": "high", "recommendations": []})),
    ]
    mock_anthropic_client.messages.create.side_effect = responses

    with patch("agent_core.anthropic.Anthropic", return_value=mock_anthropic_client):
        events = []
        result = run_pipeline_parallel(
            "Q?", api_key="fake-key",
            on_event=lambda e: events.append(e),
            parallelism=1,
            include_qa=False,
            include_demo=False,
        )

    started = {e["stage"] for e in events if e["type"] == "stage_start"}
    assert "qa_review" not in started
    assert "demo" not in started
    assert "qa_review" not in result
    assert "demo_script" not in result
