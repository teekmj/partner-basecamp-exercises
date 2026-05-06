"""Tests for specialist sub-agents."""

import json
from unittest.mock import patch

import pytest

import specialists
from specialists import (
    SPECIALISTS,
    SPECIALIST_LABELS,
    CATEGORY_ROUTING,
    pick_specialist,
    get_specialist,
    list_specialists,
)
from agent_core import draft_answer


# ---------- Configuration ----------

def test_four_drafting_specialists_defined():
    """All 4 drafting specialists must be present (reviewer/demoer are also OK)."""
    drafting = {"architect", "pricing_lead", "compliance", "business_sme"}
    assert drafting <= set(SPECIALISTS.keys())


def test_each_specialist_has_distinct_prompt():
    prompts = {key: spec.prompt for key, spec in SPECIALISTS.items()}
    # All prompts must be unique
    assert len(set(prompts.values())) == len(prompts)


def test_each_specialist_has_label():
    for key in SPECIALISTS:
        assert key in SPECIALIST_LABELS
        assert SPECIALIST_LABELS[key]


def test_drafting_specialists_have_search_kb_tool():
    """Drafting specialists need the search_kb tool. Post-draft (reviewer/demoer) don't."""
    drafting_keys = {"architect", "pricing_lead", "compliance", "business_sme"}
    for key, spec in SPECIALISTS.items():
        if key in drafting_keys:
            assert spec.tools is not None
            assert "search_kb" in spec.tools, f"{key} should have search_kb"
        else:
            # Post-draft specialists explicitly have no tools
            assert spec.tools == []


def test_each_specialist_uses_opus():
    for spec in SPECIALISTS.values():
        assert spec.model == "claude-opus-4-7"


def test_list_specialists_returns_metadata():
    rows = list_specialists()
    assert len(rows) >= 4
    for row in rows:
        assert {"key", "label", "description", "model", "max_turns", "tools"} <= set(row.keys())


# ---------- Routing ----------

def test_pick_specialist_by_category():
    assert pick_specialist("technical", "anything") == "architect"
    assert pick_specialist("pricing", "anything") == "pricing_lead"
    assert pick_specialist("compliance", "anything") == "compliance"
    assert pick_specialist("company-info", "anything") == "business_sme"


def test_pick_specialist_unknown_category_uses_keywords():
    """For empty category, keyword routing kicks in."""
    assert pick_specialist(None, "What is your SOC 2 status?") == "compliance"
    assert pick_specialist(None, "What is the price per seat?") == "pricing_lead"
    assert pick_specialist(None, "How many customers do you have?") == "business_sme"
    assert pick_specialist(None, "What is your detection latency?") == "architect"


def test_pick_specialist_default_fallback():
    """No category, no keywords → architect (default)."""
    assert pick_specialist(None, "Hello world.") == "architect"
    assert pick_specialist("", "") == "architect"


def test_get_specialist_returns_definition():
    spec = get_specialist("architect")
    assert spec.description.lower().startswith("technical")


def test_get_specialist_unknown_falls_back_to_architect():
    spec = get_specialist("nonexistent_specialist")
    assert spec is SPECIALISTS["architect"]


# ---------- Routing matrix mirrors spec ----------

def test_category_routing_matches_spec():
    assert CATEGORY_ROUTING == {
        "technical": "architect",
        "pricing": "pricing_lead",
        "compliance": "compliance",
        "company-info": "business_sme",
    }


# ---------- Integration with draft_answer ----------

def test_draft_answer_assigns_specialist(mock_anthropic_client, make_text_response):
    """Drafted answer carries specialist_key + specialist_label."""
    payload = {
        "question_id": "Q3", "category": "pricing",
        "answer": "$18/seat/month", "sources": ["Pricing Sheet"],
        "confidence": "high", "flags": [],
    }
    mock_anthropic_client.messages.create.return_value = make_text_response(json.dumps(payload))

    events = []
    result = draft_answer(
        mock_anthropic_client,
        "Q3", "What is the pricing?", "pricing",
        on_event=lambda e: events.append(e),
    )
    assert result["specialist_key"] == "pricing_lead"
    assert result["specialist_label"] == "Pricing Lead"


def test_draft_answer_emits_specialist_assigned_event(mock_anthropic_client, make_text_response):
    payload = {
        "question_id": "Q1", "category": "technical",
        "answer": "x", "sources": ["s"], "confidence": "high", "flags": [],
    }
    mock_anthropic_client.messages.create.return_value = make_text_response(json.dumps(payload))

    events = []
    draft_answer(
        mock_anthropic_client, "Q1", "Latency?", "technical",
        on_event=lambda e: events.append(e),
    )
    types = [e["type"] for e in events]
    assert "specialist_assigned" in types
    spec_evt = next(e for e in events if e["type"] == "specialist_assigned")
    assert spec_evt["specialist_key"] == "architect"
    assert spec_evt["specialist_label"] == "Solutions Architect"
    assert spec_evt["qid"] == "Q1"


def test_draft_answer_use_specialists_false_uses_generic_prompt(mock_anthropic_client, make_text_response):
    """When opted out, no specialist info is attached and no event fires."""
    payload = {
        "question_id": "Q1", "category": "technical",
        "answer": "x", "sources": ["s"], "confidence": "high", "flags": [],
    }
    mock_anthropic_client.messages.create.return_value = make_text_response(json.dumps(payload))

    events = []
    result = draft_answer(
        mock_anthropic_client, "Q1", "?", "technical",
        on_event=lambda e: events.append(e),
        use_specialists=False,
    )
    assert "specialist_key" not in result
    types = [e["type"] for e in events]
    assert "specialist_assigned" not in types


def test_compliance_question_routes_to_compliance_specialist(mock_anthropic_client, make_text_response):
    payload = {
        "question_id": "Q2", "category": "compliance",
        "answer": "SOC 2 audited Dec 2024", "sources": ["Compliance Reg"],
        "confidence": "high", "flags": [],
    }
    mock_anthropic_client.messages.create.return_value = make_text_response(json.dumps(payload))

    result = draft_answer(mock_anthropic_client, "Q2", "Are you SOC 2 certified?", "compliance")
    assert result["specialist_key"] == "compliance"


def test_business_sme_handles_company_info(mock_anthropic_client, make_text_response):
    payload = {
        "question_id": "Q4", "category": "company-info",
        "answer": "47 customers", "sources": ["Vertical Report"],
        "confidence": "high", "flags": [],
    }
    mock_anthropic_client.messages.create.return_value = make_text_response(json.dumps(payload))
    result = draft_answer(mock_anthropic_client, "Q4", "How many customers?", "company-info")
    assert result["specialist_key"] == "business_sme"
    assert result["specialist_label"] == "Customer Success Lead"
