"""Generate downloadable HTML for an RFP run.

Self-contained (inline CSS, no external assets) so users can save the
file or open it in a browser and Print → Save as PDF.

Sections (in order):
  1. Cover page — client + RFP + date + sealed prepared-for header
  2. Executive summary — stats + reviewer scorecard
  3. Drafted answers — per-question, color-coded confidence
  4. Consistency review — score ring + issues + recommendations
  5. Sales presenter notes (demoer) — talking points, follow-ups, CTA
  6. Footer

Each major section starts on a new printed page.
"""

from __future__ import annotations

import html
import json
from datetime import datetime


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>{title}</title>
<style>
  @page {{ size: A4; margin: 18mm 16mm; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, "Helvetica Neue", Helvetica, Arial, sans-serif;
    font-size: 11pt; line-height: 1.55;
    color: #222; max-width: 800px; margin: 0 auto; padding: 24px 28px;
  }}
  h1 {{ font-size: 24pt; margin: 0 0 4px 0; color: #15355f; }}
  h2 {{ font-size: 14pt; margin-top: 28px; padding-bottom: 6px; border-bottom: 1px solid #ccc; color: #15355f; page-break-before: always; }}
  h2:first-of-type {{ page-break-before: auto; }}
  h3 {{ font-size: 12pt; margin: 14px 0 6px 0; color: #1a4480; }}
  .meta {{ color: #666; font-size: 9pt; margin-bottom: 18px; }}
  .meta span + span:before {{ content: " · "; }}

  /* Cover page */
  .cover {{
    height: 100vh; display: flex; flex-direction: column;
    justify-content: center; align-items: flex-start;
    border-left: 6px solid #1a4480; padding-left: 24px;
    margin-bottom: 32px;
    page-break-after: always;
  }}
  .cover .badge {{
    background: #1a4480; color: white;
    padding: 4px 10px; font-size: 10pt; font-weight: 600;
    letter-spacing: 1px; text-transform: uppercase;
    border-radius: 3px;
    margin-bottom: 14px;
  }}
  .cover h1 {{ font-size: 32pt; margin: 0; }}
  .cover .subtitle {{ font-size: 16pt; color: #555; margin-top: 6px; }}
  .cover .client {{ font-size: 18pt; margin-top: 24px; color: #15355f; font-weight: 600; }}
  .cover .description {{ color: #666; font-size: 11pt; margin-top: 8px; max-width: 520px; line-height: 1.6; }}
  .cover .footer {{
    position: absolute; bottom: 32px; left: 48px;
    font-size: 9pt; color: #888; font-family: monospace;
  }}

  /* Summary */
  .summary {{
    background: #f4f6f9; border-left: 4px solid #1a4480;
    padding: 14px 18px; margin: 18px 0;
  }}
  .summary table {{ width: 100%; border-collapse: collapse; font-size: 10pt; }}
  .summary td {{ padding: 4px 8px; }}
  .summary td:first-child {{ color: #555; width: 35%; }}

  /* QA scorecard */
  .scorecard {{
    background: white; border: 1px solid #ddd; border-radius: 8px;
    padding: 14px 18px; margin: 16px 0;
    border-left: 4px solid #2a8c4a;
  }}
  .scorecard.revise_minor {{ border-left-color: #c79100; }}
  .scorecard.revise_major {{ border-left-color: #c0392b; }}
  .verdict-pill {{
    display: inline-block; padding: 4px 10px; border-radius: 3px;
    font-size: 10pt; font-weight: 600;
    background: #e1f4e7; color: #1f5d35;
    margin-right: 8px;
  }}
  .verdict-pill.revise_minor {{ background: #fff5d8; color: #8a6300; }}
  .verdict-pill.revise_major {{ background: #fde2e2; color: #8c2920; }}
  .scores-grid {{
    display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 8px;
    margin-top: 12px;
  }}
  .score-cell {{
    background: #fafbfd; border: 1px solid #e8eef5; border-radius: 6px;
    padding: 8px 10px; text-align: center;
  }}
  .score-cell .label {{ font-size: 9pt; color: #666; text-transform: uppercase; letter-spacing: 0.4px; }}
  .score-cell .value {{ font-size: 18pt; font-weight: 600; color: #1a4480; margin-top: 4px; }}
  .score-cell .value.med {{ color: #c79100; }}
  .score-cell .value.bad {{ color: #c0392b; }}

  /* Per-question answer card */
  .question {{
    page-break-inside: avoid;
    margin-top: 20px; padding: 14px 16px;
    border: 1px solid #e0e0e0; border-radius: 6px;
    border-left: 4px solid #ccc;
  }}
  .question.high   {{ border-left-color: #2a8c4a; }}
  .question.medium {{ border-left-color: #c79100; }}
  .question.low    {{ border-left-color: #c0392b; }}
  .qid {{
    display: inline-block; background: #1a4480; color: white;
    padding: 2px 8px; border-radius: 3px; font-family: monospace;
    font-size: 9pt; margin-right: 8px;
  }}
  .cat, .conf, .specialist {{
    display: inline-block; padding: 1px 8px; border-radius: 3px;
    font-size: 9pt; text-transform: uppercase; letter-spacing: 0.5px;
    margin-left: 4px;
  }}
  .cat {{ background: #eef2f7; color: #555; }}
  .specialist {{ background: #ede8ff; color: #5a3fcf; }}
  .conf.high   {{ background: #e1f4e7; color: #1f5d35; }}
  .conf.medium {{ background: #fff5d8; color: #8a6300; }}
  .conf.low    {{ background: #fde2e2; color: #8c2920; }}
  .question-text {{ color: #555; font-style: italic; margin: 8px 0 12px 0; }}
  .answer-body {{ white-space: pre-wrap; }}
  .sources {{ margin-top: 12px; padding-top: 8px; border-top: 1px dashed #ccc; font-size: 9pt; color: #555; }}
  .source-chip {{
    display: inline-block; background: #eef2f7; padding: 2px 8px;
    border-radius: 3px; margin: 0 6px 4px 0; font-family: monospace;
    font-size: 9pt; color: #1a4480;
  }}
  .flag {{
    display: inline-block; background: #fff5d8; border: 1px solid #c79100;
    color: #8a6300; padding: 1px 8px; border-radius: 3px;
    margin-right: 6px; font-size: 9pt;
  }}

  /* Consistency review */
  .review {{
    background: #f4f6f9; border-radius: 6px; padding: 14px 16px; margin-top: 16px;
  }}
  .ring {{
    display: inline-block; width: 50px; height: 50px; line-height: 42px;
    border: 4px solid #2a8c4a; color: #2a8c4a; border-radius: 50%;
    text-align: center; font-weight: bold; font-size: 9pt; vertical-align: middle;
    text-transform: uppercase; margin-right: 14px;
  }}
  .ring.medium {{ border-color: #c79100; color: #c79100; }}
  .ring.low {{ border-color: #c0392b; color: #c0392b; }}
  .ring.unknown {{ border-color: #888; color: #888; }}
  .review-issues, .review-recs {{ margin-top: 12px; }}
  .review-issues ul, .review-recs ul {{ margin: 6px 0 0 0; padding-left: 22px; }}
  .review-issues li, .review-recs li {{ margin-bottom: 4px; font-size: 10pt; }}

  /* Client-facing sales pitch */
  .client-pitch {{
    background: linear-gradient(180deg, #f7faff 0%, #ffffff 100%);
    border: 1px solid #d6e3f3;
    border-radius: 8px;
    padding: 24px 28px;
    margin: 18px 0;
    page-break-inside: avoid;
  }}
  .client-pitch .pitch-headline {{
    font-size: 18pt; font-weight: 700;
    color: #15355f;
    line-height: 1.3;
    margin: 0 0 8px 0;
    letter-spacing: -0.2px;
  }}
  .client-pitch .pitch-tailored {{
    font-size: 9pt; color: #6b7c93; font-style: italic;
    margin-bottom: 16px;
    padding-bottom: 10px;
    border-bottom: 1px solid #e3ebf5;
  }}
  .client-pitch .pitch-narrative p {{
    margin: 0 0 12px 0;
    font-size: 11pt; line-height: 1.7; color: #2c3e55;
  }}
  .client-pitch .pillars {{
    display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px;
    margin-top: 18px;
  }}
  .client-pitch .pillar {{
    background: white;
    border: 1px solid #e3ebf5;
    border-top: 3px solid #1a4480;
    border-radius: 6px;
    padding: 12px 14px;
  }}
  .client-pitch .pillar .ptitle {{
    font-weight: 700; color: #1a4480; font-size: 10.5pt;
    margin-bottom: 6px;
  }}
  .client-pitch .pillar .pbody {{
    font-size: 10pt; color: #4a5a72; line-height: 1.5;
  }}

  /* Demoer / presenter notes */
  .demo-section {{ background: #fff8e8; border-left: 4px solid #c79100; padding: 14px 18px; margin: 16px 0; }}
  .demo-section h3 {{ color: #8a6300; }}
  .pitch {{ font-size: 12pt; color: #15355f; font-style: italic; margin-bottom: 12px; }}
  .talking-points {{ list-style: decimal; padding-left: 22px; }}
  .talking-points li {{ margin-bottom: 6px; }}
  .followup {{
    background: white; border: 1px solid #e8d68c; border-radius: 4px;
    padding: 8px 12px; margin: 6px 0;
  }}
  .followup .question {{ font-weight: 600; padding: 0; border: none; margin: 0; color: #15355f; }}
  .followup .answer-hint {{ color: #555; margin-top: 4px; font-size: 10pt; }}
  .cta {{
    margin-top: 14px; padding: 10px 14px;
    background: #1a4480; color: white; border-radius: 4px;
    font-weight: 600;
  }}

  .footer-note {{ margin-top: 32px; font-size: 8pt; color: #999; text-align: center; }}
  .print-btn {{
    position: fixed; top: 18px; right: 18px;
    background: #1a4480; color: white; border: none;
    padding: 10px 16px; border-radius: 4px; cursor: pointer;
    font-size: 12pt; font-weight: 600;
    box-shadow: 0 2px 6px rgba(0,0,0,0.2);
    z-index: 100;
  }}
  .print-btn:hover {{ background: #15355f; }}
  @media print {{
    .print-btn {{ display: none; }}
    body {{ margin: 0; padding: 24px; }}
    .cover {{ height: 95vh; }}
  }}
</style>
</head>
<body>
  <button class="print-btn" onclick="window.print()">🖨️ Print / Save as PDF</button>

  <!-- Cover -->
  <div class="cover">
    <span class="badge">RFP Response · Confidential</span>
    <h1>{title}</h1>
    <div class="subtitle">Helios Security · Endpoint Protection Platform</div>
    <div class="client">Prepared for: {client}</div>
    <div class="description">{client_description}</div>
    <div class="footer">{question_count} questions · Generated {generated_at} · Model: {model}</div>
  </div>

  <!-- Executive summary -->
  <h2>Executive Summary</h2>
  {summary_html}

  <!-- CLIENT-FACING SALES PITCH (the part the prospect actually reads) -->
  {client_pitch_html}

  <!-- QA scorecard (for internal review, but kept in deliverable for transparency) -->
  {scorecard_html}

  <!-- Drafted answers -->
  <h2>Drafted Answers</h2>
  {answers_html}

  <!-- Consistency review -->
  <h2>Consistency Review</h2>
  {review_html}

  <!-- Internal speaker notes (AE-facing) — comes last so it's clearly an appendix -->
  {demo_html}

  <div class="footer-note">
    Generated by Helios RFP Agent Platform · Multi-agent system · Model claude-opus-4-7 · Print to save as PDF.
  </div>
</body>
</html>"""


def _esc(s) -> str:
    return html.escape(str(s) if s is not None else "")


def _render_summary(final: dict, qa: dict | None = None) -> str:
    review = final.get("review") or {}
    answers = final.get("answers") or []
    high = sum(1 for a in answers if a.get("confidence") == "high")
    rows = [
        ("RFP", final.get("rfp_name", "")),
        ("Total questions", str(final.get("total_questions", len(answers)))),
        ("High-confidence answers", f"{high} / {len(answers)}"),
        ("Consistency score", review.get("consistency_score", "?")),
        ("Issues flagged (consistency)", str(len(review.get("issues", [])))),
        ("KB entries used", str(final.get("metadata", {}).get("knowledge_base_entries", "?"))),
    ]
    if qa:
        verdict = qa.get("verdict", "?")
        overall = qa.get("overall", "?")
        rows.append(("QA verdict", f"{verdict} · overall {overall}/10"))
    return (
        '<div class="summary"><h3 style="margin-top:0;">At a glance</h3><table>'
        + "".join(f"<tr><td>{_esc(k)}</td><td><strong>{_esc(v)}</strong></td></tr>" for k, v in rows)
        + "</table></div>"
    )


def _render_scorecard(qa: dict | None) -> str:
    if not qa or "scores" not in qa:
        return ""
    scores = qa.get("scores") or {}
    verdict = (qa.get("verdict") or "ship").lower()
    summary = qa.get("summary", "")
    overall = qa.get("overall", "")
    issues = qa.get("top_issues") or []
    strengths = qa.get("strengths") or []

    score_cells = ""
    for k in ["accuracy", "completeness", "cite_quality", "tone_consistency"]:
        v = scores.get(k, "?")
        klass = ""
        try:
            iv = int(v)
            if iv < 5: klass = "bad"
            elif iv < 8: klass = "med"
        except (ValueError, TypeError):
            pass
        score_cells += f'<div class="score-cell"><div class="label">{_esc(k.replace("_", " "))}</div><div class="value {klass}">{_esc(v)}</div></div>'

    issues_html = ""
    if issues:
        issues_html = "<h3>Reviewer flagged</h3><ul>" + "".join(f"<li>{_esc(i)}</li>" for i in issues) + "</ul>"

    strengths_html = ""
    if strengths:
        strengths_html = "<h3>Reviewer strengths</h3><ul>" + "".join(f"<li>{_esc(s)}</li>" for s in strengths) + "</ul>"

    return (
        f'<div class="scorecard {_esc(verdict)}">'
        f'<h3 style="margin-top:0;">QA Reviewer Scorecard</h3>'
        f'<div><span class="verdict-pill {_esc(verdict)}">{_esc(verdict.replace("_", " "))}</span>'
        f'<strong>Overall: {_esc(overall)}/10</strong></div>'
        f'<p style="color:#444; font-size: 10pt; margin: 10px 0;">{_esc(summary)}</p>'
        f'<div class="scores-grid">{score_cells}</div>'
        f'{issues_html}{strengths_html}'
        '</div>'
    )


def _render_answers(answers: list[dict]) -> str:
    parts = []
    for a in answers:
        conf = (a.get("confidence") or "medium").lower()
        sources = "".join(
            f'<span class="source-chip">{_esc(s)}</span>'
            for s in a.get("sources", [])
        )
        flags = "".join(
            f'<span class="flag">⚠ {_esc(f)}</span>'
            for f in a.get("flags", [])
        )
        spec_chip = ""
        if a.get("specialist_label"):
            spec_chip = f'<span class="specialist">🎓 {_esc(a["specialist_label"])}</span>'
        parts.append(
            f'<div class="question {conf}">'
            f'<div>'
            f'<span class="qid">{_esc(a.get("question_id", "?"))}</span>'
            f'<span class="cat">{_esc(a.get("category", ""))}</span>'
            f'{spec_chip}'
            f'<span class="conf {conf}">{_esc(conf)}</span>'
            f'</div>'
            f'<div class="question-text">{_esc(_get_question_text(a))}</div>'
            f'<div class="answer-body">{_esc(a.get("answer", ""))}</div>'
            + (f'<div class="sources"><strong>Sources:</strong><br/>{sources}</div>' if sources else "")
            + (f'<div class="sources"><strong>Flags:</strong><br/>{flags}</div>' if flags else "")
            + '</div>'
        )
    return "\n".join(parts)


def _get_question_text(answer: dict) -> str:
    """Extract the question text if it was carried through the pipeline."""
    return answer.get("question_text", "")


def _render_review(review: dict) -> str:
    score = (review.get("consistency_score") or "unknown").lower()
    issues = review.get("issues") or []
    recs = review.get("recommendations") or []

    issues_html = "<p><em>No issues found.</em></p>" if not issues else (
        '<ul>' + "".join(f"<li>{_format_issue_html(i)}</li>" for i in issues) + '</ul>'
    )
    recs_html = "<p><em>None.</em></p>" if not recs else (
        '<ul>' + "".join(f"<li>{_esc(r if isinstance(r, str) else json.dumps(r))}</li>" for r in recs) + '</ul>'
    )

    return (
        '<div class="review">'
        f'<div><span class="ring {score}">{_esc(score)}</span>'
        f'<strong>Consistency: {_esc(score)}</strong> '
        f'· {len(issues)} issue{"" if len(issues) == 1 else "s"} '
        f'· {len(recs)} recommendation{"" if len(recs) == 1 else "s"}</div>'
        f'<div class="review-issues"><h3>Issues</h3>{issues_html}</div>'
        f'<div class="review-recs"><h3>Recommendations</h3>{recs_html}</div>'
        '</div>'
    )


def _render_client_pitch(demo: dict | None) -> str:
    """Render the client-facing 'Why Helios' section — this is the section
    the prospect actually reads. Must be substantive even if the demoer
    output is partial."""
    if not demo:
        return ""
    cp = demo.get("client_pitch") or {}
    headline = cp.get("headline") or ""
    why = cp.get("why_helios") or ""
    pillars = cp.get("value_pillars") or []
    tailored = cp.get("tailored_to") or ""

    # If there's nothing worth showing, skip the section entirely
    if not (headline or why or pillars):
        return ""

    # Split the narrative into paragraphs at blank lines OR every ~80 words
    paragraphs_html = ""
    if why:
        chunks = [p.strip() for p in why.split("\n\n") if p.strip()]
        if not chunks:
            chunks = [why]
        paragraphs_html = "".join(f"<p>{_esc(p)}</p>" for p in chunks)

    pillars_html = ""
    if pillars:
        pillars_html = '<div class="pillars">' + "".join(
            f'<div class="pillar"><div class="ptitle">{_esc(p.get("title", ""))}</div>'
            f'<div class="pbody">{_esc(p.get("body", ""))}</div></div>'
            for p in pillars if isinstance(p, dict)
        ) + "</div>"

    tailored_html = (
        f'<div class="pitch-tailored">Tailored to your RFP: {_esc(tailored)}</div>'
        if tailored else ""
    )

    return (
        '<h2>Why Helios</h2>'
        '<div class="client-pitch">'
        + (f'<div class="pitch-headline">{_esc(headline)}</div>' if headline else "")
        + tailored_html
        + (f'<div class="pitch-narrative">{paragraphs_html}</div>' if paragraphs_html else "")
        + pillars_html
        + '</div>'
    )


def _render_demo(demo: dict | None) -> str:
    """Internal speaker notes for the AE — appendix in the deliverable."""
    if not demo or demo.get("parse_error"):
        return ""
    pitch = demo.get("elevator_pitch") or ""
    points = demo.get("top_talking_points") or []
    diffs = demo.get("key_differentiators") or []
    followups = demo.get("likely_followups") or []
    cta = demo.get("call_to_action") or ""

    # If everything is empty, skip
    if not (pitch or points or diffs or followups or cta):
        return ""

    points_html = "".join(f"<li>{_esc(p)}</li>" for p in points)
    diffs_html = "".join(f"<li>{_esc(d)}</li>" for d in diffs)
    followups_html = "".join(
        f'<div class="followup"><div class="question">Q: {_esc(f.get("question", ""))}</div>'
        f'<div class="answer-hint">{_esc(f.get("answer_hint", ""))}</div></div>'
        for f in followups if isinstance(f, dict)
    )

    return (
        '<h2>Internal: Account Executive Speaker Notes</h2>'
        '<div class="demo-section">'
        '<p style="font-size:9pt;color:#8a6300;margin-top:0;"><em>Internal use only — not for distribution to the prospect.</em></p>'
        '<h3 style="margin-top:0;">Elevator pitch</h3>'
        f'<div class="pitch">{_esc(pitch)}</div>'
        '<h3>Lead with these talking points</h3>'
        f'<ol class="talking-points">{points_html}</ol>'
        '<h3>Key differentiators</h3>'
        f'<ul>{diffs_html}</ul>'
        '<h3>Likely follow-up questions</h3>'
        f'{followups_html}'
        '<h3>Recommended next step</h3>'
        f'<div class="cta">{_esc(cta)}</div>'
        '</div>'
    )


def _format_issue_html(issue) -> str:
    if isinstance(issue, str):
        return _esc(issue)
    if isinstance(issue, dict):
        type_str = f"<strong>[{_esc(issue.get('type', ''))}]</strong> " if issue.get("type") else ""
        body = issue.get("description") or issue.get("issue") or json.dumps(issue)
        return type_str + _esc(body)
    return _esc(json.dumps(issue))


def render_html(final: dict, scenario: dict | None = None) -> str:
    """Render the final RFP output as a self-contained HTML document."""
    final = final or {}
    title = (scenario or {}).get("name") or final.get("rfp_name") or "RFP Response"
    client = (scenario or {}).get("client") or "—"
    client_desc = (scenario or {}).get("description") or ""
    answers = final.get("answers") or []
    review = final.get("review") or {}
    qa = final.get("qa_review")
    demo = final.get("demo_script")
    metadata = final.get("metadata") or {}

    return HTML_TEMPLATE.format(
        title=_esc(title),
        client=_esc(client),
        client_description=_esc(client_desc),
        question_count=len(answers),
        generated_at=_esc(metadata.get("generated_at") or datetime.utcnow().isoformat() + "Z"),
        model=_esc(metadata.get("model", "?")),
        summary_html=_render_summary(final, qa),
        client_pitch_html=_render_client_pitch(demo),
        scorecard_html=_render_scorecard(qa),
        answers_html=_render_answers(answers),
        review_html=_render_review(review),
        demo_html=_render_demo(demo),
    )
