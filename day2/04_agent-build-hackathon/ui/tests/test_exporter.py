"""Tests for HTML export."""

import re

import exporter


SAMPLE_FINAL = {
    "rfp_name": "Helios — Test RFP",
    "total_questions": 2,
    "answers": [
        {
            "question_id": "Q1", "category": "technical",
            "answer": "Helios provides real-time threat detection with 2.3-second latency.",
            "sources": ["Helios Doc v4.2"], "confidence": "high", "flags": [],
        },
        {
            "question_id": "Q2", "category": "pricing",
            "answer": "$18/seat/month at 500 endpoints.",
            "sources": ["Pricing Sheet"], "confidence": "medium", "flags": ["needs_review"],
        },
    ],
    "review": {
        "consistency_score": "high",
        "issues": ["Minor: cross-reference SIEM scope"],
        "recommendations": ["Add explicit add-on note in Q1"],
    },
    "metadata": {"model": "claude-opus-4-7", "knowledge_base_entries": 5, "generated_at": "2026-05-06T12:00:00Z"},
}


def test_render_html_returns_complete_document():
    html = exporter.render_html(SAMPLE_FINAL)
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html
    assert "<title>Helios — Test RFP</title>" in html


def test_render_html_includes_all_answers():
    html = exporter.render_html(SAMPLE_FINAL)
    assert "Q1" in html
    assert "Q2" in html
    assert "2.3-second latency" in html
    assert "$18/seat/month" in html


def test_render_html_includes_sources():
    html = exporter.render_html(SAMPLE_FINAL)
    assert "Helios Doc v4.2" in html
    assert "Pricing Sheet" in html


def test_render_html_includes_flags():
    html = exporter.render_html(SAMPLE_FINAL)
    assert "needs_review" in html


def test_render_html_includes_review():
    html = exporter.render_html(SAMPLE_FINAL)
    assert "Consistency: high" in html
    assert "cross-reference SIEM scope" in html
    assert "Add explicit add-on note" in html


def test_render_html_has_print_button_and_print_css():
    html = exporter.render_html(SAMPLE_FINAL)
    assert "Print / Save as PDF" in html
    assert "@media print" in html


def test_render_html_uses_scenario_metadata_when_provided():
    scenario = {"name": "Custom Scenario Name", "client": "Acme Corp"}
    html = exporter.render_html(SAMPLE_FINAL, scenario=scenario)
    assert "Custom Scenario Name" in html
    assert "Acme Corp" in html


def test_render_html_escapes_html_in_user_content():
    """Answer text containing HTML must be escaped."""
    final = {
        **SAMPLE_FINAL,
        "answers": [{
            "question_id": "Q1", "category": "technical",
            "answer": "<script>alert('xss')</script>", "sources": [],
            "confidence": "low", "flags": [],
        }],
    }
    html = exporter.render_html(final)
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_render_html_handles_missing_review():
    final = {**SAMPLE_FINAL, "review": {}}
    html = exporter.render_html(final)
    assert "unknown" in html.lower() or "Consistency:" in html


def test_render_html_handles_dict_issues():
    final = {**SAMPLE_FINAL, "review": {
        "consistency_score": "medium",
        "issues": [{"type": "inconsistency", "description": "Q1 vs Q3 conflict"}],
        "recommendations": [],
    }}
    html = exporter.render_html(final)
    assert "[inconsistency]" in html
    assert "Q1 vs Q3 conflict" in html


# ============================================================
# Client-facing sales pitch
# ============================================================

