"""Tests for Stage 3: draft_answer (mocked LLM)."""

import json

from agent_core import draft_answer, _extract_json


# -------- _extract_json helper --------

def test_extract_raw_json():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_code_fences():
    text = '```json\n{"a": 1}\n```'
    assert _extract_json(text) == {"a": 1}


def test_extract_json_with_plain_fences():
    text = '```\n{"a": 1}\n```'
    assert _extract_json(text) == {"a": 1}


def test_extract_json_embedded_in_prose():
    text = 'Here is the answer:\n{"a": 1, "b": "test"}\nThanks!'
    assert _extract_json(text) == {"a": 1, "b": "test"}


# ============================================================
# JSON repair (FR — handle LLM raw newlines inside string values)
# ============================================================

def test_extract_json_with_raw_newlines_inside_string():
    """Opus often returns long string values with literal line breaks
    instead of the required \\n escape. Parser must tolerate this."""
    text = '{"why_helios": "Paragraph one.\nParagraph two.\nParagraph three."}'
    result = _extract_json(text)
    assert result == {"why_helios": "Paragraph one.\nParagraph two.\nParagraph three."}


def test_extract_json_with_raw_newlines_and_other_fields():
    text = '{"a": "line1\nline2", "b": 42, "c": "x"}'
    result = _extract_json(text)
    assert result["a"] == "line1\nline2"
    assert result["b"] == 42


def test_extract_json_with_raw_tab_and_cr():
    text = '{"x": "tabbed\there\rand"}'
    result = _extract_json(text)
    assert result["x"] == "tabbed\there\rand"


def test_extract_json_fenced_with_raw_newlines():
    """Combination: code-fenced JSON whose strings contain raw newlines."""
    text = '```json\n{"narrative": "A.\nB.\nC."}\n```'
    result = _extract_json(text)
    assert result == {"narrative": "A.\nB.\nC."}


def test_extract_json_does_not_alter_already_escaped_strings():
    """Already-valid JSON with explicit \\n escapes must round-trip unchanged."""
    text = '{"x": "line1\\nline2"}'
    result = _extract_json(text)
    assert result["x"] == "line1\nline2"


def test_extract_json_preserves_newlines_outside_strings():
    """Repair only touches newlines INSIDE string values."""
    text = '{\n  "a": 1,\n  "b": 2\n}'
    result = _extract_json(text)
    assert result == {"a": 1, "b": 2}


def test_extract_json_handles_escaped_quote_inside_string():
    """String containing an escaped quote must not confuse the in-string tracker."""
    text = '{"q": "She said \\"hi\\".\nThen left."}'
    result = _extract_json(text)
    assert result["q"] == 'She said "hi".\nThen left.'


def test_repair_function_directly():
    from agent_core import _repair_json_strings
    assert _repair_json_strings('{"a": "x\ny"}') == '{"a": "x\\ny"}'
    # Raw newlines OUTSIDE strings are untouched
    assert _repair_json_strings('{\n  "a": "x"\n}') == '{\n  "a": "x"\n}'


# -------- draft_answer (mocked) --------

def test_draft_simple_answer_no_tool(mock_anthropic_client, make_text_response):
    """Agent returns a JSON answer immediately (end_turn, no tool call).
    Disable specialist routing so the result equals the raw payload."""
    payload = {
        "question_id": "Q1",
        "category": "technical",
        "answer": "Mocked answer",
        "sources": ["Mock Source"],
        "confidence": "high",
        "flags": [],
    }
    mock_anthropic_client.messages.create.return_value = make_text_response(json.dumps(payload))

    result = draft_answer(mock_anthropic_client, "Q1", "What is X?", "technical", use_specialists=False)
    assert result == payload


def test_draft_uses_tool_then_answers(mock_anthropic_client, make_text_response, make_tool_use_response):
    """Agent calls search_kb once, gets result, then returns answer."""
    answer = {
        "question_id": "Q1",
        "category": "technical",
        "answer": "Final answer",
        "sources": ["S"],
        "confidence": "high",
        "flags": [],
    }
    # First call: tool_use; second call: end_turn with text
    mock_anthropic_client.messages.create.side_effect = [
        make_tool_use_response("search_kb", {"query": "threat detection", "category": "technical"}),
        make_text_response(json.dumps(answer)),
    ]
    result = draft_answer(mock_anthropic_client, "Q1", "What is X?", "technical", use_specialists=False)
    assert result == answer
    # Two API calls happened
    assert mock_anthropic_client.messages.create.call_count == 2


def test_draft_emits_events(mock_anthropic_client, make_text_response, make_tool_use_response):
    """on_event is invoked for tool_call, tool_result, and answer_complete."""
    answer = {"question_id": "Q1", "answer": "Done", "sources": ["s"], "confidence": "high", "flags": []}
    mock_anthropic_client.messages.create.side_effect = [
        make_tool_use_response("search_kb", {"query": "test"}),
        make_text_response(json.dumps(answer)),
    ]

    events = []
    draft_answer(mock_anthropic_client, "Q1", "Q?", "technical", on_event=lambda e: events.append(e))

    types = [e["type"] for e in events]
    assert "tool_call" in types
    assert "tool_result" in types
    assert "answer_complete" in types


def test_draft_max_turns_protection(mock_anthropic_client, make_tool_use_response):
    """Agent returns max_turns_exceeded if it loops without ending."""
    # Always return tool_use → never end_turn
    mock_anthropic_client.messages.create.return_value = make_tool_use_response(
        "search_kb", {"query": "loop"}
    )
    result = draft_answer(mock_anthropic_client, "Q1", "Q?", "technical", max_turns=3, use_specialists=False)
    assert result["confidence"] == "low"
    assert "max_turns_exceeded" in result["flags"]
    assert mock_anthropic_client.messages.create.call_count == 3


def test_draft_handles_unparseable_json(mock_anthropic_client, make_text_response):
    """If LLM returns text that isn't JSON, draft returns a fallback object."""
    mock_anthropic_client.messages.create.return_value = make_text_response("This is not JSON.")
    result = draft_answer(mock_anthropic_client, "Q1", "Q?", "technical")
    assert result["question_id"] == "Q1"
    assert result["category"] == "technical"
    assert result["confidence"] == "low"
    assert "JSON parse failed" in result["flags"]


def test_draft_unknown_tool_does_not_crash(mock_anthropic_client, make_text_response, make_tool_use_response):
    """If LLM calls an unregistered tool, we return an error message and continue."""
    answer = {"question_id": "Q1", "answer": "ok", "sources": [], "confidence": "low", "flags": []}
    mock_anthropic_client.messages.create.side_effect = [
        make_tool_use_response("nonexistent_tool", {"foo": "bar"}),
        make_text_response(json.dumps(answer)),
    ]
    result = draft_answer(mock_anthropic_client, "Q1", "Q?", "technical", use_specialists=False)
    assert result == answer
