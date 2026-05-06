"""Tests for the eval framework."""

import json
from unittest.mock import patch

import pytest

import evals as evals_module


def test_normalize_handles_per_vs_slash():
    assert evals_module._normalize("$18/seat/month") == evals_module._normalize("$18 per seat per month")


def test_assert_contains_any_passes_with_alternative():
    text = "Latency is 2.3 seconds for signature matches."
    assert evals_module.assert_contains_any(text, ["2.3 second", "2.3s", "2.3-second"])


def test_assert_contains_any_fails_when_none_present():
    text = "Hello world"
    assert not evals_module.assert_contains_any(text, ["foo", "bar"])


def test_assert_contains_any_handles_phrasing_variations():
    text = "$18 per seat per month"
    assert evals_module.assert_contains_any(text, ["$18/seat/month"])


def test_suites_registry_has_all_four():
    assert set(evals_module.SUITES.keys()) == {"smoke", "factual", "edge", "full"}


# Mocked end-to-end suite tests
def test_run_smoke_with_mocks(mock_anthropic_client, make_text_response):
    mock_anthropic_client.messages.create.return_value = make_text_response(json.dumps({
        "question_id": "Q1", "category": "technical",
        "answer": "Latency is 2.3 seconds.",
        "sources": ["Helios Doc"], "confidence": "high", "flags": [],
    }))
    result = evals_module.run_smoke(mock_anthropic_client)
    assert result["suite"] == "smoke"
    assert result["total"] == 4  # 4 structural assertions
    assert result["passed"] == 4
    assert result["failed"] == 0


def test_run_factual_with_mocks(mock_anthropic_client, make_text_response):
    """Each question gets a stub answer that includes the expected facts."""
    fact_text = (
        "Latency is 2.3 seconds for signatures and 18 seconds for behavioral. "
        "SOC 2 audited December 2024. "
        "$18/seat/month for 500 endpoints, minimum 12 month contract. "
        "47 customers in financial services. "
        "AES-256-GCM at rest, TLS 1.3 in transit."
    )

    def _resp_for(args, **kwargs):
        return make_text_response(json.dumps({
            "question_id": "Q?", "category": "technical",
            "answer": fact_text, "sources": ["Doc"], "confidence": "high", "flags": [],
        }))
    mock_anthropic_client.messages.create.side_effect = lambda **kw: _resp_for(kw)

    result = evals_module.run_factual(mock_anthropic_client)
    # 5 questions × 2 structural + variable factual = at least 10 passes
    assert result["suite"] == "factual"
    assert result["passed"] >= 10
    assert result["failed"] == 0


def test_run_edge_with_mocks(mock_anthropic_client, make_text_response):
    """Edge cases need: low/medium confidence + flags (or correct extraction for typos)."""
    responses = [
        # E_OOS: low confidence + flags
        make_text_response(json.dumps({
            "question_id": "E_OOS", "category": "technical",
            "answer": "Out of scope.", "sources": [],
            "confidence": "low", "flags": ["out_of_scope"],
        })),
        # E_AMBIG: medium confidence + flags
        make_text_response(json.dumps({
            "question_id": "E_AMBIG", "category": "company-info",
            "answer": "Please clarify.", "sources": [],
            "confidence": "medium", "flags": ["ambiguous"],
        })),
        # E_TYPOS: high confidence with $18 in answer
        make_text_response(json.dumps({
            "question_id": "E_TYPOS", "category": "pricing",
            "answer": "$18 per seat per month for 500 endpoints.", "sources": ["Pricing"],
            "confidence": "high", "flags": [],
        })),
    ]
    mock_anthropic_client.messages.create.side_effect = responses
    result = evals_module.run_edge_cases(mock_anthropic_client)
    assert result["passed"] == 3
    assert result["failed"] == 0


def test_summary_pass_rate_calculation():
    summary = evals_module._summarize("test", [
        {"test": "a", "passed": True, "detail": "", "qid": "Q1"},
        {"test": "b", "passed": True, "detail": "", "qid": "Q1"},
        {"test": "c", "passed": False, "detail": "fail", "qid": "Q2"},
    ], 1.0)
    assert summary["total"] == 3
    assert summary["passed"] == 2
    assert summary["failed"] == 1
    assert summary["pass_rate"] == 66.7