CLIENT_PITCH_SAMPLE = {
    "client_pitch": {
        "headline": "Threat detection in 2.3 seconds, with EU residency and FedRAMP-grade compliance.",
        "why_helios": (
            "Your RFP focused on three concerns: real-time detection at scale, regulatory alignment, and predictable pricing. "
            "We address all three head-on.\n\n"
            "Helios Sentinel's signature engine triggers in 2.3 seconds and processes 50,000 events per second per tenant — proven across 47 financial services customers including Meridian National Bank. "
            "Our SOC 2 Type II (Deloitte, December 2024) and FedRAMP Moderate authorizations remove typical procurement friction.\n\n"
            "We expect this to compress your detection-to-remediation cycle and shorten vendor due diligence by weeks."
        ),
        "value_pillars": [
            {"title": "Sub-3-second detection", "body": "Signature matches in 2.3s, behavioral in 18s — measured at 50K EPS."},
            {"title": "Compliance-ready", "body": "SOC 2 Type II + FedRAMP Moderate + ISO 27001:2022 maintained continuously."},
            {"title": "Predictable pricing", "body": "Tiered per-seat pricing with mid-tier interpolation rule and 12-month minimum."},
        ],
        "tailored_to": "Q1 (latency), Q2 (certifications), Q5 (EU residency).",
    },
    "elevator_pitch": "Helios cuts RFP-to-contract time by replacing 8-hour manual responses with 90-second drafts.",
    "top_talking_points": ["Speed", "Compliance breadth", "Pricing transparency"],
    "key_differentiators": ["Built-in correlation engine", "Sub-3-second signature detection"],
    "likely_followups": [{"question": "How does pricing scale?", "answer_hint": "Volume tiers + multi-year discounts."}],
    "call_to_action": "Schedule a 60-minute architecture deep-dive with our Solutions Architect.",
}


def test_render_html_includes_client_pitch_section():
    final = {**SAMPLE_FINAL, "demo_script": CLIENT_PITCH_SAMPLE}
    html = exporter.render_html(final)
    assert "Why Helios" in html
    assert "client-pitch" in html


def test_client_pitch_headline_appears():
    final = {**SAMPLE_FINAL, "demo_script": CLIENT_PITCH_SAMPLE}
    html = exporter.render_html(final)
    assert "Threat detection in 2.3 seconds" in html


def test_client_pitch_narrative_split_into_paragraphs():
    final = {**SAMPLE_FINAL, "demo_script": CLIENT_PITCH_SAMPLE}
    html = exporter.render_html(final)
    # Three paragraphs in the why_helios narrative → three <p> tags inside .pitch-narrative
    inside = html.split('class="pitch-narrative"', 1)[1].split("</div>", 1)[0]
    assert inside.count("<p>") == 3


def test_client_pitch_value_pillars_rendered():
    final = {**SAMPLE_FINAL, "demo_script": CLIENT_PITCH_SAMPLE}
    html = exporter.render_html(final)
    assert "Sub-3-second detection" in html
    assert "Compliance-ready" in html
    assert "Predictable pricing" in html


def test_client_pitch_tailored_note_present():
    final = {**SAMPLE_FINAL, "demo_script": CLIENT_PITCH_SAMPLE}
    html = exporter.render_html(final)
    assert "Tailored to" in html
    assert "Q1 (latency)" in html


def test_client_pitch_omitted_when_demo_empty():
    """No demo_script → no Why Helios section."""
    html = exporter.render_html(SAMPLE_FINAL)  # no demo_script
    assert "Why Helios" not in html


def test_client_pitch_omitted_when_pitch_fields_empty():
    """demo_script present but client_pitch is empty stub → section is skipped."""
    final = {**SAMPLE_FINAL, "demo_script": {
        "client_pitch": {"headline": "", "why_helios": "", "value_pillars": [], "tailored_to": ""},
        "elevator_pitch": "x", "top_talking_points": [], "key_differentiators": [],
        "likely_followups": [], "call_to_action": "",
    }}
    html = exporter.render_html(final)
    assert "Why Helios" not in html


def test_speaker_notes_marked_internal():
    final = {**SAMPLE_FINAL, "demo_script": CLIENT_PITCH_SAMPLE}
    html = exporter.render_html(final)
    # Speaker notes section explicitly labeled internal
    assert "Account Executive Speaker Notes" in html
    assert "Internal use only" in html


def test_speaker_notes_appear_AFTER_client_pitch_in_doc():
    final = {**SAMPLE_FINAL, "demo_script": CLIENT_PITCH_SAMPLE}
    html = exporter.render_html(final)
    pitch_pos = html.find("Why Helios")
    notes_pos = html.find("Account Executive Speaker Notes")
    assert pitch_pos > 0
    assert notes_pos > pitch_pos, "Client pitch must appear before AE speaker notes"
