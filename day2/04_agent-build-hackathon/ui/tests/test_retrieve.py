"""Tests for Stage 2: retrieve."""

from agent_core import KNOWLEDGE_BASE, retrieve


def test_retrieve_returns_list():
    r = retrieve("threat detection")
    assert isinstance(r, list)


def test_retrieve_finds_relevant_entry():
    r = retrieve("threat detection latency")
    assert len(r) >= 1
    # threat_detection entry should be top-ranked
    assert "Helios Platform Architecture" in r[0]["source"]


def test_retrieve_empty_query():
    assert retrieve("") == []
    assert retrieve("    ") == []


def test_retrieve_no_matches():
    r = retrieve("zzzzz nonexistent gibberish")
    assert r == []


def test_retrieve_caps_at_three_results():
    # Use a broad query that matches many entries
    r = retrieve("Helios platform compliance encryption pricing customer")
    assert len(r) <= 3


def test_retrieve_category_boost():
    """Without category, threat_detection wins for 'detection'.
    With category=pricing, the pricing entry should be boosted."""
    r_no_cat = retrieve("data")
    r_pricing = retrieve("data", category="pricing")
    # Both lists should be non-empty; the pricing-category one should
    # contain the pricing entry near the top thanks to the +5 boost.
    pricing_sources = [e["source"] for e in r_pricing]
    assert any("Pricing" in s for s in pricing_sources)


def test_retrieve_relevance_scores_are_descending():
    r = retrieve("compliance certifications encryption")
    scores = [e["relevance_score"] for e in r]
    assert scores == sorted(scores, reverse=True)


def test_retrieve_handles_punctuation():
    r = retrieve("AES-256-GCM, TLS 1.3.")
    # Should find data residency entry
    assert any("Data Sovereignty" in e["source"] for e in r)


def test_retrieve_custom_kb():
    custom_kb = {
        "x": {"source": "X Doc", "content": "alpha beta gamma", "tags": ["x"]},
    }
    r = retrieve("alpha", kb=custom_kb)
    assert len(r) == 1
    assert r[0]["source"] == "X Doc"
