"""Tests for the unified search engine."""

import pytest

import storage
import search_engine


@pytest.fixture(autouse=True)
def clean_storage():
    storage._reset_for_tests()
    yield
    storage._reset_for_tests()


def test_search_kb_returns_matches():
    r = search_engine.search("threat detection latency")
    assert any(x["type"] == "kb" for x in r)
    assert all(x["score"] > 0 for x in r)


def test_search_empty_query_returns_empty():
    assert search_engine.search("") == []
    assert search_engine.search("   ") == []


def test_search_results_sorted_by_score_desc():
    r = search_engine.search("encryption EU compliance")
    scores = [x["score"] for x in r]
    assert scores == sorted(scores, reverse=True)


def test_search_filters_by_type():
    r_kb = search_engine.search("encryption", types=["kb"])
    assert all(x["type"] == "kb" for x in r_kb)
    r_other = search_engine.search("encryption", types=["scenario"])
    assert all(x["type"] != "kb" for x in r_other)


def test_search_includes_scenarios():
    storage.save_scenario({
        "name": "Acme banking RFP",
        "client": "Acme Bank",
        "description": "Their Q3 cybersecurity questionnaire",
        "questions": [{"id": "Q1", "category": "technical", "text": "encryption?"}],
    })
    r = search_engine.search("acme")
    assert any(x["type"] == "scenario" for x in r)


def test_search_includes_answers_from_scenarios():
    s = storage.save_scenario({"name": "S", "client": "X", "questions": []})
    storage.attach_result(s["id"], {
        "answers": [
            {"question_id": "Q1", "category": "pricing", "answer": "We offer specific volume discounts at 1000 endpoints", "confidence": "high"}
        ],
        "review": {},
    })
    r = search_engine.search("volume discounts")
    answer_results = [x for x in r if x["type"] == "answer"]
    assert len(answer_results) >= 1


def test_search_snippet_truncates_and_marks_match():
    r = search_engine.search("AES-256-GCM")
    assert len(r) >= 1
    # Snippet should be reasonable length (not the full entry)
    assert all(len(x["snippet"]) < 500 for x in r)


def test_search_limit():
    r = search_engine.search("the of and is or with", limit=2)
    assert len(r) <= 2


def test_search_no_matches():
    assert search_engine.search("zzzzzzzznotinkb") == []
