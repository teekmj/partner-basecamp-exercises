"""Tests for the enhanced exporter (cover page, QA scorecard, demo notes)."""

import exporter


FULL_FINAL = {
    "rfp_name": "Acme Bank — Q1 2026 Cybersecurity RFP",
    "total_questions": 2,
    "answers": [
        {
            "question_id": "Q1", "category": "technical",
            "answer": "Detection latency is 2.3s for signatures, 18s for behavioral.",
            "sources": ["Helios Doc v4.2"], "confidence": "high", "flags": [],
            "specialist_label": "Solutions Architect",
        },
        {
            "question_id": "Q2", "category": "pricing",
            "answer": "$18/seat/month at 500 endpoints.",
            "sources": ["Pricing Sheet"], "confidence": "high", "flags": [],
            "specialist_label": "Pricing Lead",
        },
    ],
    "review": {
        "consistency_score": "high",
        "issues": [],
        "recommendations": [],
    },
    "qa_review": {
        "scores": {"accuracy": 9, "completeness": 9, "cite_quality": 9, "tone_consistency": 9},
        "overall": 9.0,
        "verdict": "ship",
        "summary": "Strong, specific, well-cited.",
        "top_issues": [],
        "strengths": ["Numerically precise", "Consistent tone"],
    },
    "demo_script": {
        "elevator_pitch": "Helios detects threats in under 3 seconds with sub-$20/seat pricing.",
        "top_talking_points": ["Sub-3s detection", "$18/seat at 500 endpoints", "FedRAMP authorized"],
        "key_differentiators": ["Built-in correlation engine"],
        "likely_followups": [
            {"question": "How do you compare to CrowdStrike?", "answer_hint": "We bundle SIEM correlation; competitors charge extra."},
        ],
        "call_to_action": "Schedule a 90-minute technical workshop.",
    },
    "metadata": {
        "model": "claude-opus-4-7",
        "knowledge_base_entries": 5,
        "generated_at": "2026-05-06T12:00:00Z",
    },
}


def test_renders_complete_html_document():
    html = exporter.render_html(FULL_FINAL)
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html


def test_includes_cover_page_with_client():
    scenario = {"name": "Acme Bank — Q1 RFP", "client": "Acme Bank", "description": "Tier-1 retail bank"}
    html = exporter.render_html(FULL_FINAL, scenario=scenario)
    assert 'class="cover"' in html
    assert "Acme Bank" in html
    assert "Tier-1 retail bank" in html
    assert "Prepared for" in html
    assert "RFP Response · Confidential" in html


def test_includes_qa_scorecard():
    html = exporter.render_html(FULL_FINAL)
    assert "QA Reviewer Scorecard" in html
    assert "Overall: 9.0/10" in html or "Overall: 9/10" in html
    assert "ship" in html.lower()
    assert "accuracy" in html


def test_includes_demo_section():
    """The demo output renders as the AE-internal speaker notes appendix."""
    html = exporter.render_html(FULL_FINAL)
    assert "Account Executive Speaker Notes" in html
    assert "Elevator pitch" in html
    assert "Helios detects threats in under 3 seconds" in html
    assert "Lead with these talking points" in html
    assert "Recommended next step" in html
    assert "technical workshop" in html
    # Section is clearly marked internal (FR-158)
    assert "Internal use only" in html


def test_includes_specialist_chips_on_answers():
    html = exporter.render_html(FULL_FINAL)
    assert "Solutions Architect" in html
    assert "Pricing Lead" in html


def test_renders_without_qa_and_demo_gracefully():
    minimal = {**FULL_FINAL}
    del minimal["qa_review"]
    del minimal["demo_script"]
    html = exporter.render_html(minimal)
    assert "<!DOCTYPE html>" in html
    # Sections that depend on optional data should be absent
    assert "QA Reviewer Scorecard" not in html
    assert "Account Executive Speaker Notes" not in html
    assert "Why Helios" not in html


def test_print_button_present():
    html = exporter.render_html(FULL_FINAL)
    assert "Print / Save as PDF" in html
    assert "@media print" in html


def test_executive_summary_includes_qa_verdict():
    html = exporter.render_html(FULL_FINAL)
    # Summary table mentions QA verdict
    assert "QA verdict" in html
    assert "ship" in html.lower()


def test_each_section_starts_on_new_page():
    html = exporter.render_html(FULL_FINAL)
    # Every <h2> after the first has page-break-before
    assert "page-break-before" in html


def test_xss_safe():
    """User-supplied content (answer text, scenario name) must be HTML-escaped."""
    final = {
        **FULL_FINAL,
        "answers": [{
            "question_id": "Q1", "category": "technical",
            "answer": "<script>alert('xss')</script>",
            "sources": [], "confidence": "low", "flags": [],
        }],
    }
    html = exporter.render_html(final)
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
