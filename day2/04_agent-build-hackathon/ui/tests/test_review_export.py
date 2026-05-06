"""Tests for Stage 4 (review) and Stage 5 (export)."""

import json

from agent_core import export, review_answers


# -------- review (mocked) --------

def test_review_parses_clean_json(mock_anthropic_client, make_text_response):
    payload = {"issues": [], "consistency_score": "high", "recommendations": []}
    mock_anthropic_client.messages.create.return_value = make_text_response(json.dumps(payload))
    result = review_answers(mock_anthropic_client, [{"question_id": "Q1"}])
    assert result == payload


def test_review_parses_fenced_json(mock_anthropic_client, make_text_response):
    payload = {"issues": ["x"], "consistency_score": "medium", "recommendations": ["fix x"]}
    fenced = f"```json\n{json.dumps(payload)}\n```"
    mock_anthropic_client.messages.create.return_value = make_text_response(fenced)
    result = review_answers(mock_anthropic_client, [])
    assert result == payload


def test_review_handles_malformed_response(mock_anthropic_client, make_text_response):
    """If LLM returns unparseable text, review returns a fallback dict."""
    mock_anthropic_client.messages.create.return_value = make_text_response("Not JSON at all.")
    result = review_answers(mock_anthropic_client, [])
    assert "parse_error" in result
    assert result["consistency_score"] == "unknown"
    assert result["issues"] == []
    assert result["recommendations"] == []


def test_review_extracts_embedded_json(mock_anthropic_client, make_text_response):
    """Reviewer prose with JSON in the middle should still parse."""
    payload = {"issues": [], "consistency_score": "high", "recommendations": []}
    text = f"Here's my analysis:\n\n{json.dumps(payload)}\n\nLet me know if you want more."
    mock_anthropic_client.messages.create.return_value = make_text_response(text)
    result = review_answers(mock_anthropic_client, [])
    assert result == payload


# -------- export --------

def test_export_structure():
    out = export(
        rfp_name="Test RFP",
        questions=[{"id": "Q1"}],
        answers=[{"question_id": "Q1"}],
        review={"consistency_score": "high"},
        model="claude-opus-4-7",
    )
    assert out["rfp_name"] == "Test RFP"
    assert out["total_questions"] == 1
    assert out["answers"] == [{"question_id": "Q1"}]
    assert out["review"]["consistency_score"] == "high"
    assert out["metadata"]["model"] == "claude-opus-4-7"
    assert "knowledge_base_entries" in out["metadata"]
    assert "generated_at" in out["metadata"]


def test_export_total_questions_matches_input():
    out = export("R", [{"id": f"Q{i}"} for i in range(7)], [], {}, "m")
    assert out["total_questions"] == 7


def test_export_is_json_serializable():
    out = export("R", [{"id": "Q1"}], [{"question_id": "Q1"}], {"consistency_score": "high"}, "m")
    # Round-trips without raising
    s = json.dumps(out)
    assert json.loads(s) == out
