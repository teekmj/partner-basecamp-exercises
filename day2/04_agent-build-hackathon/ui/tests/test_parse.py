"""Tests for Stage 1: parse_questionnaire."""

import json

from agent_core import parse_questionnaire, _infer_category


# -------- Format detection --------

def test_parse_json_input():
    raw = json.dumps([
        {"id": "Q1", "category": "technical", "text": "How fast is detection?"},
        {"id": "Q2", "category": "pricing", "text": "How much per seat?"},
    ])
    qs = parse_questionnaire(raw)
    assert len(qs) == 2
    assert qs[0]["id"] == "Q1"
    assert qs[0]["category"] == "technical"
    assert qs[1]["text"] == "How much per seat?"


def test_parse_blank_separated_text():
    raw = """How fast is your threat detection?

What certifications do you hold?

What is your pricing for 1000 endpoints?"""
    qs = parse_questionnaire(raw)
    assert len(qs) == 3
    assert qs[0]["id"] == "Q1"
    assert qs[1]["id"] == "Q2"
    assert qs[2]["id"] == "Q3"


def test_parse_numbered_list():
    raw = """1. How fast is detection?
2. What certifications?
3. Pricing for 500 endpoints?"""
    qs = parse_questionnaire(raw)
    assert len(qs) == 3
    # Leading "1.", "2." should be stripped
    assert not qs[0]["text"].startswith("1.")


def test_parse_bullet_list():
    raw = """- Detection latency?
- SOC 2 status?"""
    qs = parse_questionnaire(raw)
    assert len(qs) == 2
    assert not qs[0]["text"].startswith("-")


def test_parse_q_prefixed():
    raw = "Q1. Latency?\n\nQ2. Pricing?"
    qs = parse_questionnaire(raw)
    assert len(qs) == 2
    assert not qs[0]["text"].startswith("Q1")


# -------- Edge cases --------

def test_parse_empty_string():
    assert parse_questionnaire("") == []


def test_parse_whitespace_only():
    assert parse_questionnaire("   \n\n   ") == []


def test_parse_none():
    assert parse_questionnaire(None) == []


def test_parse_malformed_json_falls_back():
    # Looks like JSON but isn't valid → should fall through to text mode
    raw = "[not actually json"
    qs = parse_questionnaire(raw)
    # Falls back to text — single line, single question
    assert len(qs) == 1


def test_parse_single_question_no_separator():
    qs = parse_questionnaire("What is your pricing?")
    assert len(qs) == 1
    assert qs[0]["id"] == "Q1"


# -------- Category inference --------

def test_category_technical():
    assert _infer_category("What is the detection latency?") == "technical"


def test_category_compliance():
    assert _infer_category("Do you hold SOC 2 or FedRAMP?") == "compliance"


def test_category_pricing():
    assert _infer_category("What is the price per seat?") == "pricing"


def test_category_company_info():
    assert _infer_category("How many customers do you have? Any references?") == "company-info"


def test_category_default_when_unmatched():
    # Random sentence with no keywords defaults to technical
    assert _infer_category("Lorem ipsum dolor sit amet") == "technical"
