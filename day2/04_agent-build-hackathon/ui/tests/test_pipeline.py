"""Integration tests for the full pipeline (mocked LLM)."""

import json
from unittest.mock import patch

from agent_core import run_pipeline


def test_pipeline_emits_all_stages(mock_anthropic_client, make_text_response):
    """Run pipeline end-to-end with mocks; verify event sequence."""
    # Each draft_answer call returns one tool_use then end_turn — but we'll
    # cheat and have each question return immediately (no tool call) by
    # making the very first response be end_turn with JSON.
    answer_template = {
        "answer": "Mocked",
        "sources": ["Mock Source"],
        "confidence": "high",
        "flags": [],
    }
    review_payload = {"issues": [], "consistency_score": "high", "recommendations": []}

    # Build a list of responses: 1 per question + 1 review
    responses = []
    for qid in ["Q1", "Q2"]:
        responses.append(make_text_response(json.dumps({**answer_template, "question_id": qid, "category": "technical"})))
    responses.append(make_text_response(json.dumps(review_payload)))

    mock_anthropic_client.messages.create.side_effect = responses

    with patch("agent_core.anthropic.Anthropic", return_value=mock_anthropic_client):
        events = []
        result = run_pipeline(
            "Question one?\n\nQuestion two?",
            api_key="fake-key",
            on_event=lambda e: events.append(e),
        )

    types = [e["type"] for e in events]

    # Stage lifecycle
    assert types.count("stage_start") == 4   # parse, retrieve_draft, review, export
    assert types.count("stage_done") == 4

    # 2 questions started + 2 done
    assert types.count("question_start") == 2
    assert types.count("question_done") == 2

    # Final pipeline event
    assert types[-1] == "pipeline_complete"

    # Result structure
    assert result["total_questions"] == 2
    assert len(result["answers"]) == 2
    assert result["review"]["consistency_score"] == "high"
    assert result["metadata"]["knowledge_base_entries"] >= 1


def test_pipeline_with_tool_use_loop(mock_anthropic_client, make_text_response, make_tool_use_response):
    """Pipeline handles per-question tool_use → tool_result → answer flow."""
    answer = {"question_id": "Q1", "category": "technical", "answer": "ok", "sources": ["S"], "confidence": "high", "flags": []}
    review_payload = {"issues": [], "consistency_score": "high", "recommendations": []}

    mock_anthropic_client.messages.create.side_effect = [
        make_tool_use_response("search_kb", {"query": "test"}),
        make_text_response(json.dumps(answer)),
        make_text_response(json.dumps(review_payload)),
    ]

    with patch("agent_core.anthropic.Anthropic", return_value=mock_anthropic_client):
        events = []
        result = run_pipeline("Q?", api_key="fake-key", on_event=events.append)

    # tool_call + tool_result events fired
    types = [e["type"] for e in events]
    assert "tool_call" in types
    assert "tool_result" in types
    assert result["total_questions"] == 1


def test_pipeline_normalizes_missing_answer_fields(mock_anthropic_client, make_text_response):
    """Even if LLM omits fields, pipeline backfills sensible defaults."""
    # Answer missing 'sources', 'flags'
    bare = {"question_id": "Q1", "answer": "x", "confidence": "high"}
    review = {"issues": [], "consistency_score": "high", "recommendations": []}
    mock_anthropic_client.messages.create.side_effect = [
        make_text_response(json.dumps(bare)),
        make_text_response(json.dumps(review)),
    ]

    with patch("agent_core.anthropic.Anthropic", return_value=mock_anthropic_client):
        result = run_pipeline("Question?", api_key="fake-key")

    a = result["answers"][0]
    assert a["sources"] == []
    assert a["flags"] == []
    assert a["category"] == "technical"  # filled from parse
    assert a["confidence"] == "high"
